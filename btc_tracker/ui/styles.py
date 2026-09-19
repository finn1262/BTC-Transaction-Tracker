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

    TradeSearchBar {
        dock: top;
        margin: 1 2 0 2;
    }

    SourceFilterTabs {
        dock: top;
        margin: 1 2 0 2;
        width: 44;
    }

    TransactionTable {
        height: 1fr;
        margin: 1 2;
    }

    SummaryPanel {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    StatusBar {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text;
        padding: 0 2;
    }

    TransactionDetailScreen #detail-panel,
    HelpScreen #help-panel {
        padding: 1 3;
    }
    """
