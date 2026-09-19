"""Bitget public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher, FetcherError


class BitgetFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from Bitget.

    Uses the public ``/api/v2/spot/market/fills`` endpoint, which needs no
    API key and returns the most recent trades only.
    """

    source_name = "bitget"
    base_url = "https://api.bitget.com"
    default_rate_limit = (10, 1.0)
    endpoints = ("/api/v2/spot/market/fills",)

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
        """Fetch the most recent trades.

        Args:
            cursor: Unused; the endpoint exposes recent trades only.

        Returns:
            The decoded payload containing the trade list.

        Raises:
            FetcherError: If Bitget reports a request error.
        """
        payload = await self._get(
            f"{self.base_url}/api/v2/spot/market/fills",
            params={"symbol": self._symbol, "limit": str(self.PAGE_SIZE)},
            endpoint="/api/v2/spot/market/fills",
        )
        if isinstance(payload, dict) and payload.get("code") not in ("00000", None):
            raise FetcherError(f"bitget: {payload.get('msg') or payload.get('code')}")
        return payload

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload.get("data", []) if isinstance(payload, dict) else []
