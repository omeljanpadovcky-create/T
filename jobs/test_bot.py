import unittest

from unittest.mock import patch

from application_generator import generate_application
from bot import application_review_keyboard, build_daily_report, score_job, send_application_package


def sample_job(**overrides):
    job = {
        "title": "Junior 3D Artist",
        "company": "Studio",
        "location": "Remote — Worldwide",
        "url": "https://example.com/jobs/junior-3d-artist",
        "description": "Create Blender game assets. English A2/B1 is acceptable.",
        "tags": ["Blender", "3D modeling"],
        "source": "Test",
        "remote": True,
    }
    job.update(overrides)
    return job


class JobFilterTests(unittest.TestCase):
    def test_accepts_remote_role_with_a2_english(self):
        score, reason = score_job(sample_job())
        self.assertGreater(score, 0, reason)

    def test_accepts_explicit_b2_requirement(self):
        score, reason = score_job(sample_job(description="English level B2 required."))
        self.assertGreater(score, 0, reason)

    def test_accepts_fluent_english_requirement(self):
        score, reason = score_job(sample_job(description="Fluent English and excellent written communication required."))
        self.assertGreater(score, 0, reason)

    def test_accepts_senior_experience_requirements(self):
        score, reason = score_job(sample_job(
            title="Senior 3D Artist",
            description="Requires 7+ years of professional experience with Blender."
        ))
        self.assertGreater(score, 0, reason)

    def test_application_draft_mentions_it_step_internship_truthfully(self):
        package = generate_application(sample_job(), {
            "name": "Test Candidate",
            "skills": ["Blender"],
            "internship_experience": [{
                "organization": "IT Step",
                "duration": "two-year",
                "type": "internship"
            }]
        })
        self.assertIn("two-year internship at IT Step", package["cover_letter"])

    def test_rejects_us_only_even_when_source_says_remote(self):
        score, reason = score_job(sample_job(
            location="Remote",
            description="Remote role. Candidates must be located in the United States."
        ))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Outside target geography")

    def test_rejects_unpaid_roles(self):
        score, reason = score_job(sample_job(description="Unpaid volunteer position."))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Unpaid or volunteer role")


    def test_daily_report_includes_counts_and_source_health(self):
        report = build_daily_report(
            scanned=120,
            eligible=8,
            new_matches=4,
            sent=4,
            source_health=[
                {"host": "remotive.com", "ok": True},
                {"host": "remotive.com", "ok": False, "source": "remotive.com · blender"},
                {"host": "remoteok.com", "ok": True},
            ],
            rejection_counts={"Not a target role": 70}
        )
        self.assertIn("Перевірено вакансій: <b>120</b>", report)
        self.assertIn("Підійшли фільтрам: <b>8</b>", report)
        self.assertIn("remotive.com: 1/2", report)
        self.assertIn("Не відповіли", report)
        self.assertIn("Not a target role", report)

    def test_daily_report_warns_when_every_source_is_down(self):
        report = build_daily_report(
            scanned=0, eligible=0, new_matches=0, sent=0,
            source_health=[{"host": "remoteok.com", "ok": False}],
            rejection_counts={}
        )
        self.assertIn("не вдалося отримати дані з жодного джерела", report)


    def test_new_vacancy_review_keyboard_requires_explicit_package_approval(self):
        keyboard = application_review_keyboard(
            "abc123",
            {"url": "https://example.com/job"}
        )
        callbacks = [
            button.get("callback_data")
            for row in keyboard["inline_keyboard"]
            for button in row
        ]
        self.assertIn("confirm|abc123", callbacks)
        self.assertNotIn("approve|abc123", callbacks)
        self.assertIn("skip|abc123", callbacks)
        self.assertNotIn("applied|abc123", callbacks)

    def test_automatic_package_sender_attaches_review_keyboard(self):
        job = sample_job()
        package = generate_application(job, {
            "name": "Test Candidate",
            "skills": ["Blender"],
            "portfolio_url": "https://portfolio.example"
        })
        sent = {"message_id": 77}
        with patch("bot.send_telegram", return_value=sent) as send:
            result = send_application_package(job, package, "abc123")
        self.assertEqual(result["message_id"], 77)
        self.assertEqual(send.call_count, 1)
        payload = send.call_args.args[0]
        keyboard = send.call_args.args[1]
        self.assertIn("COVER LETTER", payload)
        self.assertIn("confirm|abc123", [
            button.get("callback_data")
            for row in keyboard["inline_keyboard"]
            for button in row
        ])


if __name__ == "__main__":
    unittest.main()
