"""Gemini public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher


class GeminiFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from Gemini.

    Uses the public ``/v1/trades/{symbol}`` endpoint, which needs no API key
    and returns the most recent trades only.
    """

    source_name = "gemini"
    base_url = "https://api.gemini.com"
    default_rate_limit = (5, 1.0)
    endpoints = ("/v1/trades/{symbol}",)

    SYMBOL = "btcusd"
    PAGE_SIZE = 500

    def __init__(self, *args: Any, symbol: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            symbol: Trading pair to query; defaults to ``btcusd``.
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
            f"{self.base_url}/v1/trades/{self._symbol}",
            params={"limit_trades": self.PAGE_SIZE},
            endpoint="/v1/trades/{symbol}",
        )

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload if isinstance(payload, list) else []
