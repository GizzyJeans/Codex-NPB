"""Fetch and parse public data from npb.jp.

Only the Python standard library is used, matching the rest of the project.
Every parser returns plain dataclasses; nothing here decides betting policy.

Pages consumed:

- ``/bis/{year}/stats/tmb_{league}.html``  team batting (runs scored)
- ``/bis/{year}/stats/tmp_{league}.html``  team pitching (runs allowed)
- ``/bis/{year}/stats/idp{n}_{league}.html`` individual pitching per club
- ``/bis/{year}/games/gm{yyyymmdd}.html``  daily final scores
- ``/games/{year}/schedule_{mm}_detail.html`` monthly schedule
"""

from __future__ import annotations

import html
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date
from typing import Iterator

from ..teams import TEAMS, Team, resolve

USER_AGENT = "codex-npb/0.1 (+https://github.com/GizzyJeans/Codex-NPB)"
BASE = "https://npb.jp"
LEAGUE_SUFFIX = {"central": "c", "pacific": "p"}


class SourceError(RuntimeError):
    """Raised when a page cannot be fetched or parsed as expected."""


@dataclass(frozen=True)
class TeamBatting:
    team: str
    games: int
    runs_scored: int
    plate_appearances: int
    home_runs: int


@dataclass(frozen=True)
class TeamPitching:
    team: str
    games: int
    runs_allowed: int
    earned_runs: int
    innings_pitched: float
    era: float


@dataclass(frozen=True)
class PitcherLine:
    name: str
    team: str
    throws: str  # "L", "R" — NPB.jp marks left-handers with a leading asterisk
    appearances: int
    innings_pitched: float
    runs_allowed: int
    batters_faced: int
    strikeouts: int
    walks: int

    @property
    def ra9(self) -> float:
        if self.innings_pitched <= 0:
            return float("nan")
        return self.runs_allowed / self.innings_pitched * 9


@dataclass(frozen=True)
class GameResult:
    game_date: date
    away: str
    home: str
    away_score: int
    home_score: int
    venue: str
    game_number: int

    @property
    def total_runs(self) -> int:
        return self.away_score + self.home_score

    @property
    def is_draw(self) -> bool:
        return self.away_score == self.home_score


@dataclass(frozen=True)
class ScheduledGame:
    game_date: date
    away: str
    home: str
    venue: str
    start_time: str
    away_starter: str = ""
    home_starter: str = ""
    weather: str = ""
    status: str = "scheduled"
    away_score: int | None = None
    home_score: int | None = None

    @property
    def starters_announced(self) -> bool:
        return bool(self.away_starter and self.home_starter)


