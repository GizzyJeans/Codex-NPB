"""Two what-ifs for the 2026-10-15 board. Neither touches a committed file.

1. Contamination: rebuild the calibration from regular-season games only
   (through 2026-10-08), write a scratch bundle, build a scratch slate from it
   and price the board, to see what the seven Climax Series games already in
   the calibration changed.
2. Postseason scaling: price the committed slate's projections with both
   teams' expected runs multiplied by a factor, for the historical
   matchup-adjusted postseason ratios.

usage: PYTHONPATH=src python scripts/postseason/whatif_20261015.py <scratch dir>
"""
import json, sys
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path
from codex_npb.board import read_board, price_board
from codex_npb.calibration import calibrate_season
from codex_npb.pipeline_cli import slate_main
from codex_npb.sources.npb_official import GameResult

scratch = Path(sys.argv[1]); scratch.mkdir(parents=True, exist_ok=True)
D = "2026-10-15"
games = read_board(f"boards/{D}.csv")

def show(label, priced):
    print(f"\n{label}")
    for m in sorted(priced, key=lambda m: -m.expected_value):
        flag = "WATCH" if m.status == "WATCH" else m.status
        print(f"  {m.away[:16]:16s}@{m.home[:16]:16s} {m.market:6s} {m.selection[:24]:24s} {m.line:5s} p={m.model_probability:.4f} EV={m.expected_value:+.4f} gap={m.expectation_gap:+.2f} {flag}")

def committed_projections(slate_dir):
    out = {}
    for path in sorted(Path(slate_dir).glob("*.json")):
        e = json.loads(path.read_text(encoding="utf-8"))
        out[(e["game"]["away"], e["game"]["home"])] = e["model"]
    return out

# ---- 1. contamination
bundle = json.loads(Path("data/npb_bundle.json").read_text(encoding="utf-8"))
log = [GameResult(game_date=date.fromisoformat(r["game_date"]), away=r["away"], home=r["home"],
                  away_score=r["away_score"], home_score=r["home_score"], venue=r["venue"], game_number=0)
       for r in bundle["schedule"]
       if r["status"] == "final" and r["away_score"] is not None and r["game_date"] <= "2026-10-08"]
cal = calibrate_season(log)
as_json = {**{k: v for k, v in asdict(cal).items() if k != "park_factors"},
           "park_factors": {venue: asdict(f) for venue, f in cal.park_factors.items()}}
print(f"regular-season-only calibration: {as_json['games']} games, runs/team/game {as_json['runs_per_team_game']:.4f} "
      f"(committed {bundle['calibration']['runs_per_team_game']:.4f} on {bundle['calibration']['games']}), "
      f"dispersion {as_json['dispersion']:.4f} ({bundle['calibration']['dispersion']:.4f}), "
      f"final draw share {as_json['final_draw_share']:.4f} ({bundle['calibration']['final_draw_share']:.4f})")
for venue in ("甲子園", "みずほPayPay"):
    a = as_json["park_factors"].get(venue); b = bundle["calibration"]["park_factors"].get(venue)
    print(f"  park {venue}: {a and round(a.get('factor', a.get('run_factor', 0)), 4)} vs committed {b and round(b.get('factor', b.get('run_factor', 0)), 4)}  raw={a}")
bundle["calibration"] = as_json
scratch_bundle = scratch / "bundle_rs_only.json"
scratch_bundle.write_text(json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
slate_main([D, "--bundle", str(scratch_bundle), "--out", str(scratch / "slate_rs_only")])
rs_only = committed_projections(scratch / "slate_rs_only")
for k, m in rs_only.items():
    print(f"  {k[0][:18]}@{k[1][:18]}: {m['away_mu']:.4f}-{m['home_mu']:.4f}")
show("priced with the regular-season-only calibration",
     price_board(games, rs_only, dispersion=as_json["dispersion"], final_draw_share=as_json["final_draw_share"]))

# ---- 2. postseason scaling of the committed projections
proj = committed_projections(f"slates/{D}")
any_model = next(iter(proj.values()))
show("committed slate (the record)", price_board(games, proj, dispersion=any_model["dispersion"], final_draw_share=any_model["final_draw_share"]))
for factor, why in ((0.906, "2016-25 matchup-adjusted"), (0.880, "2016-25 matchup and park adjusted"), (0.800, "a harder cut, between history and 2026's first 7 games")):
    scaled = {k: {**m, "away_mu": m["away_mu"] * factor, "home_mu": m["home_mu"] * factor} for k, m in proj.items()}
    for k, m in scaled.items():
        print(f"  x{factor}: {k[0][:18]}@{k[1][:18]} {m['away_mu']:.3f}-{m['home_mu']:.3f} total {m['away_mu'] + m['home_mu']:.2f}")
    show(f"scaled x{factor} ({why})", price_board(games, scaled, dispersion=any_model["dispersion"], final_draw_share=any_model["final_draw_share"]))
