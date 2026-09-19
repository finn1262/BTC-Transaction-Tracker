"""Reusable Textual widgets for the transaction tracker."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, ClassVar

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import DataTable, Input, Select, Sparkline, Static

from btc_tracker.data.models import Transaction
from btc_tracker.services.transaction_service import SourceHealth
from btc_tracker.services.transaction_store import StoreStats
from btc_tracker.ui.styles import Styles
from btc_tracker.utils.formatting import Formatter

STATE_DOTS: dict[str, tuple[str, str]] = {
    "ok": ("\u25cf", Styles.CONFIRMED_COLOR),
    "fetching": ("\u25d0", Styles.PENDING_COLOR),
    "error": ("\u25cf", Styles.FAILED_COLOR),
    "idle": ("\u25cb", Styles.MUTED_COLOR),
}


class SortableCell(Text):
    """Rich text cell carrying the raw value used for column sorting."""

    __slots__ = ("sort_value",)

    def __init__(self, text: str, sort_value: Any = None, **kwargs: Any) -> None:
        super().__init__(text, **kwargs)
        self.sort_value = text if sort_value is None else sort_value


def cell_sort_key(value: Any) -> Any:
    """Return the raw sort value of a table cell."""
    return value.sort_value if isinstance(value, SortableCell) else value


class TransactionTable(DataTable):
    """Sortable, filterable table of exchange market trades.

    The screen hands the widget an ordered, capped view. Updates are always
    incremental: cell contents are patched in place, new rows are appended,
    dropped rows are removed in one batched pass, and the table is re-sorted.
    No full rebuild of the visible window is ever needed, so live updates
    stay in the low milliseconds. Cursor and scroll position survive updates,
    and the default top-of-table view follows new arrivals.
    """

    COLUMN_LABELS: ClassVar[tuple[str, ...]] = (
        "ID",
        "Amount (BTC)",
        "Fee",
        "Time",
        "Source",
        "Status",
    )

    PROFILES: ClassVar[dict[str, tuple[str, ...]]] = {
        "full": COLUMN_LABELS,
        "medium": ("ID", "Amount (BTC)", "Time", "Source", "Status"),
        "narrow": ("Amount (BTC)", "Time", "Source"),
    }

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
        self._profile = "full"
        self._columns: tuple[str, ...] = self.PROFILES["full"]
        self._rendered: list[Transaction] = []
        self._rendered_keys: list[str] = []
        self._applied_sort: tuple[str, bool] | None = None

    def on_mount(self) -> None:
        """Create the columns for the active profile once mounted."""
        self._mount_columns()

    def set_profile(self, profile: str) -> bool:
        """Switch the responsive column profile.

        Args:
            profile: One of the keys of :attr:`PROFILES`.

        Returns:
            ``True`` when the profile changed and the table must be repopulated.
        """
        if profile == self._profile:
            return False
        self._profile = profile
        self._columns = self.PROFILES[profile]
        self._rendered = []
        self._rendered_keys = []
        self._applied_sort = None
        if self.is_mounted:
            self.clear(columns=True)
            self._mount_columns()
        return True

    def set_transactions(
        self,
        transactions: Sequence[Transaction],
        *,
        sort_column: str = "Time",
        sort_reverse: bool = True,
    ) -> bool:
        """Apply the ordered, capped transaction view.

        Args:
            transactions: Transactions to render, already ordered and capped.
            sort_column: Active sort column, used to reorder appended rows.
            sort_reverse: Whether the active sort is descending.

        Returns:
            ``True`` when the table changed.
        """
        keys = [self.row_key_for(transaction) for transaction in transactions]
        if keys == self._rendered_keys:
            if all(new is old for new, old in zip(transactions, self._rendered)):
                return False
            for index, (new, old) in enumerate(zip(transactions, self._rendered)):
                if new is old:
                    continue
                for column, cell in zip(self._columns, self._cells(new)):
                    self.update_cell(keys[index], column, cell)
            self._rendered = list(transactions)
            return True
        known = set(self._rendered_keys)
        current = set(keys)
        added = [
            (transaction, key)
            for transaction, key in zip(transactions, keys)
            if key not in known
        ]
        removed = [key for key in self._rendered_keys if key not in current]
        self._apply_incremental(added, removed, sort_column, sort_reverse)
        return True

    @staticmethod
    def row_key_for(transaction: Transaction) -> str:
        """Return the stable row key for a transaction.

        Args:
            transaction: Transaction to key.

        Returns:
            A ``source:external_id`` row key.
        """
        return f"{transaction.source}:{transaction.external_id}"

    def rendered_keys(self) -> tuple[str, ...]:
        """Return the row keys currently rendered, in display order."""
        return tuple(self._rendered_keys)

    def _mount_columns(self) -> None:
        for column in self._columns:
            self.add_column(column, key=column)

    def _apply_incremental(
        self,
        added: Sequence[tuple[Transaction, str]],
        removed: Sequence[str],
        sort_column: str,
        sort_reverse: bool,
    ) -> None:
        cursor_key = self._cursor_key()
        old_index = self.cursor_row if self.row_count else None
        old_scroll = self.scroll_y
        if removed:
            self._remove_rows(removed)
        for transaction, key in added:
            self.add_row(*self._cells(transaction), key=key)
        removed_set = set(removed)
        kept = [
            (transaction, key)
            for transaction, key in zip(self._rendered, self._rendered_keys)
            if key not in removed_set
        ]
        self._rendered = [transaction for transaction, _ in kept] + [
            transaction for transaction, _ in added
        ]
        self._rendered_keys = [key for _, key in kept] + [
            key for _, key in added
        ]
        self._applied_sort = (sort_column, sort_reverse)
        self._sort_rows(sort_column, sort_reverse)
        self._restore_view(cursor_key, old_index, old_scroll)

    def _remove_rows(self, keys: Sequence[str]) -> None:
        """Remove several rows, rebuilding row locations once.

        ``DataTable.remove_row`` is O(rows) per call; live updates routinely
        drop many rows at once when the render cap trims the window, so this
        batches the removal into a single reindex. Falls back to the public
        API if the internal layout of the widget ever changes.
        """
        required = ("_row_locations", "_data", "_new_rows", "_updated_cells")
        if not all(hasattr(self, name) for name in required):
            for key in keys:
                self.remove_row(key)
            return
        remove = set(keys)
        offset = 0
        for key in list(self._row_locations):
            if key in remove:
                del self._row_locations[key]
                offset += 1
            else:
                self._row_locations[key] = self._row_locations.get(key) - offset
        for key in remove:
            self.rows.pop(key, None)
            self._data.pop(key, None)
            self._new_rows.discard(key)
        self._updated_cells = {
            cell for cell in self._updated_cells if cell.row_key not in remove
        }
        self.cursor_coordinate = self.cursor_coordinate
        self.hover_coordinate = self.hover_coordinate
        self._update_count += 1
        self.refresh(layout=True)
        self.check_idle()

    def _sort_rows(self, sort_column: str, sort_reverse: bool) -> None:
        if sort_column not in self._columns or self.row_count < 2:
            return
        self.sort(sort_column, key=cell_sort_key, reverse=sort_reverse)
        by_key = dict(zip(self._rendered_keys, self._rendered))
        self._rendered_keys = [str(row.key.value) for row in self.ordered_rows]
        self._rendered = [by_key[key] for key in self._rendered_keys]

    def _restore_view(
        self, cursor_key: str | None, old_index: int | None, old_scroll: float
    ) -> None:
        if not self.row_count:
            return
        at_top = old_index in (None, 0) and old_scroll < 1
        if at_top or cursor_key is None or cursor_key not in self._rendered_keys:
            self.move_cursor(row=0, column=self.cursor_column, animate=False)
            self.scroll_to(y=0, animate=False)
            return
        new_index = self._rendered_keys.index(cursor_key)
        self.move_cursor(row=new_index, column=self.cursor_column, animate=False)
        if old_index is not None:
            self.scroll_to(
                y=max(0.0, old_scroll + (new_index - old_index)), animate=False
            )

    def _cursor_key(self) -> str | None:
        if not self.row_count:
            return None
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
        except Exception:
            return None
        return cell_key.row_key.value

    def _cells(self, transaction: Transaction) -> tuple[SortableCell, ...]:
        amount_style = (
            Styles.CONFIRMED_COLOR
            if transaction.amount_sats >= 0
            else Styles.FAILED_COLOR
        )
        status_style = Styles.STATUS_COLORS.get(
            str(transaction.status), Styles.MUTED_COLOR
        )
        cells: dict[str, SortableCell] = {
            "ID": SortableCell(
                self._formatter.shorten(transaction.external_id),
                sort_value=transaction.external_id,
                style="dim",
            ),
            "Amount (BTC)": SortableCell(
                self._formatter.format_amount_with_unit(transaction.amount_sats),
                sort_value=transaction.amount_sats,
                style=amount_style,
            ),
            "Fee": SortableCell(
                self._formatter.format_fee(transaction.fee_sats),
                sort_value=transaction.fee_sats,
            ),
            "Time": SortableCell(
                self._formatter.format_timestamp(transaction.timestamp),
                sort_value=transaction.timestamp,
            ),
            "Source": SortableCell(
                transaction.source,
                sort_value=transaction.source,
                style=Styles.EXCHANGE_COLOR,
            ),
            "Status": SortableCell(
                str(transaction.status),
                sort_value=str(transaction.status),
                style=status_style,
            ),
        }
        return tuple(cells[column] for column in self._columns)


class TradeSearchBar(Input):
    """Text input filtering the trade table by id, source, or status."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the search bar."""
        kwargs.setdefault(
            "placeholder", "Filter trades by id, source, or status - type to filter"
        )
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
    """One-line totals for the whole store and the current view."""

    def __init__(self, formatter: Formatter | None = None, **kwargs: Any) -> None:
        """Initialize the summary panel.

        Args:
            formatter: Optional value formatter.
            **kwargs: Keyword arguments forwarded to :class:`Static`.
        """
        kwargs.setdefault("id", "summary-panel")
        super().__init__("", **kwargs)
        self._formatter = formatter or Formatter()

    def set_summary(self, stats: StoreStats, showing: int, matched: int) -> None:
        """Update the summary text.

        Args:
            stats: Whole-store aggregates.
            showing: Number of rows currently rendered.
            matched: Number of transactions matching the current filter.
        """
        net_color = (
            Styles.CONFIRMED_COLOR if stats.net_sats >= 0 else Styles.FAILED_COLOR
        )
        line = Text.assemble(
            (self._formatter.format_count(stats.total), "bold"),
            (" trades  ", "dim"),
            (self._formatter.format_count(stats.buys), Styles.CONFIRMED_COLOR),
            (" buys  ", "dim"),
            (self._formatter.format_count(stats.sells), Styles.FAILED_COLOR),
            (" sells  ", "dim"),
            ("net ", "dim"),
            (
                self._formatter.format_amount_with_unit(stats.net_sats),
                net_color,
            ),
            ("  volume ", "dim"),
            (self._formatter.format_sats(stats.volume_sats) + " BTC", ""),
            ("  showing ", "dim"),
            (self._formatter.format_count(showing), ""),
            (f"/{self._formatter.format_count(matched)}", "dim"),
        )
        self.update(line)


