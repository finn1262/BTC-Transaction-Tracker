"""Kraken parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import KrakenPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class KrakenParser(AbstractBaseParser):
    """Map Kraken public trades to domain entities."""

    source_name = "kraken"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Kraken trade row to a signed BTC transaction.

        Args:
            item: Raw trade row (positional array from the API).
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = KrakenPublicTradeSchema.model_validate(item)
        if schema.trade_id <= 0:
            raise ValueError("trade missing id")
        amount = self._to_sats(schema.volume, "volume")
        if schema.side.lower() == "s":
            amount = -amount
        return Transaction(
            external_id=str(schema.trade_id),
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_seconds(schema.time, "time"),
            status=TransactionStatus.CONFIRMED,
        )
