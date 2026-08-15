from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from codex_npb.ledger import append  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="One-time import of the 2026-08-13/14 chat-backed NPB records"
    )
    parser.add_argument("--output", type=Path, default=Path("records/ledger.jsonl"))
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite append-only ledger: {args.output}")

    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    events = [
        {
            "schema_version": 1,
            "event_type": "HISTORICAL_RESULTS_IMPORT",
            "recorded_at_utc": recorded_at,
            "game_date": "2026-08-13",
            "prospective_eligible": False,
            "games_final": 5,
            "games_cancelled": 1,
            "source": "https://npb.jp/bis/2026/games/gm20260813.html",
            "notes": "Results only; no provable pregame model output was imported.",
        },
        {
            "schema_version": 1,
            "event_type": "HISTORICAL_ANALYSIS_IMPORT",
            "recorded_at_utc": recorded_at,
            "source_timestamp_utc": "2026-08-14T08:10:00Z",
            "game_date": "2026-08-14",
            "prospective_eligible": False,
            "model_version": "npb-nb-v0.1-chat-snapshot",
            "formal_bets": 0,
            "watch_candidates": 6,
            "invalid_stale_candidates": 1,
            "actual_stake": 0,
            "notes": "Imported on 2026-08-15 from the prior chat; classifications preserved.",
        },
        {
            "schema_version": 1,
            "event_type": "HISTORICAL_SETTLEMENT_IMPORT",
            "recorded_at_utc": recorded_at,
            "game_date": "2026-08-14",
            "prospective_eligible": False,
            "watch_record": "6-0",
            "watch_shadow_stake": 6000,
            "watch_shadow_pnl": 5640,
            "invalid_stale_shadow_pnl": 465,
            "actual_stake": 0,
            "actual_pnl": 0,
            "source": "https://npb.jp/bis/2026/games/gm20260814.html",
            "notes": "Shadow performance is not an actual wager record.",
        },
        {
            "schema_version": 1,
            "event_type": "MODEL_RELEASE",
            "recorded_at_utc": recorded_at,
            "version": "0.1.0",
            "prospective_eligible": True,
            "notes": "Portable NPB distribution, Taiwan-tail settlement, EV and Kelly implementation.",
        },
    ]
    for event in events:
        append(args.output, event)
    print(f"Imported {len(events)} events into {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
