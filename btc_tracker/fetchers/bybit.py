"""Bybit public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher, FetcherError


class BybitFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from Bybit V5.

    Uses the public ``/v5/market/recent-trade`` endpoint, which needs no API
    key and returns the most recent trades only.
    """

    source_name = "bybit"
    base_url = "https://api.bybit.com"
    default_rate_limit = (10, 1.0)
    endpoints = ("/v5/market/recent-trade",)

    SYMBOL = "BTCUSDT"
    PAGE_SIZE = 60

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
        """Fetch the most recent trades.

        Args:
            cursor: Unused; the endpoint exposes recent trades only.

        Returns:
            The decoded payload containing the trade list.

        Raises:
            FetcherError: If Bybit reports a request error.
        """
        payload = await self._get(
            f"{self.base_url}/v5/market/recent-trade",
            params={"category": "spot", "symbol": self._symbol, "limit": self.PAGE_SIZE},
            endpoint="/v5/market/recent-trade",
        )
        if isinstance(payload, dict) and payload.get("retCode") not in (0, None):
            raise FetcherError(f"bybit: {payload.get('retMsg') or payload.get('retCode')}")
        return payload

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the result block."""
        if not isinstance(payload, dict):
            return []
        return payload.get("result", {}).get("list", [])
