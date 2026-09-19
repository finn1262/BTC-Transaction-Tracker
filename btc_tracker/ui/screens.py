"""Screens for the BTC Transaction Tracker TUI."""

import asyncio
from datetime import datetime, timezone
from typing import Any, ClassVar

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.timer import Timer
from textual.widgets import Footer, Header, Static

from btc_tracker.core.config import Config
from btc_tracker.data.models import Transaction
from btc_tracker.services.transaction_service import (
    ServiceEvent,
    TransactionService,
)
from btc_tracker.services.transaction_store import StoreStats
from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.ui.components import (
    ActivityPanel,
    SourceFilterTabs,
    SourceHealthPanel,
    StatsPanel,
    StatusBar,
    SummaryPanel,
    TradeSearchBar,
    TransactionTable,
)
from btc_tracker.ui.styles import Styles
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


class FeedUpdated(Message):
    """Posted when the live feed reports new data or source health."""

    def __init__(self, event: ServiceEvent) -> None:
        """Initialize the message.

        Args:
            event: The service event that triggered the update.
        """
        self.event = event
        super().__init__()


class MainScreen(Screen):
    """Live dashboard: toolbar, trade table, stats sidebar, status lines."""

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

    COMPACT_WIDTH: ClassVar[int] = 120
    SIDEBAR_WIDTH: ClassVar[int] = 40
    FULL_COLUMNS_WIDTH: ClassVar[int] = 88
    MEDIUM_COLUMNS_WIDTH: ClassVar[int] = 74
    ACTIVITY_MINUTES: ClassVar[int] = 30

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
            transaction_service: Live transaction feed.
            exporter: CSV exporter backing the export key.
            config: Application configuration.
            logger: Optional logger.
            formatter: Optional value formatter.
        """
        super().__init__()
        self._service = transaction_service
        self._exporter = exporter
        self._tracker_logger = logger or LoggerFactory.create("ui.main_screen")
        self._formatter = formatter or Formatter()
        self._render_limit = config.render_limit
        self._flush_interval = config.ui_flush_interval_seconds
        self._search_debounce = config.search_debounce_seconds
        self._search_text = ""
        self._filter = SourceFilterTabs.ALL
        self._sort_column = "Time"
        self._sort_reverse = True
        self._visible: list[Transaction] = []
        self._visible_key: tuple[Any, ...] | None = None
        self._matched: list[Transaction] = []
        self._matched_count = 0
        self._dirty = False
        self._flush_timer: Timer | None = None
        self._unsubscribe: Any = None

    def compose(self) -> ComposeResult:
        """Compose the responsive dashboard layout."""
        yield Header(show_clock=True)
        with Vertical(id="body"):
            with Horizontal(id="toolbar"):
                yield TradeSearchBar()
                yield SourceFilterTabs(self._service.source_names)
            with Horizontal(id="main-area"):
                yield TransactionTable(self._formatter)
                with Vertical(id="sidebar"):
                    yield StatsPanel(self._formatter)
                    yield ActivityPanel(self.ACTIVITY_MINUTES)
                    yield SourceHealthPanel(self._formatter)
            yield SummaryPanel(self._formatter)
            yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        """Subscribe to the feed and start it."""
        self._unsubscribe = self._service.subscribe(self._on_service_event)
        self.run_worker(self._start_worker(), name="feed-start", exclusive=True)
        self.query_one(TransactionTable).focus()

    def on_unmount(self) -> None:
        """Detach from the feed."""
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    async def _start_worker(self) -> None:
        try:
            await self._service.start()
        except Exception:
            self._tracker_logger.exception("failed to start the live feed")
            self.notify(
                "Failed to start the live feed. Press r to retry.",
                severity="error",
            )
        self._mark_dirty(0)

    def _on_service_event(self, event: ServiceEvent) -> None:
        if self.is_mounted:
            self.post_message(FeedUpdated(event))

    def on_feed_updated(self, message: FeedUpdated) -> None:
        """Schedule a throttled UI flush for a feed event."""
        self._mark_dirty()

    def _mark_dirty(self, delay: float | None = None) -> None:
        self._dirty = True
        if self._flush_timer is None:
            interval = self._flush_interval if delay is None else max(delay, 0.01)
            self._flush_timer = self.set_timer(interval, self._flush)

    def _flush(self) -> None:
        self._flush_timer = None
        if not self._dirty:
            return
        self._dirty = False
        self.run_worker(self._apply_flush(), name="flush", group="flush", exclusive=True)

    async def _apply_flush(self) -> None:
        visible = self._visible_transactions()
        table = self.query_one(TransactionTable)
        step = max(self._render_limit // 10, 100)
        if len(visible) > step:
            rendered = set(table.rendered_keys())
            pending = sum(
                1
                for transaction in visible
                if TransactionTable.row_key_for(transaction) not in rendered
            )
            if pending > step:
                for end in range(step, len(visible), step):
                    table.set_transactions(
                        visible[:end],
                        sort_column=self._sort_column,
                        sort_reverse=self._sort_reverse,
                    )
                    await asyncio.sleep(0)
        table.set_transactions(
            visible,
            sort_column=self._sort_column,
            sort_reverse=self._sort_reverse,
        )
        stats = self._service.stats()
        self.query_one(SummaryPanel).set_summary(
            stats, len(visible), self._matched_count
        )
        self.query_one(StatsPanel).set_stats(stats)
        self.query_one(SourceHealthPanel).set_health(
            self._service.health(), stats, datetime.now(timezone.utc)
        )
        self.query_one(ActivityPanel).set_activity(
            self._service.activity_minutes(self.ACTIVITY_MINUTES)
        )
        self.query_one(StatusBar).set_status(self._status_text(stats))

    def _visible_transactions(self) -> list[Transaction]:
        snapshot = self._service.snapshot()
        cache_key = (
            self._service.version,
            self._filter,
            self._search_text,
            self._sort_column,
            self._sort_reverse,
            self._render_limit,
        )
        if cache_key == self._visible_key:
            return self._visible
        matched: list[Transaction] = snapshot
        if self._filter != SourceFilterTabs.ALL:
            matched = [
                transaction
                for transaction in matched
                if transaction.source == self._filter
            ]
        if self._search_text:
            needle = self._search_text.lower()
            matched = [
                transaction
                for transaction in matched
                if needle in transaction.external_id.lower()
                or needle in transaction.source.lower()
                or needle in str(transaction.status).lower()
            ]
        if self._sort_column != "Time" or not self._sort_reverse:
            matched = sorted(
                matched,
                key=SORT_KEYS.get(self._sort_column, SORT_KEYS["Time"]),
                reverse=self._sort_reverse,
            )
        self._matched = matched
        self._matched_count = len(matched)
        self._visible = matched[: self._render_limit]
        self._visible_key = cache_key
        return self._visible

    def _status_text(self, stats: StoreStats) -> Text:
        health = self._service.health()
        states = [entry.state for entry in health]
        ok = states.count("ok")
        fetching = states.count("fetching")
        errors = [entry for entry in health if entry.state == "error"]
        latest_success = max(
            (entry.last_success for entry in health if entry.last_success is not None),
            default=None,
        )
        if fetching:
            live_text, live_color = "FETCHING", Styles.PENDING_COLOR
        elif errors:
            live_text, live_color = "DEGRADED", Styles.FAILED_COLOR
        elif ok:
            live_text, live_color = "LIVE", Styles.CONFIRMED_COLOR
        else:
            live_text, live_color = "STARTING", Styles.MUTED_COLOR
        status = Text.assemble(
            (live_text, f"bold {live_color}"),
            ("  ", ""),
            (self._formatter.format_count(stats.total) + " trades", ""),
            ("  sources ", "dim"),
            (f"{ok}/{len(health)}", ""),
        )
        if fetching:
            status.append(f" ({fetching} fetching)", "dim")
        if errors:
            status.append(f"  {len(errors)} error", Styles.FAILED_COLOR)
        if latest_success is not None:
            age = (datetime.now(timezone.utc) - latest_success).total_seconds()
            status.append("  updated ", "dim")
            status.append(self._formatter.format_age(age))
        else:
            status.append("  waiting for first update", "dim")
        status.append("  filter ", "dim")
        status.append(self._filter)
        status.append("  sort ", "dim")
        status.append(f"{self._sort_column} {'desc' if self._sort_reverse else 'asc'}")
        if errors:
            last = errors[0]
            message = f"{last.name}: {last.last_error}"
            status.append("  last error ", "dim")
            status.append(message[:80], Styles.FAILED_COLOR)
        return status

    def on_input_changed(self, event: Any) -> None:
        self._search_text = event.value.strip()
        self._mark_dirty(self._search_debounce)

    def on_select_changed(self, event: Any) -> None:
        self._filter = event.value
        self._mark_dirty(0)

    def on_data_table_header_selected(self, event: Any) -> None:
        column = str(event.column_key.value)
        if column == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = column in ("Time", "Amount (BTC)", "Fee")
        self._mark_dirty(0)

    def on_data_table_row_selected(self, event: Any) -> None:
        transaction = self._transaction_for_key(event.row_key.value)
        if transaction is not None:
            self.app.push_screen(TransactionDetailScreen(transaction, self._formatter))

    def _transaction_for_key(self, row_key: str) -> Transaction | None:
        return next(
            (
                item
                for item in self._matched
                if TransactionTable.row_key_for(item) == row_key
            ),
            None,
        )

    def on_resize(self, event: events.Resize) -> None:
        """Adapt the layout and table columns to the terminal size.

        The column profile is chosen from the width actually available to the
        table (terminal width minus the sidebar when it is shown) so columns
        are never clipped by the sidebar.
        """
        width = event.size.width
        wide = width >= self.COMPACT_WIDTH
        self.set_class(wide, "wide")
        table_width = width - self.SIDEBAR_WIDTH if wide else width
        if table_width >= self.FULL_COLUMNS_WIDTH:
            profile = "full"
        elif table_width >= self.MEDIUM_COLUMNS_WIDTH:
            profile = "medium"
        else:
            profile = "narrow"
        if self._sort_column not in TransactionTable.PROFILES[profile]:
            self._sort_column = "Time"
            self._sort_reverse = True
        if self.query_one(TransactionTable).set_profile(profile):
            self._mark_dirty(0)

    def action_open_detail(self) -> None:
        """Open the detail screen for the highlighted table row."""
        table = self.query_one(TransactionTable)
        if not table.row_count:
            self.notify("No trade selected.", severity="warning")
            return
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
        transaction = self._transaction_for_key(row_key)
        if transaction is None:
            self.notify("That trade is no longer loaded.", severity="warning")
            return
        self.app.push_screen(TransactionDetailScreen(transaction, self._formatter))

    def action_refresh(self) -> None:
        """Wake every feed source for an immediate fetch."""
        self._service.refresh()
        self._mark_dirty(0)

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
        """Export the current filtered view to CSV in a worker thread."""
        if not self._matched:
            self.notify("Nothing to export.", severity="warning")
            return
        transactions = list(self._matched)
        path = self._exporter.default_filename()
        self.run_worker(
            self._export_worker(transactions, path), name="export", exclusive=False
        )

    async def _export_worker(self, transactions: list[Transaction], path: Any) -> None:
        try:
            written = await asyncio.to_thread(
                self._exporter.export, transactions, path
            )
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error")
            return
        self.notify(f"Exported {len(transactions)} trades to {written}", timeout=5)

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
            "  r          Fetch immediately from all exchanges\n"
            "  s          Focus the trade search bar\n"
            "  f          Focus the source filter\n"
            "  t          Focus the trade table\n"
            "  Tab        Cycle the source filter\n"
            "  Enter      Open trade details\n"
            "  e          Export the current filtered view to CSV\n"
            "  h          Show this help screen\n"
            "  Escape     Return from a detail or help screen\n\n"
            "[bold]Live feed[/bold]\n"
            "  Trades stream in automatically; the table, totals, activity chart,\n"
            "  and per-source status update as data arrives. Sources that fail are\n"
            "  retried with backoff while the others keep streaming.\n\n"
            "[bold]Sources[/bold]\n"
            "  Binance, Coinbase, Kraken, Bybit, OKX, KuCoin, Bitget, MEXC, Gemini\n\n"
            "All sources are public, keyless exchange market-data endpoints. A positive\n"
            "amount is a buy (BTC received) and a negative amount is a sell (BTC sent)."
        )
