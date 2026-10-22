import csv
import io
from datetime import datetime, timedelta

from tests.helpers import PortalTestCase, portal


class DashboardTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("dashuser")
        self.authority_ncc = self.authority("NCC")

    def move(self, case, *statuses):
        for status in statuses:
            response = self.authority_ncc.post(
                f"/authority/case/{case}/status", {"status": status})
            self.assertEqual(response.status_code, 302)

    def page(self, query="", browser=None):
        response = (browser or self.authority_ncc).get("/authority/dashboard" + query)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_dashboard_lists_cases_and_stats(self):
        c1 = self.submit(self.user)
        page = self.page()
        self.assertIn(c1, page)
        self.assertIn("Overdue (no activity)", page)
        self.assertIn("Reports", page)
        self.assertIn("Verifications", page)

    def test_search_by_case_id(self):
        c1, c2 = self.submit(self.user), self.submit(self.user)
        page = self.page(f"?q={c1.lower()}")
        self.assertIn(c1, page)
        self.assertNotIn(c2, page)

    def test_filter_by_status_and_category(self):
        c1 = self.submit(self.user, category="Training concern")
        c2 = self.submit(self.user, category="Attendance concern")
        self.move(c1, "Under Review")
        page = self.page("?status=Under+Review")
        self.assertIn(c1, page)
        self.assertNotIn(c2, page)
        page = self.page("?category=Attendance+concern")
        self.assertIn(c2, page)
        self.assertNotIn(c1, page)

    def test_filter_by_date_range(self):
        c1 = self.submit(self.user)
        with self.db() as db:
            db.execute("UPDATE complaints SET created_at='2025-03-10 10:00:00' WHERE case_id=?", (c1,))
        c2 = self.submit(self.user)
        page = self.page("?date_from=2025-03-01&date_to=2025-03-31")
        self.assertIn(c1, page)
        self.assertNotIn(c2, page)
        page = self.page("?date_from=2025-03-11")
        self.assertNotIn(c1, page)
        self.assertIn(c2, page)

    def test_invalid_filters_do_not_crash(self):
        self.submit(self.user)
        for query in ["?status=<script>", "?date_from=garbage", "?page=-5",
                      "?page=abc", "?sort=;DROP TABLE complaints",
                      "?priority=Nope", "?q=%27%20OR%201%3D1--",
                      "?date_from=2025-05-01&date_to=2025-01-01"]:
            self.page(query)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0], 1)

    def test_organization_isolation(self):
        ncc_case = self.submit(self.user, org="NCC")
        school_user = self.make_user("schooluser", org="School")
        school_case = self.submit(school_user, org="School")
        page = self.page()
        self.assertIn(ncc_case, page)
        self.assertNotIn(school_case, page)
        # a school authority cannot reach NCC data via filters either
        school_auth = self.authority("School")
        page = self.page(f"?q={ncc_case}", school_auth)
        self.assertIn("No matching grievances found", page)
        self.assertNotIn('class="case-id"', page)

    def test_pagination(self):
        cases = [self.submit(self.user) for _ in range(23)]
        first = self.page()
        self.assertIn("Page 1 of 2", first)
        second = self.page("?page=2")
        self.assertIn("Page 2 of 2", second)
        shown = sum(1 for c in cases if c in first) + sum(1 for c in cases if c in second)
        self.assertEqual(shown, 23)
        self.assertEqual(sum(1 for c in cases if c in first and c in second), 0)

    def test_overdue_flag_filter_and_sort(self):
        old, fresh = self.submit(self.user), self.submit(self.user)
        past = (datetime.now() - timedelta(hours=100)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db() as db:
            db.execute("UPDATE complaints SET created_at=? WHERE case_id=?", (past, old))
            db.execute("UPDATE case_events SET created_at=? WHERE case_id=?", (past, old))
        page = self.page("?overdue=1")
        self.assertIn(old, page)
        self.assertNotIn(fresh, page)
        self.assertIn("Overdue", page)
        page = self.page("?sort=overdue")
        self.assertLess(page.index(old), page.index(fresh))

    def test_priority_update_and_validation(self):
        case = self.submit(self.user)
        self.authority_ncc.post(f"/authority/case/{case}/priority", {"priority": "Urgent"})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT priority FROM complaints WHERE case_id=?", (case,)).fetchone()[0], "Urgent")
            event = db.execute("SELECT description,actor_user_id FROM case_events WHERE case_id=? AND event='Priority Updated'", (case,)).fetchone()
        self.assertIsNotNone(event)
        self.assertNotIn("Urgent", event["description"])
        self.assertIsNotNone(event["actor_user_id"])
        self.authority_ncc.post(f"/authority/case/{case}/priority", {"priority": "Bogus"})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT priority FROM complaints WHERE case_id=?", (case,)).fetchone()[0], "Urgent")
        self.assertIn("Urgent priority", self.page("?priority=Urgent"))
        # complainant never sees priority
        self.assertNotIn("Urgent", self.user.get(f"/my-complaints/{case}").get_data(as_text=True))

    def test_priority_cross_org_and_closed(self):
        case = self.submit(self.user)
        response = self.authority("Hospital").post(f"/authority/case/{case}/priority", {"priority": "High"})
        self.assertEqual(response.status_code, 404)
        self.move(case, "Under Review", "In Progress", "Resolved", "Closed")
        self.authority_ncc.post(f"/authority/case/{case}/priority", {"priority": "High"})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT priority FROM complaints WHERE case_id=?", (case,)).fetchone()[0], "Normal")

    def test_priority_change_does_not_reset_inactivity_timer(self):
        case = self.submit(self.user)
        self.authority_ncc.post(f"/authority/case/{case}/priority", {"priority": "High"})
        created = portal.check_escalation_agent(case, now=datetime.now() + timedelta(hours=25))
        self.assertEqual(created, 1)


class ExportTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("exportuser", full_name="Export Person", email="exp@example.com")
        self.authority_ncc = self.authority("NCC")

    def export(self, query="", browser=None):
        response = (browser or self.authority_ncc).get("/authority/export.csv" + query)
        self.assertEqual(response.status_code, 200)
        return response, list(csv.DictReader(io.StringIO(response.get_data(as_text=True))))

    def test_csv_basics_and_privacy(self):
        case = self.submit(self.user, description="Secret narrative text here for the case.")
        response, rows = self.export()
        self.assertEqual(response.mimetype, "text/csv")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual([r["case_id"] for r in rows], [case])
        text = response.get_data(as_text=True)
        self.assertNotIn("Secret narrative", text)
        self.assertNotIn("Export Person", text)
        self.assertNotIn("exp@example.com", text)
        self.assertNotIn("exportuser", text)

    def test_csv_respects_filters_and_org(self):
        ncc = self.submit(self.user, org="NCC")
        school_user = self.make_user("schoolexp", org="School")
        school = self.submit(school_user, org="School")
        _, rows = self.export()
        ids = {r["case_id"] for r in rows}
        self.assertIn(ncc, ids)
        self.assertNotIn(school, ids)
        _, rows = self.export("?status=Escalated")
        self.assertEqual(rows, [])

    def test_csv_formula_injection_neutralized(self):
        self.submit(self.user, institution="=HYPERLINK(\"http://evil\")", unit="@cmd")
        response, rows = self.export()
        self.assertTrue(rows[0]["institution"].startswith("'="))
        self.assertTrue(rows[0]["unit"].startswith("'@"))

    def test_export_requires_authority(self):
        self.assertEqual(self.user.get("/authority/export.csv").status_code, 302)
        self.assertEqual(self.browser().get("/authority/export.csv").status_code, 302)

    def test_resolution_hours_in_csv(self):
        case = self.submit(self.user)
        for status in ["Under Review", "In Progress", "Resolved"]:
            self.authority_ncc.post(f"/authority/case/{case}/status", {"status": status})
        start = (datetime.now() - timedelta(hours=10)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db() as db:
            db.execute("UPDATE complaints SET created_at=? WHERE case_id=?", (start, case))
        _, rows = self.export()
        self.assertAlmostEqual(float(rows[0]["resolution_hours"]), 10.0, delta=0.2)


class ReportTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("reportuser")
        self.authority_ncc = self.authority("NCC")

    def test_reports_render_empty(self):
        response = self.authority_ncc.get("/authority/reports")
        self.assertEqual(response.status_code, 200)
        self.assertIn("No resolved cases", response.get_data(as_text=True))

    def test_reports_compute_metrics(self):
        case = self.submit(self.user)
        for status in ["Under Review", "In Progress", "Resolved"]:
            self.authority_ncc.post(f"/authority/case/{case}/status", {"status": status})
        start = (datetime.now() - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db() as db:
            db.execute("UPDATE complaints SET created_at=? WHERE case_id=?", (start, case))
            db.execute("UPDATE case_events SET created_at=? WHERE case_id=? AND event='Complaint Submitted'", (start, case))
        page = self.authority_ncc.get("/authority/reports").get_data(as_text=True)
        self.assertIn("6.0 h", page)  # resolution average
        self.assertIn("ncc_authority", page)  # workload attribution
        self.assertIn("Training concern", page)

    def test_reports_scoped_to_organization(self):
        self.submit(self.user, org="NCC")
        hospital = self.authority("Hospital")
        page = hospital.get("/authority/reports").get_data(as_text=True)
        self.assertIn("Cases", page)
        self.assertNotIn("Training concern", page)

    def test_reports_list_overdue(self):
        case = self.submit(self.user)
        past = (datetime.now() - timedelta(hours=60)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db() as db:
            db.execute("UPDATE complaints SET created_at=? WHERE case_id=?", (past, case))
            db.execute("UPDATE case_events SET created_at=? WHERE case_id=?", (past, case))
        page = self.authority_ncc.get("/authority/reports").get_data(as_text=True)
        self.assertIn(case, page)

    def test_reports_require_authority(self):
        self.assertEqual(self.user.get("/authority/reports").status_code, 302)
        self.assertEqual(self.browser().get("/authority/reports").status_code, 302)
