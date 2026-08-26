"""Read a Taiwanese board into markets and price every side of it.

The board lists one handicap and one total per game, with the handicap
number printed on the favourite's row and the same price quoted on both
sides. Each game therefore yields four markets to evaluate: favourite and
underdog on the spread, over and under on the total.

A symmetric price is the important wrinkle. ``no_vig_probability`` reads the
market's opinion out of the two prices, but when both sides are quoted at
the same number it returns exactly 0.50 for every game — the board carries
its opinion in the *line*, not the price. Results from such a board are
flagged so ``probability_gap`` is not mistaken for a real edge over the
market.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from .model import (
    Eligibility,
    ModelConfig,
    SpreadMarket,
    TotalMarket,
    build_score_distribution,
    evaluate_market,
    parse_tail_line,
)
from .teams import resolve

REQUIRED_COLUMNS = {
    "date",
    "away",
    "home",
    "hcap_side",
    "hcap",
    "hcap_odds",
    "total",
    "total_odds",
}


class BoardError(ValueError):
    """Raised when a board row cannot be read as a market."""


@dataclass(frozen=True)
class BoardGame:
    """One row of the board, with names resolved to canonical clubs."""

    game_date: str
    away: str
    home: str
    favorite: str
    handicap: str
    handicap_odds: float
    total_line: str
    total_odds: float

    @property
    def underdog(self) -> str:
        return self.home if self.favorite == self.away else self.away

    @property
    def is_level(self) -> bool:
        parsed = parse_tail_line(self.handicap)
        return parsed.base == 0 and parsed.sign == "flat"


@dataclass
class PricedMarket:
    game_date: str
    away: str
    home: str
    market: str
    selection: str
    line: str
    hong_kong_odds: float
    model_probability: float
    expected_value: float
    fair_decimal_odds: float
    minimum_decimal_odds: float
    status: str
    recommended_stake: float
    outcome_probabilities: dict[str, float]
    model_expectation: float
    line_expectation: float
    warnings: list[str] = field(default_factory=list)

    @property
    def expectation_gap(self) -> float:
        """Model expectation minus the line, in runs.

        On a fixed-price board this is the only honest model-versus-market
        comparison available: the board expresses its view by moving the
        line, so a gap in runs is what a disagreement actually looks like.
        """
        return self.model_expectation - self.line_expectation


def read_board(path: Path | str) -> list[BoardGame]:
    """Read a board CSV. Team names may be Chinese, Japanese or English."""
    rows = list(csv.DictReader(Path(path).read_text(encoding="utf-8").splitlines()))
    if not rows:
        raise BoardError("board file has no rows")
    missing = REQUIRED_COLUMNS - set(rows[0])
    if missing:
        raise BoardError(f"board is missing columns: {sorted(missing)}")

    games: list[BoardGame] = []
    for index, row in enumerate(rows, start=2):
        try:
            away = resolve(row["away"]).english
            home = resolve(row["home"]).english
        except KeyError as error:
            raise BoardError(f"line {index}: {error.args[0]}") from error
        side = row["hcap_side"].strip().lower()
        if side not in {"away", "home"}:
            raise BoardError(f"line {index}: hcap_side must be away or home")
        parse_tail_line(row["hcap"])
        parse_tail_line(row["total"])
        games.append(
            BoardGame(
                game_date=row["date"].strip(),
                away=away,
                home=home,
                favorite=away if side == "away" else home,
                handicap=row["hcap"].strip(),
                handicap_odds=float(row["hcap_odds"]),
                total_line=row["total"].strip(),
                total_odds=float(row["total_odds"]),
            )
        )
    return games


def _effective_line(tail: str) -> float:
    """Where a tail line effectively sits, in runs.

    A flat line sits on its base. A tail that pays the favoured side at the
    base shifts the line half a run toward that side, in proportion to the
    fraction settled.
    """
    parsed = parse_tail_line(tail)
    if parsed.sign == "flat":
        return parsed.base
    shift = 0.5 * parsed.fraction
    return parsed.base - shift if parsed.sign == "+" else parsed.base + shift


def price_game(
    game: BoardGame,
    *,
    away_mu: float,
    home_mu: float,
    dispersion: float,
    final_draw_share: float,
    eligibility: Eligibility,
    bankroll: float = 100_000,
    max_stake: float = 1_000,
    kelly_fraction: float = 0.25,
) -> list[PricedMarket]:
    """Price all four sides the board offers for one game."""
    distribution = build_score_distribution(
        ModelConfig(
            away_mu=away_mu,
            home_mu=home_mu,
            dispersion=dispersion,
            final_draw_share=final_draw_share,
        )
    )
    favorite_mu = away_mu if game.favorite == game.away else home_mu
    underdog_mu = home_mu if game.favorite == game.away else away_mu
    model_margin = favorite_mu - underdog_mu
    model_total = away_mu + home_mu
    handicap_line = _effective_line(game.handicap)
    total_line = _effective_line(game.total_line)

    priced: list[PricedMarket] = []

    def add(market, selection, label, line, odds, model_expectation, line_expectation):
        result = evaluate_market(
            distribution,
            market,
            odds,
            eligibility,
            bankroll=bankroll,
            max_stake=max_stake,
            kelly_fraction=kelly_fraction,
        )
        warnings: list[str] = []
        if result["market_no_vig_probability"] == 0.5:
            warnings.append(
                "both sides quoted at the same price: probability_gap compares the "
                "model with a coin flip, not with the market"
            )
        priced.append(
            PricedMarket(
                game_date=game.game_date,
                away=game.away,
                home=game.home,
                market=label,
                selection=selection,
                line=line,
                hong_kong_odds=odds,
                model_probability=result["effective_model_probability"],
                expected_value=result["expected_value"],
                fair_decimal_odds=result["fair_decimal_odds"],
                minimum_decimal_odds=result["minimum_decimal_odds_for_target_ev"],
                status=result["status"],
                recommended_stake=result["recommended_stake"],
                outcome_probabilities=result["outcome_probabilities"],
                model_expectation=model_expectation,
                line_expectation=line_expectation,
                warnings=warnings,
            )
        )

    for selection in (game.favorite, game.underdog):
        add(
            SpreadMarket(
                away_team=game.away,
                home_team=game.home,
                favorite=game.favorite,
                selection=selection,
                line=game.handicap,
                hong_kong_odds=game.handicap_odds,
            ),
            selection,
            "spread",
            game.handicap,
            game.handicap_odds,
            model_margin,
            handicap_line,
        )
    for selection in ("over", "under"):
        add(
            TotalMarket(
                selection=selection,
                line=game.total_line,
                hong_kong_odds=game.total_odds,
            ),
            selection,
            "total",
            game.total_line,
            game.total_odds,
            model_total,
            total_line,
        )
    return priced


def price_board(
    games: Iterable[BoardGame],
    projections: dict[tuple[str, str], dict],
    *,
    dispersion: float,
    final_draw_share: float,
    eligibility_for=None,
    **kwargs,
) -> list[PricedMarket]:
    """Price every game on the board against its projection."""
    priced: list[PricedMarket] = []
    for game in games:
        key = (game.away, game.home)
        projection = projections.get(key)
        if projection is None:
            raise BoardError(f"no projection for {game.away} @ {game.home}")
        eligibility = (
            eligibility_for(game)
            if eligibility_for
            else Eligibility(
                rules_confirmed=True,
                starters_confirmed=True,
                lineups_confirmed=False,
                data_complete=True,
                market_current=True,
            )
        )
        priced.extend(
            price_game(
                game,
                away_mu=projection["away_mu"],
                home_mu=projection["home_mu"],
                dispersion=dispersion,
                final_draw_share=final_draw_share,
                eligibility=eligibility,
                **kwargs,
            )
        )
    return priced
