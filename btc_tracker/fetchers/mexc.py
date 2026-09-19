"""MEXC public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher


class MexcFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from MEXC.

    Uses the public ``/api/v3/trades`` endpoint, which needs no API key and
    returns the most recent trades only.
    """

    source_name = "mexc"
    base_url = "https://api.mexc.com"
    default_rate_limit = (20, 1.0)
    endpoints = ("/api/v3/trades",)

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
            The raw JSON list of trades.
        """
        return await self._get(
            f"{self.base_url}/api/v3/trades",
            params={"symbol": self._symbol, "limit": self.PAGE_SIZE},
            endpoint="/api/v3/trades",
        )

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload if isinstance(payload, list) else []
