from datetime import datetime, timedelta
from unittest import mock

from tests.helpers import PortalTestCase, portal

THRESHOLDS = {
    "Submitted": 24, "Under Review": 48, "In Progress": 72,
    "Escalated": 24, "Resolved": 48
}


class EscalationTests(PortalTestCase):
    def setUp(self):
        super().setUp()
        self.user = self.make_user("escuser")
        self.case = self.submit(self.user)

    def set_status(self, status):
        with self.db() as db:
            db.execute("UPDATE complaints SET status=? WHERE case_id=?", (status, self.case))

    def run_at(self, hours, case_id=None):
        return portal.check_escalation_agent(
            case_id, now=datetime.now() + timedelta(hours=hours))

    def alerts(self):
        with self.db() as db:
            return db.execute("SELECT * FROM escalation_alerts WHERE case_id=?", (self.case,)).fetchall()

    def test_thresholds_for_every_status(self):
        for status, hours in THRESHOLDS.items():
            with self.subTest(status=status):
                with self.db() as db:
                    db.execute("DELETE FROM escalation_alerts")
                self.set_status(status)
                self.assertEqual(self.run_at(hours - 1), 0)
                self.assertEqual(self.run_at(hours + 1), 1)
                alert = self.alerts()[0]
                self.assertEqual(alert["status"], status)
                self.assertIn(str(hours), alert["reason"])
                self.assertTrue(alert["recommended_action"])

    def test_closed_cases_ignored(self):
        self.set_status("Closed")
        self.assertEqual(self.run_at(24 * 30), 0)
        self.assertEqual(self.alerts(), [])

    def test_status_never_changed_by_agent(self):
        self.run_at(500)
        with self.db() as db:
            status = db.execute("SELECT status FROM complaints WHERE case_id=?", (self.case,)).fetchone()[0]
        self.assertEqual(status, "Submitted")

    def test_no_duplicate_alerts_or_notifications(self):
        self.assertEqual(self.run_at(30), 1)
        self.assertEqual(self.run_at(31), 0)
        self.assertEqual(self.run_at(500), 0)
        self.assertEqual(len(self.alerts()), 1)
        with self.db() as db:
            count = db.execute("SELECT COUNT(*) FROM notifications WHERE case_id=? AND notification_type='escalation_alert'", (self.case,)).fetchone()[0]
        # one for complainant, one for the NCC authority
        self.assertEqual(count, 2)

    def test_alert_event_does_not_reset_timer(self):
        self.run_at(25)
        # The alert wrote a timeline event "now+25h". If it reset the timer
        # a second alert would need 24 more hours; it must still be blocked
        # by dedup and the timer must be measured from real activity.
        with self.db() as db:
            last = db.execute("""SELECT MAX(created_at) FROM case_events
                                 WHERE case_id=? AND event!='Escalation Agent Alert'""", (self.case,)).fetchone()[0]
        self.assertLess(datetime.strptime(last, "%Y-%m-%d %H:%M:%S"), datetime.now() + timedelta(minutes=1))
        self.assertEqual(self.run_at(26), 0)

    def test_new_activity_allows_new_alert_after_inactivity(self):
        self.run_at(25)
        authority = self.authority("NCC")
        authority.post(f"/authority/case/{self.case}/status", {"status": "Under Review"})
        self.assertEqual(self.run_at(26), 0)       # activity just happened
        self.assertEqual(self.run_at(26 + 49), 1)  # Under Review > 48h idle
        self.assertEqual(len(self.alerts()), 2)

    def test_complainant_message_resets_timer(self):
        self.user.post(f"/my-complaints/{self.case}/message", {"message": "any update?"})
        self.assertEqual(self.run_at(23), 0)
        self.assertEqual(self.run_at(25), 1)

    def test_notifies_correct_recipients_only(self):
        self.run_at(30)
        with self.db() as db:
            rows = db.execute("""SELECT u.username FROM notifications n JOIN users u ON u.id=n.user_id
                                 WHERE n.notification_type='escalation_alert'""").fetchall()
        names = sorted(r[0] for r in rows)
        self.assertEqual(names, ["escuser", "ncc_authority"])

    def test_alert_visible_with_reason_and_next_action(self):
        self.run_at(30)
        authority = self.authority("NCC")
        page = authority.get(f"/authority/case/{self.case}").get_data(as_text=True)
        self.assertIn("without new activity", page)
        self.assertIn("Recommended next action", page)
        self.assertIn("Authority should review the case.", page)
        user_page = self.user.get(f"/my-complaints/{self.case}").get_data(as_text=True)
        self.assertIn("without new activity", user_page)

    def test_alert_does_not_leak_to_other_org_authority(self):
        self.run_at(30)
        hospital = self.authority("Hospital")
        self.assertNotIn(self.case, hospital.get("/notifications").get_data(as_text=True))

    def test_not_run_on_every_request(self):
        portal._LAST_ESCALATION_RUN.clear()
        with mock.patch.object(portal, "check_escalation_agent") as agent:
            for _ in range(5):
                self.user.get("/my-complaints")
                self.user.get("/notifications")
        self.assertLessEqual(agent.call_count, 1)

    def test_lazy_run_can_be_disabled(self):
        portal._LAST_ESCALATION_RUN.clear()
        with mock.patch.object(portal, "ESCALATION_INTERVAL_SECONDS", 0), \
                mock.patch.object(portal, "check_escalation_agent") as agent:
            self.user.get("/my-complaints")
        self.assertEqual(agent.call_count, 0)

    def test_cli_command_runs(self):
        runner = portal.app.test_cli_runner()
        result = runner.invoke(args=["run-escalation"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("complete", result.output)

    def test_legacy_alert_rows_still_render(self):
        with self.db() as db:
            db.execute("""INSERT INTO escalation_alerts(case_id,alert_type,status,reason,created_at)
                          VALUES(?,?,?,?,?)""", (self.case, "legacy_1", "Submitted",
                                                 "Old style reason. Next action: Do it.", "2026-01-01 00:00:00"))
        self.assertEqual(self.authority("NCC").get(f"/authority/case/{self.case}").status_code, 200)
