"""Orchestration: fetch public NPB data, cache it, and build analysis inputs.

The split is deliberate. ``fetch_bundle`` touches the network and writes a
dated snapshot; ``build_slate`` is pure and turns a snapshot into the JSON
inputs ``codex_npb.cli`` already understands. Market prices are never
invented — a slate entry leaves the market block as a template and marks
eligibility as unconfirmed until a human fills it in.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

from .calibration import SeasonCalibration, calibrate_season
from .projection import (
    GameProjection,
    ProjectionSettings,
    TeamSeason,
    project_game,
)
from .roster import StarterMatch, match_starter
from .sources import NPBOfficialClient
from .teams import TEAMS

SCHEMA_VERSION = 1
MINIMUM_STARTER_INNINGS = 20.0


@dataclass
class DataBundle:
    """A dated snapshot of everything the projection needs."""

    year: int
    fetched_at_utc: str
    team_seasons: dict[str, TeamSeason]
    rosters: dict[str, list[dict]]
    calibration: SeasonCalibration
    schedule: list[dict]
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "year": self.year,
            "fetched_at_utc": self.fetched_at_utc,
            "team_seasons": {name: asdict(row) for name, row in self.team_seasons.items()},
            "rosters": self.rosters,
            "calibration": {
                **{
                    key: value
                    for key, value in asdict(self.calibration).items()
                    if key != "park_factors"
                },
                "park_factors": {
                    venue: asdict(factor)
                    for venue, factor in self.calibration.park_factors.items()
                },
            },
            "schedule": self.schedule,
        }


def fetch_bundle(
    client: NPBOfficialClient | None = None,
    *,
    year: int | None = None,
    months: Iterable[int] = range(3, 12),
) -> DataBundle:
    """Fetch team seasons, rosters, the game log and the schedule."""
    client = client or NPBOfficialClient(year)
    team_seasons: dict[str, TeamSeason] = {}
    for league in ("central", "pacific"):
        batting = {row.team: row for row in client.team_batting(league)}
        pitching = {row.team: row for row in client.team_pitching(league)}
        for name, bat in batting.items():
            pit = pitching.get(name)
            if pit is None:
                continue
            team_seasons[name] = TeamSeason(
                team=name,
                league=league,
                games=bat.games,
                runs_scored=bat.runs_scored,
                runs_allowed=pit.runs_allowed,
            )

    rosters = {
        team.english: [asdict(line) for line in client.pitchers(team)] for team in TEAMS
    }
    calibration = calibrate_season(client.season_game_log(months))
    schedule = [
        {**asdict(game), "game_date": game.game_date.isoformat()}
        for month in months
        for game in _safe_schedule(client, month)
    ]
    return DataBundle(
        year=client.year,
        fetched_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        team_seasons=team_seasons,
        rosters=rosters,
        calibration=calibration,
        schedule=schedule,
    )


def _safe_schedule(client: NPBOfficialClient, month: int) -> list:
    try:
        return client.schedule_for_month(month)
    except Exception:  # a month with no published schedule is not an error
        return []


def save_bundle(bundle: DataBundle, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle.to_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path


def load_bundle(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


@dataclass
class SlateEntry:
    """One projected game plus the analysis input skeleton it produces."""

    game_date: str
    away: str
    home: str
    venue: str
    start_time: str
    projection: GameProjection
    away_starter_match: StarterMatch | None
    home_starter_match: StarterMatch | None
    blocking: list[str] = field(default_factory=list)

    def to_analysis_input(
        self,
        *,
        dispersion: float,
        final_draw_share: float,
        bankroll: float = 100_000,
        max_stake: float = 1_000,
        kelly_fraction: float = 0.25,
    ) -> dict:
        starters_confirmed = bool(
            self.away_starter_match
            and self.away_starter_match.resolved
            and self.home_starter_match
            and self.home_starter_match.resolved
        )
        return {
            "game": {
                "date": self.game_date,
                "away": self.away,
                "home": self.home,
                "venue": self.venue,
                "start_time": self.start_time,
            },
            "model": self.projection.to_model_config(dispersion, final_draw_share),
            "projection_detail": {
                "expected_total": round(self.projection.total_mu, 3),
                "park_factor": round(self.projection.park_factor, 4),
                "league_runs_per_game": round(self.projection.league_runs_per_game, 4),
                "away_starter": self.projection.away_starter,
                "home_starter": self.projection.home_starter,
                "notes": self.projection.notes,
            },
            "market": {
                "_comment": "FILL IN FROM YOUR PLATFORM. No price is inferred.",
                "kind": "spread",
                "favorite": None,
                "selection": None,
                "line": None,
                "hong_kong_odds": None,
                "opposite_hk_odds": None,
            },
            "eligibility": {
                "rules_confirmed": False,
                "starters_confirmed": starters_confirmed,
                "lineups_confirmed": False,
                "data_complete": self.projection.data_complete,
                "market_current": False,
            },
            "blocking_conditions": self.blocking,
            "bankroll": bankroll,
            "max_stake": max_stake,
            "kelly_fraction": kelly_fraction,
        }


def build_slate(bundle: dict, target: date, *, settings: ProjectionSettings | None = None) -> list[SlateEntry]:
    """Project every scheduled game on ``target`` from a cached bundle."""
    calibration = bundle["calibration"]
    settings = settings or ProjectionSettings(
        home_field_advantage=calibration["home_field_advantage"]
    )
    seasons = {
        name: TeamSeason(**row) for name, row in bundle["team_seasons"].items()
    }
    park_factors = calibration.get("park_factors", {})
    entries: list[SlateEntry] = []

    for row in bundle["schedule"]:
        if row["game_date"] != target.isoformat() or row["status"] != "scheduled":
            continue
        away_match = _match(bundle, row["away"], row.get("away_starter", ""))
        home_match = _match(bundle, row["home"], row.get("home_starter", ""))
        park = park_factors.get(row.get("venue", ""))
        factor = None
        if park and park["home_games"] >= 30:
            factor = park["factor"]

        projection = project_game(
            away=row["away"],
            home=row["home"],
            seasons=seasons,
            settings=settings,
            away_starter=away_match.starter if away_match else None,
            home_starter=home_match.starter if home_match else None,
            park_factor=factor,
        )
        blocking = _blocking_conditions(row, away_match, home_match, park, projection)
        entries.append(
            SlateEntry(
                game_date=row["game_date"],
                away=row["away"],
                home=row["home"],
                venue=row.get("venue", ""),
                start_time=row.get("start_time", ""),
                projection=projection,
                away_starter_match=away_match,
                home_starter_match=home_match,
                blocking=blocking,
            )
        )
    return entries


def _match(bundle: dict, team: str, announced: str) -> StarterMatch | None:
    if not announced:
        return None
    lines = bundle["rosters"].get(team, [])
    return match_starter(announced, [_RosterLine(**line) for line in lines], team=team)


@dataclass(frozen=True)
class _RosterLine:
    name: str
    team: str
    throws: str
    appearances: int
    innings_pitched: float
    runs_allowed: int
    batters_faced: int
    strikeouts: int
    walks: int


def _blocking_conditions(
    row: dict,
    away_match: StarterMatch | None,
    home_match: StarterMatch | None,
    park: dict | None,
    projection: GameProjection,
) -> list[str]:
    """Everything that must be resolved by hand before this can be FORMAL."""
    blocking = ["platform tail-line rules unconfirmed", "market price not supplied"]
    for side, match in (("away", away_match), ("home", home_match)):
        if match is None:
            blocking.append(f"{side} starter not announced yet")
        elif not match.resolved:
            blocking.append(f"{side} starter unresolved ({match.reason})")
        elif match.starter and match.starter.innings_pitched < MINIMUM_STARTER_INNINGS:
            blocking.append(
                f"{side} starter {match.starter.name} has only "
                f"{match.starter.innings_pitched:.1f} IP this season"
            )
    if park is None or park["home_games"] < 30:
        blocking.append(f"park factor for {row.get('venue', '?')} not reliable")
    blocking.append("official lineups not published at projection time")
    return blocking
