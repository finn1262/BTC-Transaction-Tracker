# BTC Transaction Tracker

A terminal application that aggregates buy/sell Bitcoin market trades from
major crypto exchanges into one sortable, filterable TUI. Built in Python
3.14+ with Textual, aiohttp, and SQLite, following the OOP-first architecture.

## Phase 1 Status

| Layer | Implemented |
|---|---|
| Exchanges | Public buy/sell market trades from Binance, Coinbase Exchange, Kraken, Bybit, OKX, KuCoin, Bitget, MEXC, Gemini |
| Storage | SQLite with integer-satoshi amounts, `(source, external_id)` primary key, indexes, chunked upserts, incremental live writes, CSV export |
| Services | Real-time per-source feed loops, per-source failure isolation with backoff, in-memory deduplicating store, health reporting |
| TUI | Live event-driven table, buy/sell totals, activity sparkline, per-source health, source filters, detail view, help screen, CSV export, responsive layout |

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
| `r` | Fetch immediately from all exchanges |
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

## Real-Time Behavior

Trades stream in automatically; no manual refresh is required.

- Every source runs its own async feed loop. Loops fetch concurrently, merge
  new trades into an in-memory store, and persist only new or changed rows.
- The TUI subscribes to feed events and applies updates incrementally: new
  rows are appended and re-sorted, cells are patched in place, and the table,
  totals, activity chart, and per-source health all update together.
- Rendering is throttled to at most one flush per `UI_FLUSH_INTERVAL_SECONDS`
  (default 0.25s) so bursts of trades cannot flood the UI, and search input
  is debounced.
- A failing source is isolated: it backs off exponentially, its health is
  shown as `error`, and the remaining sources keep streaming. Press `r` to
  retry immediately.
- The table renders at most `RENDER_LIMIT` rows (newest first) while totals
  cover every loaded trade; the live store keeps at most
  `MAX_TRANSACTIONS` entities in memory. SQLite retains the full history.

## Architecture

```
btc_tracker/
├── core/        Application orchestrator + pydantic-settings configuration
├── data/        Transaction domain model + boundary validation schemas
├── fetchers/    Abstract fetcher lifecycle + per-source I/O
├── parsers/     Raw payload -> Transaction mapping
├── storage/     Abstract storage, SQLite backend, CSV export
├── services/    Source services, real-time feed, in-memory transaction store
├── ui/          Textual app, screens, widgets, styles
└── utils/       Logging, formatting, rate limiter
```

Data flow:
`Fetcher -> Parser -> TransactionService feed -> TransactionStore -> TUI events`,
with the feed persisting new/changed rows to storage as a side effect.

Key design rules:

- Amounts are **integer satoshis** end to end; no floats touch financial data.
- Fetchers own I/O, parsers own mapping, services compose the pair.
- Parsing runs in a worker thread: CPU-bound mapping never blocks the event
  loop that drives the TUI.
- Exchange fetchers are market-scoped and never receive a wallet address.
- Exchanges expose **public buy/sell market trades only** (recent BTC pairs,
  no account data). A positive amount is a buy, a negative amount is a sell.
- All network calls are async (`aiohttp`) and paced by an async sliding-window
  `RateLimiter` with exponential backoff and retry.
- The feed and the UI are decoupled by events: the UI never polls for data.
- A failing source is logged, isolated, and retried; other sources continue.

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
| `POLL_INTERVAL_SECONDS` | `5.0` | Seconds between live polls of each source |
| `BACKFILL_PAGES` | `3` | Pages fetched per source on its first feed pass |
| `POLL_PAGES` | `1` | Pages fetched per source on later live polls |
| `HISTORY_LIMIT` | `50000` | Stored rows hydrated into the feed at startup |
| `MAX_TRANSACTIONS` | `50000` | Maximum entities kept in the live in-memory store |
| `RENDER_LIMIT` | `1000` | Maximum rows rendered in the trade table |
| `UI_FLUSH_INTERVAL_SECONDS` | `0.25` | Minimum seconds between UI data flushes |
| `SEARCH_DEBOUNCE_SECONDS` | `0.15` | Debounce applied to search input changes |

## Testing

```bash
python -m pytest
```

The suite covers the transaction store, the real-time feed (incremental
persistence, failure isolation and recovery, event delivery), SQLite storage,
formatting, headless Textual screens (real-time updates, filtering, sorting,
cursor retention, resize profiles, export), performance guardrails, and
bounded high-volume stress runs.

## Notes

- `pandas` is a declared dependency but is imported lazily for batch
  transformations only; startup never loads it.
- `sqlite3` is Python stdlib and intentionally not declared as a dependency.
- Test tooling lives in the `dev` extra so runtime installs stay lean.
