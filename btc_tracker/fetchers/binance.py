"""Binance public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher


class BinanceFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot aggregate trades from Binance.

    Uses the public ``/api/v3/aggTrades`` market-data endpoint, which needs
    no API key. Older trades are paged backwards with ``endTime``.
    """

    source_name = "binance"
    base_url = "https://api.binance.com"
    default_rate_limit = (20, 1.0)
    endpoints = ("/api/v3/aggTrades",)

    SYMBOL = "BTCUSDT"
    PAGE_SIZE = 1000

    def __init__(self, *args: Any, symbol: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            symbol: Trading pair to query; defaults to ``BTCUSDT``.
            **kwargs: Keyword arguments forwarded to the base fetcher.
        """
        super().__init__(*args, **kwargs)
        self._symbol = symbol or self.SYMBOL

    async def _request(self, cursor: str | None = None) -> Any:
        """Fetch one page of aggregate trades.

        Args:
            cursor: ``endTime`` in milliseconds bounding older trades.

        Returns:
            The raw JSON list of aggregate trades.
        """
        params: dict[str, Any] = {"symbol": self._symbol, "limit": self.PAGE_SIZE}
        if cursor:
            params["endTime"] = cursor
        return await self._get(
            f"{self.base_url}/api/v3/aggTrades",
            params=params,
            endpoint="/api/v3/aggTrades",
        )

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the aggregate-trade list from the payload."""
        return payload if isinstance(payload, list) else []

    def _next_page(self, payload: Any, cursor: str | None) -> str | None:
        """Return the timestamp bounding the next older page.

        ``endTime`` is inclusive, so the oldest timestamp is reused; any
        boundary duplicates are removed by ``(source, external_id)``
        deduplication.
        """
        items = self._extract_items(payload)
        if len(items) < self.PAGE_SIZE:
            return None
        timestamps = [int(item["T"]) for item in items if item.get("T")]
        if not timestamps:
            return None
        return str(min(timestamps))
