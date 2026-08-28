import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from codex_npb.pipeline_cli import _jst_today, _pending_settlements


class JstTodayTests(unittest.TestCase):
    def test_japan_is_nine_hours_ahead(self):
        # 15:00 UTC is already the next day in Japan, which is why the daily
        # cycle scheduled then prepares the following date's games.
        with patch("codex_npb.pipeline_cli.datetime") as clock:
            clock.now.return_value = datetime(2026, 8, 28, 15, 0, tzinfo=timezone.utc)
            self.assertEqual(_jst_today(), date(2026, 8, 29))

    def test_before_the_boundary_stays_on_the_same_date(self):
        with patch("codex_npb.pipeline_cli.datetime") as clock:
            clock.now.return_value = datetime(2026, 8, 28, 14, 59, tzinfo=timezone.utc)
            self.assertEqual(_jst_today(), date(2026, 8, 28))

    def test_matches_a_manual_offset(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(_jst_today(), (now + timedelta(hours=9)).date())


class PendingSettlementTests(unittest.TestCase):
    def build(self, directory, boards, settled):
        root = Path(directory)
        (root / "boards").mkdir()
        (root / "records").mkdir()
        for day in boards:
            (root / "boards" / f"{day}.csv").write_text("date\n", encoding="utf-8")
        for day in settled:
            folder = root / "records" / day
            folder.mkdir()
            (folder / "settlements.csv").write_text("date\n", encoding="utf-8")
        return root / "boards", root / "records"

    def test_unsettled_past_boards_are_returned_oldest_first(self):
        with TemporaryDirectory() as directory:
            boards, records = self.build(
                directory, ["2026-08-26", "2026-08-27"], ["2026-08-26"]
            )
            self.assertEqual(
                _pending_settlements(boards, records, date(2026, 8, 28)),
                [date(2026, 8, 27)],
            )

    def test_the_target_date_is_never_settled(self):
        with TemporaryDirectory() as directory:
            boards, records = self.build(directory, ["2026-08-28"], [])
            self.assertEqual(
                _pending_settlements(boards, records, date(2026, 8, 28)), []
            )

    def test_future_boards_are_left_alone(self):
        with TemporaryDirectory() as directory:
            boards, records = self.build(directory, ["2026-08-30"], [])
            self.assertEqual(
                _pending_settlements(boards, records, date(2026, 8, 28)), []
            )

    def test_non_date_filenames_are_ignored(self):
        with TemporaryDirectory() as directory:
            boards, records = self.build(directory, [], [])
            (boards / "template.csv").write_text("date\n", encoding="utf-8")
            self.assertEqual(
                _pending_settlements(boards, records, date(2026, 8, 28)), []
            )

    def test_several_missed_days_all_come_back_in_order(self):
        with TemporaryDirectory() as directory:
            boards, records = self.build(
                directory, ["2026-08-25", "2026-08-26", "2026-08-27"], []
            )
            self.assertEqual(
                _pending_settlements(boards, records, date(2026, 8, 28)),
                [date(2026, 8, 25), date(2026, 8, 26), date(2026, 8, 27)],
            )


if __name__ == "__main__":
    unittest.main()
