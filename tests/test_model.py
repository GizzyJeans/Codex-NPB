import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_npb.model import (  # noqa: E402
    Eligibility,
    ModelConfig,
    ModelError,
    SpreadMarket,
    TotalMarket,
    build_score_distribution,
    evaluate_market,
    no_vig_probability,
    parse_tail_line,
)


class ModelTests(unittest.TestCase):
    def setUp(self):
        self.distribution = build_score_distribution(ModelConfig(3.10, 2.65))

    def test_distribution_is_normalized_and_has_npb_draw_residual(self):
        self.assertAlmostEqual(sum(self.distribution.probabilities.values()), 1.0)
        self.assertGreater(self.distribution.draw_probability(), 0.02)
        self.assertLess(self.distribution.draw_probability(), 0.06)

    def test_expected_runs_are_close_to_inputs_after_extras(self):
        away, home = self.distribution.expected_runs()
        self.assertGreater(away, 3.10)
        self.assertGreater(home, 2.65)
        self.assertLess(away, 3.25)
        self.assertLess(home, 2.80)

    def test_rejects_ambiguous_one_digit_tail(self):
        with self.assertRaisesRegex(ModelError, "ambiguous"):
            parse_tail_line("1-5")

    def test_total_tail_settlement(self):
        over = TotalMarket("over", "7+50", 0.93)
        self.assertEqual(over.settle(4, 3).label, "PARTIAL_WIN")
        self.assertAlmostEqual(over.settle(4, 3).profit_per_unit, 0.465)

        under = TotalMarket("under", "6-50", 0.93)
        self.assertEqual(under.settle(3, 3).label, "PARTIAL_WIN")
        self.assertAlmostEqual(under.settle(3, 3).profit_per_unit, 0.465)

    def test_spread_minus_tail_settlement(self):
        dog = SpreadMarket("Rakuten", "SoftBank", "SoftBank", "Rakuten", "2-25", 0.95)
        result = dog.settle(2, 4)
        self.assertEqual(result.label, "PARTIAL_WIN")
        self.assertAlmostEqual(result.profit_per_unit, 0.2375)

    def test_equal_prices_have_fifty_percent_no_vig_probability(self):
        self.assertAlmostEqual(no_vig_probability(0.95, 0.95), 0.5)

    def test_incomplete_confirmation_never_becomes_formal(self):
        market = TotalMarket("under", "6-50", 0.93)
        result = evaluate_market(
            self.distribution,
            market,
            0.93,
            Eligibility(False, True, False, False, False),
        )
        self.assertIn(result["status"], {"WATCH", "PASS"})
        self.assertEqual(result["recommended_stake"], 0)
        self.assertTrue(math.isfinite(result["expected_value"]))

    def test_invalidated_market_is_never_actionable(self):
        market = TotalMarket("over", "7+50", 0.93)
        result = evaluate_market(
            self.distribution,
            market,
            0.93,
            Eligibility(True, False, True, True, False, market_invalidated=True),
        )
        self.assertEqual(result["status"], "INVALID_STALE")
        self.assertEqual(result["recommended_stake"], 0)


if __name__ == "__main__":
    unittest.main()
