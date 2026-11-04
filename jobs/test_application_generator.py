import unittest

from application_generator import generate_application, render_application_text, clean


class ApplicationGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "name": "Test Candidate",
            "location": "Ukraine",
            "english_level": "A2",
            "design_practice_years": "5",
            "portfolio_items_approx": 15,
            "portfolio_url": "",
            "cv_url": "",
            "contact_email": "",
            "salary_expectation": "",
            "skills": ["Blender", "Photoshop", "Figma", "Illustrator"]
        }
        self.job = {
            "title": "Junior 3D Artist",
            "company": "Example Studio",
            "location": "Remote",
            "url": "https://example.com/jobs/3d-artist",
            "source": "Test",
            "salary": "$15–20/hour",
            "description": "We need Blender and Photoshop. Send your CV to jobs@example.com."
        }

    def test_clean_removes_html_and_collapses_whitespace(self):
        self.assertEqual(clean("<p>Hello&nbsp; world</p>"), "Hello world")

    def test_package_is_personalized_and_does_not_invent_portfolio_url(self):
        package = generate_application(self.job, self.profile)
        self.assertIn("Junior 3D Artist", package["cover_letter"])
        self.assertIn("Blender", package["cover_letter"])
        self.assertIn("Test Candidate", package["short_intro"])
        self.assertEqual(package["portfolio"]["url"], "")
        self.assertTrue(package["checks"]["portfolio_url_missing"])
        self.assertIn("[ADD YOUR PORTFOLIO LINK", package["cover_letter"])

    def test_role_specific_portfolio_is_selected_for_matching_vacancy(self):
        profile = dict(self.profile)
        profile["portfolio_3d_url"] = "https://portfolio.example/3d"
        package = generate_application(self.job, profile)
        self.assertEqual(package["portfolio"]["links"][0]["url"], "https://portfolio.example/3d")
        self.assertFalse(package["checks"]["portfolio_url_missing"])
        self.assertIn("https://portfolio.example/3d", package["cover_letter"])

    def test_email_is_extracted_only_from_job_description(self):
        package = generate_application(self.job, self.profile)
        self.assertEqual(package["email"]["to"], "jobs@example.com")

    def test_unknown_salary_does_not_get_fabricated(self):
        job = dict(self.job)
        job["salary"] = ""
        package = generate_application(job, self.profile)
        self.assertIn("share the budgeted range", package["answers"]["salary_expectation"])

    def test_generator_never_submits_application(self):
        package = generate_application(self.job, self.profile)
        self.assertTrue(package["submission"]["requires_user_review"])
        self.assertFalse(package["submission"]["will_submit_automatically"])

    def test_rendered_package_contains_submission_destination_and_fields(self):
        package = generate_application(self.job, self.profile)
        text = render_application_text(package)
        self.assertIn("COVER LETTER", text)
        self.assertIn("jobs@example.com", text)
        self.assertIn("https://example.com/jobs/3d-artist", text)
        self.assertIn("ВІДПРАВЛЕНА ЗАЯВКА", text.upper())


    def test_role_specific_game_portfolio_is_selected(self):
        profile = dict(self.profile)
        profile["portfolio_game_art_url"] = "https://portfolio.example/game"
        job = dict(self.job)
        job["title"] = "Game Artist"
        job["description"] = "Create game art assets for Unity."
        package = generate_application(job, profile)
        self.assertIn(
            {"label": "Game Art", "url": "https://portfolio.example/game"},
            package["portfolio"]["links"]
        )

    def test_cv_missing_is_reported_without_inventing_a_link(self):
        package = generate_application(self.job, self.profile)
        self.assertTrue(package["checks"]["cv_url_missing"])
        self.assertEqual(package["portfolio"]["cv_url"], "")
        self.assertIn("No CV link configured", package["portfolio"]["cv_status"])


if __name__ == "__main__":
    unittest.main()
