"""MCP tools for Robin Stocks account operations."""

from typing import Any

import robin_stocks.robinhood as rh

from mcp_robinhood.logging_config import logger
from mcp_robinhood.tools.error_handling import (
    create_error_response,
    create_no_data_response,
    create_success_response,
    execute_with_retry,
    handle_robin_stocks_errors,
    log_api_call,
    sanitize_api_response,
    validate_symbol,
)
from mcp_robinhood.tools.session_manager import ensure_authenticated_session


@handle_robin_stocks_errors
async def get_account_info() -> dict[str, Any]:
    """
    Retrieves basic information about the Robinhood account.

    Returns:
        A JSON object containing account details in the result field.
    """
    log_api_call("get_account_info")

    # Get account info with retry logic
    account_info = await execute_with_retry(rh.load_user_profile)

    if not account_info:
        return create_no_data_response("Account information not available")

    # Sanitize sensitive data
    account_info = sanitize_api_response(account_info)

    logger.info("Successfully retrieved account info.")
    return create_success_response(
        {
            "username": account_info.get("username", "N/A"),
            "created_at": account_info.get("created_at", "N/A"),
        }
    )


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@handle_robin_stocks_errors
async def get_portfolio() -> dict[str, Any]:
    """
    Provides a high-level overview of the portfolio.

    `equity` and `market_value` are brokerage-only (stocks/options) — that's how
    Robinhood's portfolio_profile endpoint defines them. `crypto_equity` and
    `total_equity` aggregate crypto holdings on top so the user sees their
    full account value.

    Returns:
        A JSON object containing the portfolio overview in the result field.
    """
    from mcp_robinhood.tools.robinhood_crypto_tools import get_crypto_positions

    log_api_call("get_portfolio")

    portfolio = await execute_with_retry(rh.load_portfolio_profile)

    if not portfolio:
        return create_no_data_response("Portfolio data not available")

    portfolio = sanitize_api_response(portfolio)

    # Aggregate crypto equity. Failures here shouldn't drop the brokerage data —
    # log and report crypto_equity as None so the caller can tell.
    crypto_equity: float | None = None
    try:
        crypto_resp = await get_crypto_positions()
        crypto_positions = crypto_resp.get("result", {}).get("positions", [])
        crypto_equity = sum(_to_float(p.get("equity")) for p in crypto_positions)
    except Exception as exc:
        logger.warning(f"Failed to compute crypto equity for portfolio: {exc}")

    brokerage_equity = _to_float(portfolio.get("equity"))
    total_equity: float | None = (
        brokerage_equity + crypto_equity if crypto_equity is not None else None
    )

    logger.info("Successfully retrieved portfolio overview.")
    return create_success_response(
        {
            "market_value": portfolio.get("market_value", "N/A"),
            "equity": portfolio.get("equity", "N/A"),
            "crypto_equity": crypto_equity,
            "total_equity": total_equity,
            "buying_power": portfolio.get("buying_power", "N/A"),
        }
    )


@handle_robin_stocks_errors
async def get_account_details() -> dict[str, Any]:
    """
    Retrieves comprehensive account details including buying power and cash balances.

    Aggregates data from load_account_profile (cash, buying power, margin balances)
    and load_portfolio_profile (equity), plus crypto positions for total_equity.
    Replaces the prior load_phoenix_account source — that endpoint now blocks
    non-mobile-app TLS fingerprints at the CloudFront edge.

    Returns:
        A JSON object with account details in the result field. Monetary fields
        are decimal strings (e.g. "9723.99"). near_margin_call is bool.
    """
    from mcp_robinhood.tools.robinhood_crypto_tools import get_crypto_positions

    log_api_call("get_account_details")

    account = await execute_with_retry(rh.load_account_profile)
    if not account:
        return create_no_data_response("No account data found")
    account = sanitize_api_response(account)

    portfolio = await execute_with_retry(rh.load_portfolio_profile)
    portfolio = sanitize_api_response(portfolio) if portfolio else {}

    margin_balances = account.get("margin_balances") or {}
    portfolio_equity = portfolio.get("equity")

    crypto_equity: float | None = None
    try:
        crypto_resp = await get_crypto_positions()
        crypto_positions = crypto_resp.get("result", {}).get("positions", [])
        crypto_equity = sum(_to_float(p.get("equity")) for p in crypto_positions)
    except Exception as exc:
        logger.warning(f"Failed to compute crypto equity for account_details: {exc}")

    total_equity: float | None = None
    if portfolio_equity is not None and crypto_equity is not None:
        total_equity = _to_float(portfolio_equity) + crypto_equity

    logger.info("Successfully retrieved account details.")
    return create_success_response(
        {
            "account_number": account.get("account_number", "N/A"),
            "account_type": account.get("type", "N/A"),
            "portfolio_equity": portfolio_equity if portfolio_equity is not None else "N/A",
            "crypto_equity": crypto_equity,
            "total_equity": total_equity,
            "account_buying_power": account.get("buying_power", "N/A"),
            "options_buying_power": account.get("buying_power", "N/A"),
            "crypto_buying_power": account.get("crypto_buying_power", "N/A"),
            "day_trade_buying_power": margin_balances.get(
                "day_trade_buying_power", "N/A"
            ),
            "overnight_buying_power": margin_balances.get(
                "overnight_buying_power", "N/A"
            ),
            "uninvested_cash": account.get("cash", "N/A"),
            "withdrawable_cash": account.get("cash_available_for_withdrawal", "N/A"),
            "cash_available_from_instant_deposits": margin_balances.get(
                "eligible_deposit_as_instant", "N/A"
            ),
            "cash_held_for_orders": account.get("cash_held_for_orders", "N/A"),
            "unsettled_funds": account.get("unsettled_funds", "N/A"),
            "unsettled_debit": account.get("unsettled_debit", "N/A"),
            "margin_amount_borrowed": margin_balances.get(
                "settled_amount_borrowed", "N/A"
            ),
            "margin_outstanding_interest": margin_balances.get(
                "outstanding_interest", "N/A"
            ),
            "near_margin_call": False,
            "pattern_day_trader": margin_balances.get("is_pdt_forever", False),
        }
    )


