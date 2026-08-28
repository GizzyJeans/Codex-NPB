import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_npb.track_record import collect, read_day

HEADER = (
    "date,away,home,market,selection,line,away_score,home_score,total_runs,"
    "result,shadow_stake,shadow_pnl,actual_stake,actual_pnl,class_at_analysis,"
    "official_source\n"
)
LEGACY_HEADER = (
    "priority,away,home,selection,away_score,home_score,total_runs,result,"
    "shadow_stake,shadow_pnl,actual_stake,actual_pnl\n"
)


def row(pnl, status, stake=1000, actual=0):
    return (
        f"2026-08-26,A,B,total,over,7,3,4,7,WIN,{stake},{pnl:+.0f},"
        f"{actual},+0,{status},https://npb.jp/\n"
    )


def make(directory, name, text):
    day = Path(directory) / name
    day.mkdir(parents=True)
    (day / "settlements.csv").write_text(text, encoding="utf-8")


class ReadDayTests(unittest.TestCase):
    def test_watch_and_all_are_tallied_separately(self):
        with TemporaryDirectory() as directory:
            make(
                directory,
                "2026-08-26",
                HEADER + row(930, "WATCH") + row(-1000, "WATCH") + row(-1000, "PASS"),
            )
            day = read_day(Path(directory) / "2026-08-26" / "settlements.csv")
        self.assertEqual(day.watch_markets, 2)
        self.assertEqual((day.watch_wins, day.watch_losses), (1, 1))
        self.assertAlmostEqual(day.watch_pnl, -70.0, places=6)
        self.assertAlmostEqual(day.all_pnl, -1070.0, places=6)

    def test_roi_uses_the_matching_stake_base(self):
        with TemporaryDirectory() as directory:
            make(directory, "2026-08-26", HEADER + row(930, "WATCH") + row(-1000, "PASS"))
            day = read_day(Path(directory) / "2026-08-26" / "settlements.csv")
        self.assertAlmostEqual(day.watch_roi, 0.93, places=6)
        self.assertAlmostEqual(day.all_roi, -0.035, places=6)

    def test_legacy_layout_returns_none_rather_than_raising(self):
        with TemporaryDirectory() as directory:
            make(directory, "2026-08-14", LEGACY_HEADER + "1,A,B,over,3,4,7,WIN,1000,950,0,0\n")
            self.assertIsNone(read_day(Path(directory) / "2026-08-14" / "settlements.csv"))


class CollectTests(unittest.TestCase):
    def build(self, directory):
        make(directory, "2026-08-26", HEADER + row(810, "WATCH") + row(-1530, "PASS"))
        make(directory, "2026-08-27", HEADER + row(-4400, "WATCH") + row(3845, "PASS"))
        make(directory, "2026-08-14", LEGACY_HEADER + "1,A,B,over,3,4,7,WIN,1000,950,0,0\n")

    def test_pre_schema_days_are_excluded_and_named(self):
        with TemporaryDirectory() as directory:
            self.build(directory)
            track = collect(Path(directory))
        self.assertEqual(len(track.days), 2)
        self.assertEqual(track.skipped, ["2026-08-14"])

    def test_cumulative_totals_sum_across_days(self):
        with TemporaryDirectory() as directory:
            self.build(directory)
            track = collect(Path(directory))
        self.assertAlmostEqual(track.watch_pnl, -3590.0, places=6)
        self.assertAlmostEqual(track.watch_stake, 2000.0, places=6)
        self.assertAlmostEqual(track.all_stake, 4000.0, places=6)

    def test_negative_selection_edge_means_the_filter_picks_worse(self):
        with TemporaryDirectory() as directory:
            self.build(directory)
            track = collect(Path(directory))
        self.assertLess(track.selection_edge, 0)
        self.assertAlmostEqual(
            track.selection_edge, track.watch_roi - track.all_roi, places=9
        )

    def test_actual_pnl_stays_zero_when_nothing_was_bet(self):
        with TemporaryDirectory() as directory:
            self.build(directory)
            track = collect(Path(directory))
        self.assertEqual(track.actual_pnl, 0.0)

    def test_empty_directory_yields_no_days(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(collect(Path(directory)).days, [])


if __name__ == "__main__":
    unittest.main()
