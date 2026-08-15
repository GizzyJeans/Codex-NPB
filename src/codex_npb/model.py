from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Literal, Protocol


class ModelError(ValueError):
    """Raised when model or market inputs are unsafe or inconsistent."""


@dataclass(frozen=True)
class ModelConfig:
    away_mu: float
    home_mu: float
    dispersion: float = 14.0
    final_draw_share: float = 0.21
    max_runs: int = 24

    def __post_init__(self) -> None:
        if self.away_mu <= 0 or self.home_mu <= 0:
            raise ModelError("expected runs must be positive")
        if self.dispersion <= 0:
            raise ModelError("dispersion must be positive")
        if not 0 <= self.final_draw_share <= 1:
            raise ModelError("final_draw_share must be between 0 and 1")
        if self.max_runs < 12:
            raise ModelError("max_runs must be at least 12")


@dataclass(frozen=True)
class Settlement:
    label: str
    profit_per_unit: float
    win_fraction: float
    loss_fraction: float
    push_fraction: float


@dataclass(frozen=True)
class TailLine:
    base: float
    sign: Literal["+", "-", "flat"]
    fraction: float
    raw: str


TAIL_RE = re.compile(r"^(\d+(?:\.\d+)?)(?:([+-])(\d{2}))?$")


def parse_tail_line(value: str) -> TailLine:
    text = value.strip().replace(" ", "")
    match = TAIL_RE.fullmatch(text)
    if not match:
        raise ModelError(
            f"ambiguous or unsupported line {value!r}; use e.g. 6.5, 7+50 or 8-25"
        )
    base = float(match.group(1))
    sign = match.group(2) or "flat"
    fraction = int(match.group(3)) / 100 if match.group(3) else 0.0
    if sign != "flat" and fraction == 0:
        raise ModelError("tail fraction must be greater than zero")
    return TailLine(base=base, sign=sign, fraction=fraction, raw=text)


def negative_binomial_pmf(k: int, mean: float, dispersion: float) -> float:
    """NB2 PMF with variance mean + mean**2 / dispersion."""
    if k < 0:
        return 0.0
    p = dispersion / (dispersion + mean)
    log_pmf = (
        math.lgamma(k + dispersion)
        - math.lgamma(dispersion)
        - math.lgamma(k + 1)
        + dispersion * math.log(p)
        + k * math.log1p(-p)
    )
    return math.exp(log_pmf)


@dataclass(frozen=True)
class ScoreDistribution:
    probabilities: dict[tuple[int, int], float]

    def expected_runs(self) -> tuple[float, float]:
        away = sum(a * probability for (a, _), probability in self.probabilities.items())
        home = sum(h * probability for (_, h), probability in self.probabilities.items())
        return away, home

    def draw_probability(self) -> float:
        return sum(
            probability
            for (away, home), probability in self.probabilities.items()
            if away == home
        )

    def most_likely_score(self) -> tuple[int, int]:
        return max(self.probabilities, key=self.probabilities.get)

    def margin_probabilities(self) -> dict[str, float]:
        buckets = {
            "away_by_1": 0.0,
            "away_by_2": 0.0,
            "away_by_3_plus": 0.0,
            "draw": 0.0,
            "home_by_1": 0.0,
            "home_by_2": 0.0,
            "home_by_3_plus": 0.0,
        }
        for (away, home), probability in self.probabilities.items():
            margin = away - home
            if margin == 0:
                buckets["draw"] += probability
            elif margin == 1:
                buckets["away_by_1"] += probability
            elif margin == 2:
                buckets["away_by_2"] += probability
            elif margin >= 3:
                buckets["away_by_3_plus"] += probability
            elif margin == -1:
                buckets["home_by_1"] += probability
            elif margin == -2:
                buckets["home_by_2"] += probability
            else:
                buckets["home_by_3_plus"] += probability
        return buckets

    def total_probabilities(self, line: float) -> dict[str, float]:
        under = exact = over = 0.0
        for (away, home), probability in self.probabilities.items():
            total = away + home
            if total < line:
                under += probability
            elif total > line:
                over += probability
            else:
                exact += probability
        return {"under": under, "exact": exact, "over": over}


