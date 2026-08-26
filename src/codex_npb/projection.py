"""Turn public NPB season data into the per-game expected runs the model needs.

``model.py`` consumes ``away_mu`` and ``home_mu`` but does not produce them.
This module closes that gap: it converts team run rates, the announced
starting pitchers, park factors and home-field advantage into a projection,
and reports which inputs were actually available so the caller can set
``Eligibility`` honestly rather than assuming confirmation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .teams import resolve


class ProjectionError(ValueError):
    """Raised when projection inputs are missing or inconsistent."""


@dataclass(frozen=True)
class TeamSeason:
    """Season-to-date team totals, as published by NPB.jp."""

    team: str
    league: str
    games: int
    runs_scored: int
    runs_allowed: int

    def __post_init__(self) -> None:
        if self.games <= 0:
            raise ProjectionError(f"{self.team}: games must be positive")

    @property
    def runs_scored_per_game(self) -> float:
        return self.runs_scored / self.games

    @property
    def runs_allowed_per_game(self) -> float:
        return self.runs_allowed / self.games


@dataclass(frozen=True)
class StarterSeason:
    """Season-to-date line for one starting pitcher."""

    name: str
    team: str
    innings_pitched: float
    runs_allowed: int

    @property
    def ra9(self) -> float:
        if self.innings_pitched <= 0:
            raise ProjectionError(f"{self.name}: no innings pitched")
        return self.runs_allowed / self.innings_pitched * 9


@dataclass(frozen=True)
class ProjectionSettings:
    """Tunable weights. Defaults are deliberately conservative.

    ``starter_innings_share`` reflects that an NPB starter covers roughly
    five and a half of nine innings; the remainder keeps the club's overall
    run-prevention rate, which already embeds its bullpen.

    The shrinkage constants are the number of games (or innings) at which an
    observed rate is weighted equally against the league mean. They exist to
    stop a small sample from producing a confident-looking projection.
    """

    starter_innings_share: float = 0.60
    team_shrinkage_games: float = 30.0
    starter_shrinkage_innings: float = 60.0
    home_field_advantage: float = 0.030
    max_park_factor: float = 1.25
    min_park_factor: float = 0.80

    def __post_init__(self) -> None:
        if not 0 <= self.starter_innings_share <= 1:
            raise ProjectionError("starter_innings_share must be between 0 and 1")
        if self.team_shrinkage_games < 0 or self.starter_shrinkage_innings < 0:
            raise ProjectionError("shrinkage constants must be non-negative")
        if abs(self.home_field_advantage) > 0.2:
            raise ProjectionError("home_field_advantage looks implausible")


@dataclass(frozen=True)
class LeagueContext:
    """League-average scoring, used as the regression target and baseline."""

    league: str
    runs_per_game: float
    games: int

    @classmethod
    def from_teams(cls, league: str, seasons: Iterable[TeamSeason]) -> "LeagueContext":
        rows = [row for row in seasons if row.league == league]
        if not rows:
            raise ProjectionError(f"no team data for league {league!r}")
        total_games = sum(row.games for row in rows)
        total_runs = sum(row.runs_scored for row in rows)
        return cls(league=league, runs_per_game=total_runs / total_games, games=total_games)


def shrink(observed: float, prior: float, sample: float, constant: float) -> float:
    """Weighted average of an observed rate and a prior, by sample size."""
    if sample < 0:
        raise ProjectionError("sample size cannot be negative")
    if sample + constant == 0:
        return prior
    return (sample * observed + constant * prior) / (sample + constant)


@dataclass
class GameProjection:
    """Expected runs plus the provenance needed to fill ``Eligibility``."""

    away: str
    home: str
    away_mu: float
    home_mu: float
    league_runs_per_game: float
    park_factor: float
    away_offense_index: float
    home_offense_index: float
    away_defense_index: float
    home_defense_index: float
    away_starter: str | None = None
    home_starter: str | None = None
    inputs_used: dict[str, bool] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def total_mu(self) -> float:
        return self.away_mu + self.home_mu

    @property
    def data_complete(self) -> bool:
        """True only when every optional input was actually supplied."""
        return all(self.inputs_used.values())

    def to_model_config(self, dispersion: float, final_draw_share: float) -> dict[str, float]:
        return {
            "away_mu": round(self.away_mu, 4),
            "home_mu": round(self.home_mu, 4),
            "dispersion": dispersion,
            "final_draw_share": final_draw_share,
            "max_runs": 24,
        }


def project_game(
    *,
    away: str,
    home: str,
    seasons: Mapping[str, TeamSeason],
    settings: ProjectionSettings | None = None,
    away_starter: StarterSeason | None = None,
    home_starter: StarterSeason | None = None,
    park_factor: float | None = None,
) -> GameProjection:
    """Project expected runs for one game.

    Offense and defense are expressed as indices relative to the league mean
    and combined multiplicatively (log5). The starting pitcher replaces part
    of the opposing club's run-prevention index in proportion to the innings
    a starter is expected to cover. Park factor and home-field advantage are
    applied last.
    """
    settings = settings or ProjectionSettings()
    away_team = resolve(away).english
    home_team = resolve(home).english
    try:
        away_season = seasons[away_team]
        home_season = seasons[home_team]
    except KeyError as error:
        raise ProjectionError(f"missing season data for {error.args[0]}") from error

    contexts = {
        league: LeagueContext.from_teams(league, seasons.values())
        for league in {away_season.league, home_season.league}
    }
    baseline = sum(context.runs_per_game for context in contexts.values()) / len(contexts)
    notes: list[str] = []
    if away_season.league != home_season.league:
        notes.append("interleague game; league baselines averaged")

    def offense_index(season: TeamSeason) -> float:
        rate = shrink(
            season.runs_scored_per_game,
            baseline,
            season.games,
            settings.team_shrinkage_games,
        )
        return rate / baseline

    def defense_index(season: TeamSeason) -> float:
        rate = shrink(
            season.runs_allowed_per_game,
            baseline,
            season.games,
            settings.team_shrinkage_games,
        )
        return rate / baseline

    away_offense = offense_index(away_season)
    home_offense = offense_index(home_season)
    away_defense = defense_index(away_season)
    home_defense = defense_index(home_season)

    def blend_starter(
        team_defense: float, starter: StarterSeason | None, label: str
    ) -> float:
        if starter is None:
            notes.append(f"{label} starter unknown; club run prevention used unadjusted")
            return team_defense
        # Shrink in raw runs-per-9 units toward the league rate, then index it.
        # A nine-inning game makes league runs/game a fair stand-in for league RA9.
        starter_rate = shrink(
            starter.ra9,
            baseline,
            starter.innings_pitched,
            settings.starter_shrinkage_innings,
        )
        starter_index = starter_rate / baseline
        share = settings.starter_innings_share
        return share * starter_index + (1 - share) * team_defense

    away_defense_effective = blend_starter(away_defense, away_starter, "away")
    home_defense_effective = blend_starter(home_defense, home_starter, "home")

    factor = 1.0 if park_factor is None else float(park_factor)
    if park_factor is None:
        notes.append("no park factor supplied; neutral 1.00 assumed")
    elif not settings.min_park_factor <= factor <= settings.max_park_factor:
        raise ProjectionError(
            f"park factor {factor} outside [{settings.min_park_factor}, "
            f"{settings.max_park_factor}]"
        )

    edge = settings.home_field_advantage / 2
    away_mu = baseline * away_offense * home_defense_effective * factor * (1 - edge)
    home_mu = baseline * home_offense * away_defense_effective * factor * (1 + edge)

    return GameProjection(
        away=away_team,
        home=home_team,
        away_mu=away_mu,
        home_mu=home_mu,
        league_runs_per_game=baseline,
        park_factor=factor,
        away_offense_index=away_offense,
        home_offense_index=home_offense,
        away_defense_index=away_defense_effective,
        home_defense_index=home_defense_effective,
        away_starter=away_starter.name if away_starter else None,
        home_starter=home_starter.name if home_starter else None,
        inputs_used={
            "away_starter": away_starter is not None,
            "home_starter": home_starter is not None,
            "park_factor": park_factor is not None,
        },
        notes=notes,
    )
