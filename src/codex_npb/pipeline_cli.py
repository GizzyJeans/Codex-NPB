"""Command line entry points for the data pipeline."""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path

from .backtest import backtest
from .pipeline import build_slate, fetch_bundle, load_bundle, save_bundle
from .projection import ProjectionSettings
from .sources import NPBOfficialClient

DEFAULT_BUNDLE = Path("data/npb_bundle.json")


def fetch_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fetch public NPB season data from npb.jp into a local snapshot"
    )
    parser.add_argument("--year", type=int, default=date.today().year)
    parser.add_argument("--out", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="seconds between requests; keep this polite",
    )
    parser.add_argument("--from-month", type=int, default=3)
    parser.add_argument("--to-month", type=int, default=11)
    args = parser.parse_args(argv)

    client = NPBOfficialClient(args.year, delay_seconds=args.delay)
    months = range(args.from_month, args.to_month + 1)
    bundle = fetch_bundle(client, months=months)
    path = save_bundle(bundle, args.out)

    calibration = bundle.calibration
    print(f"wrote {path}")
    print(f"  teams            {len(bundle.team_seasons)}")
    print(f"  rostered arms    {sum(len(v) for v in bundle.rosters.values())}")
    print(f"  schedule rows    {len(bundle.schedule)}")
    print(f"  calibrated on    {calibration.games} completed games")
    print(f"  runs/team/game   {calibration.runs_per_team_game:.3f}")
    print(f"  dispersion       {calibration.dispersion:.2f}")
    print(f"  home advantage   {calibration.home_field_advantage:.4f}")
    print(f"  final draw share {calibration.final_draw_share:.4f}")
    for warning in calibration.warnings:
        print(f"  WARNING: {warning}")
    return 0


def slate_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build per-game analysis inputs for one date from a snapshot"
    )
    parser.add_argument("game_date", help="YYYY-MM-DD")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--out", type=Path, default=None, help="directory for JSON inputs")
    args = parser.parse_args(argv)

    target = date.fromisoformat(args.game_date)
    bundle = load_bundle(args.bundle)
    calibration = bundle["calibration"]
    settings = ProjectionSettings(
        home_field_advantage=calibration["home_field_advantage"]
    )
    entries = build_slate(bundle, target, settings=settings)
    if not entries:
        print(f"no scheduled games found for {target} in {args.bundle}")
        return 1

    print(f"{target}: {len(entries)} games   (snapshot {bundle['fetched_at_utc']})")
    print(f"{'away':<30}{'home':<30}{'away_mu':>8}{'home_mu':>9}{'total':>7}  {'park':>5}  starters")
    for entry in entries:
        projection = entry.projection
        starters = (
            f"{projection.away_starter or '-'} / {projection.home_starter or '-'}"
        )
        print(
            f"{entry.away:<30}{entry.home:<30}"
            f"{projection.away_mu:>8.2f}{projection.home_mu:>9.2f}"
            f"{projection.total_mu:>7.2f}  {projection.park_factor:>5.3f}  {starters}"
        )

    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            payload = entry.to_analysis_input(
                dispersion=calibration["dispersion"],
                final_draw_share=calibration["final_draw_share"],
            )
            name = f"{entry.game_date}_{_slug(entry.away)}_at_{_slug(entry.home)}.json"
            (args.out / name).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(f"\nwrote {len(entries)} analysis inputs to {args.out}")
        print("Market prices and platform rules are left blank on purpose; fill them in,")
        print("then run: codex-npb <file>")
    return 0


def backtest_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Walk-forward backtest of the projection against the season game log"
    )
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--minimum-games", type=int, default=20)
    args = parser.parse_args(argv)

    bundle = load_bundle(args.bundle)
    calibration = bundle["calibration"]
    leagues = {name: row["league"] for name, row in bundle["team_seasons"].items()}
    parks = {
        venue: park["factor"]
        for venue, park in calibration["park_factors"].items()
        if park["home_games"] >= 30
    }
    client = NPBOfficialClient(args.year or bundle["year"], delay_seconds=args.delay)
    log = client.season_game_log(range(3, 12))

    result = backtest(
        log,
        leagues=leagues,
        settings=ProjectionSettings(
            home_field_advantage=calibration["home_field_advantage"]
        ),
        park_factors=parks,
        dispersion=calibration["dispersion"],
        final_draw_share=calibration["final_draw_share"],
        minimum_games=args.minimum_games,
    )
    print(f"graded {result.graded} games, skipped {result.skipped} early-season\n")
    print(f"{'metric':<24}{'model':>10}{'baseline':>11}{'gain':>10}")
    print(
        f"{'total runs MAE':<24}{result.total_mae:>10.4f}"
        f"{result.total_mae_baseline:>11.4f}{result.total_improvement * 100:>9.2f}%"
    )
    print(
        f"{'margin MAE':<24}{result.margin_mae:>10.4f}"
        f"{result.margin_mae_baseline:>11.4f}{result.margin_improvement * 100:>9.2f}%"
    )
    print(
        f"{'home-win Brier':<24}{result.home_win_brier:>10.4f}"
        f"{result.home_win_brier_baseline:>11.4f}{result.brier_improvement * 100:>9.2f}%"
    )
    print("\ntotals calibration (predicted vs actual over-rate):")
    for label, values in sorted(result.coverage.items()):
        print(
            f"  {label:10} {values['predicted'] * 100:6.2f}%  vs {values['actual'] * 100:6.2f}%"
            f"   gap {abs(values['predicted'] - values['actual']) * 100:5.2f}pp"
        )
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    return 0


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


if __name__ == "__main__":
    raise SystemExit(fetch_main())
