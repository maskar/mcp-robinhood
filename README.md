# mcp-robinhood

Read-only MCP server for Robinhood portfolio data. Provides AI agents with
access to account holdings, market data, and research — no trading capabilities.

Forked from [open-stocks-mcp](https://github.com/Open-Agent-Tools/open-stocks-mcp)
(Apache 2.0). Stripped to Robinhood-only, read-only tools.

## Features

### Account & Portfolio (7 tools)

| Tool | Description |
|------|-------------|
| `account_info` | Basic account information |
| `account_details` | Buying power, cash balances, margin status |
| `portfolio` | High-level portfolio overview |
| `positions` | Current stock positions with quantities and values |
| `build_holdings` | Comprehensive holdings with cost basis and performance |
| `build_user_profile` | Equity, cash, and dividend totals |
| `day_trades` | Pattern day trading count and PDT status |

### Crypto (3 tools)

| Tool | Description |
|------|-------------|
| `crypto_positions` | Current positions with quantities, prices, and P&L |
| `crypto_quote` | Real-time quote (mark, bid, ask, high, low, open) |
| `crypto_info` | Detailed cryptocurrency metadata |

### Market Data (10 tools)

| Tool | Description |
|------|-------------|
| `stock_price` | Current price and basic metrics |
| `stock_info` | Company fundamentals |
| `search_stocks_tool` | Search by symbol or company name |
| `market_hours` | Market hours and status |
| `price_history` | Historical prices (day/week/month/year) |
| `instruments_by_symbols` | Instrument metadata for multiple symbols |
| `find_instruments` | Search instruments by various criteria |
| `stock_quote_by_id` | Quote by Robinhood instrument ID |
| `pricebook_by_symbol` | Level II order book (Gold required) |
| `stock_level2_data` | Level II market data (Gold required) |

### Market Research (7 tools)

| Tool | Description |
|------|-------------|
| `top_movers_sp500` | S&P 500 top movers (up/down) |
| `top_100_stocks` | 100 most popular stocks on Robinhood |
| `top_movers` | Top 20 movers |
| `stocks_by_tag` | Filter by category (technology, biotech, etc.) |
| `stock_ratings` | Analyst ratings |
| `stock_earnings` | Earnings reports and EPS data |
| `stock_news` | News stories for a stock |
| `stock_splits` | Stock split history |
| `stock_events` | Corporate events for owned positions |

### Dividends & Income (5 tools)

| Tool | Description |
|------|-------------|
| `dividends` | All dividend payment history |
| `total_dividends` | Total dividends received all-time |
| `dividends_by_instrument` | Dividend history for a specific stock |
| `interest_payments` | Interest from cash management |
| `stock_loan_payments` | Stock lending program payments |

### Options (8 tools, read-only)

| Tool | Description |
|------|-------------|
| `options_chains` | Complete option chains for a symbol |
| `find_options` | Find options with expiration/type filters |
| `option_market_data` | Market data for a specific contract |
| `option_historicals` | Historical price data for a contract |
| `aggregate_option_positions` | Positions collapsed by underlying |
| `all_option_positions` | All option positions ever held |
| `open_option_positions` | Currently open positions |
| `open_option_positions_with_details` | Open positions with call/put enrichment |

### User Profile (7 tools)

| Tool | Description |
|------|-------------|
| `account_profile` | Trading account configuration |
| `basic_profile` | Basic user info |
| `investment_profile` | Risk assessment |
| `security_profile` | Security settings |
| `user_profile` | Comprehensive profile |
| `complete_profile` | All profile types combined |
| `account_settings` | Account preferences |

### Utility (3 tools)

| Tool | Description |
|------|-------------|
| `list_tools` | List all available tools |
| `session_status` | Authentication and session info |
| `rate_limit_status` | API rate limit usage |

## Setup

```bash
uv sync
cp .env.example .env
# Edit .env with your Robinhood credentials
```

## Configuration

```env
ROBINHOOD_USERNAME=you@example.com
ROBINHOOD_PASSWORD=your-password
# Optional: TOTP seed for 2FA
# ROBINHOOD_MFA_SECRET=AAAA BBBB CCCC DDDD
# Optional: one-time MFA code (e.g. from 1Password CLI)
# ROBINHOOD_MFA_CODE=123456
```

## Usage

```bash
# Run as MCP server (stdio)
just run

# Dev mode (inspector)
just dev
```

### Claude Desktop

Add to your Claude Desktop MCP config:

```json
{
  "mcpServers": {
    "robinhood": {
      "command": "uv",
      "args": ["--directory", "/path/to/mcp-robinhood", "run", "mcp-robinhood"],
      "env": {
        "ROBINHOOD_USERNAME": "you@example.com",
        "ROBINHOOD_PASSWORD": "your-password"
      }
    }
  }
}
```

## Project Structure

```text
mcp-robinhood/
├── src/mcp_robinhood/
│   ├── server/
│   │   └── app.py              # MCP server and tool registration
│   ├── tools/
│   │   ├── robinhood_account_tools.py
│   │   ├── robinhood_advanced_portfolio_tools.py
│   │   ├── robinhood_crypto_tools.py
│   │   ├── robinhood_dividend_tools.py
│   │   ├── robinhood_market_data_tools.py
│   │   ├── robinhood_options_tools.py
│   │   ├── robinhood_stock_tools.py
│   │   ├── robinhood_user_profile_tools.py
│   │   ├── robinhood_tools.py
│   │   ├── session_manager.py   # Auth session with auto-refresh
│   │   ├── error_handling.py    # Typed errors and response helpers
│   │   └── rate_limiter.py      # API rate limiting
│   ├── config.py
│   └── logging_config.py
├── tests/
├── pyproject.toml
├── justfile
└── LICENSE                      # Apache 2.0
```

## Acknowledgments

Based on [open-stocks-mcp](https://github.com/Open-Agent-Tools/open-stocks-mcp)
by [Open Agent Tools](https://github.com/Open-Agent-Tools), licensed under
Apache 2.0. Original trading, Schwab, and notification tools removed; retained
read-only Robinhood tools with modified configuration and project structure.
