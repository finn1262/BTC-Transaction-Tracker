"""Abstract source service composing one fetcher with one parser."""

from abc import ABC, abstractmethod
from typing import Any

from btc_tracker.data.models import Transaction
from btc_tracker.fetchers.base import AbstractBaseFetcher
from btc_tracker.parsers.base import AbstractBaseParser
from btc_tracker.utils.logger import LoggerFactory


class AbstractSourceService(ABC):
    """Compose a fetcher and parser into one interchangeable source.

    Concrete subclasses decide the fetch scope while the fetcher owns I/O
    and the parser owns mapping.
    """

    def __init__(
        self,
        fetcher: AbstractBaseFetcher,
        parser: AbstractBaseParser,
        logger: Any = None,
    ) -> None:
        """Initialize the service.

        Args:
            fetcher: Source fetcher providing raw payloads.
            parser: Parser mapping payloads to transactions.
            logger: Optional logger.
        """
        self._fetcher = fetcher
        self._parser = parser
        self._logger = logger or LoggerFactory.create(f"services.{fetcher.source_name}")

    @property
    def source_name(self) -> str:
        """Return the source name shared by the fetcher and parser."""
        return self._fetcher.source_name

    @property
    def fetcher(self) -> AbstractBaseFetcher:
        """Return the underlying fetcher."""
        return self._fetcher

    @property
    def parser(self) -> AbstractBaseParser:
        """Return the underlying parser."""
        return self._parser

    @abstractmethod
    async def fetch_transactions(
        self, address: str | None = None, *, pages: int | None = None
    ) -> list[Transaction]:
        """Fetch and map transactions for this source.

        Args:
            address: Wallet address for address-scoped sources.
            pages: Optional page cap for this fetch; ``None`` uses the
                source default.

        Returns:
            Mapped transactions.
        """
