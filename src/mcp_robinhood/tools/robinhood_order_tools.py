"""Order execution tools for Robinhood (buy, sell, cancel)."""

from typing import Any

import robin_stocks.robinhood as rh

from mcp_robinhood.logging_config import logger
from mcp_robinhood.tools.error_handling import (
    create_error_response,
    create_success_response,
    handle_robin_stocks_errors,
    validate_symbol,
)
from mcp_robinhood.tools.session_manager import ensure_authenticated_session

_CONFIRM_REQUIRED = "confirm must be True to execute this order"


@handle_robin_stocks_errors
async def place_buy_limit(symbol: str, quantity: float, limit_price: float, confirm: bool) -> dict[str, Any]:
    """Places a limit buy order for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quantity: Number of shares to buy
        limit_price: Maximum price per share to pay
        confirm: Must be True to place the order — prevents accidental execution
    """
    if not confirm:
        return create_error_response(ValueError(_CONFIRM_REQUIRED), "order confirmation")

    if not validate_symbol(symbol):
        return create_error_response(ValueError(f"Invalid symbol: {symbol}"), "symbol validation")

    symbol = symbol.strip().upper()
    authenticated, err = await ensure_authenticated_session()
    if not authenticated:
        return create_error_response(Exception(err or "Not authenticated"), "auth")

    import asyncio
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None, lambda: rh.order_buy_limit(symbol, quantity, limit_price)
    )

    if not result or result.get("detail"):
        detail = result.get("detail") if result else "No response from Robinhood"
        return create_error_response(Exception(detail), "place_buy_limit")

    logger.info(f"Buy limit placed: {quantity} {symbol} @ {limit_price} — order_id={result.get('id')}")
    return create_success_response({
        "order_id": result.get("id"),
        "symbol": symbol,
        "side": "buy",
        "type": "limit",
        "quantity": quantity,
        "limit_price": limit_price,
        "state": result.get("state"),
        "created_at": result.get("created_at"),
    })


@handle_robin_stocks_errors
async def place_sell_limit(symbol: str, quantity: float, limit_price: float, confirm: bool) -> dict[str, Any]:
    """Places a limit sell order for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        quantity: Number of shares to sell
        limit_price: Minimum price per share to accept
        confirm: Must be True to place the order — prevents accidental execution
    """
    if not confirm:
        return create_error_response(ValueError(_CONFIRM_REQUIRED), "order confirmation")

    if not validate_symbol(symbol):
        return create_error_response(ValueError(f"Invalid symbol: {symbol}"), "symbol validation")

    symbol = symbol.strip().upper()
    authenticated, err = await ensure_authenticated_session()
    if not authenticated:
        return create_error_response(Exception(err or "Not authenticated"), "auth")

    import asyncio
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None, lambda: rh.order_sell_limit(symbol, quantity, limit_price)
    )

    if not result or result.get("detail"):
        detail = result.get("detail") if result else "No response from Robinhood"
        return create_error_response(Exception(detail), "place_sell_limit")

    logger.info(f"Sell limit placed: {quantity} {symbol} @ {limit_price} — order_id={result.get('id')}")
    return create_success_response({
        "order_id": result.get("id"),
        "symbol": symbol,
        "side": "sell",
        "type": "limit",
        "quantity": quantity,
        "limit_price": limit_price,
        "state": result.get("state"),
        "created_at": result.get("created_at"),
    })


@handle_robin_stocks_errors
async def cancel_order(order_id: str, confirm: bool) -> dict[str, Any]:
    """Cancels an open stock order by order ID.

    Args:
        order_id: The Robinhood order ID to cancel
        confirm: Must be True to cancel the order — prevents accidental execution
    """
    if not confirm:
        return create_error_response(ValueError(_CONFIRM_REQUIRED), "order confirmation")

    if not order_id or not order_id.strip():
        return create_error_response(ValueError("order_id is required"), "cancel_order")

    authenticated, err = await ensure_authenticated_session()
    if not authenticated:
        return create_error_response(Exception(err or "Not authenticated"), "auth")

    import asyncio
    loop = asyncio.get_event_loop()

    result = await loop.run_in_executor(
        None, lambda: rh.cancel_stock_order(order_id.strip())
    )

    logger.info(f"Cancel requested for order_id={order_id}")
    return create_success_response({
        "order_id": order_id,
        "cancelled": result is not None,
        "detail": result if isinstance(result, str) else None,
    })
