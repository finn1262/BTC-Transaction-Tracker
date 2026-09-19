"""MEXC parser."""

from btc_tracker.data.models import Transaction, TransactionStatus
from btc_tracker.data.schema import MexcTradeSchema
from btc_tracker.parsers.base import AbstractBaseParser


class MexcParser(AbstractBaseParser):
    """Map MEXC public trades to domain entities.

    MEXC leaves the public trade id null, so the external id is derived
    deterministically from the trade fields.
    """

    source_name = "mexc"

    def _map_item(self, item: dict, address: str | None) -> Transaction | None:
        """Map one MEXC trade to a signed BTC transaction.

        Args:
            item: Raw trade dictionary.
            address: Unused for exchange market sources.

        Returns:
            The mapped transaction.

        Raises:
            ValueError: If the trade lacks an id or timestamp.
        """
        schema = MexcTradeSchema.model_validate(item)
        amount = self._to_sats(schema.qty, "qty")
        if schema.isBuyerMaker:
            amount = -amount
        return Transaction(
            external_id=schema.id or self._derive_id(schema),
            source=self.source_name,
            amount_sats=amount,
            timestamp=self._to_datetime_from_ms(schema.time, "time"),
            status=TransactionStatus.CONFIRMED,
        )

    @staticmethod
    def _derive_id(schema: MexcTradeSchema) -> str:
        """Build a deterministic id for a trade MEXC returned without one.

        Args:
            schema: Validated trade fields.

        Returns:
            A stable identifier derived from time, price, size, and side.

        Raises:
            ValueError: If the trade has no timestamp to key on.
        """
        if schema.time <= 0:
            raise ValueError("trade missing id and timestamp")
        return f"{schema.time}-{schema.price}-{schema.qty}-{schema.tradeType or 'trade'}"
