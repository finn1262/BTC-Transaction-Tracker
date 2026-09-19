"""SQLite storage backend storing amounts as integer satoshis."""

import asyncio
import sqlite3
from collections.abc import Sequence
from contextlib import closing
from pathlib import Path
from typing import Any

from btc_tracker.data.models import Transaction
from btc_tracker.storage.base import AbstractStorage, StorageError
from btc_tracker.utils.logger import LoggerFactory

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    address_from TEXT,
    address_to TEXT,
    amount_sats INTEGER NOT NULL,
    fee_sats INTEGER NOT NULL DEFAULT 0,
    timestamp DATETIME NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    block_number INTEGER,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_address_from ON transactions(address_from);
CREATE INDEX IF NOT EXISTS idx_address_to ON transactions(address_to);
CREATE INDEX IF NOT EXISTS idx_timestamp ON transactions(timestamp);
CREATE INDEX IF NOT EXISTS idx_source ON transactions(source);
"""


class SQLiteStorage(AbstractStorage):
    """Persist transactions in a local SQLite database.

    Amounts are integer satoshis because SQLite has no true DECIMAL type;
    REAL affinity would silently lose precision on financial data. Writes are
    chunked and executed inside explicit transactions for bulk efficiency.
    """

    BATCH_SIZE = 500

    _COLUMNS = (
        "source, external_id, address_from, address_to, amount_sats, "
        "fee_sats, timestamp, status, block_number"
    )
    _UPSERT_SQL = f"""
        INSERT INTO transactions ({_COLUMNS})
        VALUES (:source, :external_id, :address_from, :address_to, :amount_sats,
                :fee_sats, :timestamp, :status, :block_number)
        ON CONFLICT(source, external_id) DO UPDATE SET
            address_from = excluded.address_from,
            address_to = excluded.address_to,
            amount_sats = excluded.amount_sats,
            fee_sats = excluded.fee_sats,
            timestamp = excluded.timestamp,
            status = excluded.status,
            block_number = excluded.block_number
    """

    def __init__(self, database_path: Path | str, logger: Any = None) -> None:
        """Initialize the backend and ensure the schema exists.

        Args:
            database_path: SQLite database file path.
            logger: Optional logger.
        """
        self._path = Path(database_path)
        self._logger = logger or LoggerFactory.create("storage.sqlite")
        self._write_lock = asyncio.Lock()
        self.initialize_schema()

    @property
    def database_path(self) -> Path:
        """Return the database file path."""
        return self._path

    def initialize_schema(self) -> None:
        """Create the transactions table and indexes when absent.

        Raises:
            StorageError: If the schema cannot be created.
        """
        try:
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.executescript(SCHEMA)
                connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to initialize schema: {exc}") from exc

    async def save(self, transactions: Sequence[Transaction]) -> int:
        """Persist a batch of transactions with chunked upserts.

        Args:
            transactions: Transactions to store.

        Returns:
            The number of transactions written.

        Raises:
            StorageError: If the write fails.
        """
        if not transactions:
            return 0
        async with self._write_lock:
            return await asyncio.to_thread(self._save_sync, list(transactions))

    async def find_by_external_id(
        self, external_id: str, source: str | None = None
    ) -> Transaction | None:
        """Return one transaction by identifier, optionally scoped by source."""
        if source is None:
            sql = f"SELECT {self._COLUMNS} FROM transactions WHERE external_id = ? LIMIT 1"
            params: list[Any] = [external_id]
        else:
            sql = (
                f"SELECT {self._COLUMNS} FROM transactions "
                "WHERE external_id = ? AND source = ? LIMIT 1"
            )
            params = [external_id, source]
        rows = await self._fetch(sql, params)
        return rows[0] if rows else None

    async def get_all(self, limit: int | None = None, offset: int = 0) -> list[Transaction]:
        """Return stored transactions ordered newest first."""
        sql = f"SELECT {self._COLUMNS} FROM transactions ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        return await self._fetch(sql, [limit if limit is not None else -1, offset])

    async def delete(self, source: str, external_id: str) -> bool:
        """Delete one transaction.

        Args:
            source: Source name.
            external_id: Source-scoped identifier.

        Returns:
            ``True`` when a row was deleted.
        """
        return await asyncio.to_thread(self._delete_sync, source, external_id)

    async def count(self) -> int:
        """Return the total number of stored transactions."""
        rows = await asyncio.to_thread(self._count_sync)
        return rows

    async def close(self) -> None:
        """Release storage resources; connections are per-operation."""
        return None

    def _save_sync(self, transactions: list[Transaction]) -> int:
        rows = [transaction.to_dict() for transaction in transactions]
        try:
            with closing(self._connect()) as connection:
                for start in range(0, len(rows), self.BATCH_SIZE):
                    connection.executemany(self._UPSERT_SQL, rows[start : start + self.BATCH_SIZE])
                connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to save transactions: {exc}") from exc
        self._logger.debug("stored %d transactions", len(rows))
        return len(rows)

    def _delete_sync(self, source: str, external_id: str) -> bool:
        try:
            with closing(self._connect()) as connection:
                cursor = connection.execute(
                    "DELETE FROM transactions WHERE source = ? AND external_id = ?",
                    (source, external_id),
                )
                connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"failed to delete transaction: {exc}") from exc
        return cursor.rowcount > 0

    def _count_sync(self) -> int:
        try:
            with closing(self._connect()) as connection:
                cursor = connection.execute("SELECT COUNT(*) FROM transactions")
                return int(cursor.fetchone()[0])
        except sqlite3.Error as exc:
            raise StorageError(f"failed to count transactions: {exc}") from exc

    async def _fetch(self, sql: str, params: Sequence[Any]) -> list[Transaction]:
        rows = await asyncio.to_thread(self._fetch_sync, sql, params)
        return [Transaction.from_dict(dict(row)) for row in rows]

    def _fetch_sync(self, sql: str, params: Sequence[Any]) -> list[sqlite3.Row]:
        try:
            with closing(self._connect()) as connection:
                cursor = connection.execute(sql, params)
                return cursor.fetchall()
        except sqlite3.Error as exc:
            raise StorageError(f"query failed: {exc}") from exc

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection
