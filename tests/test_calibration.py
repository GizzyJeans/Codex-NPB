import unittest
from dataclasses import dataclass
from datetime import date

from codex_npb.calibration import (
    calibrate_season,
    estimate_dispersion,
    estimate_park_factors,
)
from codex_npb.projection import ProjectionError


@dataclass(frozen=True)
class FakeGame:
    game_date: date
    away: str
    home: str
    away_score: int
    home_score: int
    venue: str

    @property
    def total_runs(self):
        return self.away_score + self.home_score

    @property
    def is_draw(self):
        return self.away_score == self.home_score


def build_log(pattern, venue="Park A", away="A", home="B"):
    return [
        FakeGame(date(2026, 4, 1), away, home, a, h, venue) for a, h in pattern
    ]


class DispersionTests(unittest.TestCase):
    def test_matches_method_of_moments(self):
        runs = [0, 1, 2, 3, 4, 5, 10, 0, 2, 3]
        mean = sum(runs) / len(runs)
        variance = sum((r - mean) ** 2 for r in runs) / (len(runs) - 1)
        self.assertAlmostEqual(
            estimate_dispersion(runs), mean**2 / (variance - mean), places=9
        )

    def test_underdispersed_sample_returns_near_poisson(self):
        self.assertEqual(estimate_dispersion([3, 3, 3, 3, 3, 3]), 1000.0)

    def test_single_observation_rejected(self):
        with self.assertRaises(ProjectionError):
            estimate_dispersion([4])


class ParkFactorTests(unittest.TestCase):
    def test_high_scoring_park_exceeds_one(self):
        log = build_log([(6, 6)] * 60, venue="Hitters")
        log += [
            FakeGame(date(2026, 4, 2), "B", "C", 1, 1, "Neutral") for _ in range(60)
        ]
        factors = estimate_park_factors(log)
        self.assertGreater(factors["Hitters"].factor, 1.0)

    def test_thin_sample_is_regressed_and_clamped(self):
        log = [FakeGame(date(2026, 4, 1), "A", "B", 12, 12, "Tiny")]
        log += [FakeGame(date(2026, 4, 2), "B", "C", 1, 1, "Neutral") for _ in range(60)]
        factors = estimate_park_factors(log)
        # A raw ratio of 12x is regressed hard and then clamped to the range
        # project_game will accept, so it can never raise downstream.
        self.assertEqual(factors["Tiny"].raw_factor, 12.0)
        self.assertLessEqual(factors["Tiny"].factor, 1.25)
        self.assertFalse(factors["Tiny"].is_reliable)

    def test_every_factor_stays_within_projection_bounds(self):
        log = [FakeGame(date(2026, 4, 1), "A", "B", 30, 30, "Wild")]
        log += [FakeGame(date(2026, 4, 2), "B", "C", 0, 0, "Dead") for _ in range(5)]
        log += [FakeGame(date(2026, 4, 3), "C", "A", 3, 4, "Neutral") for _ in range(60)]
        for factor in estimate_park_factors(log).values():
            self.assertGreaterEqual(factor.factor, 0.80)
            self.assertLessEqual(factor.factor, 1.25)


class SeasonCalibrationTests(unittest.TestCase):
    def test_home_advantage_inverts_the_projection_formula(self):
        # Home scores 3.0, away 2.0 every game: ratio 1.5.
        log = build_log([(2, 3)] * 100)
        calibration = calibrate_season(log)
        ratio = (1 + calibration.home_field_advantage / 2) / (
            1 - calibration.home_field_advantage / 2
        )
        self.assertAlmostEqual(ratio, 1.5, places=9)

    def test_draw_rate_counted(self):
        log = build_log([(2, 2)] * 10 + [(1, 3)] * 90)
        calibration = calibrate_season(log)
        self.assertAlmostEqual(calibration.draw_rate, 0.10, places=9)

    def test_thin_log_warns(self):
        calibration = calibrate_season(build_log([(2, 3)] * 10))
        self.assertTrue(calibration.warnings)

    def test_empty_log_rejected(self):
        with self.assertRaises(ProjectionError):
            calibrate_season([])


if __name__ == "__main__":
    unittest.main()
