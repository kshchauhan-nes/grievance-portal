"""Source-level accessibility regressions; these do not replace browser testing."""
import os
import re
import unittest

from tests.helpers import ROOT


class AccessibilitySourceTests(unittest.TestCase):
    def read(self, relative_path):
        with open(os.path.join(ROOT, relative_path), encoding="utf-8") as handle:
            return handle.read()

    def test_standalone_pages_declare_mobile_viewport_and_language(self):
        for name in os.listdir(os.path.join(ROOT, "templates")):
            if name.startswith("_") or not name.endswith(".html"):
                continue
            source = self.read(os.path.join("templates", name))
            with self.subTest(template=name):
                self.assertRegex(source, r"<html\b[^>]*\blang\s*=", "Declare document language")
                self.assertRegex(source, r'<meta\s+name=["\']viewport["\']', "Support mobile viewport")

    def test_shared_stylesheet_has_visible_keyboard_focus(self):
        css = self.read(os.path.join("static", "style.css"))
        self.assertRegex(css, r":focus-visible\s*\{[^}]*outline\s*:", 
                         "Keyboard focus needs a visible outline")
        self.assertRegex(css, r"@media\s*\(max-width:", 
                         "Shared stylesheet should retain responsive breakpoints")

    def test_message_and_status_controls_have_accessible_names(self):
        checks = {
            "templates/authority_case.html": [
                r'<label\s+for=["\']case-status["\']',
                r'<select\s+id=["\']case-status["\']',
                r'<textarea\b[^>]*aria-label=["\']Message to the complainant["\']',
            ],
            "templates/my_complaint_case.html": [
                r'<textarea\b[^>]*aria-label=["\']Message to the authority["\']',
            ],
        }
        for path, patterns in checks.items():
            source = self.read(path)
            for pattern in patterns:
                with self.subTest(path=path, pattern=pattern):
                    self.assertRegex(source, pattern)

    def test_form_validation_errors_are_exposed_as_alerts(self):
        for path in ("templates/login.html", "templates/register.html", "templates/track.html",
                     "templates/verification.html", "templates/complaint.html"):
            source = self.read(path)
            with self.subTest(template=path):
                self.assertRegex(source, r'role=["\']alert["\']',
                                 "Validation errors should be programmatically exposed")

    def test_reports_logout_uses_post_and_csrf(self):
        source = self.read("templates/authority_reports.html")
        self.assertRegex(source, r'<form\s+method=["\']POST["\']\s+action="{{\s*url_for\(\s*[\'"]logout[\'"]\s*\)\s*}}"')
        self.assertIn('name="csrf_token"', source)
        self.assertNotRegex(source, r'<a\s+href="{{\s*url_for\(\s*[\'"]logout[\'"]')

if __name__ == "__main__":
    unittest.main()
