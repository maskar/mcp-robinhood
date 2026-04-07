"""MCP server for read-only Robinhood portfolio data."""

import asyncio
import sys
from typing import Any

from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from loguru import logger

from mcp_robinhood.config import settings
from mcp_robinhood.tools.rate_limiter import get_rate_limiter
from mcp_robinhood.tools.robinhood_account_tools import (
    get_account_details,
    get_account_info,
    get_portfolio,
    get_positions,
)
from mcp_robinhood.tools.robinhood_advanced_portfolio_tools import (
    get_build_holdings,
    get_build_user_profile,
    get_day_trades,
)
from mcp_robinhood.tools.robinhood_crypto_tools import (
    get_crypto_info,
    get_crypto_positions,
    get_crypto_quote,
)
from mcp_robinhood.tools.robinhood_dividend_tools import (
    get_dividends,
    get_dividends_by_instrument,
    get_interest_payments,
    get_stock_loan_payments,
    get_total_dividends,
)
from mcp_robinhood.tools.robinhood_market_data_tools import (
    get_stock_earnings,
    get_stock_events,
    get_stock_level2_data,
    get_stock_news,
    get_stock_ratings,
    get_stock_splits,
    get_stocks_by_tag,
    get_top_100,
    get_top_movers,
    get_top_movers_sp500,
)
from mcp_robinhood.tools.robinhood_options_tools import (
    find_tradable_options,
    get_aggregate_positions,
    get_all_option_positions,
    get_open_option_positions,
    get_open_option_positions_with_details,
    get_option_historicals,
    get_option_market_data,
    get_options_chains,
)
from mcp_robinhood.tools.robinhood_stock_tools import (
    find_instrument_data,
    get_instruments_by_symbols,
    get_market_hours,
    get_price_history,
    get_pricebook_by_symbol,
    get_stock_info,
    get_stock_price,
    get_stock_quote_by_id,
    search_stocks,
)
from mcp_robinhood.tools.robinhood_tools import list_available_tools
from mcp_robinhood.tools.robinhood_user_profile_tools import (
    get_account_profile,
    get_account_settings,
    get_basic_profile,
    get_complete_profile,
    get_investment_profile,
    get_security_profile,
    get_user_profile,
)
from mcp_robinhood.tools.session_manager import get_session_manager

# Fetch Vault secrets early so they override settings
from mcp_robinhood.vault import fetch_secrets, get_secret

fetch_secrets()


def _cfg(key: str) -> str:
    """Get value from Vault, falling back to settings."""
    return get_secret(key) or getattr(settings, key.lower(), "")


# --- OAuth ---


class _RobinhoodGoogleProvider(GoogleProvider):
    """GoogleProvider with email allowlist."""

    async def verify_token(self, token):
        result = await super().verify_token(token)
        if result is None:
            return None
        email = (result.claims or {}).get("email", "")
        allowed = _cfg("GOOGLE_ALLOWED_EMAIL")
        if allowed and email != allowed:
            logger.warning("Rejected OAuth attempt from: {}", email)
            return None
        return result


auth = None
_client_id = _cfg("GOOGLE_CLIENT_ID")
_public_hostname = _cfg("PUBLIC_HOSTNAME")
if _client_id and _public_hostname:
    auth = _RobinhoodGoogleProvider(
        client_id=_client_id,
        client_secret=_cfg("GOOGLE_CLIENT_SECRET"),
        base_url=f"https://{_public_hostname}",
        required_scopes=["openid", "https://www.googleapis.com/auth/userinfo.email"],
        require_authorization_consent="external",
    )
    logger.info("Google OAuth enabled")


async def _pre_register_client() -> None:
    """Pre-register the Google OAuth client so Claude.ai can use client_id/secret directly."""
    if auth is None or not _client_id:
        return
    from mcp.shared.auth import OAuthClientInformationFull

    try:
        await auth.register_client(
            OAuthClientInformationFull(
                client_id=_client_id,
                client_secret=_cfg("GOOGLE_CLIENT_SECRET"),
                redirect_uris=["https://claude.ai/api/mcp/auth_callback"],
                grant_types=["authorization_code", "refresh_token"],
                scope="openid https://www.googleapis.com/auth/userinfo.email",
                token_endpoint_auth_method="client_secret_post",
                client_name="Claude",
            )
        )
        logger.info("Pre-registered OAuth client: {}", _client_id[:20] + "...")
    except Exception as e:
        logger.warning("Failed to pre-register OAuth client: {}", e)


