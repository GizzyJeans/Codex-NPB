"""Command line entry points for the data pipeline."""

from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .backtest import backtest
from .board import price_board, read_board
from .ledger import append as ledger_append
from .track_record import collect
from .settlement import (
    OFFICIAL_SOURCE,
    first_pitch_utc,
    settle_board,
    summarize,
    write_candidates,
    write_projections,
    write_settlements,
)
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


def board_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Price a Taiwanese board against the projected slate"
    )
    parser.add_argument("board", type=Path, help="board CSV")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--slate", type=Path, required=True, help="slate directory")
    parser.add_argument(
        "--min-ev", type=float, default=0.0, help="only show markets above this EV"
    )
    args = parser.parse_args(argv)

    games = read_board(args.board)
    bundle = load_bundle(args.bundle)
    calibration = bundle["calibration"]
    projections = {}
    for path in sorted(args.slate.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        projections[(entry["game"]["away"], entry["game"]["home"])] = entry["model"]

    priced = price_board(
        games,
        projections,
        dispersion=calibration["dispersion"],
        final_draw_share=calibration["final_draw_share"],
    )
    shown = [market for market in priced if market.expected_value >= args.min_ev]
    shown.sort(key=lambda market: -market.expected_value)

    print(f"{len(priced)} markets priced, {len(shown)} at or above EV {args.min_ev:+.2%}\n")
    header = (
        f"{'game':<34}{'market':<8}{'selection':<26}{'line':>6}"
        f"{'model p':>9}{'EV':>9}{'gap(runs)':>11}{'status':>7}"
    )
    print(header)
    for market in shown:
        name = f"{market.away[:15]}@{market.home[:13]}"
        print(
            f"{name:<34}{market.market:<8}{market.selection[:24]:<26}{market.line:>6}"
            f"{market.model_probability:>9.4f}{market.expected_value:>+9.4f}"
            f"{market.expectation_gap:>+11.2f}{market.status:>7}"
        )
    warnings = {warning for market in priced for warning in market.warnings}
    for warning in sorted(warnings):
        print(f"\nWARNING: {warning}")
    return 0


def settle_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Settle a pre-game board against official NPB results"
    )
    parser.add_argument("game_date", help="YYYY-MM-DD")
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--slate", type=Path, required=True)
    parser.add_argument("--records", type=Path, default=Path("records"))
    parser.add_argument("--ledger", type=Path, default=Path("records/ledger.jsonl"))
    parser.add_argument("--shadow-stake", type=float, default=1_000)
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument(
        "--recorded-before-first-pitch",
        action="store_true",
        help="claim the day as prospective; each game is still checked individually",
    )
    parser.add_argument(
        "--priced-at",
        type=datetime.fromisoformat,
        default=None,
        help="when the board was priced (UTC); defaults to its git commit time",
    )
    parser.add_argument("--write", action="store_true", help="write records to disk")
    args = parser.parse_args(argv)

    target = date.fromisoformat(args.game_date)
    games = read_board(args.board)

    projections = {}
    for path in sorted(args.slate.glob("*.json")):
        entry = json.loads(path.read_text(encoding="utf-8"))
        projections[(entry["game"]["away"], entry["game"]["home"])] = entry
    if not projections:
        print(f"no slate entries under {args.slate}")
        return 1

    # Settle against the parameters frozen into the slate before first pitch,
    # never against whatever the bundle holds now. Re-reading the live
    # calibration would let a later data refresh silently change the EV a
    # candidate is recorded as having been priced at.
    frozen = next(iter(projections.values()))["model"]
    dispersion = frozen["dispersion"]
    final_draw_share = frozen["final_draw_share"]

    client = NPBOfficialClient(target.year, delay_seconds=args.delay)
    results = {(game.away, game.home): game for game in client.results_for(target)}
    if not results:
        print(f"npb.jp has no final scores for {target}; nothing settled")
        return 1

    priced = price_board(
        games,
        {key: entry["model"] for key, entry in projections.items()},
        dispersion=dispersion,
        final_draw_share=final_draw_share,
    )
    # The board's own commit is the authority on when the day was priced;
    # the record's integrity rests on version control, not on a claim.
    priced_at = args.priced_at or _board_commit_time(args.board)
    first_pitch = {
        key: first_pitch_utc(target, entry["game"].get("start_time", ""))
        for key, entry in projections.items()
    }
    settled = settle_board(
        priced,
        games,
        results,
        shadow_stake=args.shadow_stake,
        first_pitch=first_pitch,
        priced_at=priced_at,
    )
    summary = summarize(settled)
    late = [row for row in settled if not row.prospective]
    if late:
        names = sorted({f"{row.market.away} @ {row.market.home}" for row in late})
        print(f"priced at {priced_at:%Y-%m-%d %H:%M UTC}" if priced_at else "no price time")
        print(f"NOT prospective ({len(late)} markets): {'; '.join(names)}")
        print()

    print(f"{target}: settled {summary.graded} markets over {len(games)} games\n")
    print(f"{'game':<32}{'market':<8}{'selection':<24}{'line':>6}{'EV':>8}{'result':>14}{'shadow':>9}")
    for row in settled:
        entry = row.market
        name = f"{entry.away[:14]}@{entry.home[:12]}"
        print(
            f"{name:<32}{entry.market:<8}{entry.selection[:22]:<24}{entry.line:>6}"
            f"{entry.expected_value:>+8.3f}{row.result:>14}{row.shadow_pnl:>+9.0f}"
        )
    print(
        f"\nWATCH  {summary.watch_wins}-{summary.watch_losses}  "
        f"shadow {summary.watch_shadow_pnl:+,.0f} on {summary.watch_shadow_stake:,.0f} "
        f"(ROI {summary.watch_roi:+.1%})"
    )
    print(
        f"ALL    shadow {summary.all_shadow_pnl:+,.0f} on {summary.all_shadow_stake:,.0f} "
        f"(ROI {summary.all_roi:+.1%})"
    )
    print(f"ACTUAL stake {summary.actual_stake:,.0f}  P&L {summary.actual_pnl:+,.0f}")

    if not args.write:
        print("\n(dry run; pass --write to record)")
        return 0

    source = OFFICIAL_SOURCE.format(year=target.year, stamp=target.strftime("%Y%m%d"))
    directory = args.records / target.isoformat()
    write_projections(
        projections,
        results,
        directory / "game_projections.csv",
        model_version="npb-pipeline-v0.2",
        record_origin=(
            "prospective_pre_first_pitch"
            if args.recorded_before_first_pitch
            else "post_hoc"
        ),
    )
    write_candidates(settled, directory / "candidates.csv")
    write_settlements(settled, directory / "settlements.csv", official_source=source)
    record = ledger_append(
        args.ledger,
        {
            "event_type": "BOARD_SETTLEMENT",
            "game_date": target.isoformat(),
            "schema_version": 1,
            "recorded_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model_version": "npb-pipeline-v0.2",
            "markets_graded": summary.graded,
            "markets_prospective": summary.prospective,
            "priced_at_utc": priced_at.strftime("%Y-%m-%dT%H:%M:%SZ") if priced_at else None,
            "formal_bets": summary.formal,
            "watch_candidates": summary.watch,
            "watch_record": f"{summary.watch_wins}-{summary.watch_losses}",
            "watch_shadow_stake": summary.watch_shadow_stake,
            "watch_shadow_pnl": summary.watch_shadow_pnl,
            "all_shadow_stake": summary.all_shadow_stake,
            "all_shadow_pnl": summary.all_shadow_pnl,
            "actual_stake": summary.actual_stake,
            "actual_pnl": summary.actual_pnl,
            # Claiming the day is not enough: every market must also have
            # been priced before its own game started.
            "prospective_eligible": bool(args.recorded_before_first_pitch)
            and summary.prospective == summary.graded,
            "source": source,
            "notes": (
                "Board and projections committed before first pitch; "
                "classifications preserved as priced."
                if args.recorded_before_first_pitch
                and summary.prospective == summary.graded
                else (
                    f"{summary.graded - summary.prospective} of {summary.graded} "
                    "markets were priced after their own first pitch."
                )
            ),
        },
    )
    print(f"\nwrote {directory}/ and ledger sequence {record['sequence']}")
    return 0


