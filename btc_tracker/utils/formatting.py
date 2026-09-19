"""Satoshi/BTC conversion and timestamp presentation formatting."""

from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

SATS_PER_BTC = 100_000_000


class SatoshiConverter:
    """Convert between decimal BTC amounts and integer satoshis.

    Conversion uses :class:`~decimal.Decimal` so API string amounts never
    lose precision through binary floating point.
    """

    SATS_PER_BTC = SATS_PER_BTC
    BTC_QUANTUM = Decimal("0.00000001")

    def to_sats(self, value: str | int | float | Decimal) -> int:
        """Convert a BTC amount to satoshis.

        Args:
            value: BTC amount as string, int, float, or Decimal.

        Returns:
            The amount in integer satoshis.

        Raises:
            ValueError: If the value is not a valid decimal number.
        """
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"invalid BTC amount: {value!r}") from exc
        return int((amount * self.SATS_PER_BTC).to_integral_value(rounding=ROUND_HALF_UP))

    def to_btc(self, sats: int) -> Decimal:
        """Convert integer satoshis to a BTC decimal.

        Args:
            sats: Amount in satoshis.

        Returns:
            The amount in BTC quantized to 8 decimal places.
        """
        return (Decimal(int(sats)) / Decimal(self.SATS_PER_BTC)).quantize(self.BTC_QUANTUM)


class Formatter:
    """Format domain values for terminal presentation.

    Amounts are always handled as integer satoshis; BTC strings are produced
    with :class:`~decimal.Decimal` so no floating-point precision is lost.
    """

    def __init__(self, converter: SatoshiConverter | None = None) -> None:
        """Initialize the formatter.

        Args:
            converter: Optional satoshi converter override.
        """
        self._converter = converter or SatoshiConverter()

    def format_sats(self, sats: int) -> str:
        """Format integer satoshis as a BTC string.

        Args:
            sats: Amount in satoshis.

        Returns:
            A fixed 8-decimal BTC string (e.g. ``"0.00100000"``).
        """
        return f"{self._converter.to_btc(sats):.8f}"

    def format_amount(self, sats: int) -> str:
        """Format a signed satoshi amount as BTC with an explicit sign.

        Args:
            sats: Signed amount in satoshis.

        Returns:
            A string such as ``"+0.00100000"`` or ``"-0.00100000"``.
        """
        sign = "+" if sats >= 0 else "-"
        return f"{sign}{self.format_sats(abs(sats))}"

    def format_amount_with_unit(self, sats: int) -> str:
        """Format a signed satoshi amount as BTC including the unit.

        Args:
            sats: Signed amount in satoshis.

        Returns:
            A string such as ``"+0.00100000 BTC"``.
        """
        return f"{self.format_amount(sats)} BTC"

    def format_fee(self, sats: int) -> str:
        """Format a fee in satoshis for display.

        Args:
            sats: Fee amount in satoshis.

        Returns:
            A string such as ``"1234 sats"``.
        """
        return f"{int(sats)} sats"

    def format_timestamp(self, timestamp: datetime) -> str:
        """Format a timestamp as a UTC display string.

        Args:
            timestamp: Timezone-aware or naive datetime (naive is treated as UTC).

        Returns:
            A string such as ``"2026-09-20 14:33:00 UTC"``.
        """
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        return timestamp.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    def format_count(self, value: int) -> str:
        """Format an integer with thousands separators.

        Args:
            value: Integer to format.

        Returns:
            A string such as ``"21,088"``.
        """
        return f"{int(value):,}"

    def format_age(self, seconds: float) -> str:
        """Format an elapsed duration for compact status displays.

        Args:
            seconds: Elapsed time in seconds; negative values mean "just now".

        Returns:
            A string such as ``"just now"``, ``"12s ago"``, ``"4m ago"``, or ``"2h ago"``.
        """
        if seconds < 5:
            return "just now"
        if seconds < 60:
            return f"{int(seconds)}s ago"
        if seconds < 3600:
            return f"{int(seconds // 60)}m ago"
        return f"{int(seconds // 3600)}h ago"

    def shorten(self, value: str, leading: int = 8, trailing: int = 6) -> str:
        """Shorten a long identifier for narrow table columns.

        Args:
            value: Identifier to shorten.
            leading: Number of leading characters to keep.
            trailing: Number of trailing characters to keep.

        Returns:
            The original value when short enough, otherwise ``"head...tail"``.
        """
        if len(value) <= leading + trailing + 3:
            return value
        return f"{value[:leading]}...{value[-trailing:]}"