def build_score_distribution(config: ModelConfig) -> ScoreDistribution:
    away_pmf = [
        negative_binomial_pmf(run, config.away_mu, config.dispersion)
        for run in range(config.max_runs + 1)
    ]
    home_pmf = [
        negative_binomial_pmf(run, config.home_mu, config.dispersion)
        for run in range(config.max_runs + 1)
    ]
    away_norm = sum(away_pmf)
    home_norm = sum(home_pmf)
    away_pmf = [value / away_norm for value in away_pmf]
    home_pmf = [value / home_norm for value in home_pmf]

    final: dict[tuple[int, int], float] = {}
    away_share = config.away_mu / (config.away_mu + config.home_mu)
    for away, away_probability in enumerate(away_pmf):
        for home, home_probability in enumerate(home_pmf):
            probability = away_probability * home_probability
            if away != home:
                final[(away, home)] = final.get((away, home), 0.0) + probability
                continue
            draw_probability = probability * config.final_draw_share
            resolved = probability - draw_probability
            final[(away, home)] = final.get((away, home), 0.0) + draw_probability
            final[(away + 1, home)] = final.get((away + 1, home), 0.0) + resolved * away_share
            final[(away, home + 1)] = final.get((away, home + 1), 0.0) + resolved * (1 - away_share)

    normalizer = sum(final.values())
    return ScoreDistribution({score: value / normalizer for score, value in final.items()})


class Market(Protocol):
    hong_kong_odds: float

    def settle(self, away_score: int, home_score: int) -> Settlement: ...


def _full_win(odds: float) -> Settlement:
    return Settlement("WIN", odds, 1.0, 0.0, 0.0)


def _full_loss() -> Settlement:
    return Settlement("LOSS", -1.0, 0.0, 1.0, 0.0)


def _push() -> Settlement:
    return Settlement("PUSH", 0.0, 0.0, 0.0, 1.0)


def _partial_win(odds: float, fraction: float) -> Settlement:
    return Settlement("PARTIAL_WIN", odds * fraction, fraction, 0.0, 1 - fraction)


def _partial_loss(fraction: float) -> Settlement:
    return Settlement("PARTIAL_LOSS", -fraction, 0.0, fraction, 1 - fraction)


@dataclass(frozen=True)
class TotalMarket:
    selection: Literal["over", "under"]
    line: str
    hong_kong_odds: float

    def __post_init__(self) -> None:
        if self.selection not in {"over", "under"}:
            raise ModelError("total selection must be over or under")
        if self.hong_kong_odds <= 0:
            raise ModelError("Hong Kong odds must be positive")
        parse_tail_line(self.line)

    def settle(self, away_score: int, home_score: int) -> Settlement:
        parsed = parse_tail_line(self.line)
        total = away_score + home_score
        is_over = self.selection == "over"
        if total > parsed.base:
            return _full_win(self.hong_kong_odds) if is_over else _full_loss()
        if total < parsed.base:
            return _full_loss() if is_over else _full_win(self.hong_kong_odds)
        if parsed.sign == "flat":
            return _push()
        selected_gets_partial_win = (parsed.sign == "+" and is_over) or (
            parsed.sign == "-" and not is_over
        )
        if selected_gets_partial_win:
            return _partial_win(self.hong_kong_odds, parsed.fraction)
        return _partial_loss(parsed.fraction)


@dataclass(frozen=True)
class SpreadMarket:
    away_team: str
    home_team: str
    favorite: str
    selection: str
    line: str
    hong_kong_odds: float

    def __post_init__(self) -> None:
        teams = {self.away_team, self.home_team}
        if self.favorite not in teams or self.selection not in teams:
            raise ModelError("favorite and selection must match one of the teams")
        if self.hong_kong_odds <= 0:
            raise ModelError("Hong Kong odds must be positive")
        parse_tail_line(self.line)

    def settle(self, away_score: int, home_score: int) -> Settlement:
        parsed = parse_tail_line(self.line)
        favorite_score = away_score if self.favorite == self.away_team else home_score
        dog_score = home_score if self.favorite == self.away_team else away_score
        margin = favorite_score - dog_score
        selected_favorite = self.selection == self.favorite
        if margin > parsed.base:
            return _full_win(self.hong_kong_odds) if selected_favorite else _full_loss()
        if margin < parsed.base:
            return _full_loss() if selected_favorite else _full_win(self.hong_kong_odds)
        if parsed.sign == "flat":
            return _push()
        selected_gets_partial_win = (
            parsed.sign == "+" and selected_favorite
        ) or (parsed.sign == "-" and not selected_favorite)
        if selected_gets_partial_win:
            return _partial_win(self.hong_kong_odds, parsed.fraction)
        return _partial_loss(parsed.fraction)


