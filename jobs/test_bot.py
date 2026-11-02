import unittest

from bot import score_job


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

    def test_rejects_explicit_b2_requirement(self):
        score, reason = score_job(sample_job(description="English level B2 required."))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "English requirement above A2/B1")

    def test_rejects_strong_written_and_spoken_english(self):
        score, reason = score_job(sample_job(description="Strong written and spoken English required."))
        self.assertEqual(score, 0)
        self.assertEqual(reason, "English requirement above A2/B1")

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


if __name__ == "__main__":
    unittest.main()
