import os
import re
import subprocess
import sys
import unittest

from tests.helpers import ROOT, SEED_PASSWORD, PortalTestCase, portal


class TemplateIntegrityTests(unittest.TestCase):
    def test_no_markdown_fences_in_sources(self):
        offenders = []
        for folder in ("templates", "static"):
            for name in os.listdir(os.path.join(ROOT, folder)):
                path = os.path.join(ROOT, folder, name)
                with open(path, encoding="utf-8") as handle:
                    if "```" in handle.read():
                        offenders.append(path)
        with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
            if "```" in handle.read():
                offenders.append("app.py")
        self.assertEqual(offenders, [])

    def test_every_url_for_endpoint_exists(self):
        endpoints = set(portal.app.view_functions)
        missing = []
        for name in os.listdir(os.path.join(ROOT, "templates")):
            with open(os.path.join(ROOT, "templates", name), encoding="utf-8") as handle:
                text = handle.read()
            for endpoint in re.findall(r"url_for\(\s*['\"]([a-z_]+)['\"]", text):
                if endpoint not in endpoints:
                    missing.append((name, endpoint))
        self.assertEqual(missing, [])

    def test_every_form_has_csrf_token(self):
        for name in os.listdir(os.path.join(ROOT, "templates")):
            with open(os.path.join(ROOT, "templates", name), encoding="utf-8") as handle:
                text = handle.read()
            forms = sum(
                1 for tag in re.findall(r"<form\b[^>]*>", text, re.S)
                if re.search(r"method\s*=\s*[\"']?post", tag, re.I)
            )
            tokens = len(re.findall(r'name="csrf_token"', text))
            self.assertGreaterEqual(tokens, forms, name)


class ConfigurationTests(unittest.TestCase):
    def run_python(self, code, env_extra):
        env = {k: v for k, v in os.environ.items()
               if k not in ("SECRET_KEY", "APP_ENV", "FLASK_DEBUG")}
        env.update(env_extra)
        return subprocess.run(
            [sys.executable, "-c", code], cwd=ROOT, env=env,
            capture_output=True, text=True
        )

    def test_production_requires_secret_key(self):
        result = self.run_python("import app", {"APP_ENV": "production"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SECRET_KEY", result.stderr)

    def test_production_with_secret_key_has_secure_cookies(self):
        result = self.run_python(
            "import app; print(app.app.config['SESSION_COOKIE_SECURE'])",
            {"APP_ENV": "production", "SECRET_KEY": "x" * 40,
             "DATABASE_PATH": os.devnull + ".unused"}
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("True", result.stdout)

    def test_no_predictable_secret_fallback(self):
        with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
            self.assertNotIn("development-secret-change-this", handle.read())

    def test_debug_not_hardcoded(self):
        with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as handle:
            self.assertNotIn("debug=True", handle.read())


class CsrfAndHeadersTests(PortalTestCase):
    def test_post_without_token_rejected(self):
        browser = self.browser()
        response = browser.post("/login", {"username": "a", "password": "b"},
                                csrf=False)
        self.assertEqual(response.status_code, 400)

    def test_post_with_wrong_token_rejected(self):
        browser = self.browser()
        browser.get("/login")
        response = browser.client.post("/login", data={
            "username": "a", "password": "b", "csrf_token": "forged"})
        self.assertEqual(response.status_code, 400)

    def test_forged_message_rejected_for_logged_in_user(self):
        user = self.make_user("csrfuser")
        case = self.submit(user)
        response = user.post(f"/my-complaints/{case}/message",
                             {"message": "forged"}, csrf=False)
        self.assertEqual(response.status_code, 400)

    def test_security_headers_present(self):
        response = self.browser().get("/")
        self.assertEqual(response.headers["X-Frame-Options"], "DENY")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'",
                      response.headers["Content-Security-Policy"])

    def test_authenticated_pages_not_cached(self):
        user = self.make_user("cacheuser")
        self.assertEqual(user.get("/my-complaints").headers["Cache-Control"],
                         "no-store")

    def test_cookie_flags(self):
        browser = self.browser()
        response = browser.get("/login")
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Lax", cookie)

    def test_error_pages(self):
        browser = self.browser()
        response = browser.get("/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Page not found", response.get_data(as_text=True))


class AuthTests(PortalTestCase):
    def test_register_login_logout(self):
        browser = self.browser()
        self.assertEqual(self.register(browser, "alice1").status_code, 302)
        self.assertEqual(browser.login("alice1", "Password#123").status_code, 302)
        self.assertEqual(browser.get("/my-complaints").status_code, 200)
        browser.logout()
        self.assertEqual(browser.get("/my-complaints").status_code, 302)

    def test_passwords_are_hashed(self):
        self.make_user("hashuser")
        with self.db() as db:
            stored = db.execute("SELECT password_hash FROM users WHERE username='hashuser'").fetchone()[0]
        self.assertNotIn("Password#123", stored)

    def test_wrong_password_rejected(self):
        self.make_user("bob1")
        browser = self.browser()
        response = browser.login("bob1", "wrong-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Invalid username or password",
                      response.get_data(as_text=True))

    def test_registration_validation(self):
        browser = self.browser()
        cases = [
            dict(username="ab"), dict(username="bad name!"),
            dict(password="short"), dict(email="not-an-email"),
            dict(phone="abc"), dict(full_name="")
        ]
        for overrides in cases:
            kwargs = dict(username="validname", full_name="Valid Name",
                          password="Password#123", email="a@b.co",
                          phone="9876543210")
            kwargs.update(overrides)
            response = self.register(browser, **kwargs)
            self.assertEqual(response.status_code, 200, overrides)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM users WHERE role='user'").fetchone()[0], 0)

    def test_duplicate_username_rejected(self):
        browser = self.browser()
        self.register(browser, "dupe1")
        response = self.register(browser, "dupe1")
        self.assertEqual(response.status_code, 200)
        self.assertIn("already exists", response.get_data(as_text=True))

    def test_login_throttle(self):
        self.make_user("throttle1")
        browser = self.browser()
        for _ in range(portal.LOGIN_MAX_FAILURES):
            browser.login("throttle1", "wrong")
        response = browser.login("throttle1", "Password#123")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Too many failed attempts", response.get_data(as_text=True))

    def test_seeded_authorities_need_env_password(self):
        with self.db() as db:
            rows = db.execute("SELECT username FROM users WHERE role='authority'").fetchall()
        self.assertEqual(len(rows), 3)
        browser = self.browser()
        self.assertEqual(browser.login("ncc_authority", "Authority@123").status_code, 200)

    def test_no_seed_without_env(self):
        import tempfile
        handle, path = tempfile.mkstemp(suffix=".db")
        os.close(handle); os.remove(path)
        saved = os.environ.pop("SEED_AUTHORITY_PASSWORD")
        try:
            portal.app.config["DATABASE"] = path
            portal.init_db()
            connection = portal.get_db()
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0], 0)
            finally:
                connection.close()
        finally:
            os.environ["SEED_AUTHORITY_PASSWORD"] = saved
            portal.app.config["DATABASE"] = self.db_path
            os.remove(path)


