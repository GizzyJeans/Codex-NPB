"""Split a pitching staff into rotation and bullpen.

The projection needs these separately. Blending a named starter against the
club's *overall* run prevention double-counts the rotation, because the
overall figure already contains the starters' innings. For a club whose
rotation and bullpen differ sharply — Rakuten in 2026 ran a 3.54 rotation
behind a 5.07 bullpen — that understates runs allowed badly.

NPB does not publish games started on the season stat pages, and the
schedule's pitcher cells switch from 先発 to 勝/敗 once a game is final, so
role is inferred from innings per appearance instead. The distribution is
sharply bimodal: relievers sit near one inning an outing, starters near
five and a half, with almost nobody between three and four.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

ROTATION_INNINGS_PER_APPEARANCE = 3.5


class StaffError(ValueError):
    """Raised when a staff cannot be split into two usable groups."""


@dataclass(frozen=True)
class StaffSplit:
    """One club's rotation and bullpen totals."""

    team: str
    league: str
    rotation_innings: float
    rotation_runs: int
    bullpen_innings: float
    bullpen_runs: int

    @property
    def rotation_ra9(self) -> float:
        if self.rotation_innings <= 0:
            raise StaffError(f"{self.team}: no rotation innings")
        return self.rotation_runs / self.rotation_innings * 9

    @property
    def bullpen_ra9(self) -> float:
        if self.bullpen_innings <= 0:
            raise StaffError(f"{self.team}: no bullpen innings")
        return self.bullpen_runs / self.bullpen_innings * 9

    @property
    def total_innings(self) -> float:
        return self.rotation_innings + self.bullpen_innings

    @property
    def starter_innings_share(self) -> float:
        return self.rotation_innings / self.total_innings


@dataclass(frozen=True)
class LeagueStaffContext:
    """League-average rotation and bullpen rates, and the innings split."""

    league: str
    rotation_ra9: float
    bullpen_ra9: float
    starter_innings_share: float

    @classmethod
    def from_splits(cls, league: str, splits: Iterable[StaffSplit]) -> "LeagueStaffContext":
        rows = [split for split in splits if split.league == league]
        if not rows:
            raise StaffError(f"no staff data for league {league!r}")
        rotation_innings = sum(row.rotation_innings for row in rows)
        bullpen_innings = sum(row.bullpen_innings for row in rows)
        rotation_runs = sum(row.rotation_runs for row in rows)
        bullpen_runs = sum(row.bullpen_runs for row in rows)
        if rotation_innings <= 0 or bullpen_innings <= 0:
            raise StaffError(f"league {league!r} has an empty rotation or bullpen")
        return cls(
            league=league,
            rotation_ra9=rotation_runs / rotation_innings * 9,
            bullpen_ra9=bullpen_runs / bullpen_innings * 9,
            starter_innings_share=rotation_innings / (rotation_innings + bullpen_innings),
        )


def split_staff(
    roster: Sequence,
    *,
    team: str,
    league: str,
    threshold: float = ROTATION_INNINGS_PER_APPEARANCE,
) -> StaffSplit:
    """Classify one club's pitchers by innings per appearance.

    ``roster`` entries need ``innings_pitched``, ``appearances`` and
    ``runs_allowed``. Pitchers with no innings are ignored entirely rather
    than being counted as a zero-rate bullpen arm.
    """
    rotation_innings = bullpen_innings = 0.0
    rotation_runs = bullpen_runs = 0
    for line in roster:
        innings = _get(line, "innings_pitched")
        appearances = _get(line, "appearances")
        runs = _get(line, "runs_allowed")
        if innings <= 0 or appearances <= 0:
            continue
        if innings / appearances >= threshold:
            rotation_innings += innings
            rotation_runs += int(runs)
        else:
            bullpen_innings += innings
            bullpen_runs += int(runs)
    return StaffSplit(
        team=team,
        league=league,
        rotation_innings=rotation_innings,
        rotation_runs=rotation_runs,
        bullpen_innings=bullpen_innings,
        bullpen_runs=bullpen_runs,
    )


def _get(line, field: str):
    return line[field] if isinstance(line, Mapping) else getattr(line, field)


def split_all(
    rosters: Mapping[str, Sequence],
    leagues: Mapping[str, str],
    *,
    threshold: float = ROTATION_INNINGS_PER_APPEARANCE,
) -> dict[str, StaffSplit]:
    return {
        team: split_staff(
            roster, team=team, league=leagues.get(team, "central"), threshold=threshold
        )
        for team, roster in rosters.items()
    }
