"""Thin composition root for the BTC Transaction Tracker.

All dependency construction lives in :class:`btc_tracker.core.app.Application`;
this module only delegates to it.
"""

from btc_tracker.core.app import Application


if __name__ == "__main__":
    Application.main()
