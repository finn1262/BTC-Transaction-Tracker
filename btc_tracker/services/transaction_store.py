"""In-memory, deduplicated transaction store backing the live TUI.

The store is the single source of truth for the UI. It maintains ordering,
aggregate statistics, and activity buckets incrementally, so small live
batches do not require reprocessing the full transaction history.
"""

from bisect import bisect_left
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from btc_tracker.data.models import Transaction

TransactionKey = tuple[str, str]
SortKey = tuple[float, TransactionKey]


@dataclass(frozen=True)
class MergeResult:
    """Outcome of merging a batch of transactions into the store.

    Attributes:
        added: Transactions whose ``(source, external_id)`` was unseen.
        updated: Known transactions whose fields changed.
        unchanged: Known transactions identical to the stored entity.
    """

    added: tuple[Transaction, ...] = ()
    updated: tuple[Transaction, ...] = ()
    unchanged: int = 0

    @property
    def added_count(self) -> int:
        """Return the number of newly added transactions."""
        return len(self.added)

    @property
    def updated_count(self) -> int:
        """Return the number of updated transactions."""
        return len(self.updated)

    @property
    def changed(self) -> bool:
        """Return whether the merge changed the store."""
        return bool(self.added or self.updated)


@dataclass(frozen=True)
class SourceStats:
    """Per-source aggregate for the statistics panel."""

    name: str
    count: int
    buy_sats: int
    sell_sats: int
    net_sats: int
    volume_sats: int
    latest: datetime | None


@dataclass(frozen=True)
class StoreStats:
    """Whole-store aggregate for the statistics panel."""

    total: int
    buys: int
    sells: int
    net_sats: int
    volume_sats: int
    latest: datetime | None
    sources: tuple[SourceStats, ...]


@dataclass
class _SourceAccumulator:
    count: int = 0
    buys: int = 0
    sells: int = 0
    buy_sats: int = 0
    sell_sats: int = 0
    latest: datetime | None = None
    latest_dirty: bool = False


class TransactionStore:
    """Index transactions by ``(source, external_id)`` with cached views.

    All operations are synchronous and intended to run on the event loop.
    Sort keys are computed only for new or rescheduled transactions; totals
    and activity counts change only for added, updated, or evicted entities.
    Snapshots and statistics are materialized lazily and cached until a change.
    """

    ACTIVITY_BUCKET_SECONDS = 60

    def __init__(self, max_transactions: int = 50_000) -> None:
        """Initialize the store.

        Args:
            max_transactions: Maximum entities retained in memory; the oldest
                are evicted first.

        Raises:
            ValueError: If ``max_transactions`` is less than one.
        """
        if max_transactions < 1:
            raise ValueError("max_transactions must be at least 1")
        self._max_transactions = max_transactions
        self._index: dict[TransactionKey, Transaction] = {}
        self._order: list[SortKey] = []
        self._snapshot: list[Transaction] | None = None
        self._stats: StoreStats | None = None
        self._sources: dict[str, _SourceAccumulator] = {}
        self._activity: dict[int, int] = {}
        self._version = 0

    def __len__(self) -> int:
        return len(self._index)

    @property
    def total(self) -> int:
        """Return the number of stored transactions."""
        return len(self._index)

    @property
    def version(self) -> int:
        """Return a counter that increments on every change.

        Consumers can use the version to cache derived views safely.
        """
        return self._version

    def get(self, source: str, external_id: str) -> Transaction | None:
        """Return one stored transaction by its deduplication key."""
        return self._index.get((source, external_id))

    def merge(self, transactions: Sequence[Transaction]) -> MergeResult:
        """Merge a batch, deduplicating by ``(source, external_id)``.

        Args:
            transactions: Transactions to merge; order is irrelevant.

        Returns:
            The added, updated, and unchanged counts.
        """
        added: list[Transaction] = []
        updated: list[Transaction] = []
        previous: dict[TransactionKey, Transaction | None] = {}
        unchanged = 0
        for transaction in transactions:
            key = transaction.dedup_key
            existing = self._index.get(key)
            if existing is None:
                previous.setdefault(key, None)
                self._index[key] = transaction
                added.append(transaction)
            elif self._is_changed(existing, transaction):
                previous.setdefault(key, existing)
                self._index[key] = transaction
                updated.append(transaction)
            else:
                unchanged += 1
        if previous:
            self._apply_changes(previous)
        return MergeResult(tuple(added), tuple(updated), unchanged)

    def snapshot(self) -> list[Transaction]:
        """Return the cached newest-first view of every stored transaction.

        The returned list is owned by the store and must be treated as
        read-only; it is replaced, never mutated, when the store changes.
        """
        if self._snapshot is None:
            self._snapshot = [self._index[key] for _, key in self._order]
        return self._snapshot

    def stats(self) -> StoreStats:
        """Return cached whole-store aggregates."""
        if self._stats is None:
            self._stats = self._compute_stats()
        return self._stats

    def activity_minutes(
        self, minutes: int, now: datetime | None = None
    ) -> list[int]:
        """Return per-minute transaction counts for the trailing window.

        Args:
            minutes: Number of one-minute buckets to return.
            now: Optional reference time; defaults to the current UTC time.

        Returns:
            Counts ordered oldest bucket first, newest bucket last.
        """
        reference = now or datetime.now(timezone.utc)
        end = int(reference.timestamp()) // self.ACTIVITY_BUCKET_SECONDS
        start = end - max(minutes, 1) + 1
        return [
            self._activity.get(start + offset, 0) for offset in range(max(minutes, 1))
        ]

    def clear(self) -> None:
        """Drop every stored transaction."""
        self._index.clear()
        self._order = []
        self._snapshot = None
        self._stats = None
        self._sources = {}
        self._activity = {}
        self._version += 1

    def _apply_changes(
        self, previous: dict[TransactionKey, Transaction | None]
    ) -> None:
        arrivals: list[SortKey] = []
        for key, existing in previous.items():
            transaction = self._index[key]
            if existing is not None:
                self._adjust_aggregates(existing, -1)
            self._adjust_aggregates(transaction, 1)
            if existing is None:
                arrivals.append(self._sort_key(transaction))
            elif existing.timestamp != transaction.timestamp:
                position = bisect_left(self._order, self._sort_key(existing))
                self._order.pop(position)
                arrivals.append(self._sort_key(transaction))
        if arrivals:
            # Timsort reuses the already-sorted history; only new keys need
            # computing, and status/amount-only updates never sort at all.
            self._order.extend(arrivals)
            self._order.sort()
        while len(self._order) > self._max_transactions:
            _, key = self._order.pop()
            self._adjust_aggregates(self._index.pop(key), -1)
        self._snapshot = None
        self._stats = None
        self._version += 1

    def _adjust_aggregates(self, transaction: Transaction, delta: int) -> None:
        amount = transaction.amount_sats
        timestamp = transaction.timestamp
        source = transaction.source
        accumulator = self._sources.get(source)
        if accumulator is None:
            accumulator = self._sources[source] = _SourceAccumulator()
        accumulator.count += delta
        if amount > 0:
            accumulator.buys += delta
            accumulator.buy_sats += amount * delta
        elif amount < 0:
            accumulator.sells += delta
            accumulator.sell_sats += abs(amount) * delta
        if delta > 0:
            if accumulator.latest is None or timestamp >= accumulator.latest:
                accumulator.latest = timestamp
                accumulator.latest_dirty = False
        elif timestamp == accumulator.latest:
            accumulator.latest_dirty = True
        if not accumulator.count:
            del self._sources[source]

        minute = int(timestamp.timestamp()) // self.ACTIVITY_BUCKET_SECONDS
        count = self._activity.get(minute, 0) + delta
        if count:
            self._activity[minute] = count
        else:
            self._activity.pop(minute, None)

    def _refresh_latest(self) -> None:
        """Repair source timestamps only when their newest trade was removed."""
        pending = {
            name for name, accumulator in self._sources.items()
            if accumulator.latest_dirty
        }
        if not pending:
            return
        for _, key in self._order:
            source = key[0]
            if source in pending:
                accumulator = self._sources[source]
                accumulator.latest = self._index[key].timestamp
                accumulator.latest_dirty = False
                pending.remove(source)
                if not pending:
                    break

    def _compute_stats(self) -> StoreStats:
        self._refresh_latest()
        sources = tuple(
            SourceStats(
                name=name,
                count=accumulator.count,
                buy_sats=accumulator.buy_sats,
                sell_sats=accumulator.sell_sats,
                net_sats=accumulator.buy_sats - accumulator.sell_sats,
                volume_sats=accumulator.buy_sats + accumulator.sell_sats,
                latest=accumulator.latest,
            )
            for name, accumulator in sorted(self._sources.items())
        )
        return StoreStats(
            total=len(self._index),
            buys=sum(accumulator.buys for accumulator in self._sources.values()),
            sells=sum(accumulator.sells for accumulator in self._sources.values()),
            net_sats=sum(source.net_sats for source in sources),
            volume_sats=sum(source.volume_sats for source in sources),
            latest=self._index[self._order[0][1]].timestamp if self._order else None,
            sources=sources,
        )

    @staticmethod
    def _sort_key(transaction: Transaction) -> SortKey:
        return (-transaction.timestamp.timestamp(), transaction.dedup_key)

    @staticmethod
    def _is_changed(existing: Transaction, candidate: Transaction) -> bool:
        return (
            existing.amount_sats != candidate.amount_sats
            or existing.fee_sats != candidate.fee_sats
            or existing.timestamp != candidate.timestamp
            or existing.status != candidate.status
            or existing.address_from != candidate.address_from
            or existing.address_to != candidate.address_to
            or existing.block_number != candidate.block_number
        )