class AccessControlTests(PortalTestCase):
    def test_anonymous_redirected(self):
        browser = self.browser()
        for path in ["/complaint", "/my-complaints", "/track", "/notifications",
                     "/verification", "/authority/dashboard",
                     "/authority/verifications"]:
            self.assertEqual(browser.get(path).status_code, 302, path)

    def test_idor_other_user_case_hidden(self):
        owner = self.make_user("owner1")
        case = self.submit(owner)
        other = self.make_user("other1")
        self.assertEqual(other.get(f"/my-complaints/{case}").status_code, 404)
        self.assertEqual(other.post(f"/my-complaints/{case}/message",
                                    {"message": "hello"}).status_code, 404)
        response = other.post("/track", {"case_id": case})
        self.assertIn("No case found", response.get_data(as_text=True))

    def test_cross_organization_authority_blocked(self):
        owner = self.make_user("owner2", org="NCC")
        case = self.submit(owner, org="NCC")
        hospital = self.authority("Hospital")
        self.assertEqual(hospital.get(f"/authority/case/{case}").status_code, 404)
        self.assertEqual(hospital.post(f"/authority/case/{case}/status",
                                       {"status": "Under Review"}).status_code, 404)
        self.assertEqual(hospital.post(f"/authority/case/{case}/message",
                                       {"message": "hi"}).status_code, 404)
        self.assertEqual(hospital.post(f"/authority/case/{case}/reveal-identity",
                                       {"reason": "x" * 40}).status_code, 404)
        dashboard = hospital.get("/authority/dashboard").get_data(as_text=True)
        self.assertNotIn(case, dashboard)

    def test_user_cannot_access_authority_routes(self):
        user = self.make_user("plain1")
        case = self.submit(user)
        self.assertEqual(user.get("/authority/dashboard").status_code, 302)
        self.assertEqual(user.get(f"/authority/case/{case}").status_code, 302)
        self.assertEqual(user.post(f"/authority/case/{case}/status",
                                   {"status": "Under Review"}).status_code, 302)
        with self.db() as db:
            status = db.execute("SELECT status FROM complaints WHERE case_id=?", (case,)).fetchone()[0]
        self.assertEqual(status, "Submitted")

    def test_authority_cannot_submit_complaints(self):
        authority = self.authority("NCC")
        self.assertEqual(authority.get("/complaint").status_code, 302)
        self.assertEqual(authority.get("/my-complaints").status_code, 302)

    def test_sql_injection_attempt_is_inert(self):
        user = self.make_user("sqli1")
        response = user.post("/track", {"case_id": "' OR '1'='1"})
        self.assertIn("No case found", response.get_data(as_text=True))

    def test_xss_is_escaped(self):
        user = self.make_user("xss1")
        case = self.submit(user, institution="<script>alert(1)</script>",
                           description="<img src=x onerror=alert(1)> padding text")
        page = user.get(f"/my-complaints/{case}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertNotIn("<img src=x", page)
        authority = self.authority("NCC")
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertNotIn("<script>alert(1)</script>", page)


if __name__ == "__main__":
    unittest.main()
