"""Derive model parameters from an actual season game log.

Every constant the score model needs — dispersion, home-field advantage,
the post-regulation draw share and park factors — is estimated here from
observed games instead of being carried as a hand-picked default. Each
estimate reports the sample it came from so a thin sample is visible rather
than silently trusted.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Sequence

from .model import ModelConfig, build_score_distribution
from .projection import ProjectionError


@dataclass(frozen=True)


class ParkFactor:
    venue: str
    factor: float
    home_games: int
    raw_factor: float

    @property
    def is_reliable(self) -> bool:
        return self.home_games >= 30


@dataclass


class SeasonCalibration:
    """Parameters estimated from a season game log."""

    games: int
    runs_per_team_game: float
    home_runs_per_game: float
    away_runs_per_game: float
    home_field_advantage: float
    draw_rate: float
    dispersion: float
    final_draw_share: float
    park_factors: dict[str, ParkFactor] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def park_factor_for(self, venue: str, *, require_reliable: bool = True) -> float | None:
        entry = self.park_factors.get(venue)
        if entry is None:
            return None
        if require_reliable and not entry.is_reliable:
            return None
        return entry.factor


def _team_game_runs(log: Sequence) -> list[int]:
    runs: list[int] = []
    for game in log:
        runs.append(game.away_score)
        runs.append(game.home_score)
    return runs


def estimate_dispersion(runs: Sequence[int]) -> float:
    """Method-of-moments NB2 dispersion: variance = mean + mean^2 / dispersion.

    Returns a large value (near-Poisson) when the sample is not overdispersed,
    which keeps ``ModelConfig`` valid instead of raising.
    """
    if len(runs) < 2:
        raise ProjectionError("need at least two observations to estimate dispersion")
    mean = sum(runs) / len(runs)
    variance = sum((value - mean) ** 2 for value in runs) / (len(runs) - 1)
    if variance <= mean:
        return 1000.0
    return mean**2 / (variance - mean)


def estimate_park_factors(
    log: Sequence,
    *,
    shrinkage_games: float = 40.0,
    lower_bound: float = 0.80,
    upper_bound: float = 1.25,
) -> dict[str, ParkFactor]:
    """Runs at a venue versus the same clubs' scoring away from it.

    Comparing a venue against the league at large would confuse a park with
    the quality of the clubs that happen to host there. The baseline used
    here is the road scoring of the very clubs that play home games at the
    venue, so team strength appears on both sides of the ratio and cancels.

    The raw ratio is then regressed toward a neutral 1.00 by sample size, so
    a park with few games cannot swing a projection on noise alone, and the
    result is clamped to the range ``ProjectionSettings`` accepts so a freak
    single game can never produce a factor that the projection rejects.
    """
    venue_totals: dict[str, list[int]] = defaultdict(list)
    venue_hosts: dict[str, set[str]] = defaultdict(set)
    road_totals: dict[str, list[int]] = defaultdict(list)

    for game in log:
        if not game.venue:
            continue
        venue_totals[game.venue].append(game.total_runs)
        venue_hosts[game.venue].add(game.home)

    for game in log:
        if not game.venue:
            continue
        # Every game is a road game for the visiting club.
        road_totals[game.away].append(game.total_runs)

    factors: dict[str, ParkFactor] = {}
    for venue, totals in venue_totals.items():
        baseline_runs = [
            total
            for host in venue_hosts[venue]
            for total in road_totals.get(host, [])
        ]
        if not baseline_runs or not totals:
            continue
        here_rate = sum(totals) / len(totals)
        baseline_rate = sum(baseline_runs) / len(baseline_runs)
        raw = here_rate / baseline_rate if baseline_rate else 1.0
        weight = len(totals) / (len(totals) + shrinkage_games)
        regressed = 1.0 + weight * (raw - 1.0)
        factors[venue] = ParkFactor(
            venue=venue,
            factor=min(upper_bound, max(lower_bound, regressed)),
            home_games=len(totals),
            raw_factor=raw,
        )
    return factors


def estimate_final_draw_share(
    runs_per_team_game: float, dispersion: float, observed_draw_rate: float
) -> float:
    """Fraction of regulation ties that survive NPB's twelve-inning limit.

    The score model draws ties from the probability that both clubs finish
    regulation level, so this share is the observed draw rate divided by that
    modelled tie probability.
    """
    probe = build_score_distribution(
        ModelConfig(
            away_mu=runs_per_team_game,
            home_mu=runs_per_team_game,
            dispersion=dispersion,
            final_draw_share=1.0,
            max_runs=24,
        )
    )
    regulation_tie = probe.draw_probability()
    if regulation_tie <= 0:
        return 0.0
    return min(1.0, observed_draw_rate / regulation_tie)


def calibrate_season(log: Sequence, *, minimum_games: int = 100) -> SeasonCalibration:
    """Estimate every tunable parameter from a completed-game log."""
    games = list(log)
    if not games:
        raise ProjectionError("cannot calibrate from an empty game log")
    warnings: list[str] = []
    if len(games) < minimum_games:
        warnings.append(
            f"only {len(games)} games in the log; estimates are not stable"
        )

    home_runs = sum(game.home_score for game in games) / len(games)
    away_runs = sum(game.away_score for game in games) / len(games)
    per_team = (home_runs + away_runs) / 2
    draws = sum(1 for game in games if game.is_draw)
    draw_rate = draws / len(games)

    # Solve (1 + h/2) / (1 - h/2) = home_runs / away_runs for h.
    ratio = home_runs / away_runs if away_runs else 1.0
    advantage = 2 * (ratio - 1) / (ratio + 1)

    dispersion = estimate_dispersion(_team_game_runs(games))
    draw_share = estimate_final_draw_share(per_team, dispersion, draw_rate)
    if draws < 5:
        warnings.append(
            f"only {draws} drawn games observed; final_draw_share is imprecise"
        )

    return SeasonCalibration(
        games=len(games),
        runs_per_team_game=per_team,
        home_runs_per_game=home_runs,
        away_runs_per_game=away_runs,
        home_field_advantage=advantage,
        draw_rate=draw_rate,
        dispersion=dispersion,
        final_draw_share=draw_share,
        park_factors=estimate_park_factors(games),
        warnings=warnings,
    )