@handle_robin_stocks_errors
async def get_positions() -> dict[str, Any]:
    """
    Retrieves current stock positions with quantities and values.

    Returns:
        A JSON object containing current stock positions in the result field.
    """
    log_api_call("get_positions")

    # Get positions with retry logic
    positions = await execute_with_retry(rh.get_open_stock_positions)

    if not positions:
        return create_success_response(
            {"positions": [], "count": 0, "message": "No open stock positions found."}
        )

    position_list = []
    for position in positions:
        # Get symbol from instrument URL with retry logic
        instrument_url = position.get("instrument")
        symbol = "N/A"
        if instrument_url:
            try:
                symbol = await execute_with_retry(rh.get_symbol_by_url, instrument_url)
            except Exception as e:
                logger.warning(
                    f"Failed to get symbol for instrument {instrument_url}: {e}"
                )

        quantity = position.get("quantity", "0")

        # Only include positions with non-zero quantity
        if float(quantity) > 0:
            position_data = {
                "symbol": symbol,
                "quantity": quantity,
                "average_buy_price": position.get("average_buy_price", "0"),
                "updated_at": position.get("updated_at", "N/A"),
            }
            position_list.append(position_data)

    logger.info("Successfully retrieved current positions.")
    return create_success_response(
        {"positions": position_list, "count": len(position_list)}
    )


@handle_robin_stocks_errors
async def get_position_for_symbol(symbol: str) -> dict[str, Any]:
    """Gets the current position for a single stock symbol including quantity, cost basis, current value, and P&L.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    if not validate_symbol(symbol):
        return create_error_response(ValueError(f"Invalid symbol: {symbol}"), "symbol validation")

    symbol = symbol.strip().upper()
    authenticated, err = await ensure_authenticated_session()
    if not authenticated:
        return create_error_response(Exception(err or "Not authenticated"), "auth")

    log_api_call("get_position_for_symbol", symbol=symbol)

    import asyncio
    loop = asyncio.get_event_loop()

    positions = await execute_with_retry(rh.get_open_stock_positions)
    if not positions:
        return create_no_data_response(f"No open positions found", {"symbol": symbol})

    # Find matching position by resolving symbol for each
    matched = None
    for pos in positions:
        instrument_url = pos.get("instrument", "")
        try:
            pos_symbol = await loop.run_in_executor(None, rh.get_symbol_by_url, instrument_url)
            if pos_symbol and pos_symbol.upper() == symbol:
                matched = pos
                break
        except Exception:
            continue

    if not matched:
        return create_no_data_response(f"No open position found for {symbol}", {"symbol": symbol})

    quantity = float(matched.get("quantity", 0))
    avg_price = float(matched.get("average_buy_price", 0))
    total_cost = round(quantity * avg_price, 2)

    price_str = await execute_with_retry(rh.get_latest_price, symbol)
    current_price = float(price_str[0]) if price_str and price_str[0] else 0.0
    current_value = round(quantity * current_price, 2)
    unrealized_gain = round(current_value - total_cost, 2)
    unrealized_pct = round((unrealized_gain / total_cost * 100), 2) if total_cost else 0.0

    logger.info(f"Position for {symbol}: {quantity} shares, unrealized={unrealized_gain}")
    return create_success_response({
        "symbol": symbol,
        "quantity": quantity,
        "average_buy_price": round(avg_price, 4),
        "total_cost": total_cost,
        "current_price": round(current_price, 4),
        "current_value": current_value,
        "unrealized_gain_loss": unrealized_gain,
        "unrealized_gain_loss_pct": unrealized_pct,
        "shares_held_for_sells": float(matched.get("shares_held_for_sells", 0)),
        "updated_at": matched.get("updated_at", ""),
    })
