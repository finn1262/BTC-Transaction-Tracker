"""Bybit parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import BybitPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class BybitParser(AbstractBaseParser):
    """Map Bybit public trades to domain entities."""

    source_name = "bybit"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Bybit trade to a signed BTC transaction.

        Args:
            item: Raw recent-trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = BybitPublicTradeSchema.model_validate(item)
        if not schema.execId:
            raise ValueError("trade missing execId")
        amount = self._to_sats(schema.size, "size")
        if schema.side.lower() == "sell":
            amount = -amount
        return Transaction(
            external_id=schema.execId,
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.time, "time"),
            status=TransactionStatus.CONFIRMED,
        )
