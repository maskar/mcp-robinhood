"""Tax lot reconstruction from Robinhood order history."""

from datetime import date, datetime
from itertools import combinations
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


def _get_position_data(instrument_id: str) -> dict:
    """Return position dict including clearing_cost_basis."""
    positions = request_get(
        "https://api.robinhood.com/positions/",
        "pagination",
        {"nonzero": "true", "fetch_tax_lot_related_info": "true"},
    )
    for p in positions or []:
        if p and p.get("instrument_id") == instrument_id:
            return p
    return {}


def _get_filled_orders(instrument_id: str) -> list[dict]:
    orders = request_get(
        "https://api.robinhood.com/orders/",
        "pagination",
        {"instrument": f"https://api.robinhood.com/instruments/{instrument_id}/"},
    )
    filled = [o for o in (orders or []) if o and o.get("state") == "filled"]
    filled.sort(key=lambda x: x.get("created_at", ""))
    return filled


def _days_held(ts: str) -> int:
    d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    return (date.today() - d).days


def _build_buy_lots(orders: list[dict]) -> list[dict]:
    """Extract all buy executions as individual lots."""
    lots = []
    for o in orders:
        if o["side"] != "buy":
            continue
        for e in o.get("executions", []):
            ts = e.get("timestamp", o.get("created_at", ""))
            lots.append({
                "qty": float(e["quantity"]),
                "price": float(e["price"]),
                "date": ts,
            })
    return lots


def _solve_lots(buy_lots: list[dict], target_qty: float, target_cost: float) -> list[dict] | None:
    """Find the subset of buy lots matching target quantity and cost basis.

    Uses the clearing_cost_basis from the position API as ground truth.
    Works for up to ~20 lots; falls back to FIFO if no exact match found.
    """
    n = len(buy_lots)
    if n > 20:
        return None  # too many to brute-force

    tolerance = 1.0  # $1 rounding tolerance

    # Try all subsets — for n<=20, 2^20 = 1M iterations, fast enough
    for r in range(n + 1):
        for combo in combinations(range(n), r):
            qty = sum(buy_lots[i]["qty"] for i in combo)
            if abs(qty - target_qty) > 1e-4:
                continue
            cost = sum(buy_lots[i]["qty"] * buy_lots[i]["price"] for i in combo)
            if abs(cost - target_cost) <= tolerance:
                return [buy_lots[i] for i in combo]
    return None


def _fifo_lots(buy_lots: list[dict], sell_qty: float) -> list[dict]:
    """Apply FIFO to buy lots given total sell quantity."""
    remaining = [dict(lot) for lot in buy_lots]
    to_sell = sell_qty
    for lot in remaining:
        if to_sell <= 1e-6:
            break
        consumed = min(lot["qty"], to_sell)
        lot["qty"] -= consumed
        to_sell -= consumed
    return [lot for lot in remaining if lot["qty"] > 1e-6]


@handle_robin_stocks_errors
async def get_tax_lots(symbol: str) -> dict[str, Any]:
    """Gets tax lots for a stock position by matching order history to clearing cost basis.

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

    position, orders = await asyncio.gather(
        loop.run_in_executor(None, _get_position_data, instrument_id),
        loop.run_in_executor(None, _get_filled_orders, instrument_id),
    )

    if not orders:
        return create_no_data_response(f"No order history for {symbol}", {"symbol": symbol})

    position_qty = float(position.get("quantity", 0))
    clearing_cost = float(position.get("clearing_cost_basis") or 0)
    clearing_avg = float(position.get("clearing_average_cost") or 0)

    buy_lots = _build_buy_lots(orders)
    total_bought = sum(lot["qty"] for lot in buy_lots)
    total_sold = total_bought - position_qty

    # Try to find exact lot combination matching clearing_cost_basis
    method = "exact_match"
    open_lots_raw = _solve_lots(buy_lots, position_qty, clearing_cost) if clearing_cost else None

    if open_lots_raw is None:
        # Fall back to FIFO
        method = "fifo_estimate"
        open_lots_raw = _fifo_lots(buy_lots, total_sold)

    lots = []
    for lot in sorted(open_lots_raw, key=lambda x: x["date"]):
        days = _days_held(lot["date"])
        lots.append({
            "acquisition_date": lot["date"][:10],
            "quantity": round(lot["qty"], 8),
            "cost_per_share": round(lot["price"], 4),
            "total_cost": round(lot["qty"] * lot["price"], 2),
            "days_held": days,
            "term": "long" if days >= 365 else "short",
        })

    reconstructed_cost = sum(lot["total_cost"] for lot in lots)

    logger.info(f"Tax lots for {symbol}: {len(lots)} lots via {method}")
    return create_success_response({
        "symbol": symbol,
        "total_shares": position_qty,
        "total_cost_basis": clearing_cost or round(reconstructed_cost, 2),
        "average_cost": clearing_avg or (round(reconstructed_cost / position_qty, 4) if position_qty else 0),
        "lots": lots,
        "lot_count": len(lots),
        "method": method,
    })
