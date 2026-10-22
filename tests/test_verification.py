from tests.helpers import PortalTestCase, ORG


class VerificationTests(PortalTestCase):
    def request(self, user, org="NCC", method="Institutional ID", reference="REF-998"):
        return user.post("/verification", {
            "organization_id": str(ORG[org]),
            "verification_method": method,
            "reference_detail": reference
        })

    def count(self, where="1=1"):
        with self.db() as db:
            return db.execute(f"SELECT COUNT(*) FROM verifications WHERE {where}").fetchone()[0]

    def test_pages_render(self):
        user = self.make_user("vuser1")
        page = user.get("/verification").get_data(as_text=True)
        self.assertIn("What each method proves", page)
        self.assertNotIn("Document Verification", page)
        self.assertEqual(self.authority("NCC").get("/authority/verifications").status_code, 200)

    def test_submit_creates_pending_and_notifies_authority(self):
        user = self.make_user("vuser2")
        self.assertEqual(self.request(user).status_code, 302)
        self.assertEqual(self.count("verification_status='Pending'"), 1)
        with self.db() as db:
            n = db.execute("""SELECT COUNT(*) FROM notifications n JOIN users u ON u.id=n.user_id
                              WHERE n.notification_type='verification_request' AND u.username='ncc_authority'""").fetchone()[0]
        self.assertEqual(n, 1)

    def test_duplicate_pending_blocked(self):
        user = self.make_user("vuser3")
        self.request(user)
        response = self.request(user)
        self.assertIn("already pending", response.get_data(as_text=True))
        self.assertEqual(self.count(), 1)

    def test_same_user_can_request_other_org(self):
        user = self.make_user("vuser4")
        self.request(user, org="NCC")
        self.request(user, org="School")
        self.assertEqual(self.count(), 2)

    def test_invalid_method_and_reference_rejected(self):
        user = self.make_user("vuser5")
        self.assertIn("valid verification method",
                      self.request(user, method="Document Verification").get_data(as_text=True))
        self.assertIn("Enter your", self.request(user, reference="ab").get_data(as_text=True))
        self.assertIn("Enter your", self.request(user, reference="x" * 101).get_data(as_text=True))
        self.assertEqual(self.count(), 0)

    def test_authority_list_minimizes_personal_data(self):
        user = self.make_user("vuser6", full_name="Hidden Name",
                              email="hidden@example.com", phone="9123456789")
        self.request(user)
        page = self.authority("NCC").get("/authority/verifications").get_data(as_text=True)
        self.assertIn("vuser6", page)
        self.assertIn("REF-998", page)
        self.assertNotIn("Hidden Name", page)
        self.assertNotIn("hidden@example.com", page)
        self.assertNotIn("9123456789", page)

    def test_name_visible_only_after_approval_and_never_email_phone(self):
        user = self.make_user("vuser7", full_name="Approved Name",
                              email="approved@example.com", phone="9000000001")
        authority = self.authority("NCC")
        self.verify_user(user, authority)
        page = authority.get("/authority/verifications").get_data(as_text=True)
        self.assertIn("Approved Name", page)
        self.assertNotIn("approved@example.com", page)
        self.assertNotIn("9000000001", page)

    def test_approve_records_audit_and_notifies_user(self):
        user = self.make_user("vuser8")
        authority = self.authority("NCC")
        self.request(user)
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
            auth_id = db.execute("SELECT id FROM users WHERE username='ncc_authority'").fetchone()[0]
        authority.post(f"/authority/verifications/{vid}/status",
                       {"status": "Verified", "review_note": "Matched records"})
        with self.db() as db:
            row = db.execute("SELECT * FROM verifications WHERE id=?", (vid,)).fetchone()
            self.assertEqual(row["verification_status"], "Verified")
            self.assertEqual(row["reviewed_by"], auth_id)
            self.assertTrue(row["reviewed_at"])
            self.assertTrue(row["verified_at"])
            self.assertEqual(row["review_note"], "Matched records")
            note = db.execute("""SELECT message FROM notifications n JOIN users u ON u.id=n.user_id
                                 WHERE u.username='vuser8' AND notification_type='verification_update'""").fetchone()
            self.assertIn("approved", note["message"])
            self.assertIn("Matched records", note["message"])
        page = user.get("/verification").get_data(as_text=True)
        self.assertIn("Matched records", page)

    def test_reject_has_no_verified_at(self):
        user = self.make_user("vuser9")
        authority = self.authority("NCC")
        self.request(user)
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
        authority.post(f"/authority/verifications/{vid}/status", {"status": "Rejected"})
        with self.db() as db:
            row = db.execute("SELECT * FROM verifications WHERE id=?", (vid,)).fetchone()
        self.assertEqual(row["verification_status"], "Rejected")
        self.assertIsNone(row["verified_at"])
        self.assertTrue(row["reviewed_at"])
        self.assertEqual(self.request(user).status_code, 302)  # may re-request

    def test_review_is_final_and_not_repeatable(self):
        user = self.make_user("vuser10")
        authority = self.authority("NCC")
        self.request(user)
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
        authority.post(f"/authority/verifications/{vid}/status", {"status": "Rejected"})
        authority.post(f"/authority/verifications/{vid}/status", {"status": "Verified"})
        with self.db() as db:
            status = db.execute("SELECT verification_status FROM verifications WHERE id=?", (vid,)).fetchone()[0]
        self.assertEqual(status, "Rejected")

    def test_cannot_request_when_already_verified(self):
        user = self.make_user("vuser11")
        self.verify_user(user, self.authority("NCC"))
        response = self.request(user)
        self.assertIn("already verified", response.get_data(as_text=True))

    def test_wrong_org_authority_cannot_review(self):
        user = self.make_user("vuser12")
        self.request(user, org="NCC")
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
        response = self.authority("Hospital").post(
            f"/authority/verifications/{vid}/status", {"status": "Verified"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.count("verification_status='Pending'"), 1)

    def test_user_cannot_review_own_request(self):
        user = self.make_user("vuser13")
        self.request(user)
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
        response = user.post(f"/authority/verifications/{vid}/status", {"status": "Verified"})
        self.assertEqual(response.status_code, 302)  # bounced by role check
        self.assertEqual(self.count("verification_status='Pending'"), 1)

    def test_authority_cannot_approve_own_user_row(self):
        # defence in depth: a verification row owned by an authority account
        authority = self.authority("NCC")
        with self.db() as db:
            auth_id = db.execute("SELECT id FROM users WHERE username='ncc_authority'").fetchone()[0]
            db.execute("""INSERT INTO verifications(user_id,organization_id,verification_method,
                          verification_status,created_at) VALUES(?,3,'Institutional ID','Pending','2026-01-01 00:00:00')""", (auth_id,))
            vid = db.execute("SELECT MAX(id) FROM verifications").fetchone()[0]
        response = authority.post(f"/authority/verifications/{vid}/status", {"status": "Verified"})
        self.assertEqual(response.status_code, 403)

    def test_invalid_review_status_ignored(self):
        user = self.make_user("vuser14")
        authority = self.authority("NCC")
        self.request(user)
        with self.db() as db:
            vid = db.execute("SELECT id FROM verifications").fetchone()[0]
        authority.post(f"/authority/verifications/{vid}/status", {"status": "Pending"})
        authority.post(f"/authority/verifications/{vid}/status", {"status": "<b>x</b>"})
        self.assertEqual(self.count("verification_status='Pending'"), 1)
