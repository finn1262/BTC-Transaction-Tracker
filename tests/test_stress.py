"""Bounded stress tests: high volume, many sources, and long sessions."""

import asyncio

from tests.conftest import (
    FakeSource,
    InMemoryStorage,
    build_test_app,
    build_test_config,
    wait_until,
)

from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.ui.components import TransactionTable


async def test_high_volume_multi_source_stays_bounded() -> None:
    sources = [
        FakeSource("binance", batch_size=50),
        FakeSource("kraken", batch_size=50),
        FakeSource("okx", batch_size=50),
        FakeSource("coinbase", batch_size=50),
    ]
    storage = InMemoryStorage()
    service = TransactionService(
        sources,
        storage,
        poll_interval=0.02,
        backfill_pages=1,
        poll_pages=1,
        max_transactions=500,
    )
    drift: list[float] = []

    async def ticker() -> None:
        loop = asyncio.get_running_loop()
        previous = loop.time()
        while True:
            await asyncio.sleep(0.01)
            now = loop.time()
            drift.append(now - previous - 0.01)
            previous = now

    try:
        await service.start()
        task = asyncio.create_task(ticker())
        assert await wait_until(lambda: service.total >= 400, timeout=4.0)
        await asyncio.sleep(0.4)
        task.cancel()
        assert service.total <= 500
        assert len(storage.rows) >= service.total
        saved_ids = [
            transaction.dedup_key
            for batch in storage.save_calls
            for transaction in batch
        ]
        assert len(saved_ids) == len(set(saved_ids)), "feed persisted duplicates"
        assert max(drift) < 0.25, f"event loop stalled for {max(drift):.3f}s"
    finally:
        await service.stop()


async def test_continuous_arrivals_keep_tui_updated_and_capped() -> None:
    source = FakeSource("binance", batch_size=20)
    config = build_test_config(
        poll_interval_seconds=0.02,
        render_limit=25,
        max_transactions=200,
    )
    app, screen, service, _ = build_test_app([source], config=config)
    try:
        async with app.run_test(size=(120, 30)) as pilot:
            table = screen.query_one(TransactionTable)
            assert await wait_until(lambda: table.row_count > 0, timeout=3.0)
            first = service.total
            assert await wait_until(lambda: service.total > first, timeout=3.0)
            await asyncio.sleep(0.4)
            await pilot.pause()
            assert table.row_count <= 25
            assert service.total <= 200
    finally:
        await service.stop()


async def test_failure_and_recovery_under_load() -> None:
    flaky = FakeSource("flaky", batch_size=10, error=RuntimeError("temporary"))
    stable = FakeSource("stable", batch_size=10)
    service = TransactionService(
        [flaky, stable],
        InMemoryStorage(),
        poll_interval=0.05,
        max_transactions=1_000,
    )
    try:
        await service.start()
        assert await wait_until(lambda: service.total >= 10, timeout=3.0)
        assert await wait_until(
            lambda: service.health()[0].state == "error", timeout=3.0
        )
        flaky.error = None
        service.refresh()
        assert await wait_until(
            lambda: service.health()[0].state == "ok", timeout=3.0
        )
        assert service.total >= 20
    finally:
        await service.stop()
