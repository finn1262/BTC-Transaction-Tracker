"""Headless Textual tests for the live dashboard."""

import asyncio
import csv
from pathlib import Path

import pytest
from textual.widgets import Footer, Header

from tests.conftest import (
    FakeSource,
    InMemoryStorage,
    build_test_app,
    build_test_config,
    make_transaction,
    ordered_transactions,
    wait_until,
)

from btc_tracker.storage.csv_export import CsvExporter
from btc_tracker.ui.components import (
    ActivityPanel,
    SourceFilterTabs,
    SourceHealthPanel,
    StatsPanel,
    StatusBar,
    SummaryPanel,
    TradeSearchBar,
    TransactionTable,
)

FULL_COLUMNS = ["ID", "Amount (BTC)", "Fee", "Time", "Source", "Status"]
MEDIUM_COLUMNS = ["ID", "Amount (BTC)", "Time", "Source", "Status"]
NARROW_COLUMNS = ["Amount (BTC)", "Time", "Source"]


def column_labels(table: TransactionTable) -> list[str]:
    return [str(column.label) for column in table.ordered_columns]


class TestLayout:
    @pytest.mark.parametrize(
        "size", [(40, 12), (50, 16), (80, 24), (120, 40), (200, 60)]
    )
    async def test_bottom_widgets_never_overlap(self, size: tuple[int, int]) -> None:
        source = FakeSource("binance", batch_size=3)
        app, screen, service, _ = build_test_app([source])
        width, height = size
        try:
            async with app.run_test(size=size) as pilot:
                await pilot.pause()
                assert await wait_until(
                    lambda: screen.query_one(TransactionTable).row_count > 0,
                    timeout=3.0,
                )
                header = screen.query_one(Header)
                summary = screen.query_one(SummaryPanel)
                status = screen.query_one(StatusBar)
                footer = screen.query_one(Footer)
                table = screen.query_one(TransactionTable)
                assert header.region.y == 0
                assert summary.region.y == height - 3
                assert status.region.y == height - 2
                assert footer.region.y == height - 1
                for widget in (header, summary, status, footer):
                    assert widget.region.width == width
                    assert widget.region.x == 0
                assert table.region.height >= 1
                assert table.region.y >= header.region.bottom
        finally:
            await service.stop()

    async def test_sidebar_shows_only_on_wide_terminals(self) -> None:
        source = FakeSource("binance", batch_size=2)
        app, screen, service, _ = build_test_app([source])
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.pause()
                assert screen.query_one("#sidebar").display is True
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                await pilot.pause()
                assert screen.query_one("#sidebar").display is False
        finally:
            await service.stop()

    async def test_sidebar_panels_are_visible_on_wide_terminals(self) -> None:
        source = FakeSource("binance", batch_size=2)
        app, screen, service, _ = build_test_app([source])
        try:
            async with app.run_test(size=(160, 45)) as pilot:
                await pilot.pause()
                assert await wait_until(
                    lambda: screen.query_one(TransactionTable).row_count > 0
                )
                stats = screen.query_one(StatsPanel)
                activity = screen.query_one(ActivityPanel)
                health = screen.query_one(SourceHealthPanel)
                assert stats.region.height >= 6
                assert activity.region.height >= 2
                assert health.region.height >= 1
                assert stats.region.y < activity.region.y < health.region.y
        finally:
            await service.stop()


