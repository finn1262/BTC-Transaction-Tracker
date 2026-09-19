"""Aggregate every source into one deduplicated, persisted transaction list."""

import asyncio
from collections.abc import Sequence
from typing import Any

from btc_tracker.data.models import Transaction
from btc_tracker.services.base import AbstractSourceService
from btc_tracker.storage.base import AbstractStorage
from btc_tracker.utils.logger import LoggerFactory


class TransactionService:
    """Orchestrate all sources, isolate failures, deduplicate, and persist."""

    def __init__(
        self,
        sources: Sequence[AbstractSourceService],
        storage: AbstractStorage,
        logger: Any = None,
    ) -> None:
        """Initialize the service.

        Args:
            sources: Source services to aggregate.
            storage: Persistence backend.
            logger: Optional logger.
        """
        self._sources = list(sources)
        self._storage = storage
        self._logger = logger or LoggerFactory.create("services.transaction")

    @property
    def source_names(self) -> list[str]:
        """Return the names of all configured sources."""
        return [source.source_name for source in self._sources]

    async def fetch_all_transactions(self, address: str | None = None) -> list[Transaction]:
        """Fetch from all sources, isolate failures, deduplicate, and store.

        Args:
            address: Wallet address forwarded to address-scoped sources.

        Returns:
            Deduplicated transactions ordered newest first.
        """
        results = await asyncio.gather(
            *(source.fetch_transactions(address) for source in self._sources),
            return_exceptions=True,
        )
        transactions, failures = self._partition_results(results)
        for source_name, error in failures.items():
            self._logger.warning("source failed: %s: %s", source_name, error)
        merged = self._deduplicate(transactions)
        if merged:
            await self._storage.save(merged)
        self._logger.info(
            "aggregated %d transactions from %d sources (%d failed)",
            len(merged),
            len(self._sources),
            len(failures),
        )
        return merged

    async def get_stored_transactions(self, limit: int | None = None) -> list[Transaction]:
        """Load previously persisted transactions.

        Args:
            limit: Optional maximum number of rows.

        Returns:
            Stored transactions ordered newest first.
        """
        return await self._storage.get_all(limit=limit)

    async def save_transactions(self, transactions: Sequence[Transaction]) -> int:
        """Persist transactions, for example from the live feed.

        Args:
            transactions: Transactions to store.

        Returns:
            The number of transactions written.
        """
        return await self._storage.save(transactions)

    def _partition_results(
        self, results: Sequence[Any]
    ) -> tuple[list[Transaction], dict[str, Exception]]:
        transactions: list[Transaction] = []
        failures: dict[str, Exception] = {}
        for source, result in zip(self._sources, results, strict=True):
            if isinstance(result, BaseException):
                failures[source.source_name] = result
            else:
                transactions.extend(result)
        return transactions, failures

    def _deduplicate(self, transactions: Sequence[Transaction]) -> list[Transaction]:
        unique: dict[tuple[str, str], Transaction] = {}
        for transaction in transactions:
            key = transaction.dedup_key
            existing = unique.get(key)
            if existing is None or (transaction.is_confirmed and not existing.is_confirmed):
                unique[key] = transaction
        return sorted(unique.values(), key=lambda item: item.timestamp, reverse=True)
