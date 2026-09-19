"""Dark theme palette and stylesheet for the terminal UI."""

from typing import ClassVar


class Styles:
    """Central styling constants for the Textual application."""

    CONFIRMED_COLOR = "#22c55e"
    PENDING_COLOR = "#eab308"
    FAILED_COLOR = "#ef4444"
    EXCHANGE_COLOR = "#3b82f6"
    MUTED_COLOR = "#94a3b8"

    STATUS_COLORS: ClassVar[dict[str, str]] = {
        "confirmed": CONFIRMED_COLOR,
        "pending": PENDING_COLOR,
        "failed": FAILED_COLOR,
    }

    CSS: ClassVar[str] = """
    Screen {
        background: $surface;
    }

    #body {
        height: 1fr;
    }

    #toolbar {
        height: 3;
        padding: 0 1;
    }

    TradeSearchBar {
        width: 1fr;
    }

    SourceFilterTabs {
        width: 34;
        margin-left: 1;
    }

    #main-area {
        height: 1fr;
    }

    TransactionTable {
        width: 1fr;
    }

    #sidebar {
        width: 40;
        display: none;
        padding: 0 1;
        border-left: solid $panel;
    }

    MainScreen.wide #sidebar {
        display: block;
    }

    .panel-title {
        height: 1;
        color: $text-muted;
        text-style: bold;
    }

    StatsPanel {
        height: auto;
    }

    ActivityPanel {
        height: auto;
        margin-top: 1;
    }

    SourceHealthPanel {
        height: auto;
        margin-top: 1;
    }

    SummaryPanel {
        height: 1;
        padding: 0 2;
        background: $panel;
        color: $text-muted;
    }

    StatusBar {
        height: 1;
        padding: 0 2;
        background: $panel;
        color: $text;
    }

    TransactionDetailScreen #detail-panel,
    HelpScreen #help-panel {
        padding: 1 3;
    }
    """
