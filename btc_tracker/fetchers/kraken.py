"""Kraken public market-data fetcher."""

from typing import Any

from btc_tracker.fetchers.base import AbstractBaseFetcher, FetcherError


class KrakenFetcher(AbstractBaseFetcher):
    """Fetch recent BTC spot trades from Kraken.

    Uses the public ``/0/public/Trades`` endpoint, which needs no API key
    and returns the last 1000 trades only.
    """

    source_name = "kraken"
    base_url = "https://api.kraken.com"
    default_rate_limit = (10, 1.0)
    endpoints = ("/0/public/Trades",)

    PAIR = "XBTUSD"
    PAGE_SIZE = 1000

    def __init__(self, *args: Any, pair: str | None = None, **kwargs: Any) -> None:
        """Initialize the fetcher.

        Args:
            *args: Positional arguments forwarded to the base fetcher.
            pair: Trading pair to query; defaults to ``XBTUSD``.
            **kwargs: Keyword arguments forwarded to the base fetcher.
        """
        super().__init__(*args, **kwargs)
        self._pair = pair or self.PAIR

    async def _request(self, cursor: str | None = None) -> Any:
        """Fetch the most recent trades.

        Args:
            cursor: Unused; the endpoint exposes recent trades only.

        Returns:
            The decoded payload containing the trade rows.

        Raises:
            FetcherError: If Kraken reports a request error.
        """
        payload = await self._get(
            f"{self.base_url}/0/public/Trades",
            params={"pair": self._pair, "count": self.PAGE_SIZE},
            endpoint="/0/public/Trades",
        )
        errors = payload.get("error") if isinstance(payload, dict) else None
        if errors:
            raise FetcherError(f"kraken: {'; '.join(str(error) for error in errors)}")
        return payload

    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the trade rows from the pair-keyed result block."""
        result = payload.get("result", {}) if isinstance(payload, dict) else {}
        for key, value in result.items():
            if key != "last" and isinstance(value, list):
                return value
        return []
