"""Binance parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import BinanceAggTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class BinanceParser(AbstractBaseParser):
    """Map Binance aggregate trades to domain entities."""

    source_name = "binance"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one Binance aggregate trade to a signed BTC transaction.

        Args:
            item: Raw aggregate-trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks a valid id or timestamp.
        """
        schema = BinanceAggTradeSchema.model_validate(item)
        if schema.a <= 0:
            raise ValueError("agg trade missing id")
        amount = self._to_sats(schema.q, "q")
        if schema.m:
            amount = -amount
        return Transaction(
            external_id=str(schema.a),
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.T, "T"),
            status=TransactionStatus.CONFIRMED,
        )