def no_vig_probability(selection_hk_odds: float, opposite_hk_odds: float) -> float:
    if selection_hk_odds <= 0 or opposite_hk_odds <= 0:
        raise ModelError("both market prices must be positive")
    selected = 1 / (1 + selection_hk_odds)
    opposite = 1 / (1 + opposite_hk_odds)
    return selected / (selected + opposite)


def _full_kelly(outcomes: Iterable[tuple[float, float]]) -> float:
    rows = list(outcomes)
    if sum(probability * profit for probability, profit in rows) <= 0:
        return 0.0
    worst_loss = max((-profit for _, profit in rows if profit < 0), default=0.0)
    if worst_loss == 0:
        return 1.0
    low, high = 0.0, min(1.0, 0.999999 / worst_loss)
    for _ in range(90):
        middle = (low + high) / 2
        derivative = sum(
            probability * profit / (1 + middle * profit)
            for probability, profit in rows
        )
        if derivative > 0:
            low = middle
        else:
            high = middle
    return (low + high) / 2


@dataclass(frozen=True)
class Eligibility:
    rules_confirmed: bool
    starters_confirmed: bool
    lineups_confirmed: bool
    data_complete: bool
    market_current: bool
    market_invalidated: bool = False


def evaluate_market(
    distribution: ScoreDistribution,
    market: Market,
    opposite_hk_odds: float,
    eligibility: Eligibility,
    *,
    bankroll: float = 100_000,
    max_stake: float = 1_000,
    kelly_fraction: float = 0.25,
    minimum_ev: float = 0.04,
    minimum_gap: float = 0.03,
) -> dict[str, float | str | dict[str, float]]:
    outcome_probabilities = {
        "WIN": 0.0,
        "PARTIAL_WIN": 0.0,
        "PUSH": 0.0,
        "PARTIAL_LOSS": 0.0,
        "LOSS": 0.0,
    }
    win_equivalent = loss_equivalent = push_equivalent = 0.0
    kelly_rows: list[tuple[float, float]] = []
    for (away, home), probability in distribution.probabilities.items():
        settlement = market.settle(away, home)
        outcome_probabilities[settlement.label] += probability
        win_equivalent += probability * settlement.win_fraction
        loss_equivalent += probability * settlement.loss_fraction
        push_equivalent += probability * settlement.push_fraction
        kelly_rows.append((probability, settlement.profit_per_unit))

    ev = market.hong_kong_odds * win_equivalent - loss_equivalent
    effective_probability = win_equivalent / (win_equivalent + loss_equivalent)
    fair_decimal = 1 + loss_equivalent / win_equivalent
    minimum_decimal = 1 + (minimum_ev + loss_equivalent) / win_equivalent
    market_probability = no_vig_probability(market.hong_kong_odds, opposite_hk_odds)
    gap = effective_probability - market_probability
    full_kelly = _full_kelly(kelly_rows)
    stake = min(max_stake, bankroll * full_kelly * kelly_fraction)

    flags = {
        "rules_confirmed": eligibility.rules_confirmed,
        "starters_confirmed": eligibility.starters_confirmed,
        "lineups_confirmed": eligibility.lineups_confirmed,
        "data_complete": eligibility.data_complete,
        "market_current": eligibility.market_current,
        "market_invalidated": eligibility.market_invalidated,
    }
    all_confirmed = all(
        value for key, value in flags.items() if key != "market_invalidated"
    ) and not eligibility.market_invalidated
    if eligibility.market_invalidated:
        status = "INVALID_STALE"
        stake = 0.0
    elif ev >= minimum_ev and gap >= minimum_gap and all_confirmed:
        status = "FORMAL"
    elif ev >= minimum_ev and gap >= minimum_gap:
        status = "WATCH"
        stake = 0.0
    else:
        status = "PASS"
        stake = 0.0

    return {
        "status": status,
        "expected_value": ev,
        "effective_model_probability": effective_probability,
        "market_no_vig_probability": market_probability,
        "probability_gap": gap,
        "fair_decimal_odds": fair_decimal,
        "minimum_decimal_odds_for_target_ev": minimum_decimal,
        "full_kelly_fraction": full_kelly,
        "recommended_stake": stake,
        "outcome_probabilities": outcome_probabilities,
        "confirmation_flags": flags,
        "weighted_push_fraction": push_equivalent,
    }
