import unittest
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_npb.board import BoardGame, PricedMarket
from codex_npb.settlement import (
    SettlementError,
    first_pitch_utc,
    settle_board,
    summarize,
    write_settlements,
)


@dataclass(frozen=True)
class FakeResult:
    away_score: int
    home_score: int

    @property
    def total_runs(self):
        return self.away_score + self.home_score


GAME = BoardGame(
    game_date="2026-08-26",
    away="Yokohama DeNA BayStars",
    home="Hiroshima Carp",
    favorite="Yokohama DeNA BayStars",
    handicap="1-50",
    handicap_odds=0.95,
    total_line="6-50",
    total_odds=0.93,
)


def priced(market, selection, line, odds, status="WATCH", ev=0.2):
    return PricedMarket(
        game_date="2026-08-26",
        away=GAME.away,
        home=GAME.home,
        market=market,
        selection=selection,
        line=line,
        hong_kong_odds=odds,
        model_probability=0.62,
        market_no_vig_probability=0.5,
        expected_value=ev,
        fair_decimal_odds=1.6,
        minimum_decimal_odds=1.7,
        status=status,
        recommended_stake=0.0,
        outcome_probabilities={},
        model_expectation=0.26,
        line_expectation=1.25,
    )


def priced_market_for(game, market, selection, line, odds):
    """A PricedMarket for an arbitrary board game, for timing tests."""
    return PricedMarket(
        game_date=game.game_date, away=game.away, home=game.home,
        market=market, selection=selection, line=line, hong_kong_odds=odds,
        model_probability=0.55, market_no_vig_probability=0.5,
        expected_value=0.1, fair_decimal_odds=1.8, minimum_decimal_odds=1.9,
        status="WATCH", recommended_stake=0.0, outcome_probabilities={},
        model_expectation=6.2, line_expectation=6.0,
    )


