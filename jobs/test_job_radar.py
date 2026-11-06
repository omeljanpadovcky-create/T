import unittest

from bot import build_ukrainian_conclusion, score_job


class JobRadarFilterTests(unittest.TestCase):
    def job(self, title, description="", location="Remote · Worldwide"):
        return {
            "title": title,
            "company": "Example Studio",
            "location": location,
            "url": "https://example.com/jobs/123",
            "description": description,
            "tags": [],
            "source": "Test",
            "remote": True,
        }

    def test_3d_artist_is_accepted_even_when_english_is_c1(self):
        job = self.job("3D Artist", "Blender, game-ready assets. English C1 required.")
        score, _ = score_job(job)
        self.assertGreaterEqual(score, 50)
        conclusion = build_ukrainian_conclusion(job, score, "blender")
        self.assertIn("не причина автоматичного відсіву", conclusion)

    def test_senior_3d_artist_is_not_rejected_by_seniority(self):
        score, _ = score_job(self.job("Senior 3D Artist", "Blender and 3D modeling"))
        self.assertGreaterEqual(score, 50)

    def test_game_asset_role_is_accepted(self):
        score, _ = score_job(self.job("Junior Game Asset Artist", "Blender, low poly, UV mapping"))
        self.assertGreaterEqual(score, 50)

    def test_technical_artist_role_is_accepted(self):
        score, _ = score_job(self.job("Junior Technical Artist", "Blender and Unreal Engine"))
        self.assertGreaterEqual(score, 50)

    def test_ui_ux_role_is_outside_current_scope(self):
        score, reason = score_job(self.job("UI/UX Designer", "Figma and web design"))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Not a target role")

    def test_unpaid_role_is_rejected(self):
        score, reason = score_job(self.job("3D Artist", "Unpaid volunteer opportunity"))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Unpaid or volunteer role")


if __name__ == "__main__":
    unittest.main()
