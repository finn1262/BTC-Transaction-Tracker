# BTC Transaction Tracker

A terminal application that aggregates buy/sell Bitcoin market trades from
major crypto exchanges into one sortable, filterable TUI. Built in Python
3.14+ with Textual, aiohttp, and SQLite, following the OOP-first architecture.

## Phase 1 Status

| Layer | Implemented |
|---|---|
| Exchanges | Public buy/sell market trades from Binance, Coinbase Exchange, Kraken, Bybit, OKX, KuCoin, Bitget, MEXC, Gemini |
| Storage | SQLite with integer-satoshi amounts, `(source, external_id)` primary key, indexes, chunked upserts, CSV export |
| Services | Aggregation, per-source failure isolation, deduplication by `(source, external_id)` |
| TUI | Sortable/filterable table of trades, buy/sell totals, source filters, detail view, help screen, CSV export |

## Requirements

- Python 3.14 or newer
- A terminal with true-color support (recommended)

## Setup

Windows quick start:

```bat
install.bat        :: create .venv and install runtime dependencies
install.bat dev    :: also install the test tooling
launch.bat         :: start the app; arguments are forwarded
```

Manual setup (any OS):

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

python -m pip install -e ".[dev]"
```

No API keys are required: exchange fetchers read public market-data
endpoints. Copy `.env.example` to `.env` only if you want to override the
application defaults.

## Running

```bat
launch.bat
launch.bat --log-level DEBUG
```

Or run the Python entrypoint directly:

```bash
python main.py
python main.py --log-level DEBUG
```

After installation the console script is also available:

```bash
btc-tracker
```

## Keybindings

| Key | Action |
|---|---|
| `q` | Quit |
| `r` | Refresh buy/sell trades from all exchanges |
| `s` | Focus the trade search bar |
| `f` | Focus the source filter |
| `t` | Focus the trade table |
| `Tab` | Cycle the source filter |
| `Enter` | Open the selected trade's details |
| `e` | Export the current filtered view to CSV |
| `h` | Help screen |
| `Escape` | Blur the search bar / return from a detail or help screen |

Single-key shortcuts apply when the search bar is not focused; press
`Escape` to blur it.

## Architecture

```
btc_tracker/
├── core/        Application orchestrator + pydantic-settings configuration
├── data/        Transaction domain model + boundary validation schemas
├── fetchers/    Abstract fetcher lifecycle + per-source I/O
├── parsers/     Raw payload -> Transaction mapping
├── storage/     Abstract storage, SQLite backend, CSV export
├── services/    Source services + transaction aggregation
├── ui/          Textual app, screens, widgets, styles
└── utils/       Logging, formatting, rate limiter
```

Data flow: `Fetcher -> Parser -> Transaction -> TransactionService -> Storage -> TUI`.

Key design rules:

- Amounts are **integer satoshis** end to end; no floats touch financial data.
- Fetchers own I/O, parsers own mapping, services compose the pair.
- Exchange fetchers are market-scoped and never receive a wallet address.
- Exchanges expose **public buy/sell market trades only** (recent BTC pairs,
  no account data). A positive amount is a buy, a negative amount is a sell.
- All network calls are async (`aiohttp`) and paced by an async sliding-window
  `RateLimiter` with exponential backoff and retry.
- A failing source is logged and skipped; other sources still complete.

## Configuration

All settings are read from environment variables or `.env`
(see [`.env.example`](.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_PATH` | `btc_tracker.db` | SQLite database file |
| `LOG_LEVEL` | `INFO` | Logging level |
| `HTTP_TIMEOUT_SECONDS` | `30` | Per-request timeout |
| `MAX_RETRIES` | `3` | Attempts per HTTP request |
| `DEFAULT_RATE_LIMIT_REQUESTS` | `10` | Requests allowed per rate-limit window |
| `DEFAULT_RATE_LIMIT_WINDOW_SECONDS` | `1.0` | Rate-limit window length in seconds |

## Testing

```bash
python -m pytest
```

The suite mirrors the package layout and covers unit behavior, mocked network
I/O, the full fetch -> parse -> store -> export pipeline, headless Textual
screens, and the Phase 1 performance targets (10k transactions parsed and
serialized in under 2 seconds; cold start under 3 seconds).

## Notes

- `pandas` is a declared dependency but is imported lazily for batch
  transformations only; startup never loads it.
- `sqlite3` is Python stdlib and intentionally not declared as a dependency.
- Test tooling lives in the `dev` extra so runtime installs stay lean.
