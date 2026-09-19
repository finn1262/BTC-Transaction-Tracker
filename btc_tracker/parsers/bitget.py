"""Bitget parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import BitgetPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class BitgetParser(AbstractBaseParser):
    """Map Bitget public trades to domain entities."""

    source_name = "bitget"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Bitget trade to a signed BTC transaction.

        Args:
            item: Raw market-fill dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = BitgetPublicTradeSchema.model_validate(item)
        if not schema.tradeId:
            raise ValueError("trade missing tradeId")
        amount = self._to_sats(schema.size, "size")
        if schema.side.lower() == "sell":
            amount = -amount
        return Transaction(
            external_id=schema.tradeId,
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.ts, "ts"),
            status=TransactionStatus.CONFIRMED,
        )
