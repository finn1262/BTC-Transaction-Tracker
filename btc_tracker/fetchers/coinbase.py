"""Coinbase public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher


class CoinbaseFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from Coinbase Exchange.

    Uses the public ``/products/{product_id}/trades`` endpoint, which needs
    no API key and returns the most recent trades only.
    """

    source_name = "coinbase"
    base_url = "https://api.exchange.coinbase.com"
    default_rate_limit = (10, 1.0)
    endpoints = ("/products/{product_id}/trades",)

    PRODUCT_ID = "BTC-USD"
    PAGE_SIZE = 100

    def __init__(self, *args: Any, product_id: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            product_id: Trading pair to query; defaults to ``BTC-USD``.
            **kwargs: Keyword arguments forwarded to the base fetcher.
        """
        super().__init__(*args, **kwargs)
        self._product_id = product_id or self.PRODUCT_ID

    async def _request(self, cursor: str | None = None) -> Any:
        """Fetch the most recent trades.

        Args:
            cursor: Unused; the endpoint exposes recent trades only.

        Returns:
            The raw JSON list of trades.
        """
        return await self._get(
            f"{self.base_url}/products/{self._product_id}/trades",
            params={"limit": self.PAGE_SIZE},
            endpoint="/products/{product_id}/trades",
        )

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade list from the payload."""
        return payload if isinstance(payload, list) else []