class StatsPanel(Static):
    """Multi-line totals for the sidebar."""

    def __init__(self, formatter: Formatter | None = None, **kwargs: Any) -> None:
        """Initialize the stats panel.

        Args:
            formatter: Optional value formatter.
            **kwargs: Keyword arguments forwarded to :class:`Static`.
        """
        kwargs.setdefault("id", "stats-panel")
        super().__init__("", **kwargs)
        self._formatter = formatter or Formatter()

    def set_stats(self, stats: StoreStats) -> None:
        """Update the sidebar totals.

        Args:
            stats: Whole-store aggregates.
        """
        net_color = (
            Styles.CONFIRMED_COLOR if stats.net_sats >= 0 else Styles.FAILED_COLOR
        )
        lines = [
            Text("TOTALS", style=f"bold {Styles.MUTED_COLOR}"),
            Text.assemble(
                ("Trades   ", "dim"), (self._formatter.format_count(stats.total), "")
            ),
            Text.assemble(
                ("Buys     ", "dim"),
                (self._formatter.format_count(stats.buys), Styles.CONFIRMED_COLOR),
            ),
            Text.assemble(
                ("Sells    ", "dim"),
                (self._formatter.format_count(stats.sells), Styles.FAILED_COLOR),
            ),
            Text.assemble(
                ("Net      ", "dim"),
                (self._formatter.format_amount_with_unit(stats.net_sats), net_color),
            ),
            Text.assemble(
                ("Volume   ", "dim"),
                (self._formatter.format_sats(stats.volume_sats) + " BTC", ""),
            ),
        ]
        self.update(Text("\n").join(lines))