class TestRealTimeUpdates:
    async def test_new_transactions_appear_without_user_action(self) -> None:
        source = FakeSource("binance", batch_size=4)
        app, screen, service, _ = build_test_app([source])
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count >= 4, timeout=3.0)
                first = table.row_count
                assert await wait_until(
                    lambda: table.row_count > first, timeout=3.0
                )
        finally:
            await service.stop()

    async def test_duplicate_transactions_render_once(self) -> None:
        transaction = make_transaction("dup-1")
        source = FakeSource("binance", batches=[[transaction]])
        app, screen, service, storage = build_test_app([source])
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: source.calls >= 3, timeout=3.0)
                await pilot.pause()
                assert service.total == 1
                assert table.row_count == 1
                assert len(storage.save_calls) == 1
        finally:
            await service.stop()

    async def test_totals_and_status_update_with_data(self) -> None:
        source = FakeSource("binance", batch_size=3)
        app, screen, service, _ = build_test_app([source])
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count >= 3, timeout=3.0)
                summary = str(screen.query_one(SummaryPanel).content)
                stats = str(screen.query_one(StatsPanel).content)
                status = str(screen.query_one(StatusBar).content)
                assert "trades" in summary
                assert "TOTALS" in stats
                assert "LIVE" in status or "FETCHING" in status
                assert "sources" in status
        finally:
            await service.stop()

    async def test_cursor_key_survives_incoming_rows(self) -> None:
        storage = InMemoryStorage(ordered_transactions(20))
        source = FakeSource("binance", batch_size=1)
        config = build_test_config(render_limit=50)
        app, screen, service, _ = build_test_app([source], storage=storage, config=config)
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count == 20, timeout=3.0)
                table.move_cursor(row=5)
                await pilot.pause()
                key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                assert await wait_until(
                    lambda: table.row_count > 20, timeout=3.0
                )
                await pilot.pause()
                current = table.coordinate_to_cell_key(
                    table.cursor_coordinate
                ).row_key.value
                assert current == key
        finally:
            await service.stop()

    async def test_render_limit_caps_rows_but_not_totals(self) -> None:
        storage = InMemoryStorage(ordered_transactions(30))
        source = FakeSource("binance", batches=[[]])
        config = build_test_config(render_limit=10)
        app, screen, service, _ = build_test_app([source], storage=storage, config=config)
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count == 10, timeout=3.0)
                assert service.total == 30
                summary = str(screen.query_one(SummaryPanel).content)
                assert "30" in summary
        finally:
            await service.stop()


class TestFilteringAndSorting:
    async def test_search_filters_rows(self) -> None:
        storage = InMemoryStorage(
            [
                make_transaction("alpha-1", "binance"),
                make_transaction("beta-2", "kraken"),
            ]
        )
        source = FakeSource("binance", batches=[[]])
        app, screen, service, _ = build_test_app([source], storage=storage)
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                search = screen.query_one(TradeSearchBar)
                assert await wait_until(lambda: table.row_count == 2, timeout=3.0)
                search.value = "alpha"
                assert await wait_until(lambda: table.row_count == 1, timeout=2.0)
                search.value = ""
                assert await wait_until(lambda: table.row_count == 2, timeout=2.0)
        finally:
            await service.stop()

    async def test_source_filter_limits_rows(self) -> None:
        storage = InMemoryStorage(
            [
                make_transaction("a-1", "binance"),
                make_transaction("b-1", "binance"),
                make_transaction("c-1", "kraken"),
            ]
        )
        sources = [FakeSource("binance", batches=[[]]), FakeSource("kraken", batches=[[]])]
        app, screen, service, _ = build_test_app(sources, storage=storage)
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                select = screen.query_one(SourceFilterTabs)
                assert await wait_until(lambda: table.row_count == 3, timeout=3.0)
                select.value = "kraken"
                assert await wait_until(lambda: table.row_count == 1, timeout=2.0)
                select.value = SourceFilterTabs.ALL
                assert await wait_until(lambda: table.row_count == 3, timeout=2.0)
        finally:
            await service.stop()

    async def test_sorting_by_amount_reorders_rows(self) -> None:
        storage = InMemoryStorage(
            [
                make_transaction("small", amount_sats=10),
                make_transaction("large", amount_sats=1_000_000),
            ]
        )
        source = FakeSource("binance", batches=[[]])
        app, screen, service, _ = build_test_app([source], storage=storage)
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count == 2, timeout=3.0)

                class _ColumnKey:
                    value = "Amount (BTC)"

                class _HeaderSelected:
                    column_key = _ColumnKey()

                screen.on_data_table_header_selected(_HeaderSelected())
                assert await wait_until(
                    lambda: table
                    .coordinate_to_cell_key(table.cursor_coordinate)
                    .row_key.value.startswith("binance:large"),
                    timeout=2.0,
                )
        finally:
            await service.stop()


