"""Tax lot reconstruction from Robinhood order history."""

from datetime import date, datetime, timezone
from typing import Any

from robin_stocks.robinhood.helper import request_get

from mcp_robinhood.logging_config import logger
from mcp_robinhood.tools.error_handling import (
    create_error_response,
    create_no_data_response,
    create_success_response,
    handle_robin_stocks_errors,
    validate_symbol,
)
from mcp_robinhood.tools.session_manager import ensure_authenticated_session


def _instrument_id_for_symbol(symbol: str) -> str | None:
    data = request_get(
        "https://api.robinhood.com/instruments/",
        "indexzero",
        {"symbol": symbol},
    )
    return data.get("id") if data else None


def _get_position_quantity(instrument_id: str) -> float:
    positions = request_get(
        "https://api.robinhood.com/positions/",
        "pagination",
        {"nonzero": "true"},
    )
    for p in positions or []:
        if p and p.get("instrument_id") == instrument_id:
            return float(p.get("quantity", 0))
    return 0.0


def _get_filled_orders(instrument_id: str) -> list[dict]:
    orders = request_get(
        "https://api.robinhood.com/orders/",
        "pagination",
        {"instrument": f"https://api.robinhood.com/instruments/{instrument_id}/"},
    )
    filled = [o for o in (orders or []) if o and o.get("state") == "filled"]
    filled.sort(key=lambda x: x.get("created_at", ""))
    return filled


def _days_held(acquisition_date: str) -> int:
    d = datetime.fromisoformat(acquisition_date.replace("Z", "+00:00")).date()
    return (date.today() - d).days


def _reconstruct_fifo_lots(orders: list[dict]) -> list[dict]:
    """Apply FIFO to order history and return remaining open lots."""
    # Build raw lots from buy executions
    raw_lots: list[dict] = []
    sell_queue: list[tuple[float, float, str]] = []  # (qty, price, date) of sells

    buys = []
    sells = []
    for o in orders:
        for e in o.get("executions", []):
            qty = float(e["quantity"])
            price = float(e["price"])
            ts = e.get("timestamp", o.get("created_at", ""))
            if o["side"] == "buy":
                buys.append({"qty": qty, "price": price, "date": ts})
            else:
                sells.append({"qty": qty, "price": price, "date": ts})

    # Apply FIFO: consume sells from oldest buys
    buy_idx = 0
    buy_remaining = [b["qty"] for b in buys]

    for sell in sells:
        remaining_sell = sell["qty"]
        while remaining_sell > 1e-6 and buy_idx < len(buys):
            available = buy_remaining[buy_idx]
            consumed = min(available, remaining_sell)
            buy_remaining[buy_idx] -= consumed
            remaining_sell -= consumed
            if buy_remaining[buy_idx] < 1e-6:
                buy_idx += 1

    # Remaining buys are open lots
    lots = []
    for i, buy in enumerate(buys):
        qty = buy_remaining[i]
        if qty > 1e-6:
            acq_date = buy["date"][:10]
            days = _days_held(buy["date"])
            lots.append({
                "acquisition_date": acq_date,
                "quantity": round(qty, 8),
                "cost_per_share": round(buy["price"], 4),
                "total_cost": round(qty * buy["price"], 2),
                "days_held": days,
                "term": "long" if days >= 365 else "short",
            })

    return lots


@handle_robin_stocks_errors
async def get_tax_lots(symbol: str) -> dict[str, Any]:
    """Get tax lots for a stock position reconstructed via FIFO from order history.

    Args:
        symbol: Stock ticker symbol (e.g., "CAVA")
    """
    if not validate_symbol(symbol):
        return create_error_response(ValueError(f"Invalid symbol: {symbol}"), "symbol validation")

    symbol = symbol.strip().upper()
    authenticated, err = await ensure_authenticated_session()
    if not authenticated:
        return create_error_response(Exception(err or "Not authenticated"), "auth")

    import asyncio

    loop = asyncio.get_event_loop()

    instrument_id = await loop.run_in_executor(None, _instrument_id_for_symbol, symbol)
    if not instrument_id:
        return create_no_data_response(f"No instrument found for symbol: {symbol}", {"symbol": symbol})

    orders, position_qty = await asyncio.gather(
        loop.run_in_executor(None, _get_filled_orders, instrument_id),
        loop.run_in_executor(None, _get_position_quantity, instrument_id),
    )

    if not orders:
        return create_no_data_response(f"No order history for {symbol}", {"symbol": symbol})

    lots = _reconstruct_fifo_lots(orders)

    if not lots:
        return create_no_data_response(f"No open tax lots for {symbol}", {"symbol": symbol})

    total_cost = sum(lot["total_cost"] for lot in lots)
    total_qty = sum(lot["quantity"] for lot in lots)

    logger.info(f"Reconstructed {len(lots)} FIFO tax lots for {symbol}")
    return create_success_response({
        "symbol": symbol,
        "total_shares": round(total_qty, 8),
        "position_shares": position_qty,
        "total_cost_basis": round(total_cost, 2),
        "average_cost": round(total_cost / total_qty, 4) if total_qty else 0,
        "lots": lots,
        "lot_count": len(lots),
        "note": "FIFO reconstruction from order history",
    })
