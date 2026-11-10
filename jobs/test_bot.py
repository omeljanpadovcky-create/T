import unittest
from unittest.mock import patch

from bot import (
    VacancyLinkParser,
    job_identity_keys,
    normalize_job_url,
    score_job,
    send_job_card,
    is_delivery_qualified,
    summarize_vacancy_description,
    vacancy_salary,
)


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



class VacancyDeduplicationTests(unittest.TestCase):
    def test_normalizes_tracking_parameters_and_trailing_slash(self):
        self.assertEqual(
            normalize_job_url("https://www.example.com/jobs/123/?utm_source=linkedin#apply"),
            "https://example.com/jobs/123"
        )

    def test_same_title_and_company_deduplicates_across_different_urls(self):
        first = sample_job(url="https://site-a.com/job/1")
        second = sample_job(url="https://site-b.com/jobs/999")
        self.assertTrue(job_identity_keys(first) & job_identity_keys(second))

    def test_different_company_is_not_collapsed_by_title_company_key(self):
        first = sample_job(company="Studio A")
        second = sample_job(company="Studio B")
        first_keys = job_identity_keys(first)
        second_keys = job_identity_keys(second)
        self.assertNotIn(
            next(k for k in first_keys if k not in {
                __import__("hashlib").sha256(first["url"].encode("utf-8")).hexdigest(),
                __import__("hashlib").sha256(("url:" + normalize_job_url(first["url"])).encode("utf-8")).hexdigest()
            }),
            second_keys
        )

class JobFilterTests(unittest.TestCase):
    def test_accepts_remote_role_with_a2_english(self):
        score, reason = score_job(sample_job())
        self.assertGreaterEqual(score, 80, reason)

    def test_english_requirement_does_not_exclude_role(self):
        score, reason = score_job(sample_job(
            description="Fluent English required. Create Blender game assets."
        ))
        self.assertGreaterEqual(score, 80, reason)

    def test_accepts_senior_experience_requirements(self):
        score, reason = score_job(sample_job(
            title="Senior 3D Artist",
            description="Requires 7+ years of professional experience with Blender, 3D modeling and game-ready assets."
        ))
        self.assertGreaterEqual(score, 80, reason)

    def test_keeps_us_only_lead_for_manual_review(self):
        score, reason = score_job(sample_job(
            location="Remote",
            description="Remote role. Candidates must be located in the United States."
        ))
        self.assertGreater(score, 0)
        self.assertIn("verify manually", reason)

    def test_rejects_generic_graphic_designer_without_target_art_evidence(self):
        score, reason = score_job(sample_job(
            title="Graphic Designer",
            description="Create social media banners and marketing layouts in Photoshop."
        ))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "Excluded role")

    def test_keeps_unpaid_roles_with_warning_for_manual_review(self):
        score, reason = score_job(sample_job(description="Unpaid volunteer position."))
        self.assertGreater(score, 0)
        self.assertIn("unpaid/volunteer", reason)

    def test_keeps_lower_scoring_target_role_with_relevance_warning(self):
        score, reason = score_job(sample_job(
            title="3D Artist",
            location="Unknown",
            description="Simple 3D work."
        ))
        self.assertGreater(score, 0)
        self.assertLess(score, 80)
        self.assertIn("lower relevance", reason)


    def test_delivery_threshold_is_strictly_above_80(self):
        self.assertFalse(is_delivery_qualified(80))
        self.assertFalse(is_delivery_qualified(79))
        self.assertTrue(is_delivery_qualified(81))


class VacancyCardTests(unittest.TestCase):
    def test_card_sends_simple_vacancy_alert_without_buttons(self):
        job = {
            "id": "abc123", "title": "Junior 3D Artist", "company": "Example Studio",
            "location": "Remote · Worldwide", "url": "https://example.com/jobs/junior-3d-artist",
            "description": "Blender and game-ready assets", "source": "Test", "score": 90,
            "reason": "3D Artist"
        }
        with patch("bot.summarize_vacancy_description", return_value="Summary"), patch(
            "bot.send_telegram"
        ) as send:
            result = send_job_card(job, "abc123")
        self.assertEqual(result, send.return_value)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(len(send.call_args.args), 1)
        self.assertIn("Junior 3D Artist", send.call_args.args[0])
        self.assertIn("Відкрити вакансію", send.call_args.args[0])
        self.assertNotIn("reply_markup", send.call_args.kwargs)

    def test_salary_uses_only_advertised_value(self):
        self.assertEqual(vacancy_salary(sample_job()), "Не вказано")
        self.assertIn("$1200", vacancy_salary(sample_job(salary="$1200/month")))


class DescriptionSummaryTests(unittest.TestCase):
    def test_local_fallback_returns_two_sentences(self):
        description = (
            "The artist creates game-ready Blender assets. "
            "The role requires experience with UV mapping and texturing. "
            "The job is fully remote and paid monthly."
        )
        with patch.dict("os.environ", {"APINEX_API_KEY": ""}):
            summary = summarize_vacancy_description(description)
        self.assertGreaterEqual(summary.count("."), 2)
        self.assertIn("Blender", summary)


class VacancyParserTests(unittest.TestCase):
    def test_extracts_dou_public_vacancy_links(self):
        parser = VacancyLinkParser("DOU")
        parser.feed('<a class="vt" href="/vacancies/12345/">Junior 3D Artist</a>')
        self.assertEqual(parser.links[0]["title"], "Junior 3D Artist")

    def test_extracts_djinni_public_vacancy_links(self):
        parser = VacancyLinkParser("Djinni")
        parser.feed('<a href="/jobs/123456-3d-artist/">3D Artist</a>')
        self.assertEqual(parser.links[0]["title"], "3D Artist")

    def test_extracts_workua_public_vacancy_links(self):
        parser = VacancyLinkParser("Work.ua")
        parser.feed('<a href="/jobs/123456/">Junior 3D Artist</a>')
        self.assertEqual(parser.links[0]["url"], "/jobs/123456/")

    def test_extracts_robotaua_public_vacancy_links(self):
        parser = VacancyLinkParser("Robota.ua")
        parser.feed('<a href="/company123/vacancy456/">3D Artist</a>')
        self.assertEqual(parser.links[0]["title"], "3D Artist")

    def test_extracts_linkedin_public_vacancy_links(self):
        parser = VacancyLinkParser("LinkedIn")
        parser.feed('<a href="/jobs/view/123456/">3D Artist</a>')
        self.assertEqual(parser.links[0]["title"], "3D Artist")


if __name__ == "__main__":
    unittest.main()
