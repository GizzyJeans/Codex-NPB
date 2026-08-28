"""Cumulative record across settled days.

A single day's shadow result is noise; what matters is whether the WATCH
filter beats the baseline of simply pricing everything. Both are reported
side by side, because a filter that trails the all-markets figure is
destroying value rather than merely failing to add it.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class DayRecord:
    game_date: str
    watch_markets: int
    watch_wins: int
    watch_losses: int
    watch_stake: float
    watch_pnl: float
    all_markets: int
    all_stake: float
    all_pnl: float
    actual_stake: float
    actual_pnl: float

    @property
    def watch_roi(self) -> float:
        return self.watch_pnl / self.watch_stake if self.watch_stake else 0.0

    @property
    def all_roi(self) -> float:
        return self.all_pnl / self.all_stake if self.all_stake else 0.0


@dataclass
class TrackRecord:
    days: list[DayRecord] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def watch_stake(self) -> float:
        return sum(day.watch_stake for day in self.days)

    @property
    def watch_pnl(self) -> float:
        return sum(day.watch_pnl for day in self.days)

    @property
    def all_stake(self) -> float:
        return sum(day.all_stake for day in self.days)

    @property
    def all_pnl(self) -> float:
        return sum(day.all_pnl for day in self.days)

    @property
    def watch_roi(self) -> float:
        return self.watch_pnl / self.watch_stake if self.watch_stake else 0.0

    @property
    def all_roi(self) -> float:
        return self.all_pnl / self.all_stake if self.all_stake else 0.0

    @property
    def actual_pnl(self) -> float:
        return sum(day.actual_pnl for day in self.days)

    @property
    def selection_edge(self) -> float:
        """WATCH return minus the all-markets return.

        Negative means the filter picked worse than pricing everything, which
        is a stronger statement than simply having no edge.
        """
        return self.watch_roi - self.all_roi


REQUIRED_COLUMNS = {"class_at_analysis", "shadow_stake", "shadow_pnl", "actual_pnl"}


def read_day(path: Path) -> DayRecord | None:
    """Read one settled day, or None if the file predates this schema.

    The 2026-08-13 and 2026-08-14 records were imported from chat after the
    fact and carry a different layout. They are marked not prospective in the
    ledger, so folding them into a forward-looking track record would be
    exactly the retro-fitting this project is built to avoid.
    """
    rows = list(csv.DictReader(path.read_text(encoding="utf-8").splitlines()))
    if not rows:
        raise ValueError(f"{path} has no settled markets")
    if not REQUIRED_COLUMNS.issubset(rows[0]):
        return None
    watch = [row for row in rows if row["class_at_analysis"] == "WATCH"]
    return DayRecord(
        game_date=rows[0]["date"],
        watch_markets=len(watch),
        watch_wins=sum(1 for row in watch if float(row["shadow_pnl"]) > 0),
        watch_losses=sum(1 for row in watch if float(row["shadow_pnl"]) < 0),
        watch_stake=sum(float(row["shadow_stake"]) for row in watch),
        watch_pnl=sum(float(row["shadow_pnl"]) for row in watch),
        all_markets=len(rows),
        all_stake=sum(float(row["shadow_stake"]) for row in rows),
        all_pnl=sum(float(row["shadow_pnl"]) for row in rows),
        actual_stake=sum(float(row["actual_stake"]) for row in rows),
        actual_pnl=sum(float(row["actual_pnl"]) for row in rows),
    )


def collect(records_dir: Path) -> TrackRecord:
    days: list[DayRecord] = []
    skipped: list[str] = []
    for path in sorted(Path(records_dir).glob("*/settlements.csv")):
        day = read_day(path)
        if day is None:
            skipped.append(path.parent.name)
        else:
            days.append(day)
    return TrackRecord(days=days, skipped=skipped)
