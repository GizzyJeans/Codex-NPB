"""NPB-specific quantitative market evaluation."""

from .calibration import calibrate_season
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
from .projection import GameProjection, ProjectionSettings, TeamSeason, project_game
from .roster import match_starter

__all__ = [
    "GameProjection",
    "ProjectionSettings",
    "TeamSeason",
    "calibrate_season",
    "match_starter",
    "project_game",
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
