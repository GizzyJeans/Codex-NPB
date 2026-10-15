"""How much lower postseason scoring runs than the two teams' regular season predicts.

For each postseason game the expectation is the matchup of regular-season
per-game rates, (A scored + B allowed)/2 + (B scored + A allowed)/2, optionally
times a crude park factor for the home side (its home-game totals over its
road-game totals that season). The pooled ratio is sum(actual)/sum(expected);
the interval resamples postseason games.

usage: python scripts/postseason/ratio.py <games.csv> <seed>
"""
import csv, random, sys
from collections import defaultdict

rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
seed = int(sys.argv[2])
for r in rows:
    for k in ("year", "away_score", "home_score", "total", "number"):
        r[k] = int(r[k])

def team_rates(year):
    scored = defaultdict(float); allowed = defaultdict(float); games = defaultdict(int)
    home_tot = defaultdict(list); road_tot = defaultdict(list)
    for r in rows:
        if r["year"] != year or r["kind"] != "RS":
            continue
        a, h = r["away"], r["home"]
        scored[a] += r["away_score"]; allowed[a] += r["home_score"]; games[a] += 1
        scored[h] += r["home_score"]; allowed[h] += r["away_score"]; games[h] += 1
        home_tot[h].append(r["total"]); road_tot[a].append(r["total"])
    rate = {t: (scored[t] / games[t], allowed[t] / games[t]) for t in games}
    park = {t: (sum(home_tot[t]) / len(home_tot[t])) / (sum(road_tot[t]) / len(road_tot[t])) for t in home_tot if road_tot[t]}
    return rate, park

post = []
for year in sorted({r["year"] for r in rows}):
    rate, park = team_rates(year)
    for r in rows:
        if r["year"] != year or r["kind"] == "RS":
            continue
        a, h = r["away"], r["home"]
        if a not in rate or h not in rate:
            continue
        exp = (rate[a][0] + rate[h][1]) / 2 + (rate[h][0] + rate[a][1]) / 2
        post.append({**r, "exp": exp, "exp_park": exp * park.get(h, 1.0)})

def pooled(sel, key):
    return sum(p["total"] for p in sel) / sum(p[key] for p in sel)

def interval(sel, key, n=20000):
    random.seed(seed)
    b = sorted(pooled([random.choice(sel) for _ in sel], key) for _ in range(n))
    return b[int(0.025 * n)], b[int(0.975 * n)]

print(f"{'season':>8} {'games':>5} {'actual':>7} {'matchup':>8} {'ratio':>6} {'w/ park':>8} {'ratio':>6}")
for year in sorted({p["year"] for p in post}):
    sel = [p for p in post if p["year"] == year]
    print(f"{year:>8} {len(sel):>5} {sum(p['total'] for p in sel)/len(sel):7.2f} {sum(p['exp'] for p in sel)/len(sel):8.2f} "
          f"{pooled(sel, 'exp'):6.3f} {sum(p['exp_park'] for p in sel)/len(sel):8.2f} {pooled(sel, 'exp_park'):6.3f}")
for label, sel in (("2016-25", [p for p in post if 2016 <= p["year"] <= 2025]),
                   ("2016-25 CS", [p for p in post if 2016 <= p["year"] <= 2025 and p["kind"] == "CS"]),
                   ("2016-25 JS", [p for p in post if 2016 <= p["year"] <= 2025 and p["kind"] == "JS"]),
                   ("2026", [p for p in post if p["year"] == 2026])):
    lo, hi = interval(sel, "exp")
    lo2, hi2 = interval(sel, "exp_park")
    print(f"{label:>10} n={len(sel):3d}  ratio {pooled(sel, 'exp'):.3f} [{lo:.3f}, {hi:.3f}]   with park {pooled(sel, 'exp_park'):.3f} [{lo2:.3f}, {hi2:.3f}]"
          f"   actual {sum(p['total'] for p in sel)/len(sel):.2f} vs matchup {sum(p['exp'] for p in sel)/len(sel):.2f}")
