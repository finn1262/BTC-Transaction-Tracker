"""Market-scoped exchange source service."""

import asyncio
from typing import Any

from btc_tracker.data.models import Transaction
from btc_tracker.fetchers.base import AbstractBaseFetcher
from btc_tracker.parsers.base import AbstractBaseParser
from btc_tracker.services.base import AbstractSourceService


class ExchangeService(AbstractSourceService):
    """Compose an exchange fetcher and parser into a market-data source.

    Exchange sources expose public market trades only; they are never passed
    a wallet address and do not report account balances.
    """

    def __init__(
        self,
        fetcher: AbstractBaseFetcher,
        parser: AbstractBaseParser,
        logger: Any = None,
    ) -> None:
        """Initialize the service.

        Args:
            fetcher: Public exchange fetcher implementing pagination.
            parser: Parser mapping exchange payloads to transactions.
            logger: Optional logger.
        """
        super().__init__(fetcher, parser, logger)

    async def fetch_transactions(
        self, address: str | None = None, *, pages: int | None = None
    ) -> list[Transaction]:
        """Fetch and map recent exchange market trades.

        Parsing runs in a worker thread: mapping thousands of raw trades is
        CPU-bound and must never stall the event loop that drives the TUI.

        Args:
            address: Ignored; exchange sources are market-scoped.
            pages: Optional page cap for this fetch.

        Returns:
            Mapped transactions.
        """
        raw = await self._fetcher.fetch(max_pages=pages)
        if not raw:
            return []
        return await asyncio.to_thread(self._parser.parse, raw)
