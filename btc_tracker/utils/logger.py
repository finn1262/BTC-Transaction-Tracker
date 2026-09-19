"""Structured logging factory that stays out of the TUI's way.

While a Textual app is running, records are routed to the app's logging
system instead of the terminal so they never corrupt the rendered screen.
Outside an app, Rich-formatted output goes to stderr as before.
"""

import logging

from rich.logging import RichHandler
from textual.logging import TextualHandler, active_app


class _TrackerHandler(logging.Handler):
    """Route records to the active Textual app, or Rich when none is running."""

    def __init__(self) -> None:
        super().__init__()
        formatter = logging.Formatter("%(message)s")
        self._rich = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            show_time=True,
            markup=False,
        )
        self._rich.setFormatter(formatter)
        self._textual = TextualHandler()
        self._textual.setFormatter(formatter)

    def emit(self, record: logging.LogRecord) -> None:
        if active_app.get(None) is not None:
            self._textual.emit(record)
        else:
            self._rich.emit(record)


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
        if not any(isinstance(handler, _TrackerHandler) for handler in root.handlers):
            root.addHandler(_TrackerHandler())
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
