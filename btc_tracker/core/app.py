"""Application orchestrator owning configuration, services, and lifecycle."""

import argparse
import asyncio
from typing import Any, ClassVar

import aiohttp

from btc_tracker.core.config import Config
from btc_tracker.fetchers.base import AbstractBaseFetcher
from btc_tracker.fetchers.binance import BinanceFetcher
from btc_tracker.fetchers.bitget import BitgetFetcher
from btc_tracker.fetchers.bybit import BybitFetcher
from btc_tracker.fetchers.coinbase import CoinbaseFetcher
from btc_tracker.fetchers.gemini import GeminiFetcher
from btc_tracker.fetchers.kraken import KrakenFetcher
from btc_tracker.fetchers.kucoin import KucoinFetcher
from btc_tracker.fetchers.mexc import MexcFetcher
from btc_tracker.fetchers.okx import OkxFetcher
from btc_tracker.parsers.base import AbstractBaseParser
from btc_tracker.parsers.binance import BinanceParser
from btc_tracker.parsers.bitget import BitgetParser
from btc_tracker.parsers.bybit import BybitParser
from btc_tracker.parsers.coinbase import CoinbaseParser
from btc_tracker.parsers.gemini import GeminiParser
from btc_tracker.parsers.kraken import KrakenParser
from btc_tracker.parsers.kucoin import KucoinParser
from btc_tracker.parsers.mexc import MexcParser
from btc_tracker.parsers.okx import OkxParser
from btc_tracker.services.base import AbstractSourceService
from btc_tracker.services.exchange_service import ExchangeService
from btc_tracker.services.transaction_service import TransactionService
from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.storage.sqlite import SQLiteStorage
from btc_tracker.ui.app import BTCTrackerApp
from btc_tracker.utils.logger import LoggerFactory
from btc_tracker.utils.rate_limiter import RateLimiter


class Application:
    """Build dependencies, run the TUI, and release resources.

    This is the composition root: it owns the HTTP session, storage backend,
    and service graph. No business logic lives here.
    """

    EXCHANGE_SOURCES: ClassVar[dict[str, tuple[type[AbstractBaseFetcher], type[AbstractBaseParser]]]] = {
        "binance": (BinanceFetcher, BinanceParser),
        "coinbase": (CoinbaseFetcher, CoinbaseParser),
        "kraken": (KrakenFetcher, KrakenParser),
        "bybit": (BybitFetcher, BybitParser),
        "okx": (OkxFetcher, OkxParser),
        "kucoin": (KucoinFetcher, KucoinParser),
        "bitget": (BitgetFetcher, BitgetParser),
        "mexc": (MexcFetcher, MexcParser),
        "gemini": (GeminiFetcher, GeminiParser),
    }

    def __init__(self, config: Config, logger: Any = None) -> None:
        """Initialize the orchestrator.

        Args:
            config: Application configuration.
            logger: Optional logger.
        """
        self._config = config
        self._logger = logger or LoggerFactory.create("core.app", config.log_level)
        self._session: aiohttp.ClientSession | None = None
        self._storage: SQLiteStorage | None = None
        self._transaction_service: TransactionService | None = None

    async def run(self) -> None:
        """Build dependencies and run the TUI until the user quits."""
        self._logger.info("starting BTC Transaction Tracker")
        self._session = aiohttp.ClientSession()
        try:
            self._storage = SQLiteStorage(self._config.database_path, self._logger)
            services = self._build_services(self._session)
            self._transaction_service = TransactionService(
                services,
                self._storage,
                self._logger,
                poll_interval=self._config.poll_interval_seconds,
                backfill_pages=self._config.backfill_pages,
                poll_pages=self._config.poll_pages,
                history_limit=self._config.history_limit,
                max_transactions=self._config.max_transactions,
            )
            ui_app = BTCTrackerApp(
                transaction_service=self._transaction_service,
                exporter=CsvExporter(self._logger),
                config=self._config,
                logger=self._logger,
            )
            await ui_app.run_async()
        finally:
            await self._shutdown()

    async def _shutdown(self) -> None:
        if self._transaction_service is not None:
            await self._transaction_service.stop()
            self._transaction_service = None
        if self._session is not None:
            await self._session.close()
            self._session = None
        if self._storage is not None:
            await self._storage.close()
            self._storage = None
        self._logger.info("shutdown complete")

    def _build_services(self, session: aiohttp.ClientSession) -> list[AbstractSourceService]:
        rate_limiter = RateLimiter(
            default_max_requests=self._config.default_rate_limit_requests,
            default_window_seconds=self._config.default_rate_limit_window_seconds,
        )
        services: list[AbstractSourceService] = []
        for name, (fetcher_class, parser_class) in self.EXCHANGE_SOURCES.items():
            fetcher = fetcher_class(
                session=session,
                rate_limiter=rate_limiter,
                logger=self._logger,
                timeout=self._config.http_timeout_seconds,
                max_retries=self._config.max_retries,
            )
            services.append(ExchangeService(fetcher, parser_class(self._logger), self._logger))
        self._logger.info("configured %d sources", len(services))
        return services

    @classmethod
    def main(cls) -> None:
        """Parse CLI arguments and run the application."""
        parser = argparse.ArgumentParser(
            prog="btc-tracker",
            description="Aggregate BTC buy/sell market trades from exchanges.",
        )
        parser.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, ...)")
        args = parser.parse_args()
        config = Config(log_level=args.log_level) if args.log_level else Config()
        logger = LoggerFactory.create("core.app", config.log_level)
        try:
            asyncio.run(cls(config, logger).run())
        except KeyboardInterrupt:
            logger.info("interrupted; shutting down")
