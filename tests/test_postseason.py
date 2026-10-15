"""Postseason handling: the run factor, the slate, and which dates qualify.

Agreed on 2026-10-15 after the analysis in
reports/2026-10-15-postseason-analysis.md: postseason games leave the
season calibration, and a postseason date's expected runs are scaled by
POSTSEASON_RUN_FACTOR.
"""

import copy
import unittest
from datetime import date

from codex_npb.pipeline import _postseason_dates, build_slate
from codex_npb.projection import (
    POSTSEASON_RUN_FACTOR,
    ProjectionError,
    ProjectionSettings,
    TeamSeason,
    apply_postseason,
    project_game,
)
from codex_npb.sources.npb_official import SourceError

CENTRAL = [
    "Yomiuri Giants",
    "Hanshin Tigers",
    "Chunichi Dragons",
    "Hiroshima Carp",
    "Tokyo Yakult Swallows",
    "Yokohama DeNA BayStars",
]


def seasons():
    runs = {name: 500 + 10 * i for i, name in enumerate(CENTRAL)}
    return {name: TeamSeason(name, "central", 143, runs[name], 520) for name in CENTRAL}


def bundle(**extra):
    row = {
        "away": "Yokohama DeNA BayStars",
        "home": "Hanshin Tigers",
        "venue": "甲子園",
        "start_time": "18:00",
        "away_starter": "",
        "home_starter": "",
        "status": "scheduled",
    }
    return {
        "team_seasons": {
            name: {"team": s.team, "league": s.league, "games": s.games,
                   "runs_scored": s.runs_scored, "runs_allowed": s.runs_allowed}
            for name, s in seasons().items()
        },
        "rosters": {},
        "calibration": {"home_field_advantage": 0.03, "park_factors": {},
                        "dispersion": 2.95, "final_draw_share": 0.16},
        "schedule": [
            {**row, "game_date": "2026-10-15"},
            {**row, "game_date": "2026-09-20"},
        ],
        "staff": {},
        **extra,
    }


class RunFactorTests(unittest.TestCase):
    def projection(self):
        return project_game(away="Yokohama DeNA BayStars", home="Hanshin Tigers", seasons=seasons())

    def test_both_sides_scale_by_the_factor(self):
        base = self.projection()
        adjusted = apply_postseason(base, 0.906)
        self.assertAlmostEqual(adjusted.away_mu, base.away_mu * 0.906)
        self.assertAlmostEqual(adjusted.home_mu, base.home_mu * 0.906)
        self.assertAlmostEqual(adjusted.total_mu, base.total_mu * 0.906)
        self.assertEqual(adjusted.postseason_run_factor, 0.906)
        self.assertIn("postseason game", adjusted.notes[-1])
        self.assertIsNone(base.postseason_run_factor, "the input projection is not modified")

    def test_a_projection_is_never_adjusted_twice(self):
        with self.assertRaises(ProjectionError):
            apply_postseason(apply_postseason(self.projection(), 0.906), 0.906)

    def test_default_factor_is_the_agreed_one(self):
        self.assertEqual(POSTSEASON_RUN_FACTOR, 0.906)
        self.assertEqual(ProjectionSettings().postseason_run_factor, 0.906)
        with self.assertRaises(ProjectionError):
            ProjectionSettings(postseason_run_factor=0.3)


class SlateTests(unittest.TestCase):
    def test_a_postseason_date_is_scaled_and_says_so(self):
        plain = build_slate(bundle(), date(2026, 10, 15))[0]
        post = build_slate(bundle(postseason_dates=["2026-10-15"]), date(2026, 10, 15))[0]
        self.assertAlmostEqual(post.projection.away_mu, plain.projection.away_mu * POSTSEASON_RUN_FACTOR)
        self.assertAlmostEqual(post.projection.home_mu, plain.projection.home_mu * POSTSEASON_RUN_FACTOR)
        payload = post.to_analysis_input(dispersion=2.95, final_draw_share=0.16)
        self.assertEqual(payload["projection_detail"]["postseason_run_factor"], POSTSEASON_RUN_FACTOR)
        self.assertEqual(payload["model"]["away_mu"], round(post.projection.away_mu, 4))
        self.assertTrue(any("postseason game" in note for note in payload["projection_detail"]["notes"]))

    def test_a_regular_season_date_is_untouched(self):
        entry = build_slate(bundle(postseason_dates=["2026-10-15"]), date(2026, 9, 20))[0]
        payload = entry.to_analysis_input(dispersion=2.95, final_draw_share=0.16)
        self.assertIsNone(payload["projection_detail"]["postseason_run_factor"])
        self.assertFalse(any("postseason" in note for note in payload["projection_detail"]["notes"]))

    def test_an_unchecked_date_is_flagged_not_guessed(self):
        plain = build_slate(bundle(), date(2026, 10, 15))[0]
        entry = build_slate(bundle(postseason_unchecked=["2026-10-15"]), date(2026, 10, 15))[0]
        self.assertAlmostEqual(entry.projection.away_mu, plain.projection.away_mu)
        self.assertIsNone(entry.projection.postseason_run_factor)
        self.assertTrue(any("postseason status unknown" in note for note in entry.projection.notes))

    def test_an_old_bundle_without_the_keys_still_builds(self):
        old = copy.deepcopy(bundle())
        entry = build_slate(old, date(2026, 10, 15))[0]
        self.assertIsNone(entry.projection.postseason_run_factor)


class PostseasonDateTests(unittest.TestCase):
    class Client:
        def __init__(self, postseason, failing=()):
            self.postseason, self.failing, self.calls = set(postseason), set(failing), []

        def is_postseason_date(self, day):
            self.calls.append(day.isoformat())
            if day.isoformat() in self.failing:
                raise SourceError("page unavailable")
            return day.isoformat() in self.postseason

    SCHEDULE = [
        {"game_date": "2026-10-08", "status": "final", "game_number": 25},
        {"game_date": "2026-10-14", "status": "final", "game_number": 1},
        {"game_date": "2026-10-15", "status": "scheduled", "game_number": None},
        {"game_date": "2026-10-16", "status": "scheduled", "game_number": None},
        {"game_date": "2026-09-30", "status": "scheduled", "game_number": None},
    ]

    def test_played_by_number_upcoming_by_page_failures_left_unchecked(self):
        client = self.Client(postseason={"2026-10-15"}, failing={"2026-10-16"})
        found, unchecked = _postseason_dates(client, self.SCHEDULE)
        self.assertEqual(found, ["2026-10-14", "2026-10-15"])
        self.assertEqual(unchecked, ["2026-10-16"])
        # A played game needs no request, and September is never checked.
        self.assertEqual(sorted(client.calls), ["2026-10-15", "2026-10-16"])

    def test_rows_without_a_number_key_are_still_read(self):
        schedule = [{"game_date": "2026-10-15", "status": "scheduled"}]
        found, unchecked = _postseason_dates(self.Client(postseason={"2026-10-15"}), schedule)
        self.assertEqual((found, unchecked), (["2026-10-15"], []))


if __name__ == "__main__":
    unittest.main()
