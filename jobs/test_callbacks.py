import unittest

from unittest.mock import patch

from callbacks import handle_callback


class CallbackStateTransitionTests(unittest.TestCase):
    def setUp(self):
        self.allowed_chat = "12345"
        self.applications = {"abc123": {"id": "abc123", "title": "Junior 3D Artist"}}
        self.editing = {}

    def callback(self, action, status):
        statuses = {"abc123": {"status": status}}
        update = {
            "callback_query": {
                "id": None,
                "data": f"{action}|abc123",
                "message": {"chat": {"id": 12345}, "message_id": 10}
            }
        }
        with patch("callbacks.api") as api:
            result = handle_callback(update, self.applications, statuses,
                                     self.allowed_chat, self.editing)
        return result, statuses, api

    def test_confirm_selects_job_and_offers_application_preparation(self):
        self.applications["abc123"]["url"] = "https://example.com/job"
        result, statuses, api = self.callback("confirm", "new")
        self.assertTrue(result)
        self.assertEqual(statuses["abc123"]["status"], "selected")
        api.assert_called_once()
        args, kwargs = api.call_args
        self.assertEqual(args[0], "editMessageText")
        keyboard = args[1]["reply_markup"]["inline_keyboard"]
        self.assertTrue(any(
            button.get("callback_data") == "prepare|abc123"
            for row in keyboard for button in row
        ))

    def test_prepare_generates_package_and_adds_approval_controls(self):
        self.applications["abc123"].update({
            "url": "https://example.com/job",
            "company": "Example Studio",
            "location": "Remote",
            "description": "Figma UI/UX design"
        })
        result, statuses, api = self.callback("prepare", "selected")
        self.assertTrue(result)
        self.assertEqual(statuses["abc123"]["status"], "awaiting_approval")
        self.assertEqual(statuses["abc123"]["package_revision"], 1)
        methods = [call.args[0] for call in api.call_args_list]
        self.assertEqual(methods, ["sendMessage"])
        final_payload = api.call_args_list[-1].args[1]
        keyboard = final_payload["reply_markup"]["inline_keyboard"]
        callback_values = {
            button.get("callback_data")
            for row in keyboard for button in row
        }
        self.assertIn("approve|abc123", callback_values)
        self.assertIn("edit|abc123", callback_values)

    def test_failed_package_delivery_keeps_vacancy_retryable(self):
        self.applications["abc123"].update({
            "url": "https://example.com/job",
            "company": "Example Studio",
            "location": "Remote"
        })
        statuses = {"abc123": {"status": "selected", "package_revision": 1}}
        update = {
            "callback_query": {
                "id": None,
                "data": "prepare|abc123",
                "message": {"chat": {"id": 12345}, "message_id": 10}
            }
        }
        with patch("callbacks.api") as api, patch(
            "callbacks.send_package", side_effect=RuntimeError("delivery failed")
        ):
            result = handle_callback(
                update, self.applications, statuses, self.allowed_chat, self.editing
            )
        self.assertTrue(result)
        self.assertEqual(statuses["abc123"]["status"], "selected")
        self.assertNotIn("prepared_at", statuses["abc123"])
        self.assertTrue(any(call.args[0] == "sendMessage" for call in api.call_args_list))

    def test_skipped_job_cannot_be_selected_again(self):
        result, statuses, api = self.callback("confirm", "skipped")
        self.assertFalse(result)
        self.assertEqual(statuses["abc123"]["status"], "skipped")
        api.assert_not_called()

    def test_submitted_job_cannot_be_selected_again(self):
        result, statuses, api = self.callback("confirm", "submitted_user_confirmed")
        self.assertFalse(result)
        self.assertEqual(statuses["abc123"]["status"], "submitted_user_confirmed")
        api.assert_not_called()

    def test_unapproved_package_cannot_be_marked_as_submitted(self):
        result, statuses, api = self.callback("applied", "awaiting_approval")
        self.assertFalse(result)
        self.assertEqual(statuses["abc123"]["status"], "awaiting_approval")
        api.assert_not_called()

    def test_approved_package_can_be_marked_submitted_only_by_user_action(self):
        result, statuses, api = self.callback("applied", "approved")
        self.assertTrue(result)
        self.assertEqual(statuses["abc123"]["status"], "submitted_user_confirmed")
        api.assert_called_once()


    def test_auto_prepared_package_can_be_approved_without_prior_callback_state(self):
        applications = {
            "abc123": {
                "id": "abc123",
                "title": "Junior 3D Artist",
                "company": "Studio",
                "status": "awaiting_approval",
                "package_revision": 1,
                "url": "https://example.com/job"
            }
        }
        statuses = {}
        update = {
            "callback_query": {
                "id": None,
                "data": "approve|abc123",
                "message": {"chat": {"id": 12345}, "message_id": 10}
            }
        }
        with patch("callbacks.api") as api:
            result = handle_callback(
                update, applications, statuses, self.allowed_chat, self.editing
            )
        self.assertTrue(result)
        self.assertEqual(statuses["abc123"]["status"], "approved")
        self.assertEqual(statuses["abc123"]["package_revision"], 1)
        api.assert_called_once()


if __name__ == "__main__":
    unittest.main()
