"""Automated web workflow and access-control tests."""
from tests.helpers import PortalTestCase, ORG


class WorkflowTests(PortalTestCase):

    def test_registration_and_login(self):
        browser = self.browser()
        response = self.register(
            browser, "workflow_user_01",
            org="School",
            full_name="Workflow Test User",
            email="workflow01@example.com"
        )
        self.assertEqual(response.status_code, 302)
        response = browser.login("workflow_user_01", "Password#123")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/")

    def test_duplicate_username_is_rejected(self):
        browser = self.browser()
        self.register(browser, "workflow_duplicate")
        response = self.register(browser, "workflow_duplicate")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Username already exists",
            response.get_data(as_text=True)
        )

    def test_complaint_submission_and_tracking(self):
        browser = self.make_user("workflow_submitter", org="School")
        case_id = self.submit(browser, org="School")

        response = browser.post("/track", {"case_id": case_id})
        self.assertEqual(response.status_code, 200)
        self.assertIn(case_id, response.get_data(as_text=True))

    def test_user_cannot_track_another_users_case(self):
        owner = self.make_user("workflow_owner", org="NCC")
        case_id = self.submit(owner, org="NCC")

        other = self.make_user("workflow_other", org="NCC")
        response = other.post("/track", {"case_id": case_id})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            case_id, response.get_data(as_text=True)
        )

    def test_my_complaints_shows_only_own_cases(self):
        owner = self.make_user("workflow_list_owner", org="NCC")
        case_id = self.submit(owner, org="NCC")

        other = self.make_user("workflow_list_other", org="NCC")
        response = other.get("/my-complaints")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(
            case_id, response.get_data(as_text=True)
        )

    def test_anonymous_request_cannot_open_complaint_form(self):
        browser = self.browser()
        response = browser.get("/complaint")
        self.assertIn(response.status_code, (302, 401, 403))

    def test_invalid_case_id_does_not_show_a_case(self):
        browser = self.make_user("workflow_invalid_case")
        response = browser.post(
            "/track", {"case_id": "NOT-A-REAL-CASE"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "No case found", response.get_data(as_text=True)
        )
