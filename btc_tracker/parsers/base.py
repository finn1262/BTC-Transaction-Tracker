"""Abstract parser mapping raw provider payloads to Transaction entities."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import InvalidOperation
from typing import Any, ClassVar

from pydantic import ValidationError

from btc_tracker.data.models import Transaction
from btc_tracker.utils.formatting import SatoshiConverter
from btc_tracker.utils.logger import LoggerFactory


class ParserError(Exception):
    """Raised when a payload cannot be mapped to domain entities."""


class AbstractBaseParser(ABC):
    """Template for raw-payload to domain-model mapping.

    Parsers contain no network code. Each malformed item is logged and
    skipped so one bad record cannot discard an entire page.
    """

    source_name: ClassVar[str] = ""

    def __init__(self, logger: Any = None, converter: SatoshiConverter | None = None) -> None:
        """Initialize the parser.

        Args:
            logger: Optional logger; a namespaced logger is created otherwise.
            converter: Optional satoshi converter override.

        Raises:
            ValueError: If ``source_name`` is not declared.
        """
        if not self.source_name:
            raise ValueError(f"{type(self).__name__} must declare a source_name")
        self._logger = logger or LoggerFactory.create(f"parsers.{self.source_name}")
        self._converter = converter or SatoshiConverter()

    def parse(self, raw: Any, address: str | None = None) -> list[Transaction]:
        """Map a list of raw provider items to transactions.

        Args:
            raw: List of raw item dictionaries from a fetcher.
            address: Reserved for address-scoped sources; ignored by exchanges.

        Returns:
            A list of valid :class:`Transaction` entities.
        """
        transactions: list[Transaction] = []
        for item in raw or []:
            try:
                transaction = self._map_item(item, address)
            except (
                ValidationError,
                ValueError,
                KeyError,
                TypeError,
                ArithmeticError,
                InvalidOperation,
            ) as exc:
                self._logger.warning("%s: skipping malformed item: %s", self.source_name, exc)
                continue
            if transaction is not None:
                transactions.append(transaction)
        return transactions

    @abstractmethod
    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one raw item, returning ``None`` to filter it out."""

    def _to_sats(self, value: Any, field: str = "amount") -> int:
        """Convert a provider BTC amount to satoshis.

        Args:
            value: Amount in BTC (string, int, float, or Decimal).
            field: Field name used in error messages.

        Returns:
            Amount in satoshis.

        Raises:
            ValueError: If the amount cannot be converted.
        """
        try:
            return self._converter.to_sats(value)
        except ValueError as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc

    @staticmethod
    def _to_datetime_from_ms(value: Any, field: str = "timestamp") -> datetime:
        """Convert a millisecond epoch value to a UTC datetime.

        Args:
            value: Milliseconds since the Unix epoch.
            field: Field name used in error messages.

        Returns:
            A timezone-aware UTC datetime.

        Raises:
            ValueError: If the value is missing or not positive.
        """
        try:
            milliseconds = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
        if milliseconds <= 0:
            raise ValueError(f"{field} must be positive")
        return datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)

    @staticmethod
    def _to_datetime_from_nanoseconds(value: Any, field: str = "timestamp") -> datetime:
        """Convert a nanosecond epoch value to a UTC datetime.

        Args:
            value: Nanoseconds since the Unix epoch.
            field: Field name used in error messages.

        Returns:
            A timezone-aware UTC datetime.

        Raises:
            ValueError: If the value is missing or not positive.
        """
        try:
            nanoseconds = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
        if nanoseconds <= 0:
            raise ValueError(f"{field} must be positive")
        return datetime.fromtimestamp(nanoseconds / 1_000_000_000, tz=timezone.utc)

    @staticmethod
    def _to_datetime_from_seconds(value: Any, field: str = "timestamp") -> datetime:
        """Convert a seconds epoch value to a UTC datetime.

        Args:
            value: Seconds since the Unix epoch.
            field: Field name used in error messages.

        Returns:
            A timezone-aware UTC datetime.

        Raises:
            ValueError: If the value is missing or not positive.
        """
        try:
            seconds = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid {field}: {value!r}") from exc
        if seconds <= 0:
            raise ValueError(f"{field} must be positive")
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
