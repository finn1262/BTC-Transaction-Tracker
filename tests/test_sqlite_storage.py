"""Unit tests for the SQLite storage backend."""

import asyncio
from pathlib import Path
from threading import Event

import pytest

from tests.conftest import make_transaction

from btc_tracker.data.models import Transaction
from btc_tracker.storage.sqlite import SQLiteStorage


@pytest.fixture()
def storage(tmp_path: Path) -> SQLiteStorage:
    return SQLiteStorage(tmp_path / "test.db")


class TestRoundTrip:
    async def test_save_and_get_all(self, storage: SQLiteStorage) -> None:
        transactions = [
            make_transaction("a", "binance", amount_sats=100),
            make_transaction("b", "kraken", amount_sats=-50),
        ]
        written = await storage.save(transactions)
        assert written == 2
        loaded = await storage.get_all()
        assert {transaction.external_id for transaction in loaded} == {"a", "b"}

    async def test_save_empty_batch(self, storage: SQLiteStorage) -> None:
        assert await storage.save([]) == 0

    async def test_upsert_updates_existing_row(self, storage: SQLiteStorage) -> None:
        await storage.save([make_transaction("a", status="pending")])
        await storage.save([make_transaction("a", status="confirmed")])
        loaded = await storage.get_all()
        assert len(loaded) == 1
        assert loaded[0].status == "confirmed"

    async def test_find_by_external_id(self, storage: SQLiteStorage) -> None:
        await storage.save([make_transaction("a", "binance"), make_transaction("a", "kraken")])
        found = await storage.find_by_external_id("a", "kraken")
        assert found is not None
        assert found.source == "kraken"
        assert await storage.find_by_external_id("missing") is None

    async def test_count_and_delete(self, storage: SQLiteStorage) -> None:
        await storage.save([make_transaction("a"), make_transaction("b")])
        assert await storage.count() == 2
        assert await storage.delete("binance", "a") is True
        assert await storage.delete("binance", "a") is False
        assert await storage.count() == 1

    async def test_get_all_honors_limit(self, storage: SQLiteStorage) -> None:
        await storage.save([make_transaction(str(index)) for index in range(10)])
        assert len(await storage.get_all(limit=3)) == 3

    async def test_persists_across_instances(self, tmp_path: Path) -> None:
        first = SQLiteStorage(tmp_path / "shared.db")
        await first.save([make_transaction("a")])
        second = SQLiteStorage(tmp_path / "shared.db")
        assert await second.count() == 1

    async def test_amounts_round_trip_as_integers(self, storage: SQLiteStorage) -> None:
        transaction = make_transaction("a", amount_sats=-123_456_789)
        await storage.save([transaction])
        loaded = (await storage.get_all())[0]
        assert loaded.amount_sats == -123_456_789
        assert isinstance(loaded.amount_sats, int)

    async def test_large_batch_is_chunked(self, storage: SQLiteStorage) -> None:
        transactions = [make_transaction(str(index)) for index in range(1_500)]
        assert await storage.save(transactions) == 1_500
        assert await storage.count() == 1_500

    async def test_history_conversion_keeps_event_loop_responsive(
        self, storage: SQLiteStorage, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        transaction = make_transaction("history")
        await storage.save([transaction])
        loop = asyncio.get_running_loop()
        started = asyncio.Event()
        release = Event()
        from_dict = Transaction.from_dict

        def slow_conversion(data: dict) -> Transaction:
            loop.call_soon_threadsafe(started.set)
            if not release.wait(timeout=2.0):
                raise TimeoutError("event loop stalled during history conversion")
            return from_dict(data)

        monkeypatch.setattr(Transaction, "from_dict", slow_conversion)
        load = asyncio.create_task(storage.get_all())
        try:
            # The event loop must be able to respond while conversion is busy.
            await asyncio.wait_for(started.wait(), timeout=3.0)
            assert not load.done()
        finally:
            release.set()
            loaded = await load
        assert loaded == [transaction]
