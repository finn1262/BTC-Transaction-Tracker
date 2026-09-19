"""Abstract persistence interface for transactions."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from btc_tracker.data.models import Transaction


class StorageError(Exception):
    """Raised when a persistence operation fails."""


class AbstractStorage(ABC):
    """Contract every storage backend must satisfy.

    Implementations persist :class:`Transaction` entities keyed by
    ``(source, external_id)`` and expose lookup by identifier and
    time-ordered retrieval.
    """

    @abstractmethod
    async def save(self, transactions: Sequence[Transaction]) -> int:
        """Persist a batch of transactions, upserting duplicates.

        Args:
            transactions: Transactions to store.

        Returns:
            The number of transactions written.
        """

    @abstractmethod
    async def find_by_external_id(
        self, external_id: str, source: str | None = None
    ) -> Transaction | None:
        """Return one transaction by its source-scoped identifier.

        Args:
            external_id: Source-scoped trade identifier.
            source: Optional source discriminator.

        Returns:
            The matching transaction, or ``None``.
        """

    @abstractmethod
    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Transaction]:
        """Return stored transactions ordered newest first.

        Args:
            limit: Optional maximum number of rows.
            offset: Number of rows to skip.

        Returns:
            The requested page of transactions.
        """

    @abstractmethod
    async def delete(self, source: str, external_id: str) -> bool:
        """Delete one transaction.

        Args:
            source: Source name.
            external_id: Source-scoped identifier.

        Returns:
            ``True`` when a row was deleted.
        """

    @abstractmethod
    async def count(self) -> int:
        """Return the total number of stored transactions."""

    @abstractmethod
    async def close(self) -> None:
        """Release any storage-owned resources."""
