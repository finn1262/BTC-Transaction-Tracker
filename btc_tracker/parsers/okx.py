"""OKX parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import OkxPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class OkxParser(AbstractBaseParser):
    """Map OKX public trades to domain entities."""

    source_name = "okx"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one OKX trade to a signed BTC transaction.

        Args:
            item: Raw trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = OkxPublicTradeSchema.model_validate(item)
        if not schema.tradeId:
            raise ValueError("trade missing tradeId")
        amount = self._to_sats(schema.sz, "sz")
        if schema.side.lower() == "sell":
            amount = -amount
        return Transaction(
            external_id=schema.tradeId,
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.ts, "ts"),
            status=TransactionStatus.CONFIRMED,
        )