class ActivityPanel(Vertical):
    """Sparkline of trades per minute over the recent window."""

    def __init__(self, minutes: int = 30, **kwargs: Any) -> None:
        """Initialize the activity panel.

        Args:
            minutes: Size of the trailing window in minutes.
            **kwargs: Keyword arguments forwarded to :class:`Vertical`.
        """
        kwargs.setdefault("id", "activity-panel")
        super().__init__(**kwargs)
        self._minutes = minutes

    def compose(self) -> ComposeResult:
        """Compose the title and sparkline."""
        yield Static(
            f"ACTIVITY \u00b7 trades/min \u00b7 last {self._minutes}m",
            classes="panel-title",
        )
        yield Sparkline(
            id="activity-spark",
            min_color=Styles.MUTED_COLOR,
            max_color=Styles.EXCHANGE_COLOR,
        )

    def set_activity(self, values: Sequence[int]) -> None:
        """Update the sparkline data.

        Args:
            values: One count per minute, oldest first.
        """
        self.query_one(Sparkline).data = [float(value) for value in values]


class SourceHealthPanel(Static):
    """Per-source live status: state, count, and freshness."""

    def __init__(self, formatter: Formatter | None = None, **kwargs: Any) -> None:
        """Initialize the health panel.

        Args:
            formatter: Optional value formatter.
            **kwargs: Keyword arguments forwarded to :class:`Static`.
        """
        kwargs.setdefault("id", "source-health")
        super().__init__("", **kwargs)
        self._formatter = formatter or Formatter()

    def set_health(
        self,
        health: Sequence[SourceHealth],
        stats: StoreStats,
        now: datetime,
    ) -> None:
        """Update the per-source status lines.

        Args:
            health: Per-source health in display order.
            stats: Store aggregates providing per-source counts.
            now: Reference time for freshness labels.
        """
        counts = {source.name: source.count for source in stats.sources}
        lines = [Text("SOURCES", style=f"bold {Styles.MUTED_COLOR}")]
        for entry in health:
            dot, color = STATE_DOTS.get(entry.state, STATE_DOTS["idle"])
            if entry.last_success is not None:
                age = self._formatter.format_age(
                    (now - entry.last_success).total_seconds()
                )
            else:
                age = "waiting"
            lines.append(
                Text.assemble(
                    (f"{dot} ", color),
                    (f"{entry.name:<9}", ""),
                    (f"{entry.state:<8}", color),
                    (f"{counts.get(entry.name, 0):>7,}", ""),
                    (f"  {age}", "dim"),
                )
            )
        self.update(Text("\n").join(lines))


class StatusBar(Static):
    """Status line with feed state, counts, filter, and sort."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize the status bar."""
        kwargs.setdefault("id", "status-bar")
        super().__init__("Starting...", **kwargs)

    def set_status(self, message: Text) -> None:
        """Replace the status text.

        Args:
            message: Status message to display.
        """
        self.update(message)
