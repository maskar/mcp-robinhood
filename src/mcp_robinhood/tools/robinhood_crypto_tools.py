"""MCP tools for Robinhood cryptocurrency data (read-only)."""

from typing import Any

import robin_stocks.robinhood as rh

from mcp_robinhood.logging_config import logger
from mcp_robinhood.tools.error_handling import (
    create_error_response,
    create_success_response,
    execute_with_retry,
    handle_robin_stocks_errors,
    sanitize_api_response,
)


@handle_robin_stocks_errors
async def get_crypto_positions() -> dict[str, Any]:
    """Get current cryptocurrency positions with quantities and market values."""
    positions = await execute_with_retry(rh.crypto.get_crypto_positions)
    if not positions:
        return create_success_response({"positions": [], "count": 0})

    rows: list[dict[str, Any]] = []
    for pos in positions:
        qty = _to_float(pos.get("quantity"))
        if qty <= 0:
            continue

        avg_cost = _to_float(pos.get("cost_bases", [{}])[0].get("direct_cost_basis"))
        currency = pos.get("currency", {})
        symbol = ""
        if isinstance(currency, dict):
            symbol = (currency.get("code") or currency.get("name") or "").upper()

        if not symbol:
            continue

        # Fetch current quote
        price = 0.0
        try:
            quote = await execute_with_retry(rh.crypto.get_crypto_quote, symbol)
            if quote:
                price = _to_float(quote.get("mark_price"))
        except Exception as exc:
            logger.warning(f"Crypto quote failed for {symbol}: {exc}")

        equity = price * qty
        cost_basis = _to_float(pos.get("cost_bases", [{}])[0].get("direct_cost_basis"))
        pnl = equity - cost_basis if cost_basis else None

        rows.append({
            "symbol": symbol,
            "quantity": qty,
            "average_cost": avg_cost / qty if qty and avg_cost else 0.0,
            "current_price": price,
            "equity": equity,
            "cost_basis": cost_basis,
            "unrealized_pnl": pnl,
        })

    return create_success_response(
        sanitize_api_response({"positions": rows, "count": len(rows)})
    )


@handle_robin_stocks_errors
async def get_crypto_quote(symbol: str) -> dict[str, Any]:
    """Get real-time quote for a cryptocurrency.

    Args:
        symbol: Crypto symbol (e.g., "BTC", "ETH", "DOGE")
    """
    quote = await execute_with_retry(rh.crypto.get_crypto_quote, symbol.upper())
    if not quote:
        return create_error_response(ValueError(f"No quote data for {symbol}"))

    return create_success_response(sanitize_api_response({
        "symbol": symbol.upper(),
        "mark_price": _to_float(quote.get("mark_price")),
        "ask_price": _to_float(quote.get("ask_price")),
        "bid_price": _to_float(quote.get("bid_price")),
        "high_price": _to_float(quote.get("high_price")),
        "low_price": _to_float(quote.get("low_price")),
        "open_price": _to_float(quote.get("open_price")),
    }))


@handle_robin_stocks_errors
async def get_crypto_info(symbol: str) -> dict[str, Any]:
    """Get detailed information about a cryptocurrency.

    Args:
        symbol: Crypto symbol (e.g., "BTC", "ETH")
    """
    info = await execute_with_retry(rh.crypto.get_crypto_info, symbol.upper())
    if not info:
        return create_error_response(ValueError(f"No info for {symbol}"))

    return create_success_response(sanitize_api_response(info))


def _to_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except Exception:
        return default
