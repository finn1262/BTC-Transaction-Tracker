"""Coinbase parser."""

from datetime import datetime, timezone

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import CoinbaseTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class CoinbaseParser(AbstractBaseParser):
    """Map Coinbase Exchange public trades to domain entities."""

    source_name = "coinbase"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Coinbase trade to a signed BTC transaction.

        Coinbase reports the maker order side, so a maker buy means the
        taker sold and the amount is negative (and vice versa).

        Args:
            item: Raw trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = CoinbaseTradeSchema.model_validate(item)
        if schema.trade_id <= 0:
            raise ValueError("trade missing trade_id")
        amount = self._to_sats(schema.size, "size")
        if schema.side.lower() == "buy":
            amount = -amount
        return Transaction(
            external_id=str(schema.trade_id),
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._parse_trade_time(schema.time),
            status=TransactionStatus.CONFIRMED,
        )

    @staticmethod
    def _parse_trade_time(value: str) -> datetime:
        """Parse an ISO-8601 trade timestamp.

        Args:
            value: ISO timestamp from the API.

        Returns:
            A timezone-aware UTC datetime.

        Raises:
            ValueError: If the timestamp is missing or malformed.
        """
        if not value:
            raise ValueError("trade missing time")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
