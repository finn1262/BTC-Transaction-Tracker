"""Unit tests for value formatting helpers."""

from datetime import datetime, timedelta, timezone

from btc_tracker.utils.formatting import Formatter, SatoshiConverter


class TestSatoshiConverter:
    def test_to_sats_uses_decimal_precision(self) -> None:
        converter = SatoshiConverter()
        assert converter.to_sats("0.00000001") == 1
        assert converter.to_sats("1.23456789") == 123_456_789
        assert converter.to_sats("-0.5") == -50_000_000

    def test_to_btc_quantizes(self) -> None:
        converter = SatoshiConverter()
        assert str(converter.to_btc(123_456_789)) == "1.23456789"

    def test_invalid_amount_raises(self) -> None:
        converter = SatoshiConverter()
        try:
            converter.to_sats("not-a-number")
        except ValueError:
            return
        raise AssertionError("expected ValueError")


class TestFormatter:
    def test_amount_helpers(self) -> None:
        formatter = Formatter()
        assert formatter.format_amount(1_000_000) == "+0.01000000"
        assert formatter.format_amount(-1_000_000) == "-0.01000000"
        assert formatter.format_amount_with_unit(1_000_000) == "+0.01000000 BTC"
        assert formatter.format_sats(0) == "0.00000000"

    def test_format_count(self) -> None:
        formatter = Formatter()
        assert formatter.format_count(21_088) == "21,088"
        assert formatter.format_count(0) == "0"

    def test_format_age(self) -> None:
        formatter = Formatter()
        assert formatter.format_age(0) == "just now"
        assert formatter.format_age(12) == "12s ago"
        assert formatter.format_age(120) == "2m ago"
        assert formatter.format_age(7_200) == "2h ago"

    def test_format_timestamp_treats_naive_as_utc(self) -> None:
        formatter = Formatter()
        naive = datetime(2026, 9, 20, 14, 33, 0)
        assert formatter.format_timestamp(naive) == "2026-09-20 14:33:00 UTC"

    def test_format_timestamp_converts_to_utc(self) -> None:
        formatter = Formatter()
        offset = timezone(timedelta(hours=8))
        moment = datetime(2026, 9, 20, 22, 33, 0, tzinfo=offset)
        assert formatter.format_timestamp(moment) == "2026-09-20 14:33:00 UTC"

    def test_shorten(self) -> None:
        formatter = Formatter()
        assert formatter.shorten("short") == "short"
        shortened = formatter.shorten("x" * 100)
        assert "..." in shortened
        assert len(shortened) == 8 + 3 + 6
