import unittest

from codex_npb.projection import (
    ProjectionError,
    ProjectionSettings,
    StarterSeason,
    TeamSeason,
    project_game,
    shrink,
)


def even_league(runs=350, games=100):
    names = [
        "Yomiuri Giants",
        "Hanshin Tigers",
        "Chunichi Dragons",
        "Hiroshima Carp",
        "Tokyo Yakult Swallows",
        "Yokohama DeNA BayStars",
    ]
    return {n: TeamSeason(n, "central", games, runs, runs) for n in names}


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
        )
        self.assertTrue(projection.data_complete)

    def test_unknown_team_rejected(self):
        with self.assertRaises(KeyError):
            project_game(away="Seattle Mariners", home="Yomiuri Giants", seasons=even_league())

    def test_zero_games_rejected(self):
        with self.assertRaises(ProjectionError):
            TeamSeason("Yomiuri Giants", "central", 0, 0, 0)


if __name__ == "__main__":
    unittest.main()