mcp = FastMCP(
    "Robinhood",
    instructions="Read-only access to Robinhood portfolio data.",
    auth=auth,
)


# --- Utility ---


@mcp.tool()
async def list_tools() -> dict[str, Any]:
    """Provides a list of available tools and their descriptions."""
    return await list_available_tools(mcp)


@mcp.tool()
async def session_status() -> dict[str, Any]:
    """Gets current session status and authentication information."""
    session_manager = get_session_manager()
    session_info = session_manager.get_session_info()
    return {"result": {**session_info, "status": "success"}}


@mcp.tool()
async def rate_limit_status() -> dict[str, Any]:
    """Gets current rate limit usage and statistics."""
    rate_limiter = get_rate_limiter()
    stats = rate_limiter.get_stats()
    return {"result": {**stats, "status": "success"}}


# --- Account & Portfolio ---


@mcp.tool()
async def account_info() -> dict[str, Any]:
    """Gets basic Robinhood account information."""
    return await get_account_info()


@mcp.tool()
async def portfolio() -> dict[str, Any]:
    """Provides a high-level overview of the portfolio."""
    return await get_portfolio()


@mcp.tool()
async def account_details() -> dict[str, Any]:
    """Gets comprehensive account details including buying power and cash balances."""
    return await get_account_details()


@mcp.tool()
async def positions() -> dict[str, Any]:
    """Gets current stock positions with quantities and values."""
    return await get_positions()


@mcp.tool()
async def build_holdings() -> dict[str, Any]:
    """Builds comprehensive holdings with dividend information and performance metrics."""
    return await get_build_holdings()


@mcp.tool()
async def build_user_profile() -> dict[str, Any]:
    """Builds comprehensive user profile with equity, cash, and dividend totals."""
    return await get_build_user_profile()


@mcp.tool()
async def day_trades() -> dict[str, Any]:
    """Gets pattern day trading information and tracking."""
    return await get_day_trades()


# --- Crypto ---


@mcp.tool()
async def crypto_positions() -> dict[str, Any]:
    """Gets current cryptocurrency positions with quantities and market values."""
    return await get_crypto_positions()


@mcp.tool()
async def crypto_quote(symbol: str) -> dict[str, Any]:
    """Gets real-time quote for a cryptocurrency.

    Args:
        symbol: Crypto symbol (e.g., "BTC", "ETH", "DOGE")
    """
    return await get_crypto_quote(symbol)


@mcp.tool()
async def crypto_info(symbol: str) -> dict[str, Any]:
    """Gets detailed information about a cryptocurrency.

    Args:
        symbol: Crypto symbol (e.g., "BTC", "ETH")
    """
    return await get_crypto_info(symbol)


# --- Market Data ---


@mcp.tool()
async def stock_price(symbol: str) -> dict[str, Any]:
    """Gets current stock price and basic metrics.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_price(symbol)


@mcp.tool()
async def stock_info(symbol: str) -> dict[str, Any]:
    """Gets detailed company information and fundamentals.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_info(symbol)


@mcp.tool()
async def search_stocks_tool(query: str) -> dict[str, Any]:
    """Searches for stocks by symbol or company name.

    Args:
        query: Search query (symbol or company name)
    """
    return await search_stocks(query)


@mcp.tool()
async def market_hours() -> dict[str, Any]:
    """Gets current market hours and status."""
    return await get_market_hours()


@mcp.tool()
async def price_history(symbol: str, period: str = "week") -> dict[str, Any]:
    """Gets historical price data for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        period: Time period ("day", "week", "month", "3month", "year", "5year")
    """
    return await get_price_history(symbol, period)


