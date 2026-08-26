import unittest
from datetime import date

from codex_npb.sources.npb_official import (
    _parse_daily_results,
    _parse_pitchers,
    _parse_schedule,
    _parse_team_batting,
    _parse_team_pitching,
    _to_float,
    _to_int,
)

TEAM_BATTING = """
<table><tr><th>チーム</th><th>打率</th><th>試合</th><th>打席</th><th>打数</th><th>得点</th>
<th>安打</th><th>本塁打</th></tr>
<tr><td>阪神</td><td>.246</td><td>112</td><td>4224</td><td>3719</td><td>419</td>
<td>915</td><td>101</td></tr>
<tr><td>中　日</td><td>.240</td><td>116</td><td>4300</td><td>3800</td><td>390</td>
<td>900</td><td>80</td></tr></table>
"""

TEAM_PITCHING = """
<table><tr><th>チーム</th><th>防御率</th><th>試合</th><th>投球回</th><th>失点</th>
<th>自責点</th></tr>
<tr><td>阪神</td><td>2.90</td><td>112</td><td>994</td><td>353</td><td>320</td></tr>
<tr><td>巨人</td><td>2.94</td><td>114</td><td>1018.2</td><td>363</td><td>333</td></tr></table>
"""

PITCHERS = """
<table><tr><th>選手</th><th>登板</th><th>打者</th><th>投球回</th><th>四球</th>
<th>三振</th><th>失点</th></tr>
<tr><td>*床田 寛樹</td><td>18</td><td>430</td><td>108.1</td><td>20</td><td>90</td>
<td>44</td></tr>
<tr><td>森下 暢仁</td><td>17</td><td>410</td><td>100.2</td><td>25</td><td>95</td>
<td>47</td></tr>
<tr><td>清宮 虎多朗</td><td>1</td><td>3</td><td>+</td><td>1</td><td>0</td><td>2</td></tr>
</table>
"""

RESULTS = """
<a href="/scores/2026/0815/s-db-18/" class="link_box"><div class="unit">
<div class="team_left"><div class="team_name">ヤクルト</div></div>
<div class="score_text score_left">4</div>
<div class="round">18回戦<br>神　宮</div>
<div class="score_text score_right">3</div>
<div class="team_right"><div class="team_name">DeNA</div></div>
</div></a>
<a href="/scores/2026/0815/d-g-19/" class="link_box"><div class="unit">
<div class="score_text score_left">&nbsp;</div>
<div class="round">19回戦<br>バンテリンドーム</div>
<div class="score_text score_right">&nbsp;</div>
</div></a>
"""

SCHEDULE = """
<tr id="date0827" class="">
<th rowspan="5">8/27</th>
<td><div class="team1">ヤクルト</div><div class="score1">&nbsp;</div>
<div class="state">-</div><div class="score2">&nbsp;</div>
<div class="team2">巨人</div></td>
<td><div class="place">神　宮</div><div class="time">18:00</div>
<div class="weather"><img src="x.gif" alt="くもり時々雨"></div></td>
<td><div class="comment"></div></td>
<td><div class="pit">先発：山野</div><div class="pit">先発：井上</div></td>
</tr>
<tr id="date0826" class="open">
<td><div class="team1">中日</div><div class="score1">5</div>
<div class="state">-</div><div class="score2">2</div>
<div class="team2">阪神</div></td>
<td><div class="place">バンテリンドーム</div><div class="time">18:00</div></td>
<td><div class="comment"></div></td>
<td><div class="pit">先発：涌井</div><div class="pit">先発：伊藤将</div></td>
</tr>
"""


class NumberParsingTests(unittest.TestCase):
    def test_innings_thirds(self):
        self.assertAlmostEqual(_to_float("1018.2"), 1018 + 2 / 3, places=9)
        self.assertAlmostEqual(_to_float("108.1"), 108 + 1 / 3, places=9)

    def test_plus_marks_no_outs_recorded(self):
        self.assertEqual(_to_float("+"), 0.0)
        self.assertEqual(_to_int("+"), 0)

    def test_blank_and_dash_are_zero(self):
        for blank in ("", "-", "―", "  "):
            self.assertEqual(_to_float(blank), 0.0)
            self.assertEqual(_to_int(blank), 0)

    def test_plain_decimal_is_untouched(self):
        self.assertAlmostEqual(_to_float("2.90"), 2.90, places=9)


class StatsParserTests(unittest.TestCase):
    def test_team_batting(self):
        rows = list(_parse_team_batting(TEAM_BATTING))
        self.assertEqual(rows[0].team, "Hanshin Tigers")
        self.assertEqual(rows[0].runs_scored, 419)
        # A full-width space in the source name must still resolve.
        self.assertEqual(rows[1].team, "Chunichi Dragons")

    def test_team_pitching(self):
        rows = list(_parse_team_pitching(TEAM_PITCHING))
        self.assertEqual(rows[0].runs_allowed, 353)
        self.assertAlmostEqual(rows[1].innings_pitched, 1018 + 2 / 3, places=9)

    def test_pitchers_and_handedness(self):
        rows = list(_parse_pitchers(PITCHERS, "Hiroshima Carp"))
        self.assertEqual(rows[0].name, "床田 寛樹")
        self.assertEqual(rows[0].throws, "L")
        self.assertEqual(rows[1].throws, "R")
        self.assertAlmostEqual(rows[0].ra9, 44 / (108 + 1 / 3) * 9, places=9)

    def test_pitcher_with_no_outs_recorded_parses_as_zero_innings(self):
        rows = list(_parse_pitchers(PITCHERS, "Hokkaido Nippon-Ham Fighters"))
        self.assertEqual(rows[2].innings_pitched, 0.0)


class GameParserTests(unittest.TestCase):
    def test_daily_results_assign_home_and_away_correctly(self):
        games = list(_parse_daily_results(RESULTS, date(2026, 8, 15)))
        self.assertEqual(len(games), 1)
        game = games[0]
        self.assertEqual(game.home, "Tokyo Yakult Swallows")
        self.assertEqual(game.away, "Yokohama DeNA BayStars")
        self.assertEqual((game.away_score, game.home_score), (3, 4))
        self.assertEqual(game.venue, "神宮")

    def test_unplayed_game_is_skipped(self):
        self.assertEqual(len(list(_parse_daily_results(RESULTS, date(2026, 8, 15)))), 1)

    def test_schedule_reads_starters_and_status(self):
        games = {g.game_date: g for g in _parse_schedule(SCHEDULE, 2026, 8)}
        upcoming = games[date(2026, 8, 27)]
        self.assertEqual(upcoming.home, "Tokyo Yakult Swallows")
        self.assertEqual(upcoming.away, "Yomiuri Giants")
        self.assertEqual(upcoming.home_starter, "山野")
        self.assertEqual(upcoming.away_starter, "井上")
        self.assertEqual(upcoming.status, "scheduled")
        self.assertTrue(upcoming.starters_announced)
        self.assertEqual(upcoming.weather, "くもり時々雨")

    def test_completed_schedule_row_carries_score(self):
        games = {g.game_date: g for g in _parse_schedule(SCHEDULE, 2026, 8)}
        played = games[date(2026, 8, 26)]
        self.assertEqual(played.status, "final")
        self.assertEqual((played.away_score, played.home_score), (2, 5))

    def test_other_months_are_filtered_out(self):
        self.assertEqual(list(_parse_schedule(SCHEDULE, 2026, 7)), [])


if __name__ == "__main__":
    unittest.main()
