"""CSV export backing the TUI export key."""

import csv
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from btc_tracker.data.models import Transaction
from btc_tracker.utils.formatting import Formatter
from btc_tracker.utils.logger import LoggerFactory


class CsvExporter:
    """Export transactions from the current view to a CSV file."""

    COLUMNS = (
        "source",
        "external_id",
        "address_from",
        "address_to",
        "amount_sats",
        "amount_btc",
        "fee_sats",
        "timestamp",
        "status",
        "block_number",
    )

    def __init__(self, logger: Any = None, formatter: Formatter | None = None) -> None:
        """Initialize the exporter.

        Args:
            logger: Optional logger.
            formatter: Optional formatter used for the BTC column.
        """
        self._logger = logger or LoggerFactory.create("storage.csv_export")
        self._formatter = formatter or Formatter()

    def export(self, transactions: Sequence[Transaction], destination: Path | str) -> Path:
        """Write transactions to a CSV file.

        Args:
            transactions: Transactions to export.
            destination: Output file path; parent directories are created.

        Returns:
            The written file path.
        """
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=self.COLUMNS)
            writer.writeheader()
            writer.writerows(self._row(transaction) for transaction in transactions)
        self._logger.info("exported %d transactions to %s", len(transactions), path)
        return path

    def default_filename(self, directory: Path | str = ".") -> Path:
        """Return a timestamped export path.

        Args:
            directory: Directory to place the export in.

        Returns:
            A path such as ``btc_transactions_20260920_143300.csv``.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return Path(directory) / f"btc_transactions_{stamp}.csv"

    def _row(self, transaction: Transaction) -> dict[str, Any]:
        row = transaction.to_dict()
        row["amount_btc"] = self._formatter.format_amount(transaction.amount_sats)
        return row
