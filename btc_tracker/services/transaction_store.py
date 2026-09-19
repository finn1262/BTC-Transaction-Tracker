"""In-memory, deduplicated transaction store backing the live TUI.

The store is the single source of truth for the UI. It keeps an indexed,
newest-first view of the most recent transactions and derives aggregate
statistics and activity buckets once per change so rendering never re-scans
the full dataset.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone

from btc_tracker.data.models import Transaction

SortKey = tuple[float, str, str]


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
    buy_sats: int = 0
    sell_sats: int = 0
    volume_sats: int = 0
    latest: datetime | None = None


class TransactionStore:
    """Index transactions by ``(source, external_id)`` with cached views.

    All operations are synchronous and intended to run on the event loop:
    merging a batch touches only the batch plus one re-index of the stored
    entities, and :meth:`snapshot`, :meth:`stats`, and activity buckets are
    cached until the next change.
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
        self._index: dict[tuple[str, str], Transaction] = {}
        self._ordered: list[Transaction] = []
        self._snapshot: list[Transaction] | None = None
        self._stats: StoreStats | None = None
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
        unchanged = 0
        for transaction in transactions:
            key = transaction.dedup_key
            existing = self._index.get(key)
            if existing is None:
                self._index[key] = transaction
                added.append(transaction)
            elif self._is_changed(existing, transaction):
                self._index[key] = transaction
                updated.append(transaction)
            else:
                unchanged += 1
        if added or updated:
            self._reindex()
        return MergeResult(tuple(added), tuple(updated), unchanged)

    def snapshot(self) -> list[Transaction]:
        """Return the cached newest-first view of every stored transaction.

        The returned list is owned by the store and must be treated as
        read-only; it is replaced, never mutated, when the store changes.
        """
        if self._snapshot is None:
            self._snapshot = list(self._ordered)
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
        self._ordered = []
        self._snapshot = None
        self._stats = None
        self._activity = {}
        self._version += 1

    def _reindex(self) -> None:
        ordered = sorted(self._index.values(), key=self._sort_key)
        if len(ordered) > self._max_transactions:
            ordered = ordered[: self._max_transactions]
            self._index = {transaction.dedup_key: transaction for transaction in ordered}
        self._ordered = ordered
        self._snapshot = None
        self._stats = None
        self._version += 1
        self._recompute_activity()

    def _recompute_activity(self) -> None:
        activity: dict[int, int] = {}
        for transaction in self._ordered:
            minute = int(transaction.timestamp.timestamp()) // self.ACTIVITY_BUCKET_SECONDS
            activity[minute] = activity.get(minute, 0) + 1
        self._activity = activity

    def _compute_stats(self) -> StoreStats:
        total = len(self._ordered)
        buys = sells = net_sats = volume_sats = 0
        latest: datetime | None = None
        per_source: dict[str, _SourceAccumulator] = {}
        for transaction in self._ordered:
            amount = transaction.amount_sats
            volume_sats += abs(amount)
            net_sats += amount
            if amount > 0:
                buys += 1
            elif amount < 0:
                sells += 1
            if latest is None or transaction.timestamp > latest:
                latest = transaction.timestamp
            accumulator = per_source.setdefault(transaction.source, _SourceAccumulator())
            accumulator.count += 1
            accumulator.volume_sats += abs(amount)
            if amount > 0:
                accumulator.buy_sats += amount
            elif amount < 0:
                accumulator.sell_sats += abs(amount)
            if accumulator.latest is None or transaction.timestamp > accumulator.latest:
                accumulator.latest = transaction.timestamp
        sources = tuple(
            SourceStats(
                name=name,
                count=accumulator.count,
                buy_sats=accumulator.buy_sats,
                sell_sats=accumulator.sell_sats,
                net_sats=accumulator.buy_sats - accumulator.sell_sats,
                volume_sats=accumulator.volume_sats,
                latest=accumulator.latest,
            )
            for name, accumulator in sorted(per_source.items())
        )
        return StoreStats(
            total=total,
            buys=buys,
            sells=sells,
            net_sats=net_sats,
            volume_sats=volume_sats,
            latest=latest,
            sources=sources,
        )

    @staticmethod
    def _sort_key(transaction: Transaction) -> SortKey:
        return (-transaction.timestamp.timestamp(), transaction.source, transaction.external_id)

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
