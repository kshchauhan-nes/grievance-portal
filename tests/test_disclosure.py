from tests.helpers import PortalTestCase


class DisclosurePolicyTests(PortalTestCase):
    def setup_case(self, privacy="confidential", verified=True):
        user = self.make_user("complainant1", full_name="Secret Person",
                              email="secret@example.com", phone="9999999999")
        case = self.submit(user, privacy=privacy)
        authority = self.authority("NCC")
        if verified:
            self.verify_user(user, authority)
        return user, authority, case

    def test_confidential_hidden_by_default(self):
        user, authority, case = self.setup_case()
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertNotIn("Secret Person", page)
        self.assertNotIn("secret@example.com", page)
        self.assertIn("Disclose Identity", page)

    def test_identified_complaint_shows_identity(self):
        user, authority, case = self.setup_case(privacy="identified", verified=False)
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertIn("Secret Person", page)

    def test_unverified_complainant_blocks_disclosure(self):
        user, authority, case = self.setup_case(verified=False)
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertNotIn("Disclose Identity", page)
        self.assertIn("not verified", page)
        response = authority.post(f"/authority/case/{case}/reveal-identity",
                                  {"reason": "A sufficiently long case reason."})
        self.assertEqual(response.status_code, 302)
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identity_disclosures").fetchone()[0], 0)
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertNotIn("Secret Person", page)

    def test_rejected_verification_does_not_unlock(self):
        user = self.make_user("complainant2", full_name="Rejected Person")
        case = self.submit(user)
        authority = self.authority("NCC")
        user.post("/verification", {"organization_id": "3",
                                    "verification_method": "Institutional ID",
                                    "reference_detail": "X-1"})
        with self.db() as db:
            vid = db.execute("SELECT MAX(id) FROM verifications").fetchone()[0]
        authority.post(f"/authority/verifications/{vid}/status", {"status": "Rejected"})
        authority.post(f"/authority/case/{case}/reveal-identity",
                       {"reason": "A sufficiently long case reason."})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identity_disclosures").fetchone()[0], 0)

    def test_short_reason_rejected(self):
        user, authority, case = self.setup_case()
        authority.post(f"/authority/case/{case}/reveal-identity", {"reason": "short"})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identity_disclosures").fetchone()[0], 0)

    def test_valid_disclosure_recorded_and_notified(self):
        user, authority, case = self.setup_case()
        reason = "Safety investigation requires contacting the complainant."
        response = authority.post(f"/authority/case/{case}/reveal-identity", {"reason": reason})
        self.assertEqual(response.status_code, 302)
        page = authority.get(f"/authority/case/{case}").get_data(as_text=True)
        self.assertIn("Secret Person", page)
        self.assertIn(reason, page)
        with self.db() as db:
            rows = db.execute("SELECT reason, disclosed_by FROM identity_disclosures WHERE case_id=?", (case,)).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["reason"], reason)
            event = db.execute("SELECT 1 FROM case_events WHERE case_id=? AND event='Identity Disclosed'", (case,)).fetchone()
            self.assertIsNotNone(event)
            note = db.execute("SELECT message FROM notifications WHERE case_id=? AND notification_type='identity_disclosed'", (case,)).fetchone()
            self.assertIsNotNone(note)
            self.assertIn(reason, note["message"])

    def test_double_disclosure_not_duplicated(self):
        user, authority, case = self.setup_case()
        reason = "Safety investigation requires contacting the complainant."
        authority.post(f"/authority/case/{case}/reveal-identity", {"reason": reason})
        authority.post(f"/authority/case/{case}/reveal-identity", {"reason": reason})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identity_disclosures").fetchone()[0], 1)

    def test_verification_in_other_org_does_not_unlock(self):
        user = self.make_user("complainant3", org="NCC")
        case = self.submit(user, org="NCC")
        school = self.authority("School")
        self.verify_user(user, school, org="School")
        ncc = self.authority("NCC")
        ncc.post(f"/authority/case/{case}/reveal-identity",
                 {"reason": "A sufficiently long case reason."})
        with self.db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM identity_disclosures").fetchone()[0], 0)

    def test_complainant_sees_disclosure_in_timeline(self):
        user, authority, case = self.setup_case()
        authority.post(f"/authority/case/{case}/reveal-identity",
                       {"reason": "Safety investigation requires contacting the complainant."})
        page = user.get(f"/my-complaints/{case}").get_data(as_text=True)
        self.assertIn("Identity Disclosed", page)
