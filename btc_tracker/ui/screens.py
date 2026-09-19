"""Screens for the BTC Transaction Tracker TUI."""

from collections.abc import Sequence
from typing import Any

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from btc_tracker.core.config import Config
from btc_tracker.data.models import Transaction
from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.ui.components import (
    SourceFilterTabs,
    StatusBar,
    SummaryPanel,
    TradeSearchBar,
    TransactionTable,
)
from btc_tracker.utils.formatting import Formatter
from btc_tracker.utils.logger import LoggerFactory

SORT_KEYS = {
    "ID": lambda transaction: transaction.external_id,
    "Amount (BTC)": lambda transaction: transaction.amount_sats,
    "Fee": lambda transaction: transaction.fee_sats,
    "Time": lambda transaction: transaction.timestamp,
    "Source": lambda transaction: transaction.source,
    "Status": lambda transaction: str(transaction.status),
}


class MainScreen(Screen):
    """Dashboard: search bar, source filter, trade table, status line."""

    BINDINGS = [
        Binding("r", "refresh", "Refresh"),
        Binding("s", "focus_search", "Search"),
        Binding("f", "focus_filter", "Filter"),
        Binding("t", "focus_table", "Table"),
        Binding("enter", "open_detail", "Details"),
        Binding("e", "export", "Export"),
        Binding("h", "help", "Help"),
        Binding("tab", "cycle_filter", "Cycle Source", priority=True),
        Binding("escape", "unfocus", "Unfocus", show=False),
    ]

    def __init__(
        self,
        transaction_service: TransactionService,
        exporter: CsvExporter,
        config: Config,
        logger: Any = None,
        formatter: Formatter | None = None,
    ) -> None:
        """Initialize the main screen.

        Args:
            transaction_service: Aggregation service.
            exporter: CSV exporter backing the export key.
            config: Application configuration.
            logger: Optional logger.
            formatter: Optional value formatter.
        """
        super().__init__()
        self._service = transaction_service
        self._exporter = exporter
        self._config = config
        self._tracker_logger = logger or LoggerFactory.create("ui.main_screen")
        self._formatter = formatter or Formatter()
        self._transactions: list[Transaction] = []
        self._search_text = ""
        self._filter = SourceFilterTabs.ALL
        self._sort_column = "Time"
        self._sort_reverse = True
        self._visible: list[Transaction] = []

    def compose(self) -> ComposeResult:
        """Compose the screen layout."""
        yield Header(show_clock=True)
        yield TradeSearchBar()
        yield SourceFilterTabs(self._service.source_names)
        yield TransactionTable(self._formatter)
        yield SummaryPanel(self._formatter)
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        """Load stored trades and fetch fresh market data."""
        self.run_worker(self._load_worker(), name="load", exclusive=True)

    async def _load_worker(self) -> None:
        try:
            transactions = await self._service.get_stored_transactions()
            self._set_transactions(transactions)
            self.action_refresh()
        except Exception as exc:
            self._tracker_logger.exception("failed to load stored transactions")
            self.notify(f"Failed to load stored transactions: {exc}", severity="error")

    def _set_transactions(self, transactions: Sequence[Transaction]) -> None:
        self._transactions = list(transactions)
        self._refresh_view()

    def _visible_transactions(self) -> list[Transaction]:
        visible = list(self._transactions)
        if self._filter != SourceFilterTabs.ALL:
            visible = [
                transaction for transaction in visible if transaction.source == self._filter
            ]
        if self._search_text:
            needle = self._search_text.lower()
            visible = [
                transaction
                for transaction in visible
                if needle in transaction.external_id.lower()
                or needle in transaction.source.lower()
            ]
        sort_key = SORT_KEYS.get(self._sort_column, SORT_KEYS["Time"])
        return sorted(visible, key=sort_key, reverse=self._sort_reverse)

    def _refresh_view(self) -> None:
        visible = self._visible_transactions()
        self._visible = visible
        self.query_one(TransactionTable).set_transactions(visible)
        self.query_one(SummaryPanel).set_summary(visible, len(self._transactions))
        self.query_one(StatusBar).set_status(
            f"Loaded: {len(self._transactions)} trades | Showing: {len(visible)} | "
            f"Filter: {self._filter} | Sort: {self._sort_column}"
        )

    def on_input_changed(self, event: Any) -> None:
        self._search_text = event.value.strip()
        self._refresh_view()

    def on_select_changed(self, event: Any) -> None:
        self._filter = event.value
        self._refresh_view()

    def on_data_table_header_selected(self, event: Any) -> None:
        column = str(event.column_key.value)
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = column in ("Time", "Amount (BTC)", "Fee")
        self._refresh_view()

    def on_data_table_row_selected(self, event: Any) -> None:
        row_key = event.row_key.value
        transaction = next(
            (
                item
                for item in self._visible
                if TransactionTable.row_key_for(item) == row_key
            ),
            None,
        )
        if transaction is not None:
            self.app.push_screen(TransactionDetailScreen(transaction, self._formatter))

    def action_open_detail(self) -> None:
        """Open the detail screen for the highlighted table row."""
        table = self.query_one(TransactionTable)
        if not self._visible:
            self.notify("No trade selected.", severity="warning")
            return
        index = min(max(table.cursor_row, 0), len(self._visible) - 1)
        self.app.push_screen(TransactionDetailScreen(self._visible[index], self._formatter))

    def action_refresh(self) -> None:
        """Fetch market trades from every exchange in a Textual worker."""
        self.run_worker(self._refresh_worker(), name="refresh", exclusive=True)

    async def _refresh_worker(self) -> None:
        self.query_one(StatusBar).set_status("Fetching buy/sell trades from all exchanges...")
        try:
            transactions = await self._service.fetch_all_transactions()
            if transactions:
                self._set_transactions(transactions)
            else:
                self._refresh_view()
        except Exception as exc:
            self._tracker_logger.exception("refresh failed")
            self.notify(f"Refresh failed: {exc}", severity="error")
            return
        self.notify(f"Fetched {len(self._transactions)} buy/sell trades.", timeout=4)

    def action_focus_search(self) -> None:
        """Focus the trade search bar."""
        self.query_one(TradeSearchBar).focus()

    def action_focus_filter(self) -> None:
        """Focus the source filter."""
        self.query_one(SourceFilterTabs).focus()

    def action_focus_table(self) -> None:
        """Focus the transaction table."""
        self.query_one(TransactionTable).focus()

    def action_unfocus(self) -> None:
        """Blur the focused widget so single-key shortcuts apply."""
        self.set_focus(None)

    def action_cycle_filter(self) -> None:
        """Cycle through the source filter options."""
        self.query_one(SourceFilterTabs).cycle()

    def action_export(self) -> None:
        """Export the current filtered view to CSV."""
        visible = self._visible_transactions()
        if not visible:
            self.notify("Nothing to export.", severity="warning")
            return
        try:
            path = self._exporter.export(visible, self._exporter.default_filename())
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return
        self.notify(f"Exported {len(visible)} trades to {path}", timeout=5)

    def action_help(self) -> None:
        """Open the help screen."""
        self.app.push_screen(HelpScreen())