class SettleBoardTests(unittest.TestCase):
    def test_underdog_wins_outright_against_a_one_run_handicap(self):
        rows = settle_board(
            [priced("spread", "Hiroshima Carp", "1-50", 0.95)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
        )
        self.assertEqual(rows[0].result, "WIN")
        self.assertAlmostEqual(rows[0].shadow_pnl, 950.0, places=6)

    def test_favourite_by_exactly_one_splits_on_a_minus_tail(self):
        # 1-50: at a one-run favourite win the underdog takes half.
        rows = settle_board(
            [priced("spread", "Hiroshima Carp", "1-50", 0.95)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(4, 3)},
        )
        self.assertEqual(rows[0].result, "PARTIAL_WIN")
        self.assertAlmostEqual(rows[0].shadow_pnl, 1000 * 0.95 * 0.50, places=6)

    def test_total_settles_against_the_line(self):
        rows = settle_board(
            [priced("total", "under", "6-50", 0.93)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
        )
        self.assertEqual(rows[0].result, "WIN")
        self.assertAlmostEqual(rows[0].shadow_pnl, 930.0, places=6)

    def test_unbet_market_records_zero_actual_pnl_without_negative_zero(self):
        rows = settle_board(
            [priced("spread", "Yokohama DeNA BayStars", "1-50", 0.95)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
        )
        self.assertEqual(rows[0].result, "LOSS")
        self.assertEqual(rows[0].actual_stake, 0.0)
        self.assertEqual(f"{rows[0].actual_pnl:+.0f}", "+0")

    def test_actual_stake_is_applied_when_supplied(self):
        rows = settle_board(
            [priced("spread", "Hiroshima Carp", "1-50", 0.95)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
            actual_stakes={(GAME.away, GAME.home, "spread", "Hiroshima Carp"): 500},
        )
        self.assertAlmostEqual(rows[0].actual_pnl, 475.0, places=6)

    def test_missing_result_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(SettlementError):
            settle_board(
                [priced("spread", "Hiroshima Carp", "1-50", 0.95)], [GAME], {}
            )


class SummaryTests(unittest.TestCase):
    def rows(self):
        results = {(GAME.away, GAME.home): FakeResult(2, 3)}
        return settle_board(
            [
                priced("spread", "Hiroshima Carp", "1-50", 0.95, status="WATCH"),
                priced("spread", GAME.away, "1-50", 0.95, status="PASS", ev=-0.2),
                priced("total", "under", "6-50", 0.93, status="WATCH"),
            ],
            [GAME],
            results,
        )

    def test_watch_and_all_are_reported_separately(self):
        summary = summarize(self.rows())
        self.assertEqual(summary.graded, 3)
        self.assertEqual(summary.watch, 2)
        self.assertEqual(summary.watch_wins, 2)
        self.assertAlmostEqual(summary.watch_shadow_pnl, 1880.0, places=6)
        self.assertAlmostEqual(summary.all_shadow_pnl, 880.0, places=6)

    def test_actual_stays_zero_when_nothing_was_bet(self):
        summary = summarize(self.rows())
        self.assertEqual(summary.actual_stake, 0.0)
        self.assertEqual(summary.actual_pnl, 0.0)

    def test_roi_uses_the_matching_stake_base(self):
        summary = summarize(self.rows())
        self.assertAlmostEqual(summary.watch_roi, 1880 / 2000, places=6)
        self.assertAlmostEqual(summary.all_roi, 880 / 3000, places=6)


class WriteRecordsTests(unittest.TestCase):
    def test_settlement_csv_keeps_the_pre_game_classification(self):
        rows = settle_board(
            [priced("spread", "Hiroshima Carp", "1-50", 0.95, status="WATCH")],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
        )
        with TemporaryDirectory() as directory:
            path = write_settlements(
                rows, Path(directory) / "settlements.csv", official_source="https://npb.jp/"
            )
            text = path.read_text(encoding="utf-8")
        self.assertIn("WATCH", text)
        self.assertIn("+950", text)
        self.assertIn("class_at_analysis", text)


if __name__ == "__main__":
    unittest.main()


class ProspectiveTests(unittest.TestCase):
    """A slate is priced once, but its games do not all start together."""

    def settled(self, priced_at, start="18:00"):
        from codex_npb.settlement import first_pitch_utc

        return settle_board(
            [priced("total", "under", "6-50", 0.93)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
            first_pitch={(GAME.away, GAME.home): first_pitch_utc(date(2026, 8, 30), start)},
            priced_at=priced_at,
        )

    def test_priced_before_first_pitch_is_prospective(self):
        rows = self.settled(datetime(2026, 8, 30, 8, 59, tzinfo=timezone.utc))
        self.assertTrue(rows[0].prospective)

    def test_priced_after_first_pitch_is_not(self):
        rows = self.settled(datetime(2026, 8, 30, 9, 1, tzinfo=timezone.utc))
        self.assertFalse(rows[0].prospective)

    def test_an_early_game_can_be_late_while_the_slate_was_early(self):
        # Board committed 04:48 UTC: fine for an 18:00 JST game, too late
        # for one starting 13:00 JST (04:00 UTC).
        priced_at = datetime(2026, 8, 30, 4, 48, tzinfo=timezone.utc)
        self.assertFalse(self.settled(priced_at, start="13:00")[0].prospective)
        self.assertTrue(self.settled(priced_at, start="18:00")[0].prospective)

    def test_unknown_price_time_defaults_to_prospective(self):
        rows = settle_board(
            [priced("total", "under", "6-50", 0.93)],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
        )
        self.assertTrue(rows[0].prospective)

    def test_summary_counts_prospective_markets(self):
        from codex_npb.settlement import first_pitch_utc

        rows = settle_board(
            [
                priced("total", "under", "6-50", 0.93),
                priced("total", "over", "6-50", 0.93),
            ],
            [GAME],
            {(GAME.away, GAME.home): FakeResult(2, 3)},
            first_pitch={(GAME.away, GAME.home): first_pitch_utc(date(2026, 8, 30), "13:00")},
            priced_at=datetime(2026, 8, 30, 4, 48, tzinfo=timezone.utc),
        )
        summary = summarize(rows)
        self.assertEqual(summary.graded, 2)
        self.assertEqual(summary.prospective, 0)


class FirstPitchTests(unittest.TestCase):
    def test_jst_converts_to_utc(self):
        from codex_npb.settlement import first_pitch_utc

        self.assertEqual(
            first_pitch_utc(date(2026, 8, 30), "13:00"),
            datetime(2026, 8, 30, 4, 0, tzinfo=timezone.utc),
        )

    def test_missing_or_malformed_time_returns_none(self):
        from codex_npb.settlement import first_pitch_utc

        for value in ("", "TBD", "25:00", "18"):
            self.assertIsNone(first_pitch_utc(date(2026, 8, 30), value))


class CancelledGameTests(unittest.TestCase):
    """A rained-out game has no result and never will; it must not block the day."""

    def markets(self):
        return [
            priced("spread", "Hiroshima Carp", "1-50", 0.95, status="WATCH"),
            priced("total", "under", "6-50", 0.93, status="PASS", ev=-0.1),
        ]

    def test_missing_result_still_raises_when_not_cancelled(self):
        with self.assertRaises(SettlementError):
            settle_board(self.markets(), [GAME], {})

    def test_cancelled_game_is_voided_rather_than_graded(self):
        rows = settle_board(
            self.markets(), [GAME], {}, cancelled=[(GAME.away, GAME.home)]
        )
        self.assertEqual({row.result for row in rows}, {"VOID"})
        self.assertEqual([row.shadow_pnl for row in rows], [0.0, 0.0])

    def test_void_is_excluded_from_the_watch_record(self):
        rows = settle_board(
            self.markets(), [GAME], {}, cancelled=[(GAME.away, GAME.home)]
        )
        summary = summarize(rows)
        self.assertEqual(summary.voided, 2)
        self.assertEqual(summary.watch, 0)
        self.assertEqual((summary.watch_wins, summary.watch_losses), (0, 0))
        self.assertEqual(summary.watch_shadow_stake, 0.0)

    def test_void_is_excluded_from_the_all_markets_denominator(self):
        # A voided stake is returned, so counting it would dilute the vig
        # baseline the WATCH figure is read against.
        rows = settle_board(
            self.markets(), [GAME], {}, cancelled=[(GAME.away, GAME.home)]
        )
        self.assertEqual(summarize(rows).all_shadow_stake, 0.0)

    def test_other_games_settle_normally_alongside_a_cancellation(self):
        other = BoardGame(
            game_date="2026-09-08", away="Chunichi Dragons", home="Yomiuri Giants",
            favorite="Yomiuri Giants", handicap="1+10", handicap_odds=0.95,
            total_line="6", total_odds=0.93,
        )
        played = PricedMarket(
            game_date="2026-09-08", away=other.away, home=other.home, market="total",
            selection="under", line="6", hong_kong_odds=0.93, model_probability=0.55,
            market_no_vig_probability=0.5, expected_value=0.1, fair_decimal_odds=1.8, minimum_decimal_odds=1.9,
            status="WATCH", recommended_stake=0.0, outcome_probabilities={},
            model_expectation=6.2, line_expectation=6.0,
        )
        rows = settle_board(
            self.markets() + [played],
            [GAME, other],
            {(other.away, other.home): FakeResult(0, 3)},
            cancelled=[(GAME.away, GAME.home)],
        )
        summary = summarize(rows)
        self.assertEqual(summary.voided, 2)
        self.assertEqual(summary.watch, 1)
        self.assertEqual(summary.watch_wins, 1)


class ProjectionOriginTests(unittest.TestCase):
    """Origin is a per-game fact, not a property of the day.

    On 2026-09-13 the board arrived after two of the day's five games had
    already started. Those two were left off the board, but the slate still
    held them, and write_projections stamped the day-level
    "prospective_pre_first_pitch" onto every row -- including a game that had
    begun nearly four hours earlier.
    """

    def rows(self, **kwargs):
        import csv as _csv
        import tempfile
        from pathlib import Path as _Path
        from codex_npb.settlement import write_projections

        def entry(away, home, start):
            return {
                "game": {"date": "2026-09-13", "away": away, "home": home,
                         "start_time": start},
                "model": {"away_mu": 3.0, "home_mu": 3.5},
                "projection_detail": {"away_starter": "a", "home_starter": "b",
                                      "park_factor": 1.0},
            }

        projections = {
            ("Chiba Lotte Marines", "Fukuoka SoftBank Hawks"):
                entry("Chiba Lotte Marines", "Fukuoka SoftBank Hawks", "13:30"),
            ("Hokkaido Nippon-Ham Fighters", "Saitama Seibu Lions"):
                entry("Hokkaido Nippon-Ham Fighters", "Saitama Seibu Lions", "17:00"),
            ("Chunichi Dragons", "Hanshin Tigers"):
                entry("Chunichi Dragons", "Hanshin Tigers", "18:00"),
        }
        first_pitch = {
            k: first_pitch_utc(date(2026, 9, 13), v["game"]["start_time"])
            for k, v in projections.items()
        }
        keep = tempfile.TemporaryDirectory()
        path = write_projections(
            projections, {}, _Path(keep.name) / "p.csv",
            model_version="v", record_origin="prospective_pre_first_pitch",
            first_pitch=first_pitch, **kwargs,
        )
        rows = {(r["away"], r["home"]): r["record_origin"]
                for r in _csv.DictReader(path.read_text(encoding="utf-8").splitlines())}
        keep.cleanup()
        return rows

    def test_a_game_left_off_the_board_is_not_priced(self):
        # Priced at 08:26 UTC, with only the 18:00 JST game on the board.
        rows = self.rows(
            priced_at=datetime(2026, 9, 13, 8, 26, tzinfo=timezone.utc),
            priced_games={("Chunichi Dragons", "Hanshin Tigers")},
        )
        self.assertEqual(rows[("Chiba Lotte Marines", "Fukuoka SoftBank Hawks")],
                         "not_priced")
        self.assertEqual(rows[("Hokkaido Nippon-Ham Fighters", "Saitama Seibu Lions")],
                         "not_priced")
        self.assertEqual(rows[("Chunichi Dragons", "Hanshin Tigers")],
                         "prospective_pre_first_pitch")

    def test_a_priced_game_already_underway_is_post_hoc(self):
        # The 17:00 JST game started at 08:00 UTC; pricing it at 08:26 is late.
        rows = self.rows(
            priced_at=datetime(2026, 9, 13, 8, 26, tzinfo=timezone.utc),
            priced_games={
                ("Hokkaido Nippon-Ham Fighters", "Saitama Seibu Lions"),
                ("Chunichi Dragons", "Hanshin Tigers"),
            },
        )
        self.assertEqual(rows[("Hokkaido Nippon-Ham Fighters", "Saitama Seibu Lions")],
                         "post_hoc")
        self.assertEqual(rows[("Chunichi Dragons", "Hanshin Tigers")],
                         "prospective_pre_first_pitch")

    def test_without_timing_information_the_day_level_label_still_applies(self):
        # Older callers pass neither, and must keep their existing behaviour.
        rows = self.rows()
        self.assertEqual(set(rows.values()), {"prospective_pre_first_pitch"})


class PieceworkBoardTests(unittest.TestCase):
    """A board that arrives in pieces must not age its earlier rows.

    On 2026-09-20 only the three 14:00 JST games were published in time.
    Appending the 18:00 games later moves the file's last-commit time past
    05:00 UTC, and a single whole-file priced_at would then declare the
    afternoon games priced after their own first pitch -- losing three honest
    rows to a bookkeeping artefact.
    """

    AWAY, HOME = "Orix Buffaloes", "Hokkaido Nippon-Ham Fighters"
    EVE_AWAY, EVE_HOME = "Hiroshima Carp", "Chunichi Dragons"

    def markets(self):
        early = BoardGame(
            game_date="2026-09-20", away=self.AWAY, home=self.HOME,
            favorite=self.HOME, handicap="2+35", handicap_odds=0.95,
            total_line="8平", total_odds=0.93,
        )
        evening = BoardGame(
            game_date="2026-09-20", away=self.EVE_AWAY, home=self.EVE_HOME,
            favorite=self.EVE_HOME, handicap="1平", handicap_odds=0.95,
            total_line="6平", total_odds=0.93,
        )
        return early, evening

    def settle(self, **kwargs):
        early, evening = self.markets()
        priced = [
            priced_market_for(early, "total", "under", "8平", 0.93),
            priced_market_for(evening, "total", "under", "6平", 0.93),
        ]
        rows = settle_board(
            priced, [early, evening],
            {(self.AWAY, self.HOME): FakeResult(1, 2),
             (self.EVE_AWAY, self.EVE_HOME): FakeResult(1, 2)},
            first_pitch={
                (self.AWAY, self.HOME): first_pitch_utc(date(2026, 9, 20), "14:00"),
                (self.EVE_AWAY, self.EVE_HOME): first_pitch_utc(date(2026, 9, 20), "18:00"),
            },
            **kwargs,
        )
        return {(r.market.away, r.market.home): r.prospective for r in rows}

    def test_whole_file_timestamp_would_have_condemned_the_early_game(self):
        # The evening commit lands at 06:00 UTC, after the 05:00 first pitch.
        flags = self.settle(priced_at=datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc))
        self.assertFalse(flags[(self.AWAY, self.HOME)],
                         "this is the behaviour the per-row fix exists to avoid")
        self.assertTrue(flags[(self.EVE_AWAY, self.EVE_HOME)])

    def test_per_row_timestamps_keep_each_game_honest(self):
        flags = self.settle(
            priced_at=datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc),
            priced_at_by_game={
                (self.AWAY, self.HOME): datetime(2026, 9, 20, 3, 24, tzinfo=timezone.utc),
                (self.EVE_AWAY, self.EVE_HOME): datetime(2026, 9, 20, 6, 0, tzinfo=timezone.utc),
            },
        )
        self.assertTrue(flags[(self.AWAY, self.HOME)], "priced 03:24, starts 05:00")
        self.assertTrue(flags[(self.EVE_AWAY, self.EVE_HOME)], "priced 06:00, starts 09:00")

    def test_a_genuinely_late_row_is_still_caught(self):
        # Per-row timing is not an amnesty: a row added after its own first
        # pitch stays non-prospective.
        flags = self.settle(
            priced_at=datetime(2026, 9, 20, 3, 24, tzinfo=timezone.utc),
            priced_at_by_game={
                (self.AWAY, self.HOME): datetime(2026, 9, 20, 5, 30, tzinfo=timezone.utc),
            },
        )
        self.assertFalse(flags[(self.AWAY, self.HOME)])

    def test_games_not_named_fall_back_to_the_file_timestamp(self):
        flags = self.settle(
            priced_at=datetime(2026, 9, 20, 3, 24, tzinfo=timezone.utc),
            priced_at_by_game={},
        )
        self.assertTrue(all(flags.values()))


class PieceworkProjectionOriginTests(unittest.TestCase):
    """write_projections must use the same per-row times settle_board does.

    Per-row pricing times reached settle_board on 2026-09-20 but not
    write_projections, so on 09-20 and again on 09-23 the afternoon games of
    a two-commit board were stamped post_hoc in game_projections.csv while
    settlements.csv, correctly, recorded the very same games as prospective.
    The two files of one day disagreed about when the day was priced.
    """

    EARLY = ("Hanshin Tigers", "Tokyo Yakult Swallows")
    LATE = ("Orix Buffaloes", "Chiba Lotte Marines")

    def origins(self, **kwargs):
        import csv as _csv
        import tempfile
        from pathlib import Path as _Path
        from codex_npb.settlement import write_projections

        def entry(key, start):
            return {
                "game": {"date": "2026-09-23", "away": key[0], "home": key[1],
                         "start_time": start},
                "model": {"away_mu": 4.0, "home_mu": 3.3},
                "projection_detail": {"away_starter": "a", "home_starter": "b",
                                      "park_factor": 1.0},
            }

        projections = {self.EARLY: entry(self.EARLY, "14:00"),
                       self.LATE: entry(self.LATE, "17:00")}
        first_pitch = {
            k: first_pitch_utc(date(2026, 9, 23), v["game"]["start_time"])
            for k, v in projections.items()
        }
        keep = tempfile.TemporaryDirectory()
        path = write_projections(
            projections, {}, _Path(keep.name) / "p.csv",
            model_version="v", record_origin="prospective_pre_first_pitch",
            first_pitch=first_pitch, priced_games=set(projections),
            # The file's last commit, when the evening rows were appended.
            priced_at=datetime(2026, 9, 23, 7, 43, 18, tzinfo=timezone.utc),
            **kwargs,
        )
        rows = {(r["away"], r["home"]): r["record_origin"]
                for r in _csv.DictReader(path.read_text(encoding="utf-8").splitlines())}
        keep.cleanup()
        return rows

    def test_whole_file_time_mislabels_the_first_batch(self):
        # The defect as it shipped: no per-row times reach the writer.
        rows = self.origins()
        self.assertEqual(rows[self.EARLY], "post_hoc",
                         "this is the mislabel the per-row times exist to prevent")
        self.assertEqual(rows[self.LATE], "prospective_pre_first_pitch")

    def test_per_row_times_label_both_batches_correctly(self):
        rows = self.origins(priced_at_by_game={
            self.EARLY: datetime(2026, 9, 23, 2, 21, 45, tzinfo=timezone.utc),
            self.LATE: datetime(2026, 9, 23, 7, 43, 18, tzinfo=timezone.utc),
        })
        self.assertEqual(rows[self.EARLY], "prospective_pre_first_pitch")
        self.assertEqual(rows[self.LATE], "prospective_pre_first_pitch")

    def test_a_row_committed_after_its_own_first_pitch_is_still_post_hoc(self):
        rows = self.origins(priced_at_by_game={
            self.EARLY: datetime(2026, 9, 23, 5, 30, tzinfo=timezone.utc),
        })
        self.assertEqual(rows[self.EARLY], "post_hoc")
