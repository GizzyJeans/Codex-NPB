import unittest
from dataclasses import dataclass

from codex_npb.roster import match_starter


@dataclass(frozen=True)
class FakeLine:
    name: str
    team: str = "Hanshin Tigers"
    innings_pitched: float = 100.0
    runs_allowed: int = 40


ROSTER = [
    FakeLine("伊藤 将司"),
    FakeLine("伊藤 稜"),
    FakeLine("村上 頌樹"),
    FakeLine("東 克樹"),
    FakeLine("ロング"),
    FakeLine("新人 投手", innings_pitched=0.0, runs_allowed=0),
]


class MatchStarterTests(unittest.TestCase):
    def test_unique_surname_resolves(self):
        match = match_starter("村上", ROSTER)
        self.assertTrue(match.resolved)
        self.assertEqual(match.starter.name, "村上 頌樹")

    def test_shared_surname_is_ambiguous_not_guessed(self):
        match = match_starter("伊藤", ROSTER)
        self.assertFalse(match.resolved)
        self.assertTrue(match.ambiguous)
        self.assertEqual(set(match.candidates), {"伊藤 将司", "伊藤 稜"})

    def test_disambiguating_given_name_resolves(self):
        match = match_starter("伊藤将", ROSTER)
        self.assertTrue(match.resolved)
        self.assertEqual(match.starter.name, "伊藤 将司")

    def test_single_character_surname_resolves(self):
        self.assertEqual(match_starter("東", ROSTER).starter.name, "東 克樹")

    def test_katakana_name_resolves(self):
        self.assertEqual(match_starter("ロング", ROSTER).starter.name, "ロング")

    def test_pitcher_without_innings_is_not_resolved(self):
        match = match_starter("新人", ROSTER)
        self.assertFalse(match.resolved)
        self.assertIn("新人 投手", match.candidates)

    def test_unknown_name_reports_no_entry(self):
        match = match_starter("該当なし", ROSTER)
        self.assertFalse(match.resolved)
        self.assertFalse(match.ambiguous)
        self.assertIn("no roster entry", match.reason)

    def test_blank_announcement_is_unresolved(self):
        self.assertFalse(match_starter("", ROSTER).resolved)


if __name__ == "__main__":
    unittest.main()
