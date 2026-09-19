"""Transaction domain entity with boundary validation and serialization."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class TransactionStatus(StrEnum):
    """Lifecycle state of a transaction or trade."""

    CONFIRMED = "confirmed"
    PENDING = "pending"
    FAILED = "failed"


class Transaction:
    """Domain entity for an exchange market trade.

    Attributes are private; consumers read them through properties. All
    amounts are integer satoshis so financial precision is never lost.

    Args:
        external_id: Trade identifier scoped to the source.
        source: Source name (e.g. ``"binance"``, ``"kraken"``).
        amount_sats: Signed amount in satoshis; positive means bought.
        timestamp: Trade time; naive values are treated as UTC.
        address_from: Reserved for address-scoped sources; ``None`` for trades.
        address_to: Reserved for address-scoped sources; ``None`` for trades.
        fee_sats: Fee in satoshis, never negative.
        status: One of :class:`TransactionStatus`.
        block_number: Confirming block height when known.

    Raises:
        ValueError: If any argument fails boundary validation.
    """

    def __init__(
        self,
        external_id: str,
        source: str,
        amount_sats: int,
        timestamp: datetime,
        address_from: str | None = None,
        address_to: str | None = None,
        fee_sats: int = 0,
        status: str = TransactionStatus.CONFIRMED,
        block_number: int | None = None,
    ) -> None:
        self._external_id = self._validate_text(external_id, "external_id")
        self._source = self._validate_text(source, "source")
        self._amount_sats = self._validate_integer(amount_sats, "amount_sats", minimum=None)
        self._timestamp = self._validate_timestamp(timestamp)
        self._address_from = self._validate_optional_text(address_from, "address_from")
        self._address_to = self._validate_optional_text(address_to, "address_to")
        self._fee_sats = self._validate_integer(fee_sats, "fee_sats", minimum=0)
        self._status = self._validate_status(status)
        self._block_number = self._validate_optional_integer(block_number, "block_number")

    @property
    def external_id(self) -> str:
        """Return the source-scoped transaction identifier."""
        return self._external_id

    @property
    def source(self) -> str:
        """Return the source name."""
        return self._source

    @property
    def amount_sats(self) -> int:
        """Return the signed amount in satoshis."""
        return self._amount_sats

    @property
    def timestamp(self) -> datetime:
        """Return the UTC transaction timestamp."""
        return self._timestamp

    @property
    def address_from(self) -> str | None:
        """Return the sending address, if any."""
        return self._address_from

    @property
    def address_to(self) -> str | None:
        """Return the receiving address, if any."""
        return self._address_to

    @property
    def fee_sats(self) -> int:
        """Return the fee in satoshis."""
        return self._fee_sats

    @property
    def status(self) -> TransactionStatus:
        """Return the transaction status."""
        return self._status

    @property
    def block_number(self) -> int | None:
        """Return the confirming block height, if known."""
        return self._block_number

    @property
    def dedup_key(self) -> tuple[str, str]:
        """Return the ``(source, external_id)`` deduplication key."""
        return (self._source, self._external_id)

    @property
    def is_confirmed(self) -> bool:
        """Return whether the transaction is confirmed."""
        return self._status is TransactionStatus.CONFIRMED

    @property
    def is_incoming(self) -> bool:
        """Return whether the amount is non-negative (received)."""
        return self._amount_sats >= 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the transaction to a plain dictionary.

        Returns:
            A JSON-friendly mapping with an ISO-8601 UTC timestamp.
        """
        return {
            "source": self._source,
            "external_id": self._external_id,
            "address_from": self._address_from,
            "address_to": self._address_to,
            "amount_sats": self._amount_sats,
            "fee_sats": self._fee_sats,
            "timestamp": self._timestamp.isoformat(),
            "status": str(self._status),
            "block_number": self._block_number,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Transaction":
        """Build a transaction from a serialized dictionary.

        Args:
            data: Mapping produced by :meth:`to_dict` (extra keys ignored).

        Returns:
            The reconstructed :class:`Transaction`.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        try:
            external_id = data["external_id"]
            source = data["source"]
            amount_sats = data["amount_sats"]
            timestamp = data["timestamp"]
        except KeyError as exc:
            raise ValueError(f"missing required transaction field: {exc}") from exc
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp)
        return cls(
            external_id=external_id,
            source=source,
            amount_sats=amount_sats,
            timestamp=timestamp,
            address_from=data.get("address_from"),
            address_to=data.get("address_to"),
            fee_sats=data.get("fee_sats", 0),
            status=data.get("status", TransactionStatus.CONFIRMED),
            block_number=data.get("block_number"),
        )

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Transaction):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    def __hash__(self) -> int:
        return hash(self.dedup_key)

    def __repr__(self) -> str:
        return (
            f"Transaction(source={self._source!r}, external_id={self._external_id!r}, "
            f"amount_sats={self._amount_sats}, status={str(self._status)!r})"
        )

    @staticmethod
    def _validate_text(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field} must be a non-empty string")
        return value.strip()

    @staticmethod
    def _validate_optional_text(value: Any, field: str) -> str | None:
        if value is None:
            return None
        return Transaction._validate_text(value, field)

    @staticmethod
    def _validate_integer(value: Any, field: str, minimum: int | None) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{field} must be an integer")
        if minimum is not None and value < minimum:
            raise ValueError(f"{field} must be >= {minimum}")
        return value

    @staticmethod
    def _validate_optional_integer(value: Any, field: str) -> int | None:
        if value is None:
            return None
        return Transaction._validate_integer(value, field, minimum=0)

    @staticmethod
    def _validate_timestamp(value: Any) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("timestamp must be a datetime")
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _validate_status(value: Any) -> TransactionStatus:
        try:
            return TransactionStatus(str(value).lower())
        except ValueError as exc:
            allowed = ", ".join(member.value for member in TransactionStatus)
            raise ValueError(f"status must be one of: {allowed}") from exc
