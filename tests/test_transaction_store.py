"""Unit tests for the in-memory transaction store."""

from datetime import datetime, timedelta, timezone

from tests.conftest import make_transaction, ordered_transactions


class TestMerge:
    def test_adds_new_transactions(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        result = store.merge([make_transaction("a"), make_transaction("b")])
        assert result.added_count == 2
        assert result.updated_count == 0
        assert result.unchanged == 0
        assert store.total == 2

    def test_deduplicates_by_source_and_external_id(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        transaction = make_transaction("a", "binance")
        store.merge([transaction])
        result = store.merge([transaction, make_transaction("a", "coinbase")])
        assert result.added_count == 1
        assert result.unchanged == 1
        assert store.total == 2

    def test_detects_updates(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        timestamp = datetime.now(timezone.utc)
        store.merge([make_transaction("a", status="pending", timestamp=timestamp)])
        updated = make_transaction("a", status="confirmed", timestamp=timestamp)
        result = store.merge([updated])
        assert result.updated_count == 1
        assert result.added_count == 0
        assert store.get("binance", "a") is updated

    def test_identical_transaction_is_unchanged(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        timestamp = datetime.now(timezone.utc)
        transaction = make_transaction("a", amount_sats=5, timestamp=timestamp)
        store.merge([transaction])
        result = store.merge([transaction])
        assert result.changed is False
        assert result.unchanged == 1


class TestSnapshot:
    def test_snapshot_is_newest_first(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        store.merge(ordered_transactions(5))
        snapshot = store.snapshot()
        timestamps = [transaction.timestamp for transaction in snapshot]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_snapshot_is_cached_until_change(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        store.merge(ordered_transactions(3))
        first = store.snapshot()
        assert store.snapshot() is first
        store.merge([make_transaction("new", timestamp=datetime.now(timezone.utc))])
        assert store.snapshot() is not first

    def test_version_increments_on_change(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        before = store.version
        batch = ordered_transactions(2)
        store.merge(batch)
        assert store.version > before
        stable = store.version
        store.merge(batch)
        assert store.version == stable


class TestStats:
    def test_totals_and_per_source(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        now = datetime.now(timezone.utc)
        store = TransactionStore()
        store.merge(
            [
                make_transaction("a", "binance", amount_sats=100, timestamp=now),
                make_transaction("b", "binance", amount_sats=-40, timestamp=now),
                make_transaction("c", "kraken", amount_sats=10, timestamp=now),
            ]
        )
        stats = store.stats()
        assert stats.total == 3
        assert stats.buys == 2
        assert stats.sells == 1
        assert stats.net_sats == 70
        assert stats.volume_sats == 150
        by_name = {source.name: source for source in stats.sources}
        assert by_name["binance"].count == 2
        assert by_name["binance"].net_sats == 60
        assert by_name["kraken"].net_sats == 10

    def test_stats_cache_invalidated(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        store.merge(ordered_transactions(2))
        first = store.stats()
        assert store.stats() is first
        store.merge([make_transaction("extra")])
        assert store.stats() is not first


class TestActivity:
    def test_activity_buckets_count_per_minute(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        now = datetime.now(timezone.utc).replace(second=30, microsecond=0)
        store = TransactionStore()
        store.merge(
            [
                make_transaction("a", timestamp=now),
                make_transaction("b", timestamp=now - timedelta(seconds=10)),
                make_transaction("c", timestamp=now - timedelta(minutes=2)),
            ]
        )
        buckets = store.activity_minutes(3, now=now)
        assert buckets == [1, 0, 2]

    def test_activity_window_length(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        store.merge(ordered_transactions(3))
        assert len(store.activity_minutes(30)) == 30


class TestBounds:
    def test_prunes_oldest_transactions(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore(max_transactions=3)
        store.merge(ordered_transactions(10))
        assert store.total == 3
        snapshot = store.snapshot()
        newest = snapshot[0]
        assert newest.external_id == "binance-0"
        assert snapshot[-1].external_id == "binance-2"

    def test_rejects_invalid_capacity(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        try:
            TransactionStore(max_transactions=0)
        except ValueError:
            return
        raise AssertionError("expected ValueError")

    def test_clear_resets_store(self) -> None:
        from btc_tracker.services.transaction_store import TransactionStore

        store = TransactionStore()
        store.merge(ordered_transactions(3))
        store.clear()
        assert store.total == 0
        assert store.snapshot() == []
