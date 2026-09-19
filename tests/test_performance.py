"""Performance guardrails for parsing, store merges, feeds, and rendering."""

import time
from datetime import datetime, timedelta, timezone

from textual.app import App, ComposeResult

from tests.conftest import (
    FakeSource,
    InMemoryStorage,
    make_transaction,
    ordered_transactions,
    wait_until,
)

from btc_tracker.parsers.binance import BinanceParser
from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.services.transaction_store import TransactionStore
from btc_tracker.ui.components import TransactionTable


def binance_payload(count: int) -> list[dict]:
    now_ms = int(time.time() * 1000)
    return [
        {
            "a": index + 1,
            "p": "60000.12345678",
            "q": "0.00123456",
            "T": now_ms - index,
            "m": bool(index % 2),
        }
        for index in range(count)
    ]


def test_parse_10k_trades_under_two_seconds() -> None:
    parser = BinanceParser()
    payload = binance_payload(10_000)
    start = time.perf_counter()
    transactions = parser.parse(payload)
    elapsed = time.perf_counter() - start
    assert len(transactions) == 10_000
    assert elapsed < 2.0, f"parse took {elapsed:.3f}s"


def test_store_merge_10k_under_one_second() -> None:
    store = TransactionStore(max_transactions=20_000)
    transactions = ordered_transactions(10_000)
    start = time.perf_counter()
    result = store.merge(transactions)
    elapsed = time.perf_counter() - start
    assert result.added_count == 10_000
    assert elapsed < 1.0, f"merge took {elapsed:.3f}s"


def test_store_remerge_10k_is_fast() -> None:
    store = TransactionStore(max_transactions=20_000)
    transactions = ordered_transactions(10_000)
    store.merge(transactions)
    start = time.perf_counter()
    result = store.merge(transactions)
    elapsed = time.perf_counter() - start
    assert result.unchanged == 10_000
    assert elapsed < 1.0, f"remerge took {elapsed:.3f}s"


async def test_feed_pipeline_10k_under_three_seconds() -> None:
    source = FakeSource("binance", batch_size=10_000)
    storage = InMemoryStorage()
    service = TransactionService(
        [source],
        storage,
        poll_interval=30.0,
        backfill_pages=1,
        poll_pages=1,
        max_transactions=50_000,
    )
    try:
        start = time.perf_counter()
        await service.start()
        assert await wait_until(lambda: service.total >= 10_000, timeout=5.0)
        elapsed = time.perf_counter() - start
        assert elapsed < 3.0, f"pipeline took {elapsed:.3f}s"
    finally:
        await service.stop()


async def test_table_render_1000_rows_under_half_second() -> None:
    transactions = ordered_transactions(1_000)
    table = TransactionTable()

    class TableApp(App[None]):
        def compose(self) -> ComposeResult:
            yield table

    app = TableApp()
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        start = time.perf_counter()
        table.set_transactions(transactions)
        elapsed = time.perf_counter() - start
        assert table.row_count == 1_000
        assert elapsed < 0.5, f"table render took {elapsed:.3f}s"


async def test_table_incremental_update_under_fifty_ms() -> None:
    base = ordered_transactions(1_000)
    table = TransactionTable()

    class TableApp(App[None]):
        def compose(self) -> ComposeResult:
            yield table

    app = TableApp()
    async with app.run_test(size=(160, 50)) as pilot:
        await pilot.pause()
        table.set_transactions(base, sort_column="Time", sort_reverse=True)
        now = datetime.now(timezone.utc)
        arrivals = [
            make_transaction(
                f"new-{index}", timestamp=now + timedelta(seconds=index)
            )
            for index in range(25)
        ]
        target = list(reversed(arrivals)) + base
        start = time.perf_counter()
        table.set_transactions(target, sort_column="Time", sort_reverse=True)
        elapsed = time.perf_counter() - start
        assert table.row_count == 1_025
        assert elapsed < 0.05, f"incremental update took {elapsed:.3f}s"
        first = table.coordinate_to_cell_key(
            table.cursor_coordinate
        ).row_key.value
        assert first == "binance:new-24"
