import unittest

from unittest.mock import patch

from application_generator import generate_application
from bot import analyze_job_uk, application_review_keyboard, build_daily_report, build_ukrainian_conclusion, score_job, send_job_card


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

    def test_relevant_role_below_sixty_is_not_sent(self):
        score, reason = score_job(sample_job(
            title="3D Artist",
            description="A creative role with no matching skills listed.",
            tags=[]
        ))
        self.assertEqual(score, 0)
        self.assertIn("Below 80/100", reason)

    def test_analyzes_skills_english_and_application_email(self):
        analysis = analyze_job_uk(sample_job(
            description="Blender and Photoshop required. English B2. Send CV to jobs@example.com."
        ), {"skills": ["Blender", "Photoshop"], "english_level": "A2"})
        self.assertIn("Blender", analysis)
        self.assertIn("B2", analysis)
        self.assertIn("jobs@example.com", analysis)

    def test_accepts_explicit_b2_requirement(self):
        score, reason = score_job(sample_job(description="English level B2 required. Blender game assets."))
        self.assertGreater(score, 0, reason)

    def test_accepts_fluent_english_requirement(self):
        score, reason = score_job(sample_job(description="Fluent English and excellent written communication required. Blender game assets."))
        self.assertGreater(score, 0, reason)

    def test_accepts_senior_experience_requirements(self):
        score, reason = score_job(sample_job(
            title="Senior 3D Artist",
            description="Requires 7+ years of professional experience with Blender, 3D modeling and game-ready assets."
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


    def test_ukrainian_conclusion_mentions_a2_risk_for_b2_job(self):
        conclusion = build_ukrainian_conclusion(
            sample_job(description="English B2 required."),
            75,
            "Blender, 3D modeling"
        )
        self.assertIn("Висновок", "Висновок Мишки")
        self.assertIn("B2", conclusion)
        self.assertIn("A2", conclusion)
        self.assertIn("Збіг за навичками", conclusion)

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

    def test_vacancy_card_attaches_yes_no_review_keyboard(self):
        job = sample_job()
        sent = {"message_id": 77}
        with patch("bot.send_telegram", return_value=sent) as send:
            result = send_job_card(job, "abc123")
        self.assertEqual(result["message_id"], 77)
        self.assertEqual(send.call_count, 1)
        payload = send.call_args.args[0]
        keyboard = send.call_args.args[1]
        self.assertIn("Junior 3D Artist", payload)
        callbacks = [
            button.get("callback_data")
            for row in keyboard["inline_keyboard"]
            for button in row
        ]
        self.assertIn("confirm|abc123", callbacks)
        self.assertIn("skip|abc123", callbacks)


    def test_extracts_dou_and_djinni_public_vacancy_links(self):
        from bot import VacancyLinkParser
        dou = VacancyLinkParser("DOU")
        dou.feed('<a class="vt" href="/vacancies/12345/">Junior UI/UX Designer</a>')
        self.assertEqual(dou.links[0]["title"], "Junior UI/UX Designer")
        djinni = VacancyLinkParser("Djinni")
        djinni.feed('<a href="/jobs/123456-shopify-assistant/">Shopify Assistant</a>')
        self.assertEqual(djinni.links[0]["title"], "Shopify Assistant")

    def test_extracts_workua_public_vacancy_links(self):
        from bot import VacancyLinkParser
        parser = VacancyLinkParser("Work.ua")
        parser.feed('<a href="/jobs/123456/">Junior Graphic Designer</a>')
        self.assertEqual(parser.links[0]["url"], "/jobs/123456/")

    def test_extracts_robotaua_public_vacancy_links(self):
        from bot import VacancyLinkParser
        parser = VacancyLinkParser("Robota.ua")
        parser.feed('<a href="/company123/vacancy456/">3D Artist</a>')
        self.assertEqual(parser.links[0]["title"], "3D Artist")

    def test_extracts_ziprecruiter_public_vacancy_links(self):
        from bot import VacancyLinkParser
        parser = VacancyLinkParser("ZipRecruiter")
        parser.feed('<a href="/jobs/junior-3d-artist">Junior 3D Artist</a>')
        parser.feed('<a href="/c/example-studio/Jobs/3d-artist/-in-Remote">3D Artist</a>')
        self.assertEqual(len(parser.links), 2)
        self.assertEqual(parser.links[0]["title"], "Junior 3D Artist")

    def test_ziprecruiter_collector_searches_remote_and_marks_source(self):
        from bot import collect_ziprecruiter_jobs
        listing = '<a href="/jobs/junior-3d-artist">Junior 3D Artist</a>'
        details = {
            "title": "Junior 3D Artist",
            "company": "Studio",
            "location": "Remote — verify country restrictions",
            "url": "https://www.ziprecruiter.com/jobs/junior-3d-artist",
            "description": "Blender game assets",
            "tags": [],
            "source": "ZipRecruiter",
            "remote": True
        }
        with patch("bot.fetch_html", return_value=listing) as fetch, patch(
            "bot.extract_job_details", return_value=details
        ):
            jobs = collect_ziprecruiter_jobs()
        self.assertTrue(jobs)
        self.assertEqual(jobs[0]["source"], "ZipRecruiter")
        self.assertTrue(jobs[0]["remote"])
        self.assertIn("location=Remote", fetch.call_args_list[0].args[0])


if __name__ == "__main__":
    unittest.main()


class TelegramDeliveryTests(unittest.TestCase):
    def test_retries_telegram_429_using_retry_after(self):
        from bot import send_telegram
        limited = type("Response", (), {
            "ok": False, "status_code": 429,
            "json": lambda self: {"ok": False, "description": "Too Many Requests",
                                  "parameters": {"retry_after": 3}}
        })()
        success = type("Response", (), {
            "ok": True, "status_code": 200,
            "json": lambda self: {"ok": True, "result": {"message_id": 123}}
        })()
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}), \
             patch("bot.requests.post", side_effect=[limited, success]) as post, \
             patch("bot.time.sleep") as sleep, \
             patch("bot.time.monotonic", side_effect=[10.0, 11.0, 15.0, 16.0]):
            result = send_telegram("test")
        self.assertEqual(result["message_id"], 123)
        self.assertEqual(post.call_count, 2)
        sleep.assert_any_call(4)

    def test_does_not_retry_non_rate_limit_errors(self):
        from bot import send_telegram
        failed = type("Response", (), {
            "ok": False, "status_code": 400,
            "json": lambda self: {"ok": False, "description": "Bad Request"}
        })()
        with patch.dict("os.environ", {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_CHAT_ID": "chat"}), \
             patch("bot.requests.post", return_value=failed) as post, \
             patch("bot.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "HTTP 400"):
                send_telegram("test")
        self.assertEqual(post.call_count, 1)