@mcp.tool()
async def instruments_by_symbols(symbols: list[str]) -> dict[str, Any]:
    """Gets detailed instrument metadata for multiple symbols.

    Args:
        symbols: List of stock ticker symbols (e.g., ["AAPL", "GOOGL", "MSFT"])
    """
    return await get_instruments_by_symbols(symbols)


@mcp.tool()
async def find_instruments(query: str) -> dict[str, Any]:
    """Searches for instrument information by various criteria.

    Args:
        query: Search query string
    """
    return await find_instrument_data(query)


@mcp.tool()
async def stock_quote_by_id(instrument_id: str) -> dict[str, Any]:
    """Gets stock quote using Robinhood's internal instrument ID.

    Args:
        instrument_id: Robinhood's internal instrument ID
    """
    return await get_stock_quote_by_id(instrument_id)


@mcp.tool()
async def pricebook_by_symbol(symbol: str) -> dict[str, Any]:
    """Gets Level II order book data for a symbol (requires Gold subscription).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_pricebook_by_symbol(symbol)


# --- Dividends & Income ---


@mcp.tool()
async def dividends() -> dict[str, Any]:
    """Gets all dividend payment history for the account."""
    return await get_dividends()


@mcp.tool()
async def total_dividends() -> dict[str, Any]:
    """Gets total dividends received across all time."""
    return await get_total_dividends()


@mcp.tool()
async def dividends_by_instrument(symbol: str) -> dict[str, Any]:
    """Gets dividend history for a specific stock symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_dividends_by_instrument(symbol)


@mcp.tool()
async def interest_payments() -> dict[str, Any]:
    """Gets interest payment history from cash management."""
    return await get_interest_payments()


@mcp.tool()
async def stock_loan_payments() -> dict[str, Any]:
    """Gets stock loan payment history from the stock lending program."""
    return await get_stock_loan_payments()


# --- Market Research ---


@mcp.tool()
async def top_movers_sp500(direction: str = "up") -> dict[str, Any]:
    """Gets top S&P 500 movers for the day.

    Args:
        direction: Direction of movement, either 'up' or 'down' (default: 'up')
    """
    return await get_top_movers_sp500(direction)


@mcp.tool()
async def top_100_stocks() -> dict[str, Any]:
    """Gets top 100 most popular stocks on Robinhood."""
    return await get_top_100()


@mcp.tool()
async def top_movers() -> dict[str, Any]:
    """Gets top 20 movers on Robinhood."""
    return await get_top_movers()


@mcp.tool()
async def stocks_by_tag(tag: str) -> dict[str, Any]:
    """Gets stocks filtered by market category tag.

    Args:
        tag: Market category tag (e.g., 'technology', 'biopharmaceutical', 'upcoming-earnings')
    """
    return await get_stocks_by_tag(tag)


@mcp.tool()
async def stock_ratings(symbol: str) -> dict[str, Any]:
    """Gets analyst ratings for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_ratings(symbol)


@mcp.tool()
async def stock_earnings(symbol: str) -> dict[str, Any]:
    """Gets earnings reports for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_earnings(symbol)


@mcp.tool()
async def stock_news(symbol: str) -> dict[str, Any]:
    """Gets news stories for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_news(symbol)


@mcp.tool()
async def stock_splits(symbol: str) -> dict[str, Any]:
    """Gets stock split history for a stock.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_splits(symbol)


@mcp.tool()
async def stock_events(symbol: str) -> dict[str, Any]:
    """Gets corporate events for a stock (for owned positions).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_events(symbol)


@mcp.tool()
async def stock_level2_data(symbol: str) -> dict[str, Any]:
    """Gets Level II market data for a stock (Gold subscription required).

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_stock_level2_data(symbol)


# --- Options (read-only) ---


@mcp.tool()
async def options_chains(symbol: str) -> dict[str, Any]:
    """Gets complete option chains for a stock symbol.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
    """
    return await get_options_chains(symbol)


