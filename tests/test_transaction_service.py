"""Unit tests for the real-time transaction feed service."""

import asyncio
from datetime import datetime, timezone

from tests.conftest import (
    FakeSource,
    InMemoryStorage,
    make_transaction,
    ordered_transactions,
    wait_until,
)

from btc_tracker.services.transaction_service import (
    SourceStatusChanged,
    TransactionService,
    TransactionsChanged,
)


def build_service(
    sources,
    storage=None,
    **kwargs,
) -> TransactionService:
    storage = storage or InMemoryStorage()
    options = {"poll_interval": 0.05, "backfill_pages": 3, "poll_pages": 1}
    options.update(kwargs)
    return TransactionService(sources, storage, **options)


class TestLifecycle:
    async def test_start_hydrates_stored_transactions(self) -> None:
        storage = InMemoryStorage(ordered_transactions(5))
        source = FakeSource("binance", batches=[[make_transaction("live-1")]])
        service = build_service([source], storage)
        try:
            await service.start()
            assert service.total >= 5
            assert storage.get_all_calls == 1
            assert await wait_until(lambda: service.total == 6)
        finally:
            await service.stop()

    async def test_start_uses_backfill_then_poll_pages(self) -> None:
        source = FakeSource("binance", batch_size=2)
        service = build_service([source], backfill_pages=4, poll_pages=1)
        try:
            await service.start()
            assert await wait_until(lambda: len(source.pages_seen) >= 2)
            assert source.pages_seen[0] == 4
            assert source.pages_seen[1] == 1
        finally:
            await service.stop()

    async def test_start_is_idempotent(self) -> None:
        source = FakeSource("binance")
        service = build_service([source])
        try:
            await service.start()
            await service.start()
            assert len(service._tasks) == 1  # noqa: SLF001
        finally:
            await service.stop()

    async def test_stop_cancels_feed_loops(self) -> None:
        source = FakeSource("binance")
        service = build_service([source])
        await service.start()
        assert await wait_until(lambda: source.calls >= 1)
        await service.stop()
        calls = source.calls
        await asyncio.sleep(0.15)
        assert source.calls == calls

    async def test_source_names_preserve_order(self) -> None:
        service = build_service(
            [FakeSource("binance"), FakeSource("kraken"), FakeSource("okx")]
        )
        assert service.source_names == ["binance", "kraken", "okx"]

    async def test_requires_sources(self) -> None:
        try:
            build_service([])
        except ValueError:
            return
        raise AssertionError("expected ValueError")


class TestIngestion:
    async def test_duplicate_batches_are_not_repersisted(self) -> None:
        transaction = make_transaction("dup-1")
        source = FakeSource("binance", batches=[[transaction]])
        storage = InMemoryStorage()
        service = build_service([source], storage)
        try:
            await service.start()
            assert await wait_until(lambda: source.calls >= 3)
            assert service.total == 1
            assert len(storage.save_calls) == 1
        finally:
            await service.stop()

    async def test_changed_transactions_are_persisted(self) -> None:
        timestamp = datetime.now(timezone.utc)
        pending = make_transaction("x-1", status="pending", timestamp=timestamp)
        confirmed = make_transaction("x-1", status="confirmed", timestamp=timestamp)
        source = FakeSource("binance", batches=[[pending], [confirmed]])
        storage = InMemoryStorage()
        service = build_service([source], storage)
        try:
            await service.start()
            assert await wait_until(lambda: len(storage.save_calls) == 2)
            assert storage.rows[("binance", "x-1")].status == "confirmed"
        finally:
            await service.stop()

    async def test_multiple_sources_merge_concurrently(self) -> None:
        sources = [
            FakeSource("binance", batch_size=5),
            FakeSource("kraken", batch_size=5),
            FakeSource("okx", batch_size=5),
        ]
        service = build_service(sources)
        try:
            await service.start()
            assert await wait_until(lambda: service.total >= 15)
        finally:
            await service.stop()

    async def test_store_respects_max_transactions(self) -> None:
        source = FakeSource("binance", batch_size=10)
        service = build_service([source], max_transactions=4)
        try:
            await service.start()
            assert await wait_until(lambda: service.total == 4)
            assert service.total == 4
        finally:
            await service.stop()


