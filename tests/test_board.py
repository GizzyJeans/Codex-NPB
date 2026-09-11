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


class UnreadableHandicapTests(unittest.TestCase):
    """A tail the platform writes ambiguously must not be guessed at."""

    def board(self, handicap):
        return write(
            HEADER
            + f"2026-08-30,讀賣巨人,阪神虎,home,{handicap},0.950,5-50,0.930\n"
        )

    def test_single_digit_tail_makes_only_the_spread_unpriceable(self):
        # "1+5" could be 5% or 50%; those are different lines, so the spread
        # is not guessed at. It used to take the whole board read down with
        # it, which also threw away a total the board had priced perfectly
        # well -- and which handicap_priceable has always promised to keep.
        keep, path = self.board("1+5")
        game = read_board(path)[0]
        self.assertFalse(game.handicap_priceable)
        self.assertEqual(game.handicap, "1+5", "the raw string stays on the record")
        self.assertFalse(game.is_level)
        priced = price_game(
            game,
            away_mu=4.0,
            home_mu=4.0,
            dispersion=3.0,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        self.assertEqual({m.market for m in priced}, {"total"})
        keep.cleanup()

    def test_an_unreadable_total_still_stops_the_read(self):
        # A total that cannot be parsed is a transcription error, not a
        # platform shorthand, and leaves the row with nothing to price.
        keep, path = write(
            HEADER + "2026-08-30,讀賣巨人,阪神虎,home,1+50,0.950,5+5,0.930\n"
        )
        with self.assertRaises(Exception):
            read_board(path)
        keep.cleanup()

    def test_blank_handicap_is_accepted_and_marked_unpriceable(self):
        keep, path = self.board("")
        game = read_board(path)[0]
        self.assertFalse(game.handicap_priceable)
        self.assertFalse(game.is_level)
        keep.cleanup()

    def test_totals_still_price_when_the_handicap_cannot_be_read(self):
        keep, path = self.board("")
        game = read_board(path)[0]
        keep.cleanup()
        priced = price_game(
            game,
            away_mu=2.7,
            home_mu=2.7,
            dispersion=2.9,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        self.assertEqual({m.market for m in priced}, {"total"})
        self.assertEqual(len(priced), 2)

    def test_a_readable_handicap_still_prices_all_four(self):
        keep, path = self.board("1+50")
        game = read_board(path)[0]
        keep.cleanup()
        priced = price_game(
            game,
            away_mu=2.7,
            home_mu=2.7,
            dispersion=2.9,
            final_draw_share=0.15,
            eligibility=CONFIRMED,
        )
        self.assertEqual(len(priced), 4)


class TwoPricedBoardTests(unittest.TestCase):
    """A board that quotes the two sides differently is stating an opinion.

    Before 2026-09-11 every board carried one price for both sides of a
    market, so pricing could use that single number twice. When the sides
    differ, each has to be priced at its own number and read against the
    other -- using one side's price for both silently re-prices half the
    board.
    """

    def game(self, extra_columns="", extra_values=""):
        keep, path = write(
            HEADER.rstrip("\n") + extra_columns + "\n"
            + "2026-09-11,千葉羅德,福岡軟銀鷹,home,1+10,0.920,7平,0.900"
            + extra_values + "\n"
        )
        game = read_board(path)[0]
        keep.cleanup()
        return game

    def priced(self, game):
        return {
            (m.market, m.selection): m
            for m in price_game(
                game,
                away_mu=4.0,
                home_mu=4.2,
                dispersion=3.0,
                final_draw_share=0.15,
                eligibility=CONFIRMED,
            )
        }

    def test_each_side_is_priced_at_its_own_number(self):
        game = self.game(",hcap_odds_dog,total_odds_under", ",0.980,0.960")
        self.assertEqual(game.favorite_odds, 0.920)
        self.assertEqual(game.underdog_odds, 0.980)
        self.assertEqual(game.over_odds, 0.900)
        self.assertEqual(game.under_odds, 0.960)
        priced = self.priced(game)
        self.assertEqual(priced[("spread", "Fukuoka SoftBank Hawks")].hong_kong_odds, 0.920)
        self.assertEqual(priced[("spread", "Chiba Lotte Marines")].hong_kong_odds, 0.980)
        self.assertEqual(priced[("total", "over")].hong_kong_odds, 0.900)
        self.assertEqual(priced[("total", "under")].hong_kong_odds, 0.960)

    def test_differing_prices_make_the_market_probability_informative(self):
        priced = self.priced(self.game(",hcap_odds_dog,total_odds_under", ",0.980,0.960"))
        over = priced[("total", "over")]
        under = priced[("total", "under")]
        # The cheaper side is the one the board thinks more likely, and the
        # two no-vig probabilities must complement each other.
        self.assertGreater(over.market_no_vig_probability, 0.5)
        self.assertAlmostEqual(
            over.market_no_vig_probability + under.market_no_vig_probability,
            1.0,
            places=9,
        )
        self.assertEqual(over.warnings, [], "no coin-flip warning on a two-priced market")

    def test_a_single_price_still_applies_to_both_sides(self):
        game = self.game()
        self.assertIsNone(game.handicap_odds_dog)
        self.assertIsNone(game.total_odds_under)
        self.assertEqual(game.underdog_odds, game.favorite_odds)
        self.assertEqual(game.under_odds, game.over_odds)
        priced = self.priced(game)
        over = priced[("total", "over")]
        self.assertAlmostEqual(over.market_no_vig_probability, 0.5, places=9)
        self.assertTrue(over.warnings, "a one-priced market still carries the warning")

    def test_blank_override_columns_read_as_absent(self):
        game = self.game(",hcap_odds_dog,total_odds_under", ",,")
        self.assertEqual(game.underdog_odds, 0.920)
        self.assertEqual(game.under_odds, 0.900)


if __name__ == "__main__":
    unittest.main()
