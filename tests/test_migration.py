"""Upgrade an old-format database (created by the original code at git
commit d8f2fd3) with the new code and verify that no data is lost."""
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest

from tests.helpers import ROOT, SEED_PASSWORD, portal


def build_legacy_db(path):
    """Create a database using the ORIGINAL app.py init_db()."""
    source = subprocess.run(
        ["git", "show", "d8f2fd3:app.py"], cwd=ROOT,
        capture_output=True, text=True
    )
    if source.returncode != 0:
        return False
    workdir = tempfile.mkdtemp()
    with open(os.path.join(workdir, "legacy_app.py"), "w") as handle:
        handle.write(source.stdout)
    code = (
        "import sys; sys.path.insert(0, %r); import legacy_app as a; "
        "a.DATABASE=%r; a.init_db()" % (workdir, path)
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=workdir,
                            capture_output=True, text=True)
    return result.returncode == 0


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        handle, self.path = tempfile.mkstemp(suffix=".db")
        os.close(handle)
        os.remove(self.path)
        if not build_legacy_db(self.path):
            self.skipTest("original commit d8f2fd3 not available in git history")
        db = sqlite3.connect(self.path)
        now = "2026-01-01 10:00:00"
        db.execute("INSERT INTO users(username,password_hash,role,organization_id,created_at) VALUES('olduser','hash','user',3,?)", (now,))
        uid = db.execute("SELECT id FROM users WHERE username='olduser'").fetchone()[0]
        db.execute("INSERT INTO identity_vault(user_id,full_name,email,phone,created_at) VALUES(?,?,?,?,?)", (uid, "Old Name", "o@x.com", "123", now))
        db.execute("""INSERT INTO complaints(case_id,complaint_type,institution,unit,category,incident_date,description,status,created_at,user_id,privacy_mode,organization_id)
                      VALUES('NCC-AAAA1111','Individual','Inst','U','Training concern','2025-12-01','old description text','Resolved',?,?, 'confidential',3)""", (now, uid))
        db.execute("INSERT INTO case_events(case_id,event,description,created_at) VALUES('NCC-AAAA1111','Complaint Submitted','d','2026-01-01 10:00:00')")
        db.execute("INSERT INTO case_events(case_id,event,description,created_at) VALUES('NCC-AAAA1111','Status Changed','Status changed from In Progress to Resolved by authority.','2026-01-02 12:00:00')")
        db.execute("INSERT INTO case_messages(case_id,sender_role,sender_user_id,message,created_at) VALUES('NCC-AAAA1111','authority',1,'old msg',?)", (now,))
        db.execute("INSERT INTO verifications(user_id,organization_id,verification_method,verification_status,created_at) VALUES(?,3,'Document Verification','Pending',?)", (uid, now))
        db.execute("INSERT INTO identity_disclosures(case_id,disclosed_by,reason,created_at) VALUES('NCC-AAAA1111',1,'old reason',?)", (now,))
        db.commit()
        db.close()
        self.counts_before = self.counts()

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def counts(self):
        db = sqlite3.connect(self.path)
        try:
            return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("users", "complaints", "case_events", "case_messages",
                              "identity_vault", "verifications", "identity_disclosures",
                              "organizations", "notifications")}
        finally:
            db.close()

    def upgrade(self):
        portal.app.config["DATABASE"] = self.path
        portal.init_db()

    def test_upgrade_keeps_all_rows(self):
        self.upgrade()
        after = self.counts()
        for table, before in self.counts_before.items():
            self.assertGreaterEqual(after[table], before, table)
        # only authority accounts may be added (3 seeded via env)
        self.assertEqual(after["complaints"], 1)
        self.assertEqual(after["case_events"], 2)
        self.assertEqual(after["identity_vault"], 1)
        self.assertEqual(after["identity_disclosures"], 1)

    def test_old_rows_readable_and_new_columns_defaulted(self):
        self.upgrade()
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        row = db.execute("SELECT * FROM complaints WHERE case_id='NCC-AAAA1111'").fetchone()
        self.assertEqual(row["priority"], "Normal")
        self.assertEqual(row["description"], "old description text")
        self.assertEqual(row["resolved_at"], "2026-01-02 12:00:00")  # backfilled
        v = db.execute("SELECT * FROM verifications").fetchone()
        self.assertEqual(v["verification_method"], "Document Verification")  # old text kept
        self.assertIsNone(v["reference_detail"])
        db.close()

    def test_upgrade_is_idempotent(self):
        self.upgrade()
        first = self.counts()
        portal.init_db()
        portal.init_db()
        self.assertEqual(self.counts(), first)
        db = sqlite3.connect(self.path)
        versions = [r[0] for r in db.execute("SELECT version FROM schema_migrations ORDER BY version")]
        db.close()
        self.assertEqual(versions, [1, 2, 3, 4, 5])

    def test_existing_seeded_password_not_changed_by_upgrade(self):
        self.upgrade()
        db = sqlite3.connect(self.path)
        row = db.execute("SELECT password_hash FROM users WHERE username='ncc_authority'").fetchone()
        db.close()
        # legacy hash of Authority@123 remains: the new code never overwrites it
        from werkzeug.security import check_password_hash
        self.assertTrue(check_password_hash(row[0], "Authority@123"))
        self.assertFalse(check_password_hash(row[0], SEED_PASSWORD))

    def test_app_serves_legacy_data(self):
        self.upgrade()
        portal.app.config["TESTING"] = True
        portal._READY_DATABASES.add(self.path)
        from tests.helpers import Browser
        auth = Browser(portal.app)
        self.assertEqual(auth.login("ncc_authority", "Authority@123").status_code, 302)
        self.assertEqual(auth.get("/authority/dashboard").status_code, 200)
        page = auth.get("/authority/case/NCC-AAAA1111").get_data(as_text=True)
        self.assertIn("old description text", page)
        self.assertIn("Old Name", page)  # prior disclosure remains valid
        self.assertEqual(auth.get("/authority/verifications").status_code, 200)
        self.assertEqual(auth.get("/authority/reports").status_code, 200)
        self.assertEqual(auth.get("/authority/export.csv").status_code, 200)


if __name__ == "__main__":
    unittest.main()