def record_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Cumulative shadow record across every settled day"
    )
    parser.add_argument("--records", type=Path, default=Path("records"))
    args = parser.parse_args(argv)

    track = collect(args.records)
    if not track.days:
        print(f"no settled days found under {args.records}")
        return 1

    print(
        f"{'date':<13}{'WATCH':>7}{'W-L':>7}{'stake':>9}{'P&L':>9}{'ROI':>9}"
        f"{'  |':>4}{'all':>6}{'stake':>9}{'P&L':>9}{'ROI':>9}"
    )
    for day in track.days:
        print(
            f"{day.game_date:<13}{day.watch_markets:>7}"
            f"{f'{day.watch_wins}-{day.watch_losses}':>7}{day.watch_stake:>9,.0f}"
            f"{day.watch_pnl:>+9,.0f}{day.watch_roi:>9.1%}{'  |':>4}"
            f"{day.all_markets:>6}{day.all_stake:>9,.0f}{day.all_pnl:>+9,.0f}"
            f"{day.all_roi:>9.1%}"
        )
    print("-" * 94)
    print(
        f"{'cumulative':<13}{sum(d.watch_markets for d in track.days):>7}"
        f"{f'{sum(d.watch_wins for d in track.days)}-{sum(d.watch_losses for d in track.days)}':>7}"
        f"{track.watch_stake:>9,.0f}{track.watch_pnl:>+9,.0f}{track.watch_roi:>9.1%}"
        f"{'  |':>4}{sum(d.all_markets for d in track.days):>6}{track.all_stake:>9,.0f}"
        f"{track.all_pnl:>+9,.0f}{track.all_roi:>9.1%}"
    )
    print(f"\nactual P&L {track.actual_pnl:+,.0f}")
    if track.skipped:
        print(
            f"excluded {len(track.skipped)} pre-schema day(s) "
            f"({', '.join(track.skipped)}): imported after the fact, not prospective"
        )
    print(
        f"selection edge (WATCH ROI - all ROI): {track.selection_edge:+.1%}"
    )
    if track.selection_edge < 0:
        print(
            "  The filter is picking worse than pricing every market, so it is\n"
            "  destroying value rather than merely failing to add it."
        )
    return 0