class TestEvents:
    async def test_emits_transaction_events(self) -> None:
        source = FakeSource("binance", batch_size=2)
        service = build_service([source])
        events = []
        unsubscribe = service.subscribe(events.append)
        try:
            await service.start()
            assert await wait_until(
                lambda: any(isinstance(event, TransactionsChanged) for event in events)
            )
        finally:
            unsubscribe()
            await service.stop()

    async def test_emits_health_events(self) -> None:
        source = FakeSource("binance")
        service = build_service([source])
        events = []
        unsubscribe = service.subscribe(events.append)
        try:
            await service.start()
            assert await wait_until(
                lambda: any(isinstance(event, SourceStatusChanged) for event in events)
            )
        finally:
            unsubscribe()
            await service.stop()

    async def test_unsubscribe_stops_events(self) -> None:
        source = FakeSource("binance", batch_size=1)
        service = build_service([source])
        events = []
        unsubscribe = service.subscribe(events.append)
        try:
            await service.start()
            assert await wait_until(lambda: bool(events))
            unsubscribe()
            count = len(events)
            await asyncio.sleep(0.2)
            assert len(events) == count
        finally:
            await service.stop()

    async def test_broken_listener_does_not_break_feed(self) -> None:
        source = FakeSource("binance", batch_size=1)

        def broken(_event) -> None:
            raise RuntimeError("listener bug")

        service = build_service([source])
        service.subscribe(broken)
        try:
            await service.start()
            assert await wait_until(lambda: service.total >= 1)
        finally:
            await service.stop()


class TestResilience:
    async def test_failing_source_is_isolated(self) -> None:
        bad = FakeSource("bad", error=RuntimeError("boom"))
        good = FakeSource("good", batch_size=2)
        service = build_service([bad, good])
        try:
            await service.start()
            assert await wait_until(lambda: service.total >= 2)

            def health_map():
                return {entry.name: entry for entry in service.health()}

            assert await wait_until(
                lambda: health_map()["bad"].state == "error", timeout=3.0
            )
            assert await wait_until(
                lambda: health_map()["good"].state == "ok", timeout=3.0
            )
            assert "boom" in (health_map()["bad"].last_error or "")
        finally:
            await service.stop()

    async def test_source_recovers_after_failure(self) -> None:
        source = FakeSource("binance", error=RuntimeError("down"), batch_size=1)
        service = build_service([source])
        try:
            await service.start()
            assert await wait_until(
                lambda: service.health()[0].state == "error"
            )
            source.error = None
            service.refresh("binance")
            assert await wait_until(
                lambda: service.health()[0].state == "ok", timeout=3.0
            )
        finally:
            await service.stop()

    async def test_refresh_wakes_loop_early(self) -> None:
        source = FakeSource("binance", batch_size=1)
        service = build_service([source], poll_interval=5.0)
        try:
            await service.start()
            assert await wait_until(lambda: source.calls >= 1)
            service.refresh()
            assert await wait_until(lambda: source.calls >= 2, timeout=1.0)
        finally:
            await service.stop()

    async def test_storage_save_failure_does_not_kill_feed(self) -> None:
        storage = InMemoryStorage()
        storage.fail_saves = True
        source = FakeSource("binance", batch_size=1)
        service = build_service([source], storage)
        try:
            await service.start()
            assert await wait_until(lambda: service.total >= 2)
            storage.fail_saves = False
            assert await wait_until(lambda: bool(storage.save_calls), timeout=2.0)
        finally:
            await service.stop()

    async def test_storage_load_failure_still_starts_feed(self) -> None:
        storage = InMemoryStorage()
        storage.load_error = RuntimeError("db gone")
        source = FakeSource("binance", batch_size=1)
        service = build_service([source], storage)
        try:
            await service.start()
            assert await wait_until(lambda: service.total >= 1)
        finally:
            await service.stop()

    async def test_slow_source_does_not_block_others(self) -> None:
        slow = FakeSource("slow", delay=0.4, batch_size=1)
        fast = FakeSource("fast", batch_size=1)
        service = build_service([slow, fast])
        try:
            await service.start()
            assert await wait_until(lambda: fast.calls >= 1, timeout=2.0)
            assert await wait_until(lambda: service.total >= 1, timeout=2.0)
        finally:
            await service.stop()
