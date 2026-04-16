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


def _get_orders(instrument_id: str, states: list[str] | None = None) -> list[dict]:
    orders = request_get(
        "https://api.robinhood.com/orders/",
        "pagination",
        {"instrument": f"https://api.robinhood.com/instruments/{instrument_id}/"},
    )
    result = [o for o in (orders or []) if o]
    if states:
        result = [o for o in result if o.get("state") in states]
    result.sort(key=lambda x: x.get("created_at", ""))
    return result


def _get_filled_orders(instrument_id: str) -> list[dict]:
    return _get_orders(instrument_id, states=["filled"])


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


def _build_sell_executions(orders: list[dict]) -> list[dict]:
    """Extract all sell executions sorted chronologically."""
    sells = []
    for o in orders:
        if o["side"] != "sell":
            continue
        for e in o.get("executions", []):
            ts = e.get("timestamp", o.get("created_at", ""))
            sells.append({
                "qty": float(e["quantity"]),
                "price": float(e["price"]),
                "date": ts,
                "settlement_date": e.get("settlement_date", ""),
            })
    sells.sort(key=lambda x: x["date"])
    return sells


def _match_closed_lots(
    all_buy_lots: list[dict],
    open_lots: list[dict],
    sell_executions: list[dict],
) -> list[dict]:
    """Identify closed lots and assign sell proceeds via FIFO matching."""
    open_keys = {(lot["date"], lot["price"], lot["qty"]) for lot in open_lots}
    closed_raw = [lot for lot in all_buy_lots if (lot["date"], lot["price"], lot["qty"]) not in open_keys]
    closed_raw.sort(key=lambda x: x["date"])

    # Assign sell proceeds to closed lots via FIFO (oldest closed lot gets oldest sell price)
    sell_queue = list(sell_executions)
    sell_idx = 0
    sell_remaining = sell_queue[0]["qty"] if sell_queue else 0.0

    result = []
    for lot in closed_raw:
        lot_remaining = lot["qty"]
        proceeds = 0.0

        while lot_remaining > 1e-6 and sell_idx < len(sell_queue):
            sell = sell_queue[sell_idx]
            matched = min(lot_remaining, sell_remaining)
            proceeds += matched * sell["price"]
            sell_date = sell["date"]
            settlement = sell.get("settlement_date", "")
            lot_remaining -= matched
            sell_remaining -= matched
            if sell_remaining < 1e-6:
                sell_idx += 1
                sell_remaining = sell_queue[sell_idx]["qty"] if sell_idx < len(sell_queue) else 0.0

        cost = lot["qty"] * lot["price"]
        gain = proceeds - cost
        acq_ts = lot["date"]
        days = _days_held(acq_ts)

        result.append({
            "acquisition_date": acq_ts[:10],
            "sale_date": sell_date[:10] if proceeds else "",
            "settlement_date": settlement,
            "quantity": round(lot["qty"], 8),
            "cost_per_share": round(lot["price"], 4),
            "total_cost": round(cost, 2),
            "proceeds": round(proceeds, 2),
            "realized_gain_loss": round(gain, 2),
            "holding_days": days,
            "term": "long" if days >= 365 else "short",
        })

    return result


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


@handle_robin_stocks_errors
async def get_stock_transactions(symbol: str) -> dict[str, Any]:
    """Gets order history for a stock including filled and open orders.

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

    orders = await loop.run_in_executor(None, _get_orders, instrument_id, None)

    if not orders:
        return create_no_data_response(f"No orders found for {symbol}", {"symbol": symbol})

    transactions = []
    for o in reversed(orders):  # newest first
        execs = o.get("executions", [])
        total_qty = sum(float(e["quantity"]) for e in execs)
        transactions.append({
            "date": o.get("created_at", "")[:10],
            "side": o.get("side"),
            "state": o.get("state"),
            "quantity": float(o.get("quantity", 0)),
            "filled_quantity": total_qty,
            "average_price": float(o["average_price"]) if o.get("average_price") else None,
            "limit_price": float(o["price"]) if o.get("price") else None,
            "stop_price": float(o["stop_price"]) if o.get("stop_price") else None,
            "order_type": o.get("type"),
            "time_in_force": o.get("time_in_force"),
            "order_id": o.get("id"),
        })

    filled = [t for t in transactions if t["state"] == "filled"]
    open_orders = [t for t in transactions if t["state"] in ("queued", "unconfirmed", "confirmed", "partially_filled")]

    logger.info(f"Transactions for {symbol}: {len(transactions)} total, {len(open_orders)} open")
    return create_success_response({
        "symbol": symbol,
        "total_orders": len(transactions),
        "open_orders": open_orders,
        "filled_orders": filled,
        "all_orders": transactions,
    })


@handle_robin_stocks_errors
async def get_closed_lots(symbol: str) -> dict[str, Any]:
    """Gets closed (sold) tax lots with realized gain/loss for a stock.

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

    buy_lots = _build_buy_lots(orders)
    sell_executions = _build_sell_executions(orders)

    if not sell_executions:
        return create_no_data_response(f"No closed lots for {symbol} — no sell orders found", {"symbol": symbol})

    total_bought = sum(lot["qty"] for lot in buy_lots)
    total_sold = total_bought - position_qty

    # Identify open lots
    open_lots_raw = _solve_lots(buy_lots, position_qty, clearing_cost) if clearing_cost else None
    if open_lots_raw is None:
        open_lots_raw = _fifo_lots(buy_lots, total_sold)

    closed_lots = _match_closed_lots(buy_lots, open_lots_raw, sell_executions)

    total_cost = sum(lot["total_cost"] for lot in closed_lots)
    total_proceeds = sum(lot["proceeds"] for lot in closed_lots)
    total_gain = total_proceeds - total_cost

    logger.info(f"Closed lots for {symbol}: {len(closed_lots)} lots, realized gain={total_gain:.2f}")
    return create_success_response({
        "symbol": symbol,
        "closed_lot_count": len(closed_lots),
        "total_cost_basis": round(total_cost, 2),
        "total_proceeds": round(total_proceeds, 2),
        "total_realized_gain_loss": round(total_gain, 2),
        "lots": closed_lots,
    })
