from __future__ import annotations

import argparse
import json
from pathlib import Path

from .model import (
    Eligibility,
    ModelConfig,
    SpreadMarket,
    TotalMarket,
    build_score_distribution,
    evaluate_market,
)


def analyze(payload: dict) -> dict:
    game = payload["game"]
    model_input = payload["model"]
    market_input = payload["market"]
    eligibility_input = payload["eligibility"]

    distribution = build_score_distribution(ModelConfig(**model_input))
    if market_input["kind"] == "total":
        market = TotalMarket(
            selection=market_input["selection"],
            line=market_input["line"],
            hong_kong_odds=market_input["hong_kong_odds"],
        )
    elif market_input["kind"] == "spread":
        market = SpreadMarket(
            away_team=game["away"],
            home_team=game["home"],
            favorite=market_input["favorite"],
            selection=market_input["selection"],
            line=market_input["line"],
            hong_kong_odds=market_input["hong_kong_odds"],
        )
    else:
        raise ValueError("market.kind must be total or spread")

    result = evaluate_market(
        distribution,
        market,
        market_input["opposite_hk_odds"],
        Eligibility(**eligibility_input),
        bankroll=payload.get("bankroll", 100_000),
        max_stake=payload.get("max_stake", 1_000),
        kelly_fraction=payload.get("kelly_fraction", 0.25),
    )
    expected_away, expected_home = distribution.expected_runs()
    result.update(
        {
            "game": game,
            "expected_away_runs": expected_away,
            "expected_home_runs": expected_home,
            "most_likely_score": distribution.most_likely_score(),
            "draw_probability": distribution.draw_probability(),
            "margin_probabilities": distribution.margin_probabilities(),
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate one NPB Asian market")
    parser.add_argument("input", type=Path, help="JSON input file")
    parser.add_argument("--pretty", action="store_true", default=True)
    args = parser.parse_args(argv)
    payload = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(analyze(payload), ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
