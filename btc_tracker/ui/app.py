"""Textual application shell for the BTC Transaction Tracker."""

from typing import Any

from textual.app import App
from textual.binding import Binding

from btc_tracker.core.config import Config
from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.ui.screens import MainScreen
from btc_tracker.ui.styles import Styles
from btc_tracker.utils.logger import LoggerFactory


class BTCTrackerApp(App[None]):
    """Top-level Textual application owning screen navigation."""

    TITLE = "BTC Transaction Tracker"
    SUB_TITLE = "Market Trades"

    CSS = Styles.CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        transaction_service: TransactionService,
        exporter: CsvExporter,
        config: Config,
        logger: Any = None,
    ) -> None:
        """Initialize the application.

        Args:
            transaction_service: Aggregation service.
            exporter: CSV exporter for the export key.
            config: Application configuration.
            logger: Optional logger.
        """
        super().__init__()
        self._transaction_service = transaction_service
        self._exporter = exporter
        self._config = config
        self._tracker_logger = logger or LoggerFactory.create("ui.app")

    def on_mount(self) -> None:
        """Push the main screen on startup."""
        self.push_screen(
            MainScreen(
                transaction_service=self._transaction_service,
                exporter=self._exporter,
                config=self._config,
                logger=self._tracker_logger,
            )
        )
