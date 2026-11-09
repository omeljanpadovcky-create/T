import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent


class PlatformRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = json.loads((ROOT / "platforms.json").read_text(encoding="utf-8"))

    def test_candidate_confirmed_platform_accounts_are_recorded(self):
        self.assertEqual(
            set(self.registry["candidate_confirmed_accounts"]),
            {"LinkedIn", "ArtStation", "Djinni", "Upwork", "Fiverr", "Work.ua", "Robota.ua"}
        )

    def test_minimum_score_remains_sixty(self):
        config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["minimum_score"], 60)
        self.assertEqual(self.registry["minimum_vacancy_score"], 60)

    def test_only_existing_public_collectors_are_marked_implemented(self):
        platforms = {item["name"]: item for item in self.registry["platforms"]}
        for name in ("ArtStation", "Djinni", "Work.ua", "Robota.ua"):
            self.assertTrue(platforms[name]["collector_implemented"])
            self.assertEqual(platforms[name]["authentication"], "not_connected")
        for name in ("LinkedIn", "Upwork", "Fiverr"):
            self.assertFalse(platforms[name]["collector_implemented"])
            self.assertEqual(platforms[name]["authentication"], "not_connected")

    def test_application_submission_requires_user_confirmation(self):
        policy = self.registry["application_policy"]
        self.assertTrue(policy["generate_drafts"])
        self.assertFalse(policy["submit_without_user_confirmation"])
        self.assertTrue(policy["minimum_score_enforced"])

    def test_unverified_cv_url_is_not_committed_to_profile(self):
        profile = json.loads((ROOT / "profile.json").read_text(encoding="utf-8"))
        self.assertNotIn("cv_url", profile)


if __name__ == "__main__":
    unittest.main()
