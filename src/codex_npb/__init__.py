"""NPB-specific quantitative market evaluation."""

from .model import (
    Eligibility,
    ModelConfig,
    ScoreDistribution,
    SpreadMarket,
    TotalMarket,
    build_score_distribution,
    evaluate_market,
    no_vig_probability,
)

__all__ = [
    "Eligibility",
    "ModelConfig",
    "ScoreDistribution",
    "SpreadMarket",
    "TotalMarket",
    "build_score_distribution",
    "evaluate_market",
    "no_vig_probability",
]

__version__ = "0.1.0"
