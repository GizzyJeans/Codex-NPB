import unittest

from codex_npb.staff import StaffSplit
from codex_npb.projection import (
    ProjectionError,
    ProjectionSettings,
    StarterSeason,
    TeamSeason,
    project_game,
    shrink,
)


def even_staff(rotation_ra9=3.5, bullpen_ra9=3.5, rotation_innings=600.0, bullpen_innings=360.0):
    """A staff split where every club is league-average by construction."""
    return {
        name: StaffSplit(
            team=name,
            league="central",
            rotation_innings=rotation_innings,
            rotation_runs=round(rotation_ra9 * rotation_innings / 9),
            bullpen_innings=bullpen_innings,
            bullpen_runs=round(bullpen_ra9 * bullpen_innings / 9),
        )
        for name in NAMES
    }


NAMES = [
    "Yomiuri Giants",
    "Hanshin Tigers",
    "Chunichi Dragons",
    "Hiroshima Carp",
    "Tokyo Yakult Swallows",
    "Yokohama DeNA BayStars",
]


def even_league(runs=350, games=100):
    return {n: TeamSeason(n, "central", games, runs, runs) for n in NAMES}


class ShrinkTests(unittest.TestCase):
    def test_no_sample_returns_prior(self):
        self.assertEqual(shrink(9.0, 3.5, 0, 30), 3.5)

    def test_large_sample_approaches_observation(self):
        self.assertAlmostEqual(shrink(5.0, 3.5, 100000, 30), 5.0, places=3)

    def test_midpoint_when_sample_equals_constant(self):
        self.assertAlmostEqual(shrink(5.0, 3.0, 30, 30), 4.0)

    def test_negative_sample_rejected(self):
        with self.assertRaises(ProjectionError):
            shrink(1.0, 1.0, -1, 30)


class ProjectionTests(unittest.TestCase):
    def test_identical_teams_differ_only_by_home_advantage(self):
        seasons = even_league()
        settings = ProjectionSettings(home_field_advantage=0.04)
        projection = project_game(
            away="Hanshin Tigers", home="Yomiuri Giants", seasons=seasons, settings=settings
        )
        # The advantage is split across the two sides: home gets +h/2, away -h/2.
        self.assertAlmostEqual(projection.home_mu / projection.away_mu, 1.02 / 0.98, places=6)
        self.assertAlmostEqual(projection.league_runs_per_game, 3.5, places=6)

    def test_strong_offense_raises_its_own_expected_runs(self):
        seasons = even_league()
        seasons["Hanshin Tigers"] = TeamSeason("Hanshin Tigers", "central", 100, 500, 350)
        weak = project_game(away="Hanshin Tigers", home="Yomiuri Giants", seasons=even_league())
        strong = project_game(away="Hanshin Tigers", home="Yomiuri Giants", seasons=seasons)
        self.assertGreater(strong.away_mu, weak.away_mu)

    def test_ace_starter_suppresses_opposing_runs(self):
        seasons = even_league()
        ace = StarterSeason("Ace", "Yomiuri Giants", innings_pitched=150, runs_allowed=25)
        without = project_game(away="Hanshin Tigers", home="Yomiuri Giants", seasons=seasons)
        with_ace = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=ace,
        )
        self.assertLess(with_ace.away_mu, without.away_mu)
        self.assertAlmostEqual(with_ace.home_mu, without.home_mu, places=9)

    def test_starter_shrinkage_limits_a_tiny_sample(self):
        seasons = even_league()
        # One third of an inning, nine runs allowed: RA9 of 243 must not dominate.
        noise = StarterSeason("Noise", "Yomiuri Giants", innings_pitched=0.333, runs_allowed=9)
        projection = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=noise,
        )
        self.assertLess(projection.away_mu, 2 * 3.5)

    def test_park_factor_scales_both_sides(self):
        seasons = even_league()
        neutral = project_game(away="Hanshin Tigers", home="Yomiuri Giants", seasons=seasons)
        hitters = project_game(
            away="Hanshin Tigers", home="Yomiuri Giants", seasons=seasons, park_factor=1.2
        )
        self.assertAlmostEqual(hitters.total_mu / neutral.total_mu, 1.2, places=6)

    def test_absurd_park_factor_rejected(self):
        with self.assertRaises(ProjectionError):
            project_game(
                away="Hanshin Tigers",
                home="Yomiuri Giants",
                seasons=even_league(),
                park_factor=3.0,
            )

    def test_missing_inputs_are_reported_not_assumed(self):
        projection = project_game(
            away="Hanshin Tigers", home="Yomiuri Giants", seasons=even_league()
        )
        self.assertFalse(projection.data_complete)
        self.assertFalse(projection.inputs_used["park_factor"])
        self.assertTrue(any("park factor" in note for note in projection.notes))

    def test_complete_inputs_mark_data_complete(self):
        seasons = even_league()
        starter = StarterSeason("A", "x", innings_pitched=100, runs_allowed=40)
        projection = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            away_starter=starter,
            home_starter=starter,
            park_factor=1.0,
            staff=even_staff(),
        )
        self.assertTrue(projection.data_complete)

    def test_missing_staff_split_lowers_data_complete(self):
        projection = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=even_league(),
            park_factor=1.0,
        )
        self.assertFalse(projection.inputs_used["staff_split"])
        self.assertTrue(any("double-counts" in note for note in projection.notes))

    def test_unknown_team_rejected(self):
        with self.assertRaises(KeyError):
            project_game(away="Seattle Mariners", home="Yomiuri Giants", seasons=even_league())

    def test_zero_games_rejected(self):
        with self.assertRaises(ProjectionError):
            TeamSeason("Yomiuri Giants", "central", 0, 0, 0)


