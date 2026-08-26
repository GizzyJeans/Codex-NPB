import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from codex_npb.board import BoardError, _effective_line, price_game, read_board
from codex_npb.model import Eligibility

HEADER = "date,away,home,hcap_side,hcap,hcap_odds,total,total_odds\n"
ROW = "2026-08-26,橫濱DeNA灣星,廣島鯉魚,away,1-50,0.950,6-50,0.930\n"

CONFIRMED = Eligibility(
    rules_confirmed=True,
    starters_confirmed=True,
    lineups_confirmed=True,
    data_complete=True,
    market_current=True,
)


def write(text):
    directory = TemporaryDirectory()
    path = Path(directory.name) / "board.csv"
    path.write_text(text, encoding="utf-8")
    return directory, path


class ReadBoardTests(unittest.TestCase):
    def test_chinese_names_resolve(self):
        keep, path = write(HEADER + ROW)
        game = read_board(path)[0]
        self.assertEqual(game.away, "Yokohama DeNA BayStars")
        self.assertEqual(game.home, "Hiroshima Carp")
        self.assertEqual(game.favorite, "Yokohama DeNA BayStars")
        self.assertEqual(game.underdog, "Hiroshima Carp")
        keep.cleanup()

    def test_home_side_handicap(self):
        keep, path = write(
            HEADER + "2026-08-26,東北樂天鷹,歐力士猛牛,home,0,0.950,7-75,0.930\n"
        )
        game = read_board(path)[0]
        self.assertEqual(game.favorite, "Orix Buffaloes")
        self.assertTrue(game.is_level)
        keep.cleanup()

    def test_flat_total_written_with_the_level_character(self):
        keep, path = write(
            HEADER + "2026-08-26,阪神虎,中日龍,away,1+50,0.950,7平,0.930\n"
        )
        self.assertEqual(read_board(path)[0].total_line, "7平")
        keep.cleanup()

    def test_missing_column_rejected(self):
        keep, path = write("date,away,home\n2026-08-26,阪神虎,中日龍\n")
        with self.assertRaises(BoardError):
            read_board(path)
        keep.cleanup()

    def test_unknown_team_rejected(self):
        keep, path = write(HEADER + "2026-08-26,洋基,中日龍,away,1+50,0.950,7,0.930\n")
        with self.assertRaises(BoardError):
            read_board(path)
        keep.cleanup()

    def test_bad_side_rejected(self):
        keep, path = write(HEADER + "2026-08-26,阪神虎,中日龍,left,1+50,0.950,7,0.930\n")
        with self.assertRaises(BoardError):
            read_board(path)
        keep.cleanup()


class EffectiveLineTests(unittest.TestCase):
    def test_flat_line_sits_on_its_base(self):
        self.assertEqual(_effective_line("7"), 7.0)
        self.assertEqual(_effective_line("7平"), 7.0)

    def test_plus_tail_shifts_toward_the_favoured_side(self):
        self.assertAlmostEqual(_effective_line("7+50"), 6.75, places=9)
        self.assertAlmostEqual(_effective_line("2+70"), 1.65, places=9)

    def test_minus_tail_shifts_the_other_way(self):
        self.assertAlmostEqual(_effective_line("6-50"), 6.25, places=9)
        self.assertAlmostEqual(_effective_line("0-20"), 0.10, places=9)

    def test_half_line_is_unchanged(self):
        self.assertEqual(_effective_line("6.5"), 6.5)


class PriceGameTests(unittest.TestCase):
    def game(self):
        keep, path = write(HEADER + ROW)
        game = read_board(path)[0]
        keep.cleanup()
        return game

    def test_four_markets_are_priced(self):
        priced = price_game(
            self.game(),
            away_mu=3.3,
            home_mu=3.0,
            dispersion=2.88,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        self.assertEqual(len(priced), 4)
        self.assertEqual({m.market for m in priced}, {"spread", "total"})

    def test_two_sides_of_a_market_have_complementary_probabilities(self):
        priced = price_game(
            self.game(),
            away_mu=3.3,
            home_mu=3.0,
            dispersion=2.88,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        totals = [m for m in priced if m.market == "total"]
        self.assertAlmostEqual(
            sum(m.model_probability for m in totals), 1.0, places=6
        )

    def test_symmetric_price_is_flagged(self):
        priced = price_game(
            self.game(),
            away_mu=3.3,
            home_mu=3.0,
            dispersion=2.88,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        for market in priced:
            self.assertTrue(any("coin flip" in w for w in market.warnings))

    def test_expectation_gap_is_model_minus_line(self):
        priced = price_game(
            self.game(),
            away_mu=3.3,
            home_mu=3.0,
            dispersion=2.88,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        spread = next(m for m in priced if m.market == "spread")
        # Model margin 0.30 against an effective line of 1.25.
        self.assertAlmostEqual(spread.model_expectation, 0.30, places=6)
        self.assertAlmostEqual(spread.line_expectation, 1.25, places=6)
        self.assertAlmostEqual(spread.expectation_gap, -0.95, places=6)


if __name__ == "__main__":
    unittest.main()
