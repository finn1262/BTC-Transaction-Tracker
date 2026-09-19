"""Abstract fetcher owning the retry, timeout, rate-limit, and pagination lifecycle."""

import asyncio
import random
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

import aiohttp

from btc_tracker.utils.logger import LoggerFactory
from btc_tracker.utils.rate_limiter import RateLimiter


class FetcherError(Exception):
    """Raised when a fetch cannot be completed."""


class RateLimitError(FetcherError):
    """Raised when a provider signals rate limiting.

    Args:
        message: Human-readable description.
        retry_after: Seconds the provider asked the client to wait.
    """

    def __init__(self, message: str, retry_after: float = 0.0) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AbstractBaseFetcher(ABC):
    """Template for source fetchers.

    Subclasses implement the request/extraction hooks; this class owns the
    cross-cutting lifecycle: async rate limiting, timeouts, retries with
    exponential backoff, and cursor pagination.

    Class Attributes:
        source_name: Unique source identifier used for logging and rate limits.
        base_url: Provider API root URL.
        default_rate_limit: ``(max_requests, window_seconds)`` per endpoint.
        endpoints: Endpoint keys the default rate limit applies to.
        max_pages: Safety cap on pagination depth.
    """

    source_name: ClassVar[str] = ""
    base_url: ClassVar[str] = ""
    default_rate_limit: ClassVar[tuple[int, float]] = (10, 1.0)
    endpoints: ClassVar[tuple[str, ...]] = ()
    max_pages: ClassVar[int] = 10

    def __init__(
        self,
        session: aiohttp.ClientSession,
        rate_limiter: RateLimiter,
        logger: Any = None,
        *,
        timeout: float = 30.0,
        max_retries: int = 3,
        max_pages: int | None = None,
    ) -> None:
        """Initialize the fetcher.

        Args:
            session: Shared aiohttp session used for every request.
            rate_limiter: Async limiter coordinating request pacing.
            logger: Optional logger; a namespaced logger is created otherwise.
            timeout: Per-request timeout in seconds.
            max_retries: Maximum attempts per HTTP request.
            max_pages: Optional pagination cap override.

        Raises:
            ValueError: If ``source_name`` is not declared.
        """
        if not self.source_name:
            raise ValueError(f"{type(self).__name__} must declare a source_name")
        self._session = session
        self._rate_limiter = rate_limiter
        self._logger = logger or LoggerFactory.create(f"fetchers.{self.source_name}")
        self._timeout = timeout
        self._max_retries = max(1, max_retries)
        self._max_pages = max(1, max_pages or self.max_pages)
        for endpoint in self.endpoints:
            self._rate_limiter.configure(
                self.source_name, endpoint, self.default_rate_limit[0], self.default_rate_limit[1]
            )

    async def fetch(self, max_pages: int | None = None) -> list[dict]:
        """Fetch raw items for this source.

        Args:
            max_pages: Optional page cap for this call, clamped to the
                configured maximum. Live-feed polls use one page while the
                initial backfill may walk several pages.

        Returns:
            A flat list of raw provider item dictionaries.

        Raises:
            FetcherError: If a request fails after all retry attempts.
        """
        return await self._run_pagination(self._request, self._next_page, max_pages)

    async def _run_pagination(
        self,
        request: Callable[[str | None], Awaitable[Any]],
        next_page: Callable[[Any, str | None], str | None],
        max_pages: int | None = None,
    ) -> list[dict]:
        """Drive cursor pagination through the supplied request hook.

        Args:
            request: Coroutine function returning one page payload.
            next_page: Callable returning the next cursor or ``None``.
            max_pages: Optional page cap for this call.

        Returns:
            A flat list of extracted items across all pages.
        """
        page_cap = (
            self._max_pages
            if max_pages is None
            else max(1, min(max_pages, self._max_pages))
        )
        items: list[dict] = []
        cursor: str | None = None
        for _ in range(page_cap):
            payload = await request(cursor)
            items.extend(self._extract_items(payload))
            cursor = next_page(payload, cursor)
            if cursor is None:
                break
        else:
            self._logger.debug(
                "%s: pagination capped at %d pages; results may be truncated",
                self.source_name,
                page_cap,
            )
        return items

    @abstractmethod
    async def _request(self, cursor: str | None = None) -> Any:
        """Perform one page request and return the decoded payload."""

    @abstractmethod
    def _extract_items(self, payload: Any) -> list[dict]:
        """Return the list of raw item dictionaries from one page payload."""

    def _next_page(self, payload: Any, cursor: str | None) -> str | None:
        """Return the next cursor, or ``None`` when pagination is complete."""
        return None

    async def _get(
        self,
        url: str,
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
    ) -> Any:
        """Perform a rate-limited GET request with retries.

        Args:
            url: Absolute request URL.
            params: Optional query parameters.
            headers: Optional request headers.
            endpoint: Rate-limit key; defaults to the URL.

        Returns:
            The decoded JSON payload.
        """
        return await self._send("GET", url, params=params, headers=headers, endpoint=endpoint)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict[str, str] | None = None,
        endpoint: str | None = None,
    ) -> Any:
        """Send a request through the retry/rate-limit/backoff lifecycle.

        Args:
            method: HTTP method.
            url: Absolute request URL.
            params: Optional query parameters.
            headers: Optional request headers.
            endpoint: Rate-limit key; defaults to the URL.

        Returns:
            The decoded JSON payload.

        Raises:
            FetcherError: If every attempt fails.
        """
        key = endpoint or url
        last_error: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            await self._rate_limiter.acquire(self.source_name, key)
            try:
                timeout = aiohttp.ClientTimeout(total=self._timeout)
                async with self._session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=timeout,
                ) as response:
                    return await self._decode_response(response, url)
            except RateLimitError as exc:
                last_error = exc
                delay = self._retry_delay(attempt, exc.retry_after)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                delay = self._retry_delay(attempt)
            if attempt >= self._max_retries:
                break
            self._logger.warning(
                "%s: %s for %s (attempt %d/%d); retrying in %.1fs",
                self.source_name,
                type(last_error).__name__,
                url,
                attempt,
                self._max_retries,
                delay,
            )
            await asyncio.sleep(delay)
        raise FetcherError(
            f"{self.source_name}: request to {url} failed after {self._max_retries} attempts"
        ) from last_error

    async def _decode_response(self, response: aiohttp.ClientResponse, url: str) -> Any:
        """Validate the HTTP status and decode the JSON body.

        Args:
            response: The aiohttp response.
            url: Request URL used in error messages.

        Returns:
            The decoded JSON payload.

        Raises:
            RateLimitError: On HTTP 429.
            FetcherError: On 4xx responses or malformed JSON.
            aiohttp.ClientResponseError: On 5xx responses (retryable).
        """
        if response.status == 429:
            retry_after = self._parse_retry_after(response.headers.get("Retry-After"))
            raise RateLimitError(f"{self.source_name}: rate limited at {url}", retry_after)
        if response.status >= 500:
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=response.status,
                message=f"server error from {url}",
            )
        if response.status >= 400:
            raise FetcherError(f"{self.source_name}: HTTP {response.status} from {url}")
        try:
            return await response.json(content_type=None)
        except (ValueError, aiohttp.ContentTypeError) as exc:
            raise FetcherError(f"{self.source_name}: malformed JSON from {url}") from exc

    def _retry_delay(self, attempt: int, retry_after: float = 0.0) -> float:
        """Compute the exponential backoff delay for one attempt.

        Args:
            attempt: 1-based attempt number.
            retry_after: Provider-requested delay in seconds.

        Returns:
            Delay in seconds, capped at 60.
        """
        backoff = min(2 ** (attempt - 1), 30.0) + random.uniform(0.0, 0.5)
        return min(max(backoff, retry_after), 60.0)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float:
        """Parse a ``Retry-After`` header value.

        Args:
            value: Raw header value.

        Returns:
            Seconds to wait, or ``0.0`` when absent/unparseable.
        """
        if not value:
            return 0.0
        try:
            return max(float(value), 0.0)
        except ValueError:
            return 0.0
