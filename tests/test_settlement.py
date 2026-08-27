import unittest
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_npb.board import BoardGame, PricedMarket
from codex_npb.settlement import (
    SettlementError,
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
        expected_value=ev,
        fair_decimal_odds=1.6,
        minimum_decimal_odds=1.7,
        status=status,
        recommended_stake=0.0,
        outcome_probabilities={},
        model_expectation=0.26,
        line_expectation=1.25,
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
