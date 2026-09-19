"""Gemini parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import GeminiPublicTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class GeminiParser(AbstractBaseParser):
    """Map Gemini public trades to domain entities."""

    source_name = "gemini"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Gemini trade to a signed BTC transaction.

        Args:
            item: Raw trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = GeminiPublicTradeSchema.model_validate(item)
        if schema.tid <= 0:
            raise ValueError("trade missing tid")
        amount = self._to_sats(schema.amount, "amount")
        if schema.type.lower() == "sell":
            amount = -amount
        return Transaction(
            external_id=str(schema.tid),
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.timestampms, "timestampms"),
            status=TransactionStatus.CONFIRMED,
        )
