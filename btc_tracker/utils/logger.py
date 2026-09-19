"""Structured, Rich-formatted logging factory."""

import logging

from rich.logging import RichHandler


class LoggerFactory:
    """Create and configure namespaced loggers with Rich output.

    The factory configures the ``btc_tracker`` root logger exactly once so
    repeated calls do not duplicate handlers.
    """

    LOGGER_NAME = "btc_tracker"

    _configured_level: str | None = None

    @classmethod
    def configure(cls, level: str = "INFO") -> None:
        """Configure the package root logger.

        Args:
            level: Logging level name (e.g. ``"INFO"``, ``"DEBUG"``).
        """
        root = logging.getLogger(cls.LOGGER_NAME)
        root.setLevel(level.upper())
        root.propagate = False
        if not any(isinstance(handler, RichHandler) for handler in root.handlers):
            handler = RichHandler(
                rich_tracebacks=True,
                show_path=False,
                show_time=True,
                markup=False,
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            root.addHandler(handler)
        cls._configured_level = level.upper()

    @classmethod
    def create(cls, name: str, level: str | None = None) -> logging.Logger:
        """Return a logger under the ``btc_tracker`` namespace.

        Args:
            name: Logger name; the package prefix is added when missing.
            level: Optional per-logger level override.

        Returns:
            A configured :class:`logging.Logger`.
        """
        if cls._configured_level is None:
            cls.configure()
        qualified = name if name.startswith(cls.LOGGER_NAME) else f"{cls.LOGGER_NAME}.{name}"
        logger = logging.getLogger(qualified)
        if level is not None:
            logger.setLevel(level.upper())
        return logger
