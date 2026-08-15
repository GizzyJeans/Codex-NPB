import csv
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HistoricalRecordTests(unittest.TestCase):
    def test_candidates_never_rewrite_watch_as_actual_wagers(self):
        path = ROOT / "records" / "2026-08-14" / "candidates.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 7)
        self.assertTrue(all(float(row["actual_stake"]) == 0 for row in rows))
        self.assertEqual(sum(row["class_at_analysis"] == "WATCH" for row in rows), 6)
        self.assertEqual(
            sum(row["class_at_analysis"] == "INVALID_STALE" for row in rows), 1
        )

    def test_shadow_and_actual_pnl_are_separate(self):
        path = ROOT / "records" / "2026-08-14" / "settlements.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        watch_rows = [row for row in rows if row["priority"] != "3"]
        self.assertEqual(sum(float(row["shadow_pnl"]) for row in watch_rows), 5640)
        self.assertEqual(sum(float(row["actual_pnl"]) for row in rows), 0)


if __name__ == "__main__":
    unittest.main()
