"""Shared helpers for the portal test suite (standard library only)."""
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

SEED_PASSWORD = "TestSeedPass#2026"
os.environ["SEED_AUTHORITY_PASSWORD"] = SEED_PASSWORD
os.environ.setdefault("APP_ENV", "development")

import app as portal  # noqa: E402

ORG = {"School": 1, "Hospital": 2, "NCC": 3}
CASE_RE = re.compile(r"\b(?:SCH|HOS|NCC)-[0-9A-F]{8}\b")

CATEGORY = {
    "School": "Academic concern",
    "Hospital": "Waiting time",
    "NCC": "Training concern"
}


class Browser:
    """Test client that always sends a valid CSRF token."""

    def __init__(self, app):
        self.client = app.test_client()

    def token(self):
        with self.client.session_transaction() as sess:
            token = sess.get("_csrf")
        if not token:
            self.client.get("/login")
            with self.client.session_transaction() as sess:
                token = sess.get("_csrf")
        return token

    def get(self, path, **kwargs):
        return self.client.get(path, **kwargs)

    def post(self, path, data=None, csrf=True, **kwargs):
        data = dict(data or {})
        if csrf:
            data["csrf_token"] = self.token()
        return self.client.post(path, data=data, **kwargs)

    def login(self, username, password):
        return self.post("/login", {"username": username, "password": password})

    def logout(self):
        return self.post("/logout")


class PortalTestCase(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.remove(self.db_path)
        portal.app.config["DATABASE"] = self.db_path
        portal.app.config["TESTING"] = True
        portal._LOGIN_FAILURES.clear()
        portal._READY_DATABASES.discard(self.db_path)
        portal.init_db()
        portal._READY_DATABASES.add(self.db_path)

    def tearDown(self):
        for suffix in ("", "-wal", "-shm", "-journal"):
            try:
                os.remove(self.db_path + suffix)
            except OSError:
                pass

    # ---- helpers -------------------------------------------------
    def browser(self):
        return Browser(portal.app)

    @contextmanager
    def db(self):
        connection = portal.get_db()
        try:
            yield connection
        finally:
            connection.commit()
            connection.close()

    def register(self, browser, username, org="NCC", full_name="Test Person",
                 password="Password#123", email="t@example.com",
                 phone="9876543210"):
        return browser.post("/register", {
            "full_name": full_name, "email": email, "phone": phone,
            "username": username, "password": password,
            "organization_id": str(ORG[org])
        })

    def make_user(self, username, org="NCC", **kw):
        browser = self.browser()
        response = self.register(browser, username, org, **kw)
        self.assertEqual(response.status_code, 302, response.get_data(as_text=True)[:300])
        response = browser.login(username, kw.get("password", "Password#123"))
        self.assertEqual(response.status_code, 302)
        return browser

    def authority(self, sector="NCC"):
        browser = self.browser()
        response = browser.login(f"{sector.lower()}_authority", SEED_PASSWORD)
        self.assertEqual(response.status_code, 302)
        return browser

    def submit(self, browser, org="NCC", privacy="confidential", **overrides):
        data = {
            "complaint_type": "Individual",
            "organization_id": str(ORG[org]),
            "institution": "Test Institution",
            "unit": "Unit A",
            "category": CATEGORY[org],
            "incident_date": "2026-01-15",
            "description": "This is a sufficiently long complaint description.",
            "privacy_mode": privacy
        }
        data.update(overrides)
        response = browser.post("/complaint", data)
        self.assertEqual(response.status_code, 200)
        match = CASE_RE.search(response.get_data(as_text=True))
        self.assertIsNotNone(match, "case id not shown on confirmation")
        return match.group(0)

    def verify_user(self, user_browser, authority_browser, org="NCC",
                    method="Institutional ID"):
        response = user_browser.post("/verification", {
            "organization_id": str(ORG[org]),
            "verification_method": method,
            "reference_detail": "REF-12345"
        })
        self.assertEqual(response.status_code, 302)
        with self.db() as db:
            vid = db.execute(
                "SELECT MAX(id) FROM verifications").fetchone()[0]
        response = authority_browser.post(
            f"/authority/verifications/{vid}/status", {"status": "Verified"})
        self.assertEqual(response.status_code, 302)
        return vid
