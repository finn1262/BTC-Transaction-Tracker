"""KuCoin public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher, FetcherError


class KucoinFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from KuCoin.

    Uses the public ``/api/v1/market/histories`` endpoint, which needs no API
    key and returns the 100 most recent trades only.
    """

    source_name = "kucoin"
    base_url = "https://api.kucoin.com"
    default_rate_limit = (10, 1.0)
    endpoints = ("/api/v1/market/histories",)

    SYMBOL = "BTC-USDT"

    def __init__(self, *args: Any, symbol: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            symbol: Trading pair to query; defaults to ``BTC-USDT``.
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
            FetcherError: If KuCoin reports a request error.
        """
        payload = await self._get(
            f"{self.base_url}/api/v1/market/histories",
            params={"symbol": self._symbol},
            endpoint="/api/v1/market/histories",
        )
        if isinstance(payload, dict) and payload.get("code") not in ("200000", None):
            raise FetcherError(f"kucoin: {payload.get('msg') or payload.get('code')}")
        return payload

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload.get("data", []) if isinstance(payload, dict) else []