class TransactionDetailScreen(Screen):
    """Full detail view for one selected trade."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back", show=False),
    ]

    def __init__(self, transaction: Transaction, formatter: Formatter) -> None:
        """Initialize the detail screen.

        Args:
            transaction: Transaction to display.
            formatter: Value formatter.
        """
        super().__init__()
        self._transaction = transaction
        self._formatter = formatter

    def compose(self) -> ComposeResult:
        """Compose the detail layout."""
        yield Header(show_clock=True)
        yield Static(self._build_body(), id="detail-panel")
        yield Footer()

    def _build_body(self) -> str:
        transaction = self._transaction
        side = "BUY" if transaction.amount_sats >= 0 else "SELL"
        lines = [
            f"[bold]Trade {transaction.external_id}[/bold]",
            "",
            f"Source:        {transaction.source}",
            f"Side:          {side}",
            f"Status:        {transaction.status}",
            f"Amount:        {self._formatter.format_amount_with_unit(transaction.amount_sats)}",
            f"Fee:           {self._formatter.format_fee(transaction.fee_sats)}",
            f"Timestamp:     {self._formatter.format_timestamp(transaction.timestamp)}",
        ]
        return "\n".join(lines)


class HelpScreen(Screen):
    """Keybinding and source reference."""

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back", show=False),
    ]

    def compose(self) -> ComposeResult:
        """Compose the help layout."""
        yield Header(show_clock=True)
        yield Static(self._build_body(), id="help-panel")
        yield Footer()

    def _build_body(self) -> str:
        return (
            "[bold]BTC Transaction Tracker - Help[/bold]\n\n"
            "  q          Quit the application\n"
            "  r          Refresh buy/sell trades from all exchanges\n"
            "  s          Focus the trade search bar\n"
            "  f          Focus the source filter\n"
            "  t          Focus the trade table\n"
            "  Tab        Cycle the source filter\n"
            "  Enter      Open trade details\n"
            "  e          Export the current filtered view to CSV\n"
            "  h          Show this help screen\n"
            "  Escape     Return from a detail or help screen\n\n"
            "[bold]Sources[/bold]\n"
            "  Binance, Coinbase, Kraken, Bybit, OKX, KuCoin, Bitget, MEXC, Gemini\n\n"
            "All sources are public, keyless exchange market-data endpoints. A positive\n"
            "amount is a buy (BTC received) and a negative amount is a sell (BTC sent)."
        )
