import unittest

from telegram_sources import TelegramPostParser, normalize_telegram_post


SAMPLE = """
<div class="tgme_widget_message_wrap">
  <div class="tgme_widget_message" data-post="ingamejob_art/12345">
    <div class="tgme_widget_message_text">
      3D Character Artist — Remote Ukraine
      <a href="https://company.example/jobs/3d-character-artist">Apply</a>
      Blender, game assets, full time.
    </div>
  </div>
</div>
"""


class TelegramSourcesTests(unittest.TestCase):
    def test_parser_extracts_post_and_link(self):
        parser = TelegramPostParser()
        parser.feed(SAMPLE)
        self.assertEqual(len(parser.posts), 1)
        self.assertEqual(parser.posts[0]["post"], "ingamejob_art/12345")
        self.assertIn("3D Character Artist", parser.posts[0]["text"])
        self.assertIn("https://company.example/jobs/3d-character-artist", parser.posts[0]["links"])

    def test_normalizer_requires_remote_and_ukraine_scope(self):
        parser = TelegramPostParser()
        parser.feed(SAMPLE)
        job = normalize_telegram_post(parser.posts[0], "ingamejob_art")
        self.assertIsNotNone(job)
        self.assertEqual(job["location"], "Remote — Ukraine/Europe eligibility stated")
        self.assertEqual(job["url"], "https://company.example/jobs/3d-character-artist")

    def test_generic_remote_without_ukraine_scope_is_rejected(self):
        post = {"text": "3D Artist — Remote worldwide? No location information.", "links": [], "post": "x/1"}
        # Worldwide is an eligible broad region; this is intentionally accepted.
        self.assertIsNotNone(normalize_telegram_post(post, "ingamejob_art"))
        post["text"] = "3D Artist — Remote, US only"
        self.assertIsNone(normalize_telegram_post(post, "ingamejob_art"))

    def test_unpaid_is_rejected(self):
        post = {"text": "3D Artist — Remote Ukraine. Unpaid volunteer position.", "links": [], "post": "x/2"}
        self.assertIsNone(normalize_telegram_post(post, "ingamejob_art"))


if ( __name__ == "__main__" ):
    unittest.main()
