"""Shared fixtures and fakes for the BTC tracker test suite."""

import asyncio
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any

from textual.app import App

from btc_tracker.core.config import Config
from btc_tracker.data.models import Transaction
from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.storage.base import AbstractStorage
from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.ui.screens import MainScreen
from btc_tracker.ui.styles import Styles


def make_transaction(
    external_id: str | int = "1",
    source: str = "binance",
    amount_sats: int = 1_000,
    timestamp: datetime | None = None,
    *,
    fee_sats: int = 0,
    status: str = "confirmed",
) -> Transaction:
    """Build a transaction with sensible test defaults."""
    return Transaction(
        external_id=str(external_id),
        source=source,
        amount_sats=amount_sats,
        timestamp=timestamp or datetime.now(timezone.utc),
        fee_sats=fee_sats,
        status=status,
    )


class FakeSource:
    """Source service stub that returns scripted batches."""

    def __init__(
        self,
        name: str = "binance",
        batches: Sequence[Sequence[Transaction]] | None = None,
        *,
        delay: float = 0.0,
        error: Exception | None = None,
        batch_size: int = 3,
    ) -> None:
        self.source_name = name
        self.calls = 0
        self.pages_seen: list[int | None] = []
        self._batches = [list(batch) for batch in batches] if batches is not None else None
        self._delay = delay
        self._error = error
        self._batch_size = batch_size
        self._counter = 0

    @property
    def error(self) -> Exception | None:
        return self._error

    @error.setter
    def error(self, value: Exception | None) -> None:
        self._error = value

    async def fetch_transactions(
        self, address: str | None = None, *, pages: int | None = None
    ) -> list[Transaction]:
        self.calls += 1
        self.pages_seen.append(pages)
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        if self._batches is not None:
            index = min(self.calls - 1, len(self._batches) - 1)
            return list(self._batches[index])
        now = datetime.now(timezone.utc)
        batch = []
        for _ in range(self._batch_size):
            self._counter += 1
            batch.append(
                make_transaction(
                    f"{self.source_name}-{self._counter}",
                    self.source_name,
                    amount_sats=100 * self._counter,
                    timestamp=now,
                )
            )
        return batch


class InMemoryStorage(AbstractStorage):
    """Storage stub tracking saves for assertions."""

    def __init__(self, stored: Sequence[Transaction] = ()) -> None:
        self.rows: dict[tuple[str, str], Transaction] = {
            transaction.dedup_key: transaction for transaction in stored
        }
        self.save_calls: list[list[Transaction]] = []
        self.get_all_calls = 0
        self.fail_saves = False
        self.load_error: Exception | None = None

    async def save(self, transactions: Sequence[Transaction]) -> int:
        if self.fail_saves:
            raise RuntimeError("storage unavailable")
        batch = list(transactions)
        self.save_calls.append(batch)
        for transaction in batch:
            self.rows[transaction.dedup_key] = transaction
        return len(batch)

    async def find_by_external_id(
        self, external_id: str, source: str | None = None
    ) -> Transaction | None:
        for transaction in self.rows.values():
            if transaction.external_id == external_id and (
                source is None or transaction.source == source
            ):
                return transaction
        return None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Transaction]:
        self.get_all_calls += 1
        if self.load_error is not None:
            raise self.load_error
        ordered = sorted(self.rows.values(), key=lambda item: item.timestamp, reverse=True)
        if limit is None:
            return ordered[offset:]
        return ordered[offset : offset + limit]

    async def delete(self, source: str, external_id: str) -> bool:
        return self.rows.pop((source, external_id), None) is not None

    async def count(self) -> int:
        return len(self.rows)

    async def close(self) -> None:
        return None


class TrackerTestApp(App[None]):
    """Headless Textual app hosting a MainScreen."""

    CSS = Styles.CSS

    def __init__(self, screen: MainScreen) -> None:
        super().__init__()
        self._screen = screen

    def on_mount(self) -> None:
        self.push_screen(self._screen)


def build_test_config(**overrides: Any) -> Config:
    """Return a fast-flush config suitable for headless tests."""
    values: dict[str, Any] = {
        "ui_flush_interval_seconds": 0.02,
        "search_debounce_seconds": 0.01,
        "poll_interval_seconds": 0.05,
        "history_limit": 1_000,
        "max_transactions": 2_000,
        "render_limit": 100,
    }
    values.update(overrides)
    return Config(**values)


def build_test_app(
    sources: Sequence[FakeSource],
    storage: InMemoryStorage | None = None,
    config: Config | None = None,
    exporter: CsvExporter | None = None,
) -> tuple[TrackerTestApp, MainScreen, TransactionService, InMemoryStorage]:
    """Build a headless app wired to a real TransactionService."""
    storage = storage or InMemoryStorage()
    config = config or build_test_config()
    service = TransactionService(
        sources,
        storage,
        poll_interval=config.poll_interval_seconds,
        backfill_pages=config.backfill_pages,
        poll_pages=config.poll_pages,
        history_limit=config.history_limit,
        max_transactions=config.max_transactions,
    )
    screen = MainScreen(service, exporter or CsvExporter(), config)
    return TrackerTestApp(screen), screen, service, storage


async def wait_until(
    predicate: Callable[[], bool], timeout: float = 2.0, interval: float = 0.01
) -> bool:
    """Wait for a predicate to become true, returning its final value."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def ordered_transactions(count: int, source: str = "binance") -> list[Transaction]:
    """Return ``count`` transactions one second apart, newest first when sorted."""
    now = datetime.now(timezone.utc)
    return [
        make_transaction(
            f"{source}-{index}",
            source,
            amount_sats=100 if index % 2 == 0 else -100,
            timestamp=now - timedelta(seconds=index),
        )
        for index in range(count)
    ]
