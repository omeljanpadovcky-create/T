import unittest

from bot import (\n    build_ukrainian_conclusion, score_job, collect_jobicy_jobs, collect_working_nomads_jobs\n)


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
        self.assertGreaterEqual(score, 60)
        conclusion = build_ukrainian_conclusion(job, score, "blender")
        self.assertIn("не причина автоматичного відсіву", conclusion)

    def test_senior_3d_artist_is_not_rejected_by_seniority(self):
        score, _ = score_job(self.job("Senior 3D Artist", "Blender and 3D modeling"))
        self.assertGreaterEqual(score, 60)

    def test_game_asset_role_is_accepted(self):
        score, _ = score_job(self.job("Junior Game Asset Artist", "Blender, low poly, UV mapping"))
        self.assertGreaterEqual(score, 60)

    def test_technical_artist_role_is_accepted(self):
        score, _ = score_job(self.job("Junior Technical Artist", "Blender and Unreal Engine"))
        self.assertGreaterEqual(score, 60)

    def test_photobashing_artist_is_accepted(self):
        score, _ = score_job(self.job(
            "Photobashing Artist", "Photoshop, photobashing and digital painting"
        ))
        self.assertGreaterEqual(score, 60)

    def test_country_specific_remote_location_is_rejected(self):
        score, reason = score_job(self.job(
            "3D Artist", "Blender and game-ready assets", location="Germany"
        ))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Country-specific location; Ukraine eligibility not confirmed")

    def test_country_specific_requirement_in_description_is_rejected(self):
        score, reason = score_job(self.job(
            "3D Artist",
            "Blender. Candidates must be based in Germany.",
            location="Remote · Worldwide"
        ))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Outside target geography")

    def test_minimum_score_is_sixty(self):
        from bot import CONFIG
        self.assertEqual(CONFIG.get("minimum_score"), 60)

    def test_ui_ux_role_is_outside_current_scope(self):
        score, reason = score_job(self.job("UI/UX Designer", "Figma and web design"))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Not a target role")


    def test_jobicy_public_api_records_are_normalized(self):
        from unittest.mock import patch
        payload = {"jobs": [{
            "title": "3D Artist",
            "companyName": "Example Studio",
            "jobGeo": "Anywhere",
            "jobDescription": "Blender and game assets",
            "url": "https://jobicy.com/jobs/123",
            "pubDate": "2026-11-08"
        }]}
        with patch("bot.fetch_json", return_value=payload):
            jobs = collect_jobicy_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "Jobicy")
        self.assertEqual(jobs[0]["company"], "Example Studio")
        self.assertTrue(jobs[0]["remote"])
        self.assertEqual(jobs[0]["url"], "https://jobicy.com/jobs/123")

    def test_working_nomads_public_feed_records_are_normalized(self):
        from unittest.mock import patch
        payload = [{
            "title": "Illustrator",
            "company_name": "Creative Studio",
            "location": "Europe",
            "url": "https://workingnomads.com/jobs/123",
            "description": "Illustration and Photoshop"
        }]
        with patch("bot.fetch_json", return_value=payload):
            jobs = collect_working_nomads_jobs()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["source"], "Working Nomads")
        self.assertEqual(jobs[0]["location"], "Europe")
        self.assertTrue(jobs[0]["remote"])

    def test_unpaid_role_is_rejected(self):
        score, reason = score_job(self.job("3D Artist", "Unpaid volunteer opportunity"))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Unpaid or volunteer role")


if __name__ == "__main__":
    unittest.main()
