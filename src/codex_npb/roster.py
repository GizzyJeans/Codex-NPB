"""Match announced starters to their season pitching lines.

NPB.jp publishes the 予告先発 as a surname only (``涌井``), sometimes with
enough of the given name to disambiguate (``伊藤将`` for 伊藤将司). Season
stat pages carry the full name (``伊藤 将司``). Matching the two is where a
projection can silently attach the wrong pitcher, so an ambiguous match is
reported as ambiguous rather than resolved by guessing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .projection import StarterSeason


@dataclass(frozen=True)
class StarterMatch:
    announced: str
    team: str
    starter: StarterSeason | None
    candidates: tuple[str, ...] = ()

    @property
    def resolved(self) -> bool:
        return self.starter is not None

    @property
    def ambiguous(self) -> bool:
        return self.starter is None and len(self.candidates) > 1

    @property
    def reason(self) -> str:
        if self.resolved:
            return "matched"
        if self.ambiguous:
            return f"ambiguous: {', '.join(self.candidates)}"
        return "no roster entry found"


def _compact(name: str) -> str:
    return name.replace(" ", "").replace("　", "").strip()


def match_starter(
    announced: str, roster: Sequence, *, team: str | None = None
) -> StarterMatch:
    """Resolve one announced starter against a club's pitching lines.

    ``roster`` entries need ``name``, ``innings_pitched`` and
    ``runs_allowed``; ``PitcherLine`` from the npb.jp source satisfies this.
    """
    target = _compact(announced)
    team_name = team or (roster[0].team if roster else "")
    if not target:
        return StarterMatch(announced=announced, team=team_name, starter=None)

    exact: list = []
    prefix: list = []
    for line in roster:
        compact = _compact(line.name)
        surname = _compact(line.name.split(" ")[0]) if " " in line.name else compact
        if surname == target or compact == target:
            exact.append(line)
        elif compact.startswith(target):
            prefix.append(line)

    pool = exact or prefix
    if len(pool) == 1:
        line = pool[0]
        if line.innings_pitched <= 0:
            return StarterMatch(
                announced=announced,
                team=team_name,
                starter=None,
                candidates=(line.name,),
            )
        return StarterMatch(
            announced=announced,
            team=team_name,
            starter=StarterSeason(
                name=line.name,
                team=line.team,
                innings_pitched=line.innings_pitched,
                runs_allowed=line.runs_allowed,
            ),
        )
    return StarterMatch(
        announced=announced,
        team=team_name,
        starter=None,
        candidates=tuple(line.name for line in pool),
    )


def match_all(
    announcements: Iterable[tuple[str, str]], rosters: dict[str, Sequence]
) -> list[StarterMatch]:
    """Match ``(team, announced_name)`` pairs against per-team rosters."""
    return [
        match_starter(announced, rosters.get(team, ()), team=team)
        for team, announced in announcements
    ]
