"""Reusable Textual widgets for the transaction tracker."""

from collections.abc import Sequence
from typing import Any

from rich.text import Text
from textual.binding import Binding
from textual.widgets import DataTable, Input, Select, Static

from btc_tracker.data.models import Transaction
from btc_tracker.ui.styles import Styles
from btc_tracker.utils.formatting import Formatter


class TransactionTable(DataTable):
    """Sortable, filterable table of exchange market trades."""

    COLUMNS = ("ID", "Amount (BTC)", "Fee", "Time", "Source", "Status")

    BINDINGS = [
        Binding("enter", "select_cursor", "Details", show=False),
    ]

    def __init__(self, formatter: Formatter | None = None, **kwargs: Any) -> None:
        """Initialize the table.

        Args:
            formatter: Optional value formatter.
            **kwargs: Keyword arguments forwarded to :class:`DataTable`.
        """
        super().__init__(**kwargs)
        self._formatter = formatter or Formatter()
        self.cursor_type = "row"
        self.zebra_stripes = True

    def on_mount(self) -> None:
        """Create the columns once the widget is mounted."""
        for column in self.COLUMNS:
            self.add_column(column, key=column)

    def set_transactions(self, transactions: Sequence[Transaction]) -> None:
        """Replace the visible rows.

        Args:
            transactions: Transactions to render, already ordered.
        """
        self.clear()
        for transaction in transactions:
            self.add_row(*self._cells(transaction), key=self.row_key_for(transaction))

    @staticmethod
    def row_key_for(transaction: Transaction) -> str:
        """Return the stable row key for a transaction.

        Args:
            transaction: Transaction to key.

        Returns:
            A ``source:external_id`` row key.
        """
        return f"{transaction.source}:{transaction.external_id}"

    def _cells(self, transaction: Transaction) -> tuple[Text, ...]:
        amount_style = Styles.CONFIRMED_COLOR if transaction.amount_sats >= 0 else Styles.FAILED_COLOR
        status_style = Styles.STATUS_COLORS.get(str(transaction.status), Styles.MUTED_COLOR)
        return (
            Text(self._formatter.shorten(transaction.external_id), style="dim"),
            Text(self._formatter.format_amount_with_unit(transaction.amount_sats), style=amount_style),
            Text(self._formatter.format_fee(transaction.fee_sats)),
            Text(self._formatter.format_timestamp(transaction.timestamp)),
            Text(transaction.source, style=Styles.EXCHANGE_COLOR),
            Text(str(transaction.status), style=status_style),
        )


class TradeSearchBar(Input):
    """Text input filtering the trade table by id or source."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the search bar."""
        kwargs.setdefault("placeholder", "Filter trades by id or source - type to filter")
        kwargs.setdefault("id", "trade-search-bar")
        super().__init__(**kwargs)


class SourceFilterTabs(Select):
    """Source filter covering all trades and one view per exchange."""

    ALL = "all"

    def __init__(self, source_names: Sequence[str], **kwargs: Any) -> None:
        """Initialize the filter.

        Args:
            source_names: Names of the configured sources.
            **kwargs: Keyword arguments forwarded to :class:`Select`.
        """
        options = [("All Sources", self.ALL)]
        options.extend((name.replace("_", " ").title(), name) for name in source_names)
        self._values = [value for _, value in options]
        kwargs.setdefault("value", self.ALL)
        kwargs.setdefault("allow_blank", False)
        kwargs.setdefault("id", "source-filter")
        super().__init__(options, **kwargs)

    def cycle(self) -> str:
        """Advance to the next filter option.

        Returns:
            The newly selected filter value.
        """
        index = self._values.index(self.value) if self.value in self._values else 0
        value = self._values[(index + 1) % len(self._values)]
        self.value = value
        return value


class SummaryPanel(Static):
    """One-line dashboard summary of the current view."""

    def __init__(self, formatter: Formatter | None = None, **kwargs: Any) -> None:
        """Initialize the summary panel.

        Args:
            formatter: Optional value formatter.
            **kwargs: Keyword arguments forwarded to :class:`Static`.
        """
        kwargs.setdefault("id", "summary-panel")
        super().__init__("", **kwargs)
        self._formatter = formatter or Formatter()

    def set_summary(self, visible: Sequence[Transaction], total: int) -> None:
        """Update the summary text.

        Args:
            visible: Currently visible transactions.
            total: Total number of loaded transactions.
        """
        net_sats = sum(transaction.amount_sats for transaction in visible)
        buys = sum(1 for transaction in visible if transaction.amount_sats > 0)
        sells = sum(1 for transaction in visible if transaction.amount_sats < 0)
        sources: dict[str, int] = {}
        for transaction in visible:
            sources[transaction.source] = sources.get(transaction.source, 0) + 1
        breakdown = ", ".join(f"{name}:{count}" for name, count in sorted(sources.items()))
        self.update(
            f"Total: {total} trades | Showing: {len(visible)} | Buys: {buys} | "
            f"Sells: {sells} | Net: {self._formatter.format_amount_with_unit(net_sats)} | "
            f"{breakdown}"
        )


class StatusBar(Static):
    """Status line with record count, filter state, and refresh state."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the status bar."""
        kwargs.setdefault("id", "status-bar")
        super().__init__("Ready", **kwargs)

    def set_status(self, message: str) -> None:
        """Replace the status text.

        Args:
            message: Status message to display.
        """
        self.update(message)
