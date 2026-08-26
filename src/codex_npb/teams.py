"""Canonical NPB team registry.

Maps between the three identifier styles that appear across this project:
NPB.jp URL codes, the Japanese short names used in NPB.jp stat tables, and
the English names already used in ``records/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

League = Literal["central", "pacific"]


@dataclass(frozen=True)
class Team:
    code: str
    league: League
    jp_short: str
    jp_full: str
    english: str
    home_venues: tuple[str, ...]


TEAMS: tuple[Team, ...] = (
    Team("g", "central", "巨人", "読売ジャイアンツ", "Yomiuri Giants", ("東京ドーム",)),
    Team("t", "central", "阪神", "阪神タイガース", "Hanshin Tigers", ("甲子園",)),
    Team("db", "central", "DeNA", "横浜DeNAベイスターズ", "Yokohama DeNA BayStars", ("横浜",)),
    Team("c", "central", "広島", "広島東洋カープ", "Hiroshima Carp", ("マツダ",)),
    Team("s", "central", "ヤクルト", "東京ヤクルトスワローズ", "Tokyo Yakult Swallows", ("神宮",)),
    Team("d", "central", "中日", "中日ドラゴンズ", "Chunichi Dragons", ("バンテリンドーム", "バンテリン")),
    Team("h", "pacific", "ソフトバンク", "福岡ソフトバンクホークス", "Fukuoka SoftBank Hawks", ("みずほペイペイ", "PayPayドーム")),
    Team("f", "pacific", "日本ハム", "北海道日本ハムファイターズ", "Hokkaido Nippon-Ham Fighters", ("エスコンF",)),
    Team("m", "pacific", "ロッテ", "千葉ロッテマリーンズ", "Chiba Lotte Marines", ("ZOZOマリン",)),
    Team("l", "pacific", "西武", "埼玉西武ライオンズ", "Saitama Seibu Lions", ("ベルーナドーム", "ベルーナ")),
    Team("b", "pacific", "オリックス", "オリックス・バファローズ", "Orix Buffaloes", ("京セラD大阪",)),
    Team("e", "pacific", "楽天", "東北楽天ゴールデンイーグルス", "Tohoku Rakuten Golden Eagles", ("楽天モバイル",)),
)

BY_CODE = {team.code: team for team in TEAMS}
BY_JP_SHORT = {team.jp_short: team for team in TEAMS}
BY_ENGLISH = {team.english: team for team in TEAMS}

# Alternate short forms that are not just a whitespace difference.
_ALIASES = {
    "横浜DeNA": "DeNA",
    "ヤクルトスワローズ": "ヤクルト",
}


class UnknownTeam(KeyError):
    """Raised when a name cannot be resolved to a registered team."""


def normalize(name: str) -> str:
    """Strip every kind of whitespace, then apply known aliases.

    NPB.jp pads short names with full-width spaces (``中　日``), and tag
    stripping can turn those into ordinary spaces, so both must go.
    """
    text = re.sub(r"[\s\u3000]+", "", name)
    return _ALIASES.get(name.strip(), _ALIASES.get(text, text))


def resolve(name: str) -> Team:
    """Resolve a team from any supported identifier style."""
    text = name.strip()
    if text in BY_CODE:
        return BY_CODE[text]
    if text in BY_ENGLISH:
        return BY_ENGLISH[text]
    normalized = normalize(text)
    if normalized in BY_JP_SHORT:
        return BY_JP_SHORT[normalized]
    for team in TEAMS:
        if normalized == team.jp_full or normalized == normalize(team.jp_full):
            return team
    raise UnknownTeam(f"unknown NPB team {name!r}")


def league_of(name: str) -> League:
    return resolve(name).league
