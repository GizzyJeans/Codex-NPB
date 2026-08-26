"""Walk-forward backtest of the projection against a season game log.

Season-to-date aggregates cannot be used to grade past games: they already
contain the result being predicted. This module rebuilds each club's record
from the games played *before* the date in question, projects the game from
that state only, and grades it. A projection is only worth anything if it
beats the naive league-average baseline, so both are scored side by side.

Starting pitchers are absent here by construction — the public game log does
not say who started — so these numbers measure the team-strength, park and
home-field components alone.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from .model import ModelConfig, build_score_distribution
from .projection import ProjectionSettings, TeamSeason, project_game


@dataclass
class BacktestResult:
    graded: int
    skipped: int
    total_mae: float
    total_mae_baseline: float
    margin_mae: float
    margin_mae_baseline: float
    home_win_brier: float
    home_win_brier_baseline: float
    over_rate_at_projection: float
    coverage: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_improvement(self) -> float:
        if self.total_mae_baseline == 0:
            return 0.0
        return 1 - self.total_mae / self.total_mae_baseline

    @property
    def margin_improvement(self) -> float:
        if self.margin_mae_baseline == 0:
            return 0.0
        return 1 - self.margin_mae / self.margin_mae_baseline

    @property
    def brier_improvement(self) -> float:
        if self.home_win_brier_baseline == 0:
            return 0.0
        return 1 - self.home_win_brier / self.home_win_brier_baseline


@dataclass
class _Running:
    games: int = 0
    runs_scored: int = 0
    runs_allowed: int = 0


def backtest(
    log: Sequence,
    *,
    leagues: dict[str, str],
    settings: ProjectionSettings | None = None,
    park_factors: dict[str, float] | None = None,
    dispersion: float = 3.0,
    final_draw_share: float = 0.15,
    minimum_games: int = 20,
) -> BacktestResult:
    """Grade the projection on games played in chronological order.

    ``minimum_games`` holds back the early season, where a club's record is
    too thin for its rate to mean anything.
    """
    settings = settings or ProjectionSettings()
    park_factors = park_factors or {}
    games = sorted(log, key=lambda game: game.game_date)
    running: dict[str, _Running] = defaultdict(_Running)

    graded = skipped = 0
    total_error = baseline_total_error = 0.0
    margin_error = baseline_margin_error = 0.0
    brier = baseline_brier = 0.0
    overs = 0
    bucket_hits = defaultdict(int)
    bucket_expected: dict[str, float] = defaultdict(float)

    for game in games:
        away_state = running[game.away]
        home_state = running[game.home]
        league_games = sum(state.games for state in running.values())
        league_runs = sum(state.runs_scored for state in running.values())
        ready = (
            away_state.games >= minimum_games
            and home_state.games >= minimum_games
            and league_games > 0
        )
        if ready:
            baseline_rate = league_runs / league_games
            seasons = {
                name: TeamSeason(
                    team=name,
                    league=leagues.get(name, "central"),
                    games=state.games,
                    runs_scored=state.runs_scored,
                    runs_allowed=state.runs_allowed,
                )
                for name, state in running.items()
                if state.games > 0
            }
            try:
                projection = project_game(
                    away=game.away,
                    home=game.home,
                    seasons=seasons,
                    settings=settings,
                    park_factor=park_factors.get(game.venue),
                )
            except Exception:
                projection = None
            if projection is not None:
                graded += 1
                predicted_total = projection.total_mu
                predicted_margin = projection.home_mu - projection.away_mu
                actual_total = game.total_runs
                actual_margin = game.home_score - game.away_score

                total_error += abs(predicted_total - actual_total)
                baseline_total_error += abs(2 * baseline_rate - actual_total)
                margin_error += abs(predicted_margin - actual_margin)
                baseline_margin_error += abs(actual_margin)
                overs += actual_total > predicted_total

                distribution = build_score_distribution(
                    ModelConfig(
                        away_mu=projection.away_mu,
                        home_mu=projection.home_mu,
                        dispersion=dispersion,
                        final_draw_share=final_draw_share,
                    )
                )
                margins = distribution.margin_probabilities()
                home_win = (
                    margins["home_by_1"] + margins["home_by_2"] + margins["home_by_3_plus"]
                )
                actual_home_win = 1.0 if actual_margin > 0 else 0.0
                brier += (home_win - actual_home_win) ** 2
                baseline_brier += (0.5 - actual_home_win) ** 2

                for label, line in (("over_6.5", 6.5), ("over_7.5", 7.5), ("over_8.5", 8.5)):
                    probabilities = distribution.total_probabilities(line)
                    bucket_expected[label] += probabilities["over"]
                    bucket_hits[label] += actual_total > line
        else:
            skipped += 1

        away_state.games += 1
        away_state.runs_scored += game.away_score
        away_state.runs_allowed += game.home_score
        home_state.games += 1
        home_state.runs_scored += game.home_score
        home_state.runs_allowed += game.away_score

    if graded == 0:
        raise ValueError("no games could be graded; check the log and minimum_games")

    coverage = {
        label: {
            "predicted": bucket_expected[label] / graded,
            "actual": bucket_hits[label] / graded,
        }
        for label in bucket_expected
    }
    warnings: list[str] = []
    if graded < 200:
        warnings.append(f"only {graded} graded games; differences may be noise")
    return BacktestResult(
        graded=graded,
        skipped=skipped,
        total_mae=total_error / graded,
        total_mae_baseline=baseline_total_error / graded,
        margin_mae=margin_error / graded,
        margin_mae_baseline=baseline_margin_error / graded,
        home_win_brier=brier / graded,
        home_win_brier_baseline=baseline_brier / graded,
        over_rate_at_projection=overs / graded,
        coverage=coverage,
        warnings=warnings,
    )