class TestResize:
    async def test_resize_switches_column_profiles(self) -> None:
        source = FakeSource("binance", batch_size=2)
        app, screen, service, _ = build_test_app([source])
        try:
            async with app.run_test(size=(160, 45)) as pilot:
                table = screen.query_one(TransactionTable)
                await pilot.pause()
                assert column_labels(table) == FULL_COLUMNS
                await pilot.resize_terminal(80, 24)
                await pilot.pause()
                await pilot.pause()
                assert column_labels(table) == MEDIUM_COLUMNS
                await pilot.resize_terminal(50, 16)
                await pilot.pause()
                await pilot.pause()
                assert column_labels(table) == NARROW_COLUMNS
                await pilot.resize_terminal(160, 45)
                await pilot.pause()
                await pilot.pause()
                assert column_labels(table) == FULL_COLUMNS
        finally:
            await service.stop()


class TestResponsiveness:
    async def test_event_loop_stays_responsive_with_slow_sources(self) -> None:
        slow = FakeSource("slow", delay=0.5, batch_size=1)
        fast = FakeSource("fast", batch_size=1)
        app, screen, service, _ = build_test_app([slow, fast])
        drift: list[float] = []

        async def ticker() -> None:
            loop = asyncio.get_running_loop()
            previous = loop.time()
            while True:
                await asyncio.sleep(0.02)
                now = loop.time()
                drift.append(now - previous - 0.02)
                previous = now

        try:
            async with app.run_test(size=(120, 30)) as pilot:
                task = asyncio.create_task(ticker())
                await asyncio.sleep(0.6)
                await pilot.press("t")
                assert app.focused is screen.query_one(TransactionTable)
                task.cancel()
                assert max(drift) < 0.25
        finally:
            await service.stop()

    async def test_refresh_key_wakes_feed(self) -> None:
        source = FakeSource("binance", batch_size=1)
        config = build_test_config(poll_interval_seconds=5.0)
        app, screen, service, _ = build_test_app([source], config=config)
        try:
            async with app.run_test(size=(120, 30)) as pilot:
                assert await wait_until(lambda: source.calls >= 1, timeout=3.0)
                await pilot.press("r")
                assert await wait_until(lambda: source.calls >= 2, timeout=1.0)
        finally:
            await service.stop()

    async def test_failed_source_marks_status_degraded(self) -> None:
        bad = FakeSource("bad", error=RuntimeError("nope"))
        good = FakeSource("good", batch_size=2)
        app, screen, service, _ = build_test_app([bad, good])
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                status = screen.query_one(StatusBar)
                assert await wait_until(lambda: table.row_count >= 2, timeout=3.0)
                assert await wait_until(
                    lambda: "DEGRADED" in str(status.content), timeout=3.0
                )
                health = str(screen.query_one(SourceHealthPanel).content)
                assert "nope" in str(status.content) or "error" in health
        finally:
            await service.stop()


class TestExport:
    async def test_export_writes_filtered_view(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        storage = InMemoryStorage(
            [
                make_transaction("a-1", "binance"),
                make_transaction("b-1", "kraken"),
            ]
        )
        source = FakeSource("binance", batches=[[]])
        exporter = CsvExporter()
        app, screen, service, _ = build_test_app(
            [source], storage=storage, exporter=exporter
        )
        try:
            async with app.run_test(size=(140, 40)) as pilot:
                table = screen.query_one(TransactionTable)
                assert await wait_until(lambda: table.row_count == 2, timeout=3.0)
                await pilot.press("e")
                assert await wait_until(
                    lambda: bool(list(tmp_path.glob("btc_transactions_*.csv"))),
                    timeout=3.0,
                )
                export = next(tmp_path.glob("btc_transactions_*.csv"))
                with export.open(newline="", encoding="utf-8") as handle:
                    rows = list(csv.DictReader(handle))
                assert len(rows) == 2
                assert {row["external_id"] for row in rows} == {"a-1", "b-1"}
        finally:
            await service.stop()
