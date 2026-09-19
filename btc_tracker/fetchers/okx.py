"""OKX public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher, FetcherError


class OkxFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from OKX V5.

    Uses the public ``/api/v5/market/trades`` endpoint, which needs no API
    key and returns the most recent trades only.
    """

    source_name = "okx"
    base_url = "https://www.okx.com"
    default_rate_limit = (10, 2.0)
    endpoints = ("/api/v5/market/trades",)

    INST_ID = "BTC-USDT"
    PAGE_SIZE = 500

    def __init__(self, *args: Any, inst_id: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            inst_id: Instrument id to query; defaults to ``BTC-USDT``.
            **kwargs: Keyword arguments forwarded to the base fetcher.
        """
        super().__init__(*args, **kwargs)
        self._inst_id = inst_id or self.INST_ID

    async def _request(self, cursor: str | None = None) -> Any:
        """Fetch the most recent trades.

        Args:
            cursor: Unused; the endpoint exposes recent trades only.

        Returns:
            The decoded payload containing the trade list.

        Raises:
            FetcherError: If OKX reports a request error.
        """
        payload = await self._get(
            f"{self.base_url}/api/v5/market/trades",
            params={"instId": self._inst_id, "limit": str(self.PAGE_SIZE)},
            endpoint="/api/v5/market/trades",
        )
        if isinstance(payload, dict) and payload.get("code") not in ("0", None):
            raise FetcherError(f"okx: {payload.get('msg') or payload.get('code')}")
        return payload

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload.get("data", []) if isinstance(payload, dict) else []
