"""Settle a priced board against official results and write the record.

The point of this module is that grading happens against prices and
classifications that were fixed *before* first pitch. Nothing here may
recompute a projection or reclassify a market: a candidate that was WATCH
before the game stays WATCH afterwards, however it turned out.

Shadow profit — what a market would have returned at a notional stake — is
kept strictly separate from actual profit, which is zero unless a wager was
really placed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .board import BoardGame, PricedMarket
from .model import SpreadMarket, TotalMarket

OFFICIAL_SOURCE = "https://npb.jp/bis/{year}/games/gm{stamp}.html"


class SettlementError(ValueError):
    """Raised when a market cannot be settled against the supplied results."""


@dataclass(frozen=True)
class SettledMarket:
    market: PricedMarket
    away_score: int
    home_score: int
    result: str
    profit_per_unit: float
    shadow_stake: float
    actual_stake: float = 0.0

    @property
    def shadow_pnl(self) -> float:
        return self.shadow_stake * self.profit_per_unit + 0.0

    @property
    def actual_pnl(self) -> float:
        # The trailing addition normalises -0.0, which an unbet market would
        # otherwise write into the record as "-0".
        return self.actual_stake * self.profit_per_unit + 0.0

    @property
    def total_runs(self) -> int:
        return self.away_score + self.home_score


def settle_board(
    priced: Sequence[PricedMarket],
    games: Iterable[BoardGame],
    results: Mapping[tuple[str, str], object],
    *,
    shadow_stake: float = 1_000,
    actual_stakes: Mapping[tuple[str, str, str, str], float] | None = None,
) -> list[SettledMarket]:
    """Grade every priced market against the official score.

    ``actual_stakes`` is keyed by (away, home, market, selection) and defaults
    to nothing staked, which is what an unbet WATCH candidate must record.
    """
    favorites = {(game.away, game.home): game.favorite for game in games}
    actual_stakes = actual_stakes or {}
    settled: list[SettledMarket] = []

    for entry in priced:
        key = (entry.away, entry.home)
        result = results.get(key)
        if result is None:
            raise SettlementError(f"no official result for {entry.away} @ {entry.home}")
        if entry.market == "spread":
            market = SpreadMarket(
                away_team=entry.away,
                home_team=entry.home,
                favorite=favorites[key],
                selection=entry.selection,
                line=entry.line,
                hong_kong_odds=entry.hong_kong_odds,
            )
        elif entry.market == "total":
            market = TotalMarket(
                selection=entry.selection,
                line=entry.line,
                hong_kong_odds=entry.hong_kong_odds,
            )
        else:
            raise SettlementError(f"unknown market kind {entry.market!r}")

        outcome = market.settle(result.away_score, result.home_score)
        settled.append(
            SettledMarket(
                market=entry,
                away_score=result.away_score,
                home_score=result.home_score,
                result=outcome.label,
                profit_per_unit=outcome.profit_per_unit,
                shadow_stake=shadow_stake,
                actual_stake=actual_stakes.get(
                    (entry.away, entry.home, entry.market, entry.selection), 0.0
                ),
            )
        )
    return settled


@dataclass(frozen=True)
class SettlementSummary:
    graded: int
    watch: int
    formal: int
    watch_wins: int
    watch_losses: int
    watch_shadow_stake: float
    watch_shadow_pnl: float
    all_shadow_stake: float
    all_shadow_pnl: float
    actual_stake: float
    actual_pnl: float

    @property
    def watch_roi(self) -> float:
        return self.watch_shadow_pnl / self.watch_shadow_stake if self.watch_shadow_stake else 0.0

    @property
    def all_roi(self) -> float:
        return self.all_shadow_pnl / self.all_shadow_stake if self.all_shadow_stake else 0.0


def summarize(settled: Sequence[SettledMarket]) -> SettlementSummary:
    watch = [row for row in settled if row.market.status == "WATCH"]
    formal = [row for row in settled if row.market.status == "FORMAL"]
    return SettlementSummary(
        graded=len(settled),
        watch=len(watch),
        formal=len(formal),
        watch_wins=sum(1 for row in watch if row.shadow_pnl > 0),
        watch_losses=sum(1 for row in watch if row.shadow_pnl < 0),
        watch_shadow_stake=sum(row.shadow_stake for row in watch),
        watch_shadow_pnl=sum(row.shadow_pnl for row in watch),
        all_shadow_stake=sum(row.shadow_stake for row in settled),
        all_shadow_pnl=sum(row.shadow_pnl for row in settled),
        actual_stake=sum(row.actual_stake for row in settled),
        actual_pnl=sum(row.actual_pnl for row in settled),
    )


def write_candidates(settled: Sequence[SettledMarket], path: Path) -> Path:
    """Pre-game classifications, exactly as they stood before first pitch."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date", "away", "home", "market", "selection", "line", "hk_odds",
            "effective_model_probability", "market_no_vig_probability",
            "fair_decimal_odds", "ev", "minimum_decimal_odds",
            "model_expectation", "line_expectation", "expectation_gap",
            "class_at_analysis", "actual_stake",
        ])
        for row in settled:
            entry = row.market
            writer.writerow([
                entry.game_date, entry.away, entry.home, entry.market, entry.selection,
                entry.line, f"{entry.hong_kong_odds:.3f}",
                f"{entry.model_probability:.4f}",
                f"{0.5:.4f}" if entry.warnings else "",
                f"{entry.fair_decimal_odds:.3f}", f"{entry.expected_value:.4f}",
                f"{entry.minimum_decimal_odds:.3f}",
                f"{entry.model_expectation:.3f}", f"{entry.line_expectation:.3f}",
                f"{entry.expectation_gap:+.3f}",
                entry.status, f"{row.actual_stake:.0f}",
            ])
    return path


def write_settlements(
    settled: Sequence[SettledMarket], path: Path, *, official_source: str
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date", "away", "home", "market", "selection", "line",
            "away_score", "home_score", "total_runs", "result",
            "shadow_stake", "shadow_pnl", "actual_stake", "actual_pnl",
            "class_at_analysis", "official_source",
        ])
        for row in settled:
            entry = row.market
            writer.writerow([
                entry.game_date, entry.away, entry.home, entry.market, entry.selection,
                entry.line, row.away_score, row.home_score, row.total_runs, row.result,
                f"{row.shadow_stake:.0f}", f"{row.shadow_pnl:+.0f}",
                f"{row.actual_stake:.0f}", f"{row.actual_pnl:+.0f}",
                entry.status, official_source,
            ])
    return path


def write_projections(
    projections: Mapping[tuple[str, str], dict],
    results: Mapping[tuple[str, str], object],
    path: Path,
    *,
    model_version: str,
    record_origin: str,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "date", "away", "home", "away_mu", "home_mu", "expected_total",
            "away_starter", "home_starter", "park_factor",
            "actual_away_score", "actual_home_score", "actual_total",
            "model_version", "record_origin",
        ])
        for key, entry in sorted(projections.items()):
            result = results.get(key)
            detail = entry.get("projection_detail", {})
            model = entry["model"]
            writer.writerow([
                entry["game"]["date"], key[0], key[1],
                f"{model['away_mu']:.4f}", f"{model['home_mu']:.4f}",
                f"{model['away_mu'] + model['home_mu']:.3f}",
                detail.get("away_starter", ""), detail.get("home_starter", ""),
                f"{detail.get('park_factor', 1.0):.4f}",
                result.away_score if result else "",
                result.home_score if result else "",
                result.total_runs if result else "",
                model_version, record_origin,
            ])
    return path
