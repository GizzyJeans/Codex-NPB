"""The daily results page lags; settlement must not read that as 'no games'."""

import unittest
from datetime import date
from unittest.mock import patch

from codex_npb.sources.npb_official import NPBOfficialClient, ScheduledGame

SCHEDULED_PAGE = "<html><title>2026年8月28日 公式戦【試合予定】</title></html>"
RESULT_PAGE = """
<a href="/scores/2026/0815/s-db-18/" class="link_box"><div class="unit">
<div class="team_left"><div class="team_name">ヤクルト</div></div>
<div class="score_text score_left">4</div>
<div class="round">18回戦<br>神　宮</div>
<div class="score_text score_right">3</div>
<div class="team_right"><div class="team_name">DeNA</div></div>
</div></a>
"""


def scheduled(day, away, home, away_score, home_score, status="final"):
    return ScheduledGame(
        game_date=day,
        away=away,
        home=home,
        venue="甲子園",
        start_time="18:00",
        status=status,
        away_score=away_score,
        home_score=home_score,
    )


class ResultFallbackTests(unittest.TestCase):
    def client(self):
        return NPBOfficialClient(2026, delay_seconds=0.0)

    def test_daily_page_is_used_when_it_carries_scores(self):
        client = self.client()
        with patch.object(client, "fetch", return_value=RESULT_PAGE), patch.object(
            client, "schedule_for_month"
        ) as schedule:
            results = client.results_for(date(2026, 8, 15))
        self.assertEqual(len(results), 1)
        schedule.assert_not_called()

    def test_monthly_schedule_fills_in_when_the_daily_page_lags(self):
        client = self.client()
        rows = [
            scheduled(date(2026, 8, 28), "Yomiuri Giants", "Hanshin Tigers", 1, 4),
            scheduled(date(2026, 8, 27), "Hanshin Tigers", "Chunichi Dragons", 4, 3),
        ]
        with patch.object(client, "fetch", return_value=SCHEDULED_PAGE), patch.object(
            client, "schedule_for_month", return_value=rows
        ):
            results = client.results_for(date(2026, 8, 28))
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].away, "Yomiuri Giants")
        self.assertEqual((results[0].away_score, results[0].home_score), (1, 4))

    def test_games_not_yet_played_are_not_invented(self):
        client = self.client()
        rows = [
            scheduled(date(2026, 8, 29), "Yomiuri Giants", "Hanshin Tigers", None, None,
                      status="scheduled")
        ]
        with patch.object(client, "fetch", return_value=SCHEDULED_PAGE), patch.object(
            client, "schedule_for_month", return_value=rows
        ):
            self.assertEqual(client.results_for(date(2026, 8, 29)), [])

    def test_other_dates_in_the_month_are_not_pulled_in(self):
        client = self.client()
        rows = [scheduled(date(2026, 8, 27), "A", "B", 1, 2)]
        with patch.object(client, "fetch", return_value=SCHEDULED_PAGE), patch.object(
            client, "schedule_for_month", return_value=rows
        ):
            self.assertEqual(client.results_for(date(2026, 8, 28)), [])


if __name__ == "__main__":
    unittest.main()