@mcp.tool()
async def find_options(
    symbol: str, expiration_date: str | None = None, option_type: str | None = None
) -> dict[str, Any]:
    """Finds tradable options with optional filtering.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        expiration_date: Optional expiration date in YYYY-MM-DD format
        option_type: Optional option type ("call" or "put")
    """
    return await find_tradable_options(symbol, expiration_date, option_type)


@mcp.tool()
async def option_market_data(option_id: str) -> dict[str, Any]:
    """Gets market data for a specific option contract.

    Args:
        option_id: Unique option contract ID
    """
    return await get_option_market_data(option_id)


@mcp.tool()
async def option_historicals(
    symbol: str,
    expiration_date: str,
    strike_price: str,
    option_type: str,
    interval: str = "hour",
    span: str = "week",
) -> dict[str, Any]:
    """Gets historical price data for an option contract.

    Args:
        symbol: Stock ticker symbol (e.g., "AAPL")
        expiration_date: Expiration date in YYYY-MM-DD format
        strike_price: Strike price as string
        option_type: Option type ("call" or "put")
        interval: Time interval (default: "hour")
        span: Time span (default: "week")
    """
    return await get_option_historicals(
        symbol, expiration_date, strike_price, option_type, interval, span
    )


@mcp.tool()
async def aggregate_option_positions() -> dict[str, Any]:
    """Gets aggregated option positions collapsed by underlying stock."""
    return await get_aggregate_positions()


@mcp.tool()
async def all_option_positions() -> dict[str, Any]:
    """Gets all option positions ever held."""
    return await get_all_option_positions()


@mcp.tool()
async def open_option_positions() -> dict[str, Any]:
    """Gets currently open option positions."""
    return await get_open_option_positions()


@mcp.tool()
async def open_option_positions_with_details() -> dict[str, Any]:
    """Gets currently open option positions with enriched details including call/put type."""
    return await get_open_option_positions_with_details()


# --- User Profile ---


@mcp.tool()
async def account_profile() -> dict[str, Any]:
    """Gets trading account profile and configuration."""
    return await get_account_profile()


@mcp.tool()
async def basic_profile() -> dict[str, Any]:
    """Gets basic user profile information."""
    return await get_basic_profile()


@mcp.tool()
async def investment_profile() -> dict[str, Any]:
    """Gets investment profile and risk assessment."""
    return await get_investment_profile()


@mcp.tool()
async def security_profile() -> dict[str, Any]:
    """Gets security profile and settings."""
    return await get_security_profile()


@mcp.tool()
async def user_profile() -> dict[str, Any]:
    """Gets comprehensive user profile information."""
    return await get_user_profile()


@mcp.tool()
async def complete_profile() -> dict[str, Any]:
    """Gets complete user profile combining all profile types."""
    return await get_complete_profile()


@mcp.tool()
async def account_settings() -> dict[str, Any]:
    """Gets account settings and preferences."""
    return await get_account_settings()


# --- Server ---


def _authenticate() -> None:
    username = _cfg("ROBINHOOD_USERNAME")
    password = _cfg("ROBINHOOD_PASSWORD")
    mfa_code = _cfg("ROBINHOOD_MFA_CODE")
    mfa_secret = _cfg("ROBINHOOD_MFA_SECRET")

    if username and password:
        session_manager = get_session_manager()
        session_manager.set_credentials(username, password, mfa_code, mfa_secret)

        async def do_auth() -> bool:
            return await session_manager.ensure_authenticated()

        try:
            asyncio.run(do_auth())
            logger.info("Logged in to Robinhood")
        except Exception as e:
            logger.error(f"Login failed: {e}")
            logger.warning("Server will start but tools may be unavailable")
    else:
        logger.warning("No Robinhood credentials — set ROBINHOOD_USERNAME and ROBINHOOD_PASSWORD")


def main():
    """Entry point for mcp-robinhood command."""
    _authenticate()
    asyncio.run(_pre_register_client())
    transport = "streamable-http" if settings.mcp_transport == "http" else settings.mcp_transport
    mcp.run(
        transport=transport,
        host=settings.mcp_host,
        port=settings.mcp_port,
    )


if __name__ == "__main__":
    main()