def _jst_today() -> date:
    """The current date in Japan, which is the date NPB games are keyed by."""
    return (datetime.now(timezone.utc) + timedelta(hours=9)).date()


def _board_commit_time(board: Path) -> datetime | None:
    """When the board file was committed, read from git."""
    try:
        stamp = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", str(board)],
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp).astimezone(timezone.utc)
    except ValueError:
        return None


def _pending_settlements(boards: Path, records: Path, before: date) -> list[date]:
    """Boards that were priced but never settled, oldest first."""
    pending = []
    for path in sorted(boards.glob("*.csv")):
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day >= before:
            continue
        if not (records / day.isoformat() / "settlements.csv").exists():
            pending.append(day)
    return pending


def daily_main(argv: list[str] | None = None) -> int:
    """One run of the daily cycle: settle what finished, prepare what is next.

    Scheduled for 15:00 UTC, which is midnight in Japan. By then the day's
    games are final and the next day's 予告先発 are published, and it still
    leaves thirteen hours before the earliest possible first pitch at
    04:00 UTC.
    """
    parser = argparse.ArgumentParser(description="Run the daily NPB cycle")
    parser.add_argument("--date", default=None, help="target date; defaults to today in JST")
    parser.add_argument("--bundle", type=Path, default=DEFAULT_BUNDLE)
    parser.add_argument("--boards", type=Path, default=Path("boards"))
    parser.add_argument("--slates", type=Path, default=Path("slates"))
    parser.add_argument("--records", type=Path, default=Path("records"))
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--skip-settle", action="store_true")
    args = parser.parse_args(argv)

    target = date.fromisoformat(args.date) if args.date else _jst_today()
    print(f"=== daily cycle for {target} (JST) ===\n")

    settled_days: list[date] = []
    if not args.skip_settle:
        pending = _pending_settlements(args.boards, args.records, target)
        if not pending:
            print("settle: nothing pending\n")
        for day in pending:
            slate = args.slates / day.isoformat()
            if not slate.exists():
                print(f"settle {day}: no slate directory, skipped\n")
                continue
            print(f"--- settling {day} ---")
            try:
                settle_main([
                    day.isoformat(),
                    "--board", str(args.boards / f"{day.isoformat()}.csv"),
                    "--slate", str(slate),
                    "--records", str(args.records),
                    "--delay", str(args.delay),
                    "--write", "--recorded-before-first-pitch",
                ])
                settled_days.append(day)
            except Exception as error:  # a bad day must not block the next slate
                print(f"settle {day} failed: {error}")
            print()

    print("--- refreshing data ---")
    fetch_main([
        "--year", str(target.year),
        "--out", str(args.bundle),
        "--delay", str(args.delay),
    ])
    print()

    print(f"--- slate for {target} ---")
    slate_dir = args.slates / target.isoformat()
    slate_status = slate_main([
        target.isoformat(),
        "--bundle", str(args.bundle),
        "--out", str(slate_dir),
    ])
    if slate_status != 0:
        print(f"\nno games scheduled for {target}; nothing to prepare")

    board = args.boards / f"{target.isoformat()}.csv"
    print()
    if board.exists():
        print(f"--- pricing {board} ---")
        board_main([
            str(board), "--bundle", str(args.bundle), "--slate", str(slate_dir),
        ])
    else:
        print(f"NEXT: no board at {board}.")
        print("      Transcribe the day's lines into that file, then run:")
        print(f"      codex-npb-board {board} --slate {slate_dir}")
        print("      Commit it before first pitch or the day is not a prospective record.")

    if settled_days:
        print(f"\nsettled: {', '.join(day.isoformat() for day in settled_days)}")
    return 0


def _slug(name: str) -> str:
    return name.lower().replace(" ", "-")


if __name__ == "__main__":
    raise SystemExit(fetch_main())
