"""The homepage strip is the freshest source and the easiest to misread."""

import unittest
from datetime import date

from codex_npb.sources.npb_official import _parse_live_scoreboard

PAGE = """
<div id="header_score"><div class="score_wrap">
<div class="score_box date"><div>2026<br>8/29 Sat.</div></div>
<div class="score_box"><a href="/scores/2026/0829/l-e-21/"><div>
  <img alt="埼玉西武ライオンズ" class="logo_left">
  <img alt="東北楽天ゴールデンイーグルス" class="logo_right">
  <div class="score">1-0</div>
  <div class="state">（ベルーナ）　試合終了</div>
</div></a></div>
<div class="score_box"><a href="/scores/2026/0829/t-g-22/"><div>
  <img alt="阪神タイガース" class="logo_left">
  <img alt="読売ジャイアンツ" class="logo_right">
  <div class="score">4-1</div>
  <div class="state">（甲子園）　試合終了</div>
</div></a></div>
<div class="score_box"><a href="/scores/2026/0829/c-s-20/"><div>
  <img alt="広島東洋カープ" class="logo_left">
  <img alt="東京ヤクルトスワローズ" class="logo_right">
  <div class="score">3-2</div>
  <div class="state">（マツダ）　7回表</div>
</div></a></div>
<div class="score_box"><a href="/scores/2026/0829/db-d-22/"><div>
  <img alt="横浜DeNAベイスターズ" class="logo_left">
  <img alt="中日ドラゴンズ" class="logo_right">
  <div class="score">-</div>
  <div class="state">（横浜）18:00</div>
</div></a></div>
</div></div>
"""


class LiveScoreboardTests(unittest.TestCase):
    def parse(self, day=date(2026, 8, 29), page=PAGE):
        return list(_parse_live_scoreboard(page, day))

    def test_score_reads_home_then_away(self):
        # Slug is {home}-{away}; the linescore for this game was Rakuten 0,
        # Seibu 1, so "1-0" must resolve to the home club scoring one.
        game = next(g for g in self.parse() if g.home == "Saitama Seibu Lions")
        self.assertEqual(game.away, "Tohoku Rakuten Golden Eagles")
        self.assertEqual((game.away_score, game.home_score), (0, 1))

    def test_only_finished_games_are_returned(self):
        homes = {g.home for g in self.parse()}
        self.assertIn("Saitama Seibu Lions", homes)
        self.assertIn("Hanshin Tigers", homes)
        # Seventh inning, and not started at all.
        self.assertNotIn("Hiroshima Carp", homes)
        self.assertNotIn("Yokohama DeNA BayStars", homes)

    def test_a_different_date_returns_nothing(self):
        # The strip only ever shows one date; using it for another would
        # attach today's scores to yesterday's board.
        self.assertEqual(self.parse(day=date(2026, 8, 28)), [])

    def test_venue_is_taken_from_the_state_cell(self):
        game = next(g for g in self.parse() if g.home == "Hanshin Tigers")
        self.assertEqual(game.venue, "甲子園")

    def test_missing_date_header_yields_nothing(self):
        self.assertEqual(list(_parse_live_scoreboard("<div>no strip</div>", date(2026, 8, 29))), [])

    def test_all_finished_games_are_returned(self):
        self.assertEqual(len(self.parse()), 2)


if __name__ == "__main__":
    unittest.main()
