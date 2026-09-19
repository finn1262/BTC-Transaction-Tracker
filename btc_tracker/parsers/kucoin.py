"""KuCoin parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import KucoinPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class KucoinParser(AbstractBaseParser):
    """Map KuCoin public trades to domain entities."""

    source_name = "kucoin"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one KuCoin trade to a signed BTC transaction.

        KuCoin reports the trade time in nanoseconds.

        Args:
            item: Raw market-history dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = KucoinPublicTradeSchema.model_validate(item)
        external_id = schema.tradeId or schema.sequence
        if not external_id:
            raise ValueError("trade missing id")
        amount = self._to_sats(schema.size, "size")
        if schema.side.lower() == "sell":
            amount = -amount
        return Transaction(
            external_id=external_id,
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_nanoseconds(schema.time, "time"),
            status=TransactionStatus.CONFIRMED,
        )