def _strip_tags(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(text).replace("　", " ").strip()


def _cells(row: str) -> list[str]:
    return [_strip_tags(cell) for cell in re.findall(r"<t[dh][^>]*>.*?</t[dh]>", row, re.S)]


def _rows(table: str) -> list[list[str]]:
    return [_cells(row) for row in re.findall(r"<tr[^>]*>.*?</tr>", table, re.S)]


def _tables(document: str) -> list[str]:
    return re.findall(r"<table[^>]*>.*?</table>", document, re.S)


def _to_int(value: str) -> int:
    text = value.replace(",", "").strip().rstrip("+").strip()
    try:
        return int(text)
    except ValueError:
        return 0


def _to_float(value: str) -> float:
    """Parse NPB numeric cells.

    Innings are written as ``1018.2`` meaning 1018 and 2/3 innings. A
    trailing ``+`` marks a pitcher who faced batters without recording an
    out, so it contributes no additional third of an inning.
    """
    text = value.replace(",", "").strip().rstrip("+").strip()
    if not text or text in {"-", "―", "----"}:
        return 0.0
    if "." in text:
        whole, _, fraction = text.partition(".")
        if fraction in {"1", "2"}:
            return int(whole) + int(fraction) / 3
    try:
        return float(text)
    except ValueError:
        return 0.0


def _header_index(header: list[str]) -> dict[str, int]:
    return {name: position for position, name in enumerate(header)}


class NPBOfficialClient:
    """Small polite HTTP client for npb.jp."""

    def __init__(
        self,
        year: int | None = None,
        *,
        delay_seconds: float = 1.0,
        timeout: float = 30.0,
        retries: int = 3,
    ) -> None:
        self.year = year or date.today().year
        self.delay_seconds = delay_seconds
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0
        self._page_cache: dict[str, str] = {}

    def fetch(self, path: str) -> str:
        url = path if path.startswith("http") else f"{BASE}{path}"
        wait = self.delay_seconds - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read()
                self._last_request = time.monotonic()
                return raw.decode("utf-8", errors="replace")
            except (urllib.error.URLError, TimeoutError) as error:
                last_error = error
                if attempt < self.retries - 1:
                    time.sleep(2**attempt)
        raise SourceError(f"failed to fetch {url}: {last_error}")

    # ---------------------------------------------------------------- stats

    def team_batting(self, league: str) -> list[TeamBatting]:
        document = self.fetch(f"/bis/{self.year}/stats/tmb_{LEAGUE_SUFFIX[league]}.html")
        return list(_parse_team_batting(document))

    def team_pitching(self, league: str) -> list[TeamPitching]:
        document = self.fetch(f"/bis/{self.year}/stats/tmp_{LEAGUE_SUFFIX[league]}.html")
        return list(_parse_team_pitching(document))

    def pitchers(self, team: str | Team) -> list[PitcherLine]:
        """Top-team individual pitching for one club.

        NPB.jp keys these pages by club code, not by league: ``idp1_{code}``
        is the top team and ``idp2_{code}`` the farm side.
        """
        resolved = team if isinstance(team, Team) else resolve(team)
        path = f"/bis/{self.year}/stats/idp1_{resolved.code}.html"
        document = self._page_cache.get(path) or self.fetch(path)
        self._page_cache[path] = document
        title = re.search(r"<title>(.*?)</title>", document, re.S)
        if title and resolved.jp_full not in title.group(1):
            raise SourceError(
                f"{path} is titled {title.group(1)!r}, expected {resolved.jp_full}"
            )
        return list(_parse_pitchers(document, resolved.english))

    def all_pitchers(self) -> list[PitcherLine]:
        lines: list[PitcherLine] = []
        for team in TEAMS:
            lines.extend(self.pitchers(team))
        return lines

    # ---------------------------------------------------------------- games

    def results_for(self, game_date: date) -> list[GameResult]:
        """Final scores for one date.

        The daily page is authoritative but lags: it can still be titled
        試合予定 hours after the games have finished, in which case it carries
        no scores at all. The monthly schedule table is updated first, so it
        is used as a fallback rather than reporting a played date as empty.
        """
        stamp = game_date.strftime("%Y%m%d")
        document = self.fetch(f"/bis/{self.year}/games/gm{stamp}.html")
        results = list(_parse_daily_results(document, game_date))
        if results:
            return results
        return [
            GameResult(
                game_date=entry.game_date,
                away=entry.away,
                home=entry.home,
                away_score=entry.away_score,
                home_score=entry.home_score or 0,
                venue=entry.venue,
                game_number=0,
            )
            for entry in self.schedule_for_month(game_date.month)
            if entry.game_date == game_date
            and entry.status == "final"
            and entry.away_score is not None
        ]

    def schedule_for_month(self, month: int) -> list[ScheduledGame]:
        document = self.fetch(f"/games/{self.year}/schedule_{month:02d}_detail.html")
        return list(_parse_schedule(document, self.year, month))

    def season_game_log(self, months: Iterable[int] = range(3, 12)) -> list[GameResult]:
        """Completed games for the season, read from the monthly schedule pages.

        Far cheaper than one request per calendar day, and the monthly detail
        table carries the same final scores as the daily result pages.
        """
        log: list[GameResult] = []
        for month in months:
            try:
                entries = self.schedule_for_month(month)
            except SourceError:
                continue
            for entry in entries:
                if entry.status != "final" or entry.away_score is None:
                    continue
                log.append(
                    GameResult(
                        game_date=entry.game_date,
                        away=entry.away,
                        home=entry.home,
                        away_score=entry.away_score,
                        home_score=entry.home_score or 0,
                        venue=entry.venue,
                        game_number=0,
                    )
                )
        return log


# --------------------------------------------------------------- parsers


def _parse_team_batting(document: str) -> Iterator[TeamBatting]:
    for table in _tables(document):
        rows = [row for row in _rows(table) if row]
        if len(rows) < 2 or "得点" not in rows[0]:
            continue
        index = _header_index(rows[0])
        for row in rows[1:]:
            if len(row) < len(rows[0]):
                continue
            yield TeamBatting(
                team=resolve(row[0]).english,
                games=_to_int(row[index["試合"]]),
                runs_scored=_to_int(row[index["得点"]]),
                plate_appearances=_to_int(row[index["打席"]]),
                home_runs=_to_int(row[index["本塁打"]]),
            )
        return
    raise SourceError("team batting table not found")


def _parse_team_pitching(document: str) -> Iterator[TeamPitching]:
    for table in _tables(document):
        rows = [row for row in _rows(table) if row]
        if len(rows) < 2 or "失点" not in rows[0]:
            continue
        index = _header_index(rows[0])
        for row in rows[1:]:
            if len(row) < len(rows[0]):
                continue
            yield TeamPitching(
                team=resolve(row[0]).english,
                games=_to_int(row[index["試合"]]),
                runs_allowed=_to_int(row[index["失点"]]),
                earned_runs=_to_int(row[index["自責点"]]),
                innings_pitched=_to_float(row[index["投球回"]]),
                era=_to_float(row[index["防御率"]]),
            )
        return
    raise SourceError("team pitching table not found")


def _parse_pitchers(document: str, team_english: str) -> Iterator[PitcherLine]:
    for table in _tables(document):
        rows = [row for row in _rows(table) if row]
        if len(rows) < 2 or "投球回" not in rows[0] or "登板" not in rows[0]:
            continue
        index = _header_index(rows[0])
        for row in rows[1:]:
            if len(row) < len(rows[0]) or not row[0]:
                continue
            raw_name = re.sub(r"\s+", " ", row[0]).strip()
            yield PitcherLine(
                name=raw_name.lstrip("*").strip(),
                team=team_english,
                throws="L" if raw_name.startswith("*") else "R",
                appearances=_to_int(row[index["登板"]]),
                innings_pitched=_to_float(row[index["投球回"]]),
                runs_allowed=_to_int(row[index["失点"]]),
                batters_faced=_to_int(row[index["打者"]]),
                strikeouts=_to_int(row[index["三振"]]),
                walks=_to_int(row[index["四球"]]),
            )
        return
    raise SourceError(f"pitching table not found for {team_english}")


_RESULT_BOX_RE = re.compile(
    r'<a href="(?P<slug>/scores/\d{4}/(?P<md>\d{4})/(?P<home>[a-z]+)-(?P<away>[a-z]+)-(?P<no>\d+)/)"'
    r'[^>]*class="link_box"[^>]*>(?P<body>.*?)</a>',
    re.S,
)
_SCORE_RE = re.compile(r'class="score_text score_(left|right)"[^>]*>(.*?)</div>', re.S)
_ROUND_RE = re.compile(r'class="round"[^>]*>(.*?)</div>', re.S)


def _parse_daily_results(document: str, game_date: date) -> Iterator[GameResult]:
    """Daily result blocks put the home club on the left and the away club on the right.

    The anchor slug is ``{home}-{away}-{game_number}``, which is used as the
    authoritative side assignment; the visible names only confirm it.
    """
    for match in _RESULT_BOX_RE.finditer(document):
        body = match.group("body")
        scores = dict(_SCORE_RE.findall(body))
        home_text = scores.get("left", "").strip()
        away_text = scores.get("right", "").strip()
        if not home_text.isdigit() or not away_text.isdigit():
            continue  # postponed, cancelled or not yet played
        try:
            home = resolve(match.group("home"))
            away = resolve(match.group("away"))
        except KeyError:
            continue
        venue = ""
        round_match = _ROUND_RE.search(body)
        if round_match:
            parts = [
                _strip_tags(part).replace(" ", "")
                for part in re.split(r"<br\s*/?>", round_match.group(1))
            ]
            venue = next((part for part in parts if part and not part.endswith("回戦")), "")
        yield GameResult(
            game_date=game_date,
            away=away.english,
            home=home.english,
            away_score=int(away_text),
            home_score=int(home_text),
            venue=venue,
            game_number=int(match.group("no")),
        )


_SCHEDULE_ROW_RE = re.compile(
    r'<tr id="date(?P<md>\d{4})"[^>]*>(?P<body>.*?)</tr>', re.S
)
_DIV_RE = {
    name: re.compile(rf'<div class="{name}"[^>]*>(.*?)</div>', re.S)
    for name in ("team1", "team2", "place", "time", "score1", "score2", "state")
}
_PIT_RE = re.compile(r'<div class="pit"[^>]*>(.*?)</div>', re.S)
_WEATHER_RE = re.compile(r'<div class="weather"[^>]*>.*?alt="([^"]*)"', re.S)


def _first(pattern: re.Pattern[str], body: str) -> str:
    match = pattern.search(body)
    return _strip_tags(match.group(1)) if match else ""


def _parse_schedule(document: str, year: int, month: int) -> Iterator[ScheduledGame]:
    """Parse the monthly detail table.

    Each ``<tr id="dateMMDD">`` is one game. ``team1`` is the home club and
    ``team2`` the visitor; the two ``pit`` cells carry the announced starters
    in the same order (home first). Starter cells are surname-only, are empty
    until NPB publishes the 予告先発, and switch to 勝：/敗： decisions once
    the game is final — only 先発 cells are read here.
    """
    for match in _SCHEDULE_ROW_RE.finditer(document):
        month_day = match.group("md")
        game_month, game_day = int(month_day[:2]), int(month_day[2:])
        if game_month != month:
            continue
        body = match.group("body")
        home_raw = _first(_DIV_RE["team1"], body)
        away_raw = _first(_DIV_RE["team2"], body)
        if not home_raw or not away_raw:
            continue
        try:
            home = resolve(home_raw)
            away = resolve(away_raw)
        except KeyError:
            continue
        # Once a game is final the same cells carry 勝：/敗： (the decision
        # pitchers), not 先発：. Only an announced starter may populate these
        # fields, or historical rows would silently report winners as starters.
        starters = [
            _strip_tags(cell).removeprefix("先発：").strip()
            for cell in _PIT_RE.findall(body)
            if "先発" in _strip_tags(cell)
        ]
        starters += ["", ""]
        weather_match = _WEATHER_RE.search(body)
        state = _first(_DIV_RE["state"], body)
        score1 = _first(_DIV_RE["score1"], body).strip()
        score2 = _first(_DIV_RE["score2"], body).strip()
        final = score1.isdigit() and score2.isdigit()
        if final:
            status = "final"
        elif "中止" in state or "中止" in body:
            status = "cancelled"
        else:
            status = "scheduled"
        yield ScheduledGame(
            game_date=date(year, game_month, game_day),
            away=away.english,
            home=home.english,
            venue=_first(_DIV_RE["place"], body).replace(" ", ""),
            start_time=_first(_DIV_RE["time"], body),
            home_starter=starters[0],
            away_starter=starters[1],
            weather=weather_match.group(1) if weather_match else "",
            status=status,
            away_score=int(score2) if final else None,
            home_score=int(score1) if final else None,
        )
