"""Real-time transaction feed: aggregate sources, persist, and notify.

This service is the bridge between the data-acquisition layer and the TUI.
Each source owns an independent async loop that fetches recent market trades,
merges them into the in-memory :class:`TransactionStore`, persists only new or
changed rows, and emits events. The UI never polls for data; it subscribes and
applies whatever the feed reports.
"""

import asyncio
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Literal

from btc_tracker.data.models import Transaction
from btc_tracker.services.base import AbstractSourceService
from btc_tracker.services.transaction_store import (
    MergeResult,
    StoreStats,
    TransactionStore,
)
from btc_tracker.storage.base import AbstractStorage
from btc_tracker.utils.logger import LoggerFactory

SourceState = Literal["idle", "fetching", "ok", "error"]


@dataclass(frozen=True)
class SourceHealth:
    """Live status of one feed source."""

    name: str
    state: SourceState = "idle"
    last_success: datetime | None = None
    last_error: str | None = None
    consecutive_failures: int = 0
    last_batch: int = 0


@dataclass(frozen=True)
class TransactionsChanged:
    """Emitted after a merge changed the store."""

    added: int
    updated: int
    total: int


@dataclass(frozen=True)
class SourceStatusChanged:
    """Emitted after a source's health changed."""

    health: SourceHealth


ServiceEvent = TransactionsChanged | SourceStatusChanged
Listener = Callable[[ServiceEvent], None]


