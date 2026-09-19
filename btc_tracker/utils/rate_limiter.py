"""Async sliding-window rate limiter per source and endpoint."""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable


class RateLimiter:
    """Coordinate request pacing without blocking the event loop.

    Each ``(source, endpoint)`` pair owns an independent sliding window. The
    limiter sleeps asynchronously via :func:`asyncio.sleep`, so callers must
    ``await acquire(...)`` inside the running event loop.
    """

    def __init__(
        self,
        default_max_requests: int = 10,
        default_window_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        """Initialize the limiter.

        Args:
            default_max_requests: Fallback requests allowed per window.
            default_window_seconds: Fallback window length in seconds.
            clock: Monotonic clock callable, injectable for testing.
            sleep: Async sleep callable, injectable for testing.

        Raises:
            ValueError: If defaults are not positive.
        """
        if default_max_requests <= 0 or default_window_seconds <= 0:
            raise ValueError("rate limit defaults must be positive")
        self._default_max_requests = default_max_requests
        self._default_window_seconds = default_window_seconds
        self._clock = clock
        self._sleep = sleep
        self._limits: dict[tuple[str, str], tuple[int, float]] = {}
        self._buckets: dict[tuple[str, str], deque[float]] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    def configure(
        self,
        source: str,
        endpoint: str,
        max_requests: int,
        window_seconds: float,
    ) -> None:
        """Override the limit for one source/endpoint pair.

        Args:
            source: Source name (e.g. ``"binance"``).
            endpoint: Endpoint key (e.g. ``"/api/v3/myTrades"``).
            max_requests: Requests allowed per window.
            window_seconds: Window length in seconds.

        Raises:
            ValueError: If ``max_requests`` or ``window_seconds`` is not positive.
        """
        if max_requests <= 0 or window_seconds <= 0:
            raise ValueError("rate limit must be positive")
        self._limits[(source, endpoint)] = (max_requests, window_seconds)

    async def acquire(self, source: str, endpoint: str, weight: int = 1) -> None:
        """Wait until a request may proceed, then record it.

        Args:
            source: Source name.
            endpoint: Endpoint key.
            weight: Number of slots the request consumes.

        Raises:
            ValueError: If ``weight`` is less than one.
        """
        if weight < 1:
            raise ValueError("weight must be at least 1")
        key = (source, endpoint)
        max_requests, window = self._limits.get(
            key, (self._default_max_requests, self._default_window_seconds)
        )
        weight = min(weight, max_requests)
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            bucket = self._buckets.setdefault(key, deque())
            while True:
                now = self._clock()
                cutoff = now - window
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if len(bucket) + weight <= max_requests:
                    bucket.extend([now] * weight)
                    return
                await self._sleep(max(bucket[0] + window - now, 0.0))

    def reset(self, source: str | None = None) -> None:
        """Clear recorded request history.

        Args:
            source: When given, only clear endpoints for that source.
        """
        if source is None:
            self._buckets.clear()
            return
        for key in [key for key in self._buckets if key[0] == source]:
            del self._buckets[key]
