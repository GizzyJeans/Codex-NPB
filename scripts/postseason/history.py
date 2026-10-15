"""Regular-season vs postseason scoring on npb.jp, by season.

Reads the monthly schedule pages (the same pages the pipeline uses). A row's
score link ends in the game's number within its pairing; by October every
regular-season pairing is past game 20, so an October/November row numbered
8 or lower is a postseason game (Climax Series or Japan Series). Writes a
CSV of every final game and prints a per-season summary.

usage: PYTHONPATH=src python scripts/postseason/history.py <first year> <last year> <out.csv>
"""
import csv, re, sys
from codex_npb.sources.npb_official import NPBOfficialClient, SourceError, _SCHEDULE_ROW_RE, _DIV_RE, _first
from codex_npb.teams import resolve

first, last, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
LINK = re.compile(r'href="/scores/(\d{4})/(\d{4})/([a-z]+)-([a-z]+)-(\d+)/"')
CENTRAL = {"Yomiuri Giants", "Hanshin Tigers", "Yokohama DeNA BayStars", "Hiroshima Carp", "Chunichi Dragons", "Tokyo Yakult Swallows"}
rows = []
for year in range(first, last + 1):
    client = NPBOfficialClient(year, delay_seconds=0.3)
    for month in range(3, 12):
        try:
            document = client.fetch(f"/games/{year}/schedule_{month:02d}_detail.html")
        except SourceError as error:
            print(f"{year}-{month:02d}: {error}")
            continue
        for match in _SCHEDULE_ROW_RE.finditer(document):
            md = match.group("md")
            if int(md[:2]) != month:
                continue
            body = match.group("body")
            s1, s2 = _first(_DIV_RE["score1"], body).strip(), _first(_DIV_RE["score2"], body).strip()
            if not (s1.isdigit() and s2.isdigit()):
                continue
            try:
                home = resolve(_first(_DIV_RE["team1"], body)).english
                away = resolve(_first(_DIV_RE["team2"], body)).english
            except KeyError:
                continue
            link = LINK.search(body)
            number = int(link.group(5)) if link else -1
            post = month >= 10 and 0 < number <= 8
            kind = ("JS" if (home in CENTRAL) != (away in CENTRAL) else "CS") if post else "RS"
            rows.append({"year": year, "date": f"{year}-{md[:2]}-{md[2:]}", "away": away, "home": home,
                         "away_score": int(s2), "home_score": int(s1), "total": int(s1) + int(s2),
                         "number": number, "kind": kind})
with open(out, "w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
    writer.writeheader(); writer.writerows(rows)
print(f"wrote {len(rows)} final games to {out}")
print(f"{'year':>4} {'RS games':>8} {'RS R/G':>7} {'CS':>4} {'CS R/G':>7} {'JS':>4} {'JS R/G':>7}  post/RS")
for year in range(first, last + 1):
    by = {k: [r["total"] for r in rows if r["year"] == year and r["kind"] == k] for k in ("RS", "CS", "JS")}
    if not by["RS"]:
        continue
    rs = sum(by["RS"]) / len(by["RS"])
    post = by["CS"] + by["JS"]
    cs = f"{sum(by['CS'])/len(by['CS']):7.2f}" if by["CS"] else f"{'-':>7}"
    js = f"{sum(by['JS'])/len(by['JS']):7.2f}" if by["JS"] else f"{'-':>7}"
    ratio = f"{(sum(post)/len(post))/rs:6.3f}" if post else "   -"
    print(f"{year:>4} {len(by['RS']):>8} {rs:7.2f} {len(by['CS']):>4} {cs} {len(by['JS']):>4} {js}  {ratio}")