if __name__ == "__main__":
    unittest.main()


class BullpenDecompositionTests(unittest.TestCase):
    """The rotation must not be counted twice via the club's overall rate."""

    def staff_with_bad_bullpen(self):
        staff = even_staff()
        staff["Yomiuri Giants"] = StaffSplit(
            team="Yomiuri Giants",
            league="central",
            rotation_innings=600.0,
            rotation_runs=round(3.0 * 600 / 9),   # strong rotation
            bullpen_innings=360.0,
            bullpen_runs=round(5.0 * 360 / 9),    # weak bullpen
        )
        return staff

    def test_weak_bullpen_raises_opposing_runs(self):
        seasons = even_league()
        ace = StarterSeason("Ace", "Yomiuri Giants", innings_pitched=150, runs_allowed=50)
        balanced = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=ace,
            staff=even_staff(),
        )
        bad_pen = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=ace,
            staff=self.staff_with_bad_bullpen(),
        )
        self.assertGreater(bad_pen.away_mu, balanced.away_mu)

    def test_league_innings_split_is_used_when_not_overridden(self):
        # 600 rotation innings against 360 relief innings is a 0.625 share.
        seasons = even_league()
        starter = StarterSeason("A", "x", innings_pitched=200, runs_allowed=0)
        projection = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=starter,
            staff=even_staff(),
        )
        # With a shutout starter shrunk toward league, the blend must sit
        # between a pure-rotation and a pure-bullpen reading.
        self.assertLess(projection.away_mu, 3.5)
        self.assertGreater(projection.away_mu, 0.0)

    def test_explicit_share_overrides_the_league_split(self):
        seasons = even_league()
        ace = StarterSeason("Ace", "Yomiuri Giants", innings_pitched=150, runs_allowed=25)
        heavy = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=ace,
            staff=even_staff(),
            settings=ProjectionSettings(starter_innings_share=0.9),
        )
        light = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=seasons,
            home_starter=ace,
            staff=even_staff(),
            settings=ProjectionSettings(starter_innings_share=0.3),
        )
        self.assertLess(heavy.away_mu, light.away_mu)

    def test_unknown_starter_falls_back_to_the_club_rotation_not_overall(self):
        projection = project_game(
            away="Hanshin Tigers",
            home="Yomiuri Giants",
            seasons=even_league(),
            staff=self.staff_with_bad_bullpen(),
        )
        self.assertTrue(
            any("rotation rate used in its place" in note for note in projection.notes)
        )

    def test_share_outside_zero_to_one_rejected(self):
        with self.assertRaises(ProjectionError):
            ProjectionSettings(starter_innings_share=1.4)