class TransactionService:
    """Own the live transaction feed consumed by the TUI.

    The service hydrates the store from storage on :meth:`start`, then runs
    one loop per source. Loops fetch concurrently, back off exponentially on
    failure, and can be woken early with :meth:`refresh`.
    """

    MAX_BACKOFF_SECONDS = 60.0

    def __init__(
        self,
        sources: Sequence[AbstractSourceService],
        storage: AbstractStorage,
        logger: Any = None,
        *,
        poll_interval: float = 5.0,
        backfill_pages: int = 3,
        poll_pages: int = 1,
        history_limit: int = 50_000,
        max_transactions: int = 50_000,
    ) -> None:
        """Initialize the feed.

        Args:
            sources: Source services to aggregate.
            storage: Persistence backend for incremental writes.
            logger: Optional logger.
            poll_interval: Seconds between live polls of one source.
            backfill_pages: Pages fetched on each source's first pass.
            poll_pages: Pages fetched on later live polls.
            history_limit: Maximum stored rows hydrated at startup.
            max_transactions: Maximum entities retained in memory.

        Raises:
            ValueError: If ``poll_interval`` is not positive or no sources exist.
        """
        if poll_interval <= 0:
            raise ValueError("poll_interval must be positive")
        if not sources:
            raise ValueError("at least one source is required")
        self._sources = list(sources)
        self._source_names = [source.source_name for source in self._sources]
        self._store = TransactionStore(max_transactions=max_transactions)
        self._storage = storage
        self._logger = logger or LoggerFactory.create("services.transaction")
        self._poll_interval = poll_interval
        self._backfill_pages = max(1, backfill_pages)
        self._poll_pages = max(1, poll_pages)
        self._history_limit = max(1, history_limit)
        self._listeners: list[Listener] = []
        self._health: dict[str, SourceHealth] = {
            name: SourceHealth(name=name) for name in self._source_names
        }
        self._wakeups: dict[str, asyncio.Event] = {
            name: asyncio.Event() for name in self._source_names
        }
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False

    @property
    def source_names(self) -> list[str]:
        """Return the configured source names in display order."""
        return list(self._source_names)

    @property
    def total(self) -> int:
        """Return the number of transactions in the live store."""
        return self._store.total

    @property
    def version(self) -> int:
        """Return the store version, incremented on every change."""
        return self._store.version

    def snapshot(self) -> list[Transaction]:
        """Return the newest-first view of every stored transaction."""
        return self._store.snapshot()

    def stats(self) -> StoreStats:
        """Return aggregate statistics for the store."""
        return self._store.stats()

    def activity_minutes(self, minutes: int) -> list[int]:
        """Return per-minute transaction counts for the trailing window."""
        return self._store.activity_minutes(minutes)

    def health(self) -> tuple[SourceHealth, ...]:
        """Return per-source health in display order."""
        return tuple(self._health[name] for name in self._source_names)

    def subscribe(self, listener: Listener) -> Callable[[], None]:
        """Register a listener and return its unsubscribe callable.

        Args:
            listener: Callable invoked with each :data:`ServiceEvent`.

        Returns:
            A callable that removes the listener.
        """
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    async def start(self) -> None:
        """Hydrate from storage and start one feed loop per source."""
        if self._running:
            return
        self._running = True
        stored: list[Transaction] = []
        try:
            stored = await self._storage.get_all(limit=self._history_limit)
        except Exception as exc:  # storage must never stop the live feed
            self._logger.warning("failed to load stored transactions: %s", exc)
        if stored:
            self._store.merge(stored)
            self._logger.info("hydrated %d stored transactions", len(stored))
        for index, source in enumerate(self._sources):
            name = source.source_name
            self._tasks[name] = asyncio.create_task(
                self._run_source(source, index), name=f"btc-feed:{name}"
            )
        self._logger.info("live feed started for %d sources", len(self._sources))

    async def stop(self) -> None:
        """Cancel every feed loop and wait for them to finish."""
        self._running = False
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._logger.info("live feed stopped")

    def refresh(self, source_name: str | None = None) -> None:
        """Wake one or all feed loops for an immediate fetch.

        Args:
            source_name: Optional source to refresh; all sources when omitted.
        """
        for name, event in self._wakeups.items():
            if source_name is None or source_name == name:
                event.set()

    async def _run_source(self, source: AbstractSourceService, index: int) -> None:
        name = source.source_name
        failures = 0
        first = True
        delay = random.uniform(0.0, 0.4) + index * 0.1
        while self._running:
            if delay > 0:
                await asyncio.sleep(delay)
            if not self._running:
                break
            self._wakeups[name].clear()
            pages = self._backfill_pages if first else self._poll_pages
            self._update_health(name, state="fetching")
            try:
                transactions = await source.fetch_transactions(pages=pages)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures += 1
                self._update_health(
                    name,
                    state="error",
                    last_error=str(exc) or type(exc).__name__,
                    consecutive_failures=failures,
                )
                self._logger.warning(
                    "%s feed failed (%d consecutive): %s", name, failures, exc
                )
                delay = self._backoff_delay(failures)
                first = False
                continue
            result = self._store.merge(transactions)
            if result.changed:
                await self._persist(result, name)
            failures = 0
            self._update_health(
                name,
                state="ok",
                last_success=datetime.now(timezone.utc),
                last_error=None,
                consecutive_failures=0,
                last_batch=len(transactions),
            )
            if result.changed:
                self._notify(
                    TransactionsChanged(
                        added=result.added_count,
                        updated=result.updated_count,
                        total=self._store.total,
                    )
                )
            first = False
            delay = await self._wait_delay(name)
        self._update_health(name, state="idle")

    async def _persist(self, result: MergeResult, source_name: str) -> None:
        try:
            await self._storage.save([*result.added, *result.updated])
        except Exception as exc:  # a storage hiccup must not kill the feed
            self._logger.warning(
                "failed to persist %d transactions from %s: %s",
                result.added_count + result.updated_count,
                source_name,
                exc,
            )

    async def _wait_delay(self, name: str) -> float:
        delay = self._poll_interval * random.uniform(0.85, 1.15)
        event = self._wakeups[name]
        try:
            await asyncio.wait_for(event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return delay
        event.clear()
        return 0.0

    def _backoff_delay(self, failures: int) -> float:
        delay = self._poll_interval * (2 ** min(failures, 8))
        return min(delay, self.MAX_BACKOFF_SECONDS) * random.uniform(0.9, 1.1)

    def _update_health(self, name: str, **changes: Any) -> None:
        current = self._health[name]
        updated = replace(current, **changes)
        if updated == current:
            return
        self._health[name] = updated
        self._notify(SourceStatusChanged(updated))

    def _notify(self, event: ServiceEvent) -> None:
        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                self._logger.exception("feed listener failed")
