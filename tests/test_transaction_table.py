"""Widget-level tests for the incremental transaction table."""

from datetime import datetime, timezone

from rich.text import Text
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate

from tests.conftest import make_transaction, ordered_transactions

from btc_tracker.ui.components import TransactionTable


class TableApp(App[None]):
    def compose(self) -> ComposeResult:
        yield TransactionTable()


def table_keys(table: TransactionTable) -> list[str]:
    return [
        table.coordinate_to_cell_key(Coordinate(row, 0)).row_key.value
        for row in range(table.row_count)
    ]


def expected_keys(transactions) -> list[str]:
    return [TransactionTable.row_key_for(transaction) for transaction in transactions]


class TestSetTransactions:
    async def test_initial_render_preserves_order(self) -> None:
        transactions = ordered_transactions(50)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            assert table.row_count == 50
            assert table_keys(table) == expected_keys(transactions)

    async def test_appended_rows_are_sorted_into_place(self) -> None:
        transactions = ordered_transactions(20)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            now = datetime.now(timezone.utc)
            new = [
                make_transaction(f"new-{index}", timestamp=now)
                for index in range(3)
            ]
            table.set_transactions(
                new + transactions, sort_column="Time", sort_reverse=True
            )
            assert table.row_count == 23
            assert table_keys(table)[:3] == expected_keys(new)

    async def test_batched_removal_keeps_consistent_state(self) -> None:
        transactions = ordered_transactions(100)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            target = transactions[:10] + transactions[50:]
            table.set_transactions(target, sort_column="Time", sort_reverse=True)
            assert table.row_count == 60
            assert table_keys(table) == expected_keys(target)

    async def test_removing_every_row_empties_the_table(self) -> None:
        transactions = ordered_transactions(30)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            table.set_transactions([], sort_column="Time", sort_reverse=True)
            assert table.row_count == 0

    async def test_updated_transaction_patches_cells_in_place(self) -> None:
        timestamp = datetime.now(timezone.utc)
        original = make_transaction("x-1", status="pending", timestamp=timestamp)
        updated = make_transaction("x-1", status="confirmed", timestamp=timestamp)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions([original], sort_column="Time", sort_reverse=True)
            assert table.set_transactions(
                [updated], sort_column="Time", sort_reverse=True
            )
            cell = table.get_cell("binance:x-1", "Status")
            assert isinstance(cell, Text)
            assert cell.plain == "confirmed"

    async def test_no_change_reports_false(self) -> None:
        transactions = ordered_transactions(5)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            assert (
                table.set_transactions(
                    transactions, sort_column="Time", sort_reverse=True
                )
                is False
            )

    async def test_cursor_stays_on_same_row_when_rows_are_added(self) -> None:
        transactions = ordered_transactions(30)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            table.move_cursor(row=7)
            selected = table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
            now = datetime.now(timezone.utc)
            new = [make_transaction(f"new-{index}", timestamp=now) for index in range(4)]
            table.set_transactions(
                new + transactions, sort_column="Time", sort_reverse=True
            )
            assert (
                table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                == selected
            )

    async def test_top_view_follows_new_rows(self) -> None:
        transactions = ordered_transactions(30)
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            table.set_transactions(transactions, sort_column="Time", sort_reverse=True)
            now = datetime.now(timezone.utc)
            new = [make_transaction("newest", timestamp=now)]
            table.set_transactions(
                new + transactions, sort_column="Time", sort_reverse=True
            )
            assert table.cursor_row == 0
            assert (
                table.coordinate_to_cell_key(table.cursor_coordinate).row_key.value
                == "binance:newest"
            )


class TestProfiles:
    async def test_profile_switch_changes_columns(self) -> None:
        app = TableApp()
        async with app.run_test(size=(160, 40)) as pilot:
            table = app.query_one(TransactionTable)
            await pilot.pause()
            assert table.set_profile("narrow") is True
            assert [str(column.label) for column in table.ordered_columns] == [
                "Amount (BTC)",
                "Time",
                "Source",
            ]
            assert table.set_profile("narrow") is False
            table.set_transactions(
                ordered_transactions(3), sort_column="Time", sort_reverse=True
            )
            assert table.row_count == 3
