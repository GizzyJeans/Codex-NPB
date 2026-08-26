"""Settlement rules as confirmed by the platform, encoded as tests.

Confirmed 2026-08-26 for the Taiwan-style board this project prices against:

1. Totals: backing 大 on ``7+50`` with a final total of exactly 7 wins half
   the payout and has the other half of the stake returned.
2. Spreads, ``1+40`` when the favourite wins by exactly 1: backing the
   favourite earns 40% of the winnings; backing the underdog loses 40% of
   the stake.
3. Spreads, ``0-20`` on a draw: backing the favourite loses 20% of the
   stake; backing the underdog earns 20% of the winnings.

The distinction that matters is that a partial win pays a fraction of the
*odds*, while a partial loss costs a fraction of the *stake*.
"""

import unittest

from codex_npb.model import SpreadMarket, TotalMarket

ODDS = 0.93
SPREAD_ODDS = 0.95


class TotalTailRuleTests(unittest.TestCase):
    def test_over_7_plus_50_at_exactly_seven_wins_half(self):
        market = TotalMarket(selection="over", line="7+50", hong_kong_odds=ODDS)
        settlement = market.settle(0, 7)
        self.assertEqual(settlement.label, "PARTIAL_WIN")
        self.assertAlmostEqual(settlement.profit_per_unit, ODDS * 0.50, places=9)
        self.assertAlmostEqual(settlement.push_fraction, 0.50, places=9)

    def test_under_7_plus_50_at_exactly_seven_loses_half_the_stake(self):
        market = TotalMarket(selection="under", line="7+50", hong_kong_odds=ODDS)
        settlement = market.settle(3, 4)
        self.assertEqual(settlement.label, "PARTIAL_LOSS")
        self.assertAlmostEqual(settlement.profit_per_unit, -0.50, places=9)

    def test_flat_line_pushes_both_sides(self):
        for selection in ("over", "under"):
            settlement = TotalMarket(
                selection=selection, line="7", hong_kong_odds=ODDS
            ).settle(3, 4)
            self.assertEqual(settlement.label, "PUSH")
            self.assertEqual(settlement.profit_per_unit, 0.0)

    def test_away_from_the_line_settles_in_full(self):
        market = TotalMarket(selection="over", line="7+50", hong_kong_odds=ODDS)
        self.assertEqual(market.settle(5, 3).label, "WIN")
        self.assertEqual(market.settle(3, 3).label, "LOSS")


class SpreadTailRuleTests(unittest.TestCase):
    def spread(self, line, selection):
        return SpreadMarket(
            away_team="Fighters",
            home_team="Lions",
            favorite="Fighters",
            selection=selection,
            line=line,
            hong_kong_odds=SPREAD_ODDS,
        )

    def test_1_plus_40_favourite_by_one_earns_40_percent_of_winnings(self):
        settlement = self.spread("1+40", "Fighters").settle(4, 3)
        self.assertEqual(settlement.label, "PARTIAL_WIN")
        self.assertAlmostEqual(settlement.profit_per_unit, SPREAD_ODDS * 0.40, places=9)

    def test_1_plus_40_underdog_loses_40_percent_of_stake(self):
        settlement = self.spread("1+40", "Lions").settle(4, 3)
        self.assertEqual(settlement.label, "PARTIAL_LOSS")
        self.assertAlmostEqual(settlement.profit_per_unit, -0.40, places=9)

    def test_0_minus_20_on_a_draw_costs_the_favourite_20_percent_of_stake(self):
        settlement = self.spread("0-20", "Fighters").settle(3, 3)
        self.assertEqual(settlement.label, "PARTIAL_LOSS")
        self.assertAlmostEqual(settlement.profit_per_unit, -0.20, places=9)

    def test_0_minus_20_on_a_draw_earns_the_underdog_20_percent_of_winnings(self):
        settlement = self.spread("0-20", "Lions").settle(3, 3)
        self.assertEqual(settlement.label, "PARTIAL_WIN")
        self.assertAlmostEqual(settlement.profit_per_unit, SPREAD_ODDS * 0.20, places=9)

    def test_partial_win_pays_odds_while_partial_loss_costs_stake(self):
        win = self.spread("1+40", "Fighters").settle(4, 3)
        loss = self.spread("1+40", "Lions").settle(4, 3)
        # Not symmetric: 0.95 * 0.40 = 0.38 gained against 0.40 of stake lost.
        self.assertNotAlmostEqual(win.profit_per_unit, -loss.profit_per_unit, places=6)

    def test_beyond_the_line_settles_in_full(self):
        market = self.spread("1+40", "Fighters")
        self.assertEqual(market.settle(5, 3).label, "WIN")
        self.assertEqual(market.settle(3, 4).label, "LOSS")


if __name__ == "__main__":
    unittest.main()
