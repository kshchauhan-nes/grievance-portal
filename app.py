from flask import Flask, render_template, request, redirect, url_for, session
import os, secrets, sqlite3
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "development-secret-change-this")
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
DATABASE = "complaints.db"


# =========================================================
# DATABASE
# =========================================================

def get_db():
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def current_time():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_time(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def init_db():
    db = get_db()

    tables = [
        """CREATE TABLE IF NOT EXISTS organizations(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, sector TEXT NOT NULL,
            created_at TEXT NOT NULL)""",

        """CREATE TABLE IF NOT EXISTS users(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            organization_id INTEGER,
            created_at TEXT NOT NULL,
            FOREIGN KEY(organization_id) REFERENCES organizations(id))""",

        """CREATE TABLE IF NOT EXISTS complaints(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT UNIQUE NOT NULL,
            complaint_type TEXT NOT NULL,
            institution TEXT NOT NULL,
            unit TEXT,
            category TEXT NOT NULL,
            incident_date TEXT,
            description TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL)""",

        """CREATE TABLE IF NOT EXISTS case_events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            event TEXT NOT NULL,
            description TEXT,
            created_at TEXT NOT NULL)""",

        """CREATE TABLE IF NOT EXISTS case_messages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            sender_role TEXT NOT NULL,
            sender_user_id INTEGER,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL)""",

        """CREATE TABLE IF NOT EXISTS message_reads(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            last_read_message_id INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            UNIQUE(case_id,user_id))""",

        """CREATE TABLE IF NOT EXISTS notifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            case_id TEXT,
            notification_type TEXT NOT NULL,
            title TEXT NOT NULL,
            message TEXT NOT NULL,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL)""",

        """CREATE TABLE IF NOT EXISTS escalation_alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(case_id,alert_type))""",

        """CREATE TABLE IF NOT EXISTS verifications(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            organization_id INTEGER NOT NULL,
            verification_method TEXT NOT NULL,
            verification_status TEXT NOT NULL,
            verified_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(organization_id) REFERENCES organizations(id))""",

        """CREATE TABLE IF NOT EXISTS identity_vault(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT,
            phone TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id))""",

        """CREATE TABLE IF NOT EXISTS identity_disclosures(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id TEXT NOT NULL,
            disclosed_by INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL)"""
    ]

    for table in tables:
        db.execute(table)

    columns = {
        r["name"] for r in db.execute(
            "PRAGMA table_info(complaints)"
        ).fetchall()
    }

    migrations = {
        "user_id": "ALTER TABLE complaints ADD COLUMN user_id INTEGER",
        "privacy_mode": """ALTER TABLE complaints
            ADD COLUMN privacy_mode TEXT NOT NULL DEFAULT 'confidential'""",
        "organization_id": "ALTER TABLE complaints ADD COLUMN organization_id INTEGER"
    }

    for column, query in migrations.items():
        if column not in columns:
            db.execute(query)

    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_complaints_org ON complaints(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status)",
        "CREATE INDEX IF NOT EXISTS idx_events_case ON case_events(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_case ON case_messages(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(user_id,is_read)"
    ]

    for index in indexes:
        db.execute(index)

    now = current_time()

    if not db.execute("SELECT id FROM organizations LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO organizations(name,sector,created_at) VALUES(?,?,?)",
            [
                ("School", "School", now),
                ("Hospital", "Hospital", now),
                ("NCC", "NCC", now)
            ]
        )
    else:
        db.execute(
            """UPDATE organizations SET name='School',sector='School'
               WHERE sector='Education' OR name='Demo College'"""
        )
        db.execute(
            """UPDATE organizations SET name='Hospital',sector='Hospital'
               WHERE sector='Healthcare' OR name='Demo Hospital'"""
        )
        db.execute(
            """UPDATE organizations SET name='NCC',sector='NCC'
               WHERE name='National Cadet Corps'"""
        )

        for name, sector in [
            ("School", "School"),
            ("Hospital", "Hospital"),
            ("NCC", "NCC")
        ]:
            if not db.execute(
                "SELECT id FROM organizations WHERE sector=? LIMIT 1",
                (sector,)
            ).fetchone():
                db.execute(
                    "INSERT INTO organizations(name,sector,created_at) VALUES(?,?,?)",
                    (name, sector, current_time())
                )

    for prefix, sector in [
        ("SCH", "School"),
        ("HOS", "Hospital"),
        ("NCC", "NCC")
    ]:
        db.execute(
            """UPDATE complaints SET organization_id=(
                SELECT id FROM organizations WHERE sector=? LIMIT 1)
               WHERE case_id LIKE ?""",
            (sector, prefix + "-%")
        )

    for username, sector in [
        ("school_authority", "School"),
        ("hospital_authority", "Hospital"),
        ("ncc_authority", "NCC")
    ]:
        org = db.execute(
            "SELECT id FROM organizations WHERE sector=? LIMIT 1",
            (sector,)
        ).fetchone()

        authority = db.execute(
            "SELECT id FROM users WHERE username=?",
            (username,)
        ).fetchone()

        if org:
            if not authority:
                db.execute(
                    """INSERT INTO users
                       (username,password_hash,role,organization_id,created_at)
                       VALUES(?,?,?,?,?)""",
                    (
                        username,
                        generate_password_hash("Authority@123"),
                        "authority",
                        org["id"],
                        current_time()
                    )
                )
            else:
                db.execute(
                    """UPDATE users SET organization_id=?
                       WHERE username=? AND role='authority'""",
                    (org["id"], username)
                )

    db.commit()
    db.close()


# =========================================================
# HELPERS
# =========================================================

def logged_in():
    return "user_id" in session


def authority_session():
    return logged_in() and session.get("role") == "authority"


def get_authority(db, user_id=None):
    user_id = user_id or session.get("user_id")
    return db.execute(
        """SELECT id,username,organization_id FROM users
           WHERE id=? AND role='authority'""",
        (user_id,)
    ).fetchone()


def create_notification(db, user_id, case_id, notification_type, title, message):
    db.execute(
        """INSERT INTO notifications
           (user_id,case_id,notification_type,title,message,is_read,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            user_id, case_id, notification_type,
            title, message, 0, current_time()
        )
    )


def get_case_unread_count(case_id, user_id, role):
    sender = {"user": "authority", "authority": "complainant"}.get(role)
    if not sender:
        return 0

    db = get_db()
    row = db.execute(
        """SELECT COUNT(*) count FROM case_messages m
           LEFT JOIN message_reads r
             ON r.case_id=m.case_id AND r.user_id=?
           WHERE m.case_id=? AND m.sender_role=?
             AND m.id>COALESCE(r.last_read_message_id,0)""",
        (user_id, case_id, sender)
    ).fetchone()
    db.close()
    return row["count"]


# =========================================================
# ESCALATION
# =========================================================

ESCALATION_RULES = {
    "Submitted": (24, "Authority should review the case."),
    "Under Review": (48, "Authority should move the case forward or escalate it."),
    "In Progress": (72, "Authority should update progress, resolve the case, or escalate it."),
    "Escalated": (24, "Authority should review the escalation and take action."),
    "Resolved": (48, "Authority should confirm resolution and close the case.")
}


def run_escalation_agent(db, case_id=None):
    query = """SELECT case_id,status,user_id,organization_id,created_at
               FROM complaints WHERE status!='Closed'"""
    params = ()

    if case_id:
        query += " AND case_id=?"
        params = (case_id,)

    for complaint in db.execute(query, params).fetchall():
        rule = ESCALATION_RULES.get(complaint["status"])

        if not rule or not complaint["user_id"]:
            continue

        threshold, action = rule

        event = db.execute(
            """SELECT id,created_at FROM case_events
               WHERE case_id=? AND event!='Escalation Agent Alert'
               ORDER BY id DESC LIMIT 1""",
            (complaint["case_id"],)
        ).fetchone()

        message = db.execute(
            """SELECT created_at FROM case_messages
               WHERE case_id=? ORDER BY id DESC LIMIT 1""",
            (complaint["case_id"],)
        ).fetchone()

        times = []
        for row in (event, message):
            if row:
                parsed = parse_time(row["created_at"])
                if parsed:
                    times.append(parsed)

        created = parse_time(complaint["created_at"])
        latest = max(times) if times else (created or datetime.now())
        inactive = (datetime.now() - latest).total_seconds() / 3600

        if inactive < threshold:
            continue

        event_id = event["id"] if event else 0
        alert_type = (
            complaint["status"].lower().replace(" ", "_")
            + "_inactivity_" + str(event_id)
        )

        if db.execute(
            "SELECT id FROM escalation_alerts WHERE case_id=? AND alert_type=?",
            (complaint["case_id"], alert_type)
        ).fetchone():
            continue

        reason = (
            f"Case remained in {complaint['status']} for more than "
            f"{threshold} hours without new activity. Next action: {action}"
        )
        created_at = current_time()

        db.execute(
            """INSERT INTO escalation_alerts
               (case_id,alert_type,status,reason,created_at)
               VALUES(?,?,?,?,?)""",
            (
                complaint["case_id"], alert_type,
                complaint["status"], reason, created_at
            )
        )

        db.execute(
            """INSERT INTO case_events
               (case_id,event,description,created_at)
               VALUES(?,?,?,?)""",
            (
                complaint["case_id"],
                "Escalation Agent Alert",
                reason,
                created_at
            )
        )

        create_notification(
            db,
            complaint["user_id"],
            complaint["case_id"],
            "escalation_alert",
            "Escalation Alert",
            f"Case {complaint['case_id']} has remained in "
            f"{complaint['status']} for more than {threshold} hours. {action}"
        )

        for authority in db.execute(
            """SELECT id FROM users
               WHERE role='authority' AND organization_id=?""",
            (complaint["organization_id"],)
        ).fetchall():
            create_notification(
                db,
                authority["id"],
                complaint["case_id"],
                "escalation_alert",
                "Escalation Agent Alert",
                f"Case {complaint['case_id']} exceeded the "
                f"{threshold}-hour activity threshold while in "
                f"{complaint['status']}. {action}"
            )


def check_escalation_agent(case_id=None):
    db = get_db()
    try:
        run_escalation_agent(db, case_id)
        db.commit()
    finally:
        db.close()


# =========================================================
# NOTIFICATIONS
# =========================================================

def get_unread_message_count(user_id, role):
    db = get_db()

    if role == "user":
        row = db.execute(
            """SELECT COUNT(*) count FROM case_messages m
               JOIN complaints c ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.user_id=? AND m.sender_role='authority'
                 AND m.id>COALESCE(r.last_read_message_id,0)""",
            (user_id, user_id)
        ).fetchone()
    elif role == "authority":
        authority = get_authority(db, user_id)
        if not authority:
            db.close()
            return 0

        row = db.execute(
            """SELECT COUNT(*) count FROM case_messages m
               JOIN complaints c ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.organization_id=? AND m.sender_role='complainant'
                 AND m.id>COALESCE(r.last_read_message_id,0)""",
            (user_id, authority["organization_id"])
        ).fetchone()
    else:
        db.close()
        return 0

    count = row["count"]
    db.close()
    return count


def get_unread_system_notification_count(user_id):
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) count FROM notifications WHERE user_id=? AND is_read=0",
        (user_id,)
    ).fetchone()
    db.close()
    return row["count"]


def get_total_unread_notification_count(user_id, role):
    return (
        get_unread_message_count(user_id, role)
        + get_unread_system_notification_count(user_id)
    )


@app.context_processor
def inject_notification_count():
    if not logged_in():
        return {
            "unread_message_count": 0,
            "total_notification_count": 0,
            "unread_system_notification_count": 0,
            "notifications": []
        }

    check_escalation_agent()
    user_id = session["user_id"]
    role = session.get("role")

    db = get_db()
    notifications = []

    for item in db.execute(
        """SELECT id,case_id,notification_type,title,message,created_at
           FROM notifications WHERE user_id=? AND is_read=0
           ORDER BY id DESC LIMIT 10""",
        (user_id,)
    ).fetchall():
        notifications.append({
            "id": item["id"],
            "case_id": item["case_id"],
            "notification_type": item["notification_type"],
            "title": item["title"],
            "message": item["message"],
            "created_at": item["created_at"],
            "sender": "System",
            "source": "system"
        })

    if role == "user":
        rows = db.execute(
            """SELECT m.id,m.case_id,m.message,m.created_at,c.category
               FROM case_messages m JOIN complaints c
                 ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.user_id=? AND m.sender_role='authority'
                 AND m.id>COALESCE(r.last_read_message_id,0)
               ORDER BY m.id DESC LIMIT 10""",
            (user_id, user_id)
        ).fetchall()
        sender = "Authority"
        title = "New Authority Message"
    elif role == "authority":
        authority = get_authority(db)
        rows = []
        if authority:
            rows = db.execute(
                """SELECT m.id,m.case_id,m.message,m.created_at,c.category
                   FROM case_messages m JOIN complaints c
                     ON m.case_id=c.case_id
                   LEFT JOIN message_reads r
                     ON r.case_id=m.case_id AND r.user_id=?
                   WHERE c.organization_id=? AND m.sender_role='complainant'
                     AND m.id>COALESCE(r.last_read_message_id,0)
                   ORDER BY m.id DESC LIMIT 10""",
                (user_id, authority["organization_id"])
            ).fetchall()
        sender = "Complainant"
        title = "New Complainant Message"
    else:
        rows = []
        sender = ""
        title = ""

    for item in rows:
        notifications.append({
            "id": item["id"],
            "case_id": item["case_id"],
            "notification_type": "message",
            "title": title,
            "message": item["message"],
            "created_at": item["created_at"],
            "category": item["category"],
            "sender": sender,
            "source": "message"
        })

    db.close()
    notifications.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "unread_message_count": get_total_unread_notification_count(user_id, role),
        "total_notification_count": get_total_unread_notification_count(user_id, role),
        "unread_system_notification_count":
            get_unread_system_notification_count(user_id),
        "notifications": notifications[:10]
    }


def mark_case_messages_read(case_id, user_id, role):
    sender = {"user": "authority", "authority": "complainant"}.get(role)
    if not sender:
        return

    db = get_db()
    latest = db.execute(
        """SELECT MAX(id) message_id FROM case_messages
           WHERE case_id=? AND sender_role=?""",
        (case_id, sender)
    ).fetchone()

    if latest["message_id"]:
        db.execute(
            """INSERT INTO message_reads
               (case_id,user_id,last_read_message_id,updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(case_id,user_id) DO UPDATE SET
               last_read_message_id=excluded.last_read_message_id,
               updated_at=excluded.updated_at""",
            (case_id, user_id, latest["message_id"], current_time())
        )
        db.commit()
    db.close()


def mark_case_notifications_read(case_id, user_id):
    db = get_db()
    db.execute(
        "UPDATE notifications SET is_read=1 WHERE case_id=? AND user_id=?",
        (case_id, user_id)
    )
    db.commit()
    db.close()


def mark_all_notifications_read_for_user(user_id, role):
    db = get_db()
    db.execute(
        "UPDATE notifications SET is_read=1 WHERE user_id=?",
        (user_id,)
    )

    sender = {"user": "authority", "authority": "complainant"}.get(role)

    if sender:
        if role == "user":
            cases = db.execute(
                "SELECT case_id FROM complaints WHERE user_id=?",
                (user_id,)
            ).fetchall()
        else:
            authority = get_authority(db, user_id)
            cases = []
            if authority:
                cases = db.execute(
                    "SELECT case_id FROM complaints WHERE organization_id=?",
                    (authority["organization_id"],)
                ).fetchall()

        for case in cases:
            latest = db.execute(
                """SELECT MAX(id) message_id FROM case_messages
                   WHERE case_id=? AND sender_role=?""",
                (case["case_id"], sender)
            ).fetchone()

            if latest["message_id"]:
                db.execute(
                    """INSERT INTO message_reads
                       (case_id,user_id,last_read_message_id,updated_at)
                       VALUES(?,?,?,?)
                       ON CONFLICT(case_id,user_id) DO UPDATE SET
                       last_read_message_id=excluded.last_read_message_id,
                       updated_at=excluded.updated_at""",
                    (
                        case["case_id"], user_id,
                        latest["message_id"], current_time()
                    )
                )

    db.commit()
    db.close()


# =========================================================
# HOME / AUTH
# =========================================================

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    error = None

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        organization_id = request.form.get("organization_id")

        if not all([full_name, username, password, organization_id]):
            error = "Full name, username, password and organization are required."
        elif len(full_name) > 100:
            error = "Full name is too long."
        elif not 3 <= len(username) <= 50:
            error = "Username must contain 3-50 characters."
        elif len(password) < 6:
            error = "Password must contain at least 6 characters."
        else:
            db = get_db()
            org = db.execute(
                "SELECT id FROM organizations WHERE id=?",
                (organization_id,)
            ).fetchone()

            if not org:
                error = "Invalid organization selected."
                db.close()
            else:
                try:
                    db.execute(
                        """INSERT INTO users
                           (username,password_hash,role,organization_id,created_at)
                           VALUES(?,?,?,?,?)""",
                        (
                            username,
                            generate_password_hash(password),
                            "user",
                            organization_id,
                            current_time()
                        )
                    )

                    user_id = db.execute(
                        "SELECT last_insert_rowid()"
                    ).fetchone()[0]

                    db.execute(
                        """INSERT INTO identity_vault
                           (user_id,full_name,email,phone,created_at)
                           VALUES(?,?,?,?,?)""",
                        (
                            user_id, full_name,
                            email, phone, current_time()
                        )
                    )

                    db.commit()
                    db.close()
                    return redirect(url_for("login"))

                except sqlite3.IntegrityError:
                    db.close()
                    error = "Username already exists."

    db = get_db()
    organizations = db.execute(
        "SELECT * FROM organizations ORDER BY name"
    ).fetchall()
    db.close()

    return render_template(
        "register.html",
        organizations=organizations,
        error=error
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=?",
            (username,)
        ).fetchone()
        db.close()

        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]

            if user["role"] == "authority":
                return redirect(url_for("authority_dashboard"))

            return redirect(url_for("home"))

        error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# =========================================================
# COMPLAINT
# =========================================================

@app.route("/complaint", methods=["GET", "POST"])
def complaint():
    if not logged_in():
        return redirect(url_for("login"))

    db = get_db()
    organizations = db.execute(
        "SELECT id,name,sector FROM organizations ORDER BY name"
    ).fetchall()
    db.close()

    if request.method == "GET":
        return render_template(
            "complaint.html",
            organizations=organizations
        )

    complaint_type = request.form.get(
        "complaint_type", "Individual"
    ).strip()
    organization_id = request.form.get("organization_id", "").strip()
    institution = request.form.get("institution", "").strip()
    unit = request.form.get("unit", "").strip()
    category = request.form.get("category", "").strip()
    incident_date = request.form.get("incident_date", "").strip()
    description = request.form.get("description", "").strip()
    privacy_mode = request.form.get("privacy_mode", "").strip().lower()

    def error_page(message):
        return render_template(
            "complaint.html",
            organizations=organizations,
            error=message
        )

    if privacy_mode not in {"confidential", "identified"}:
        return error_page("Please select a valid privacy preference.")
    if not organization_id:
        return error_page("Please select a section.")
    if not institution:
        return error_page("Institution name is required.")
    if not category:
        return error_page("Please select a category.")
    if not description:
        return error_page("Complaint description is required.")
    if len(description) > 10000:
        return error_page("Complaint description is too long.")

    db = get_db()
    organization = db.execute(
        "SELECT id,name,sector FROM organizations WHERE id=?",
        (organization_id,)
    ).fetchone()

    if not organization:
        db.close()
        return error_page("Invalid section selected.")

    prefix = {
        "School": "SCH",
        "Hospital": "HOS",
        "NCC": "NCC"
    }.get(organization["sector"], "GEN")

    while True:
        case_id = prefix + "-" + secrets.token_hex(4).upper()
        if not db.execute(
            "SELECT id FROM complaints WHERE case_id=?",
            (case_id,)
        ).fetchone():
            break

    created_at = current_time()

    db.execute(
        """INSERT INTO complaints
           (case_id,complaint_type,institution,unit,category,
            incident_date,description,status,created_at,user_id,
            privacy_mode,organization_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            case_id, complaint_type, institution, unit,
            category, incident_date, description,
            "Submitted", created_at,
            session["user_id"], privacy_mode,
            organization["id"]
        )
    )

    db.execute(
        """INSERT INTO case_events
           (case_id,event,description,created_at)
           VALUES(?,?,?,?)""",
        (
            case_id,
            "Complaint Submitted",
            "The grievance was successfully submitted through the portal.",
            created_at
        )
    )

    for authority in db.execute(
        """SELECT id FROM users
           WHERE role='authority' AND organization_id=?""",
        (organization["id"],)
    ).fetchall():
        create_notification(
            db,
            authority["id"],
            case_id,
            "new_complaint",
            "New Grievance Submitted",
            f"A new grievance {case_id} was submitted."
        )

    db.commit()
    db.close()

    return render_template(
        "confirmation.html",
        case_id=case_id
    )


# =========================================================
# TRACK / MY COMPLAINTS
# =========================================================

@app.route("/track", methods=["GET", "POST"])
def track():
    if not logged_in():
        return redirect(url_for("login"))

    complaint_data = None
    events = []
    error = None

    if request.method == "POST":
        case_id = request.form.get("case_id", "").strip().upper()

        if not case_id:
            error = "Please enter a Case ID."
        else:
            db = get_db()

            if session.get("role") == "authority":
                authority = get_authority(db)
                if authority:
                    complaint_data = db.execute(
                        """SELECT * FROM complaints
                           WHERE case_id=? AND organization_id=?""",
                        (case_id, authority["organization_id"])
                    ).fetchone()
            else:
                complaint_data = db.execute(
                    """SELECT * FROM complaints
                       WHERE case_id=? AND user_id=?""",
                    (case_id, session["user_id"])
                ).fetchone()

            if complaint_data:
                events = db.execute(
                    """SELECT event,description,created_at
                       FROM case_events WHERE case_id=? ORDER BY id""",
                    (case_id,)
                ).fetchall()
            else:
                error = "No case found with that Case ID."

            db.close()

    return render_template(
        "track.html",
        complaint=complaint_data,
        events=events,
        error=error
    )


@app.route("/my-complaints")
def my_complaints():
    if not logged_in():
        return redirect(url_for("login"))

    db = get_db()
    complaints = db.execute(
        """SELECT c.*,o.name organization_name
           FROM complaints c LEFT JOIN organizations o
             ON c.organization_id=o.id
           WHERE c.user_id=? ORDER BY c.created_at DESC""",
        (session["user_id"],)
    ).fetchall()
    db.close()

    result = []
    for row in complaints:
        data = dict(row)
        data["unread_count"] = get_case_unread_count(
            data["case_id"], session["user_id"], "user"
        )
        result.append(data)

    return render_template(
        "my_complaints.html",
        complaints=result
    )


@app.route("/my-complaints/<case_id>")
def my_complaint_case(case_id):
    if not logged_in():
        return redirect(url_for("login"))

    case_id = case_id.strip().upper()
    check_escalation_agent(case_id)

    db = get_db()

    complaint_data = db.execute(
        """SELECT c.*,o.name organization_name,o.sector
           FROM complaints c LEFT JOIN organizations o
             ON c.organization_id=o.id
           WHERE c.case_id=? AND c.user_id=?""",
        (case_id, session["user_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    events = db.execute(
        """SELECT event,description,created_at
           FROM case_events WHERE case_id=? ORDER BY id""",
        (case_id,)
    ).fetchall()

    messages = db.execute(
        "SELECT * FROM case_messages WHERE case_id=? ORDER BY id",
        (case_id,)
    ).fetchall()

    alerts = db.execute(
        """SELECT alert_type,status,reason,created_at
           FROM escalation_alerts WHERE case_id=? ORDER BY id DESC""",
        (case_id,)
    ).fetchall()

    db.close()

    mark_case_messages_read(case_id, session["user_id"], "user")
    mark_case_notifications_read(case_id, session["user_id"])

    return render_template(
        "my_complaint_case.html",
        complaint=complaint_data,
        events=events,
        messages=messages,
        escalation_alerts=alerts
    )


@app.route("/my-complaints/<case_id>/message", methods=["POST"])
def complainant_send_message(case_id):
    if not logged_in():
        return redirect(url_for("login"))

    case_id = case_id.strip().upper()
    message = request.form.get("message", "").strip()

    if not message or len(message) > 5000:
        return redirect(url_for("my_complaint_case", case_id=case_id))

    db = get_db()

    complaint_data = db.execute(
        """SELECT status,organization_id FROM complaints
           WHERE case_id=? AND user_id=?""",
        (case_id, session["user_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    if complaint_data["status"] == "Closed":
        db.close()
        return redirect(url_for("my_complaint_case", case_id=case_id))

    created_at = current_time()

    db.execute(
        """INSERT INTO case_messages
           (case_id,sender_role,sender_user_id,message,created_at)
           VALUES(?,?,?,?,?)""",
        (
            case_id, "complainant",
            session["user_id"], message, created_at
        )
    )

    db.execute(
        """INSERT INTO case_events
           (case_id,event,description,created_at)
           VALUES(?,?,?,?)""",
        (
            case_id,
            "Complainant Response",
            "The complainant added a response to the case.",
            created_at
        )
    )

    for authority in db.execute(
        """SELECT id FROM users
           WHERE role='authority' AND organization_id=?""",
        (complaint_data["organization_id"],)
    ).fetchall():
        create_notification(
            db,
            authority["id"],
            case_id,
            "complainant_message",
            "New Complainant Message",
            f"The complainant added a new message to case {case_id}."
        )

    db.commit()
    db.close()

    return redirect(url_for("my_complaint_case", case_id=case_id))


# =========================================================
# AUTHORITY DASHBOARD
# =========================================================

@app.route("/authority/dashboard")
def authority_dashboard():
    if not authority_session():
        return redirect(url_for("home"))

    check_escalation_agent()

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        session.clear()
        return redirect(url_for("login"))

    org_id = authority["organization_id"]

    organization = db.execute(
        "SELECT name,sector FROM organizations WHERE id=?",
        (org_id,)
    ).fetchone()

    complaints = db.execute(
        """SELECT * FROM complaints
           WHERE organization_id=? ORDER BY created_at DESC""",
        (org_id,)
    ).fetchall()

    total = db.execute(
        "SELECT COUNT(*) count FROM complaints WHERE organization_id=?",
        (org_id,)
    ).fetchone()["count"]

    pending = db.execute(
        """SELECT COUNT(*) count FROM complaints
           WHERE organization_id=? AND status IN('Submitted','Under Review')""",
        (org_id,)
    ).fetchone()["count"]

    in_progress = db.execute(
        """SELECT COUNT(*) count FROM complaints
           WHERE organization_id=? AND status='In Progress'""",
        (org_id,)
    ).fetchone()["count"]

    resolved = db.execute(
        """SELECT COUNT(*) count FROM complaints
           WHERE organization_id=? AND status IN('Resolved','Closed')""",
        (org_id,)
    ).fetchone()["count"]

    escalated = db.execute(
        """SELECT COUNT(*) count FROM complaints
           WHERE organization_id=? AND status='Escalated'""",
        (org_id,)
    ).fetchone()["count"]

    db.close()

    result = []
    for row in complaints:
        data = dict(row)
        data["unread_count"] = get_case_unread_count(
            data["case_id"], session["user_id"], "authority"
        )
        result.append(data)

    stats = {
        "total": total,
        "pending": pending,
        "in_progress": in_progress,
        "resolved": resolved,
        "escalated": escalated
    }

    return render_template(
        "authority_dashboard.html",
        complaints=result,
        organization_name=organization["name"] if organization else "Organization",
        sector=organization["sector"] if organization else "",
        stats=stats,
        total=total,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved
    )


# =========================================================
# AUTHORITY CASE
# =========================================================

@app.route("/authority/case/<case_id>")
def authority_case(case_id):
    if not authority_session():
        return redirect(url_for("home"))

    case_id = case_id.strip().upper()
    check_escalation_agent(case_id)

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("home"))

    complaint_data = db.execute(
        """SELECT c.*,o.name organization_name,o.sector
           FROM complaints c LEFT JOIN organizations o
             ON c.organization_id=o.id
           WHERE c.case_id=? AND c.organization_id=?""",
        (case_id, authority["organization_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    privacy = complaint_data["privacy_mode"]
    identity = None
    identity_hidden = True
    can_reveal_identity = False

    if privacy == "identified":
        identity_hidden = False
        if complaint_data["user_id"]:
            identity = db.execute(
                """SELECT full_name,email,phone FROM identity_vault
                   WHERE user_id=?""",
                (complaint_data["user_id"],)
            ).fetchone()

    elif privacy == "confidential":
        disclosure = db.execute(
            "SELECT id FROM identity_disclosures WHERE case_id=? LIMIT 1",
            (case_id,)
        ).fetchone()

        if disclosure:
            identity_hidden = False
            if complaint_data["user_id"]:
                identity = db.execute(
                    """SELECT full_name,email,phone FROM identity_vault
                       WHERE user_id=?""",
                    (complaint_data["user_id"],)
                ).fetchone()
        else:
            can_reveal_identity = True

    events = db.execute(
        """SELECT event,description,created_at FROM case_events
           WHERE case_id=? ORDER BY id DESC""",
        (case_id,)
    ).fetchall()

    messages = db.execute(
        "SELECT * FROM case_messages WHERE case_id=? ORDER BY id",
        (case_id,)
    ).fetchall()

    alerts = db.execute(
        """SELECT alert_type,status,reason,created_at
           FROM escalation_alerts WHERE case_id=? ORDER BY id DESC""",
        (case_id,)
    ).fetchall()

    db.close()

    mark_case_messages_read(case_id, session["user_id"], "authority")
    mark_case_notifications_read(case_id, session["user_id"])

    return render_template(
        "authority_case.html",
        complaint=complaint_data,
        events=events,
        messages=messages,
        identity=identity,
        identity_hidden=identity_hidden,
        can_reveal_identity=can_reveal_identity,
        escalation_alerts=alerts
    )


# =========================================================
# STATUS
# =========================================================

STATUS_TRANSITIONS = {
    "Submitted": ["Under Review", "Escalated"],
    "Under Review": ["In Progress", "Escalated"],
    "In Progress": ["Resolved", "Escalated"],
    "Escalated": ["Under Review", "In Progress"],
    "Resolved": ["Closed"],
    "Closed": []
}


@app.route("/authority/case/<case_id>/status", methods=["POST"])
def authority_update_status(case_id):
    if not authority_session():
        return redirect(url_for("home"))

    case_id = case_id.strip().upper()
    new_status = request.form.get("status", "").strip()

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("home"))

    complaint_data = db.execute(
        """SELECT case_id,status,user_id FROM complaints
           WHERE case_id=? AND organization_id=?""",
        (case_id, authority["organization_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    old_status = complaint_data["status"]

    if new_status not in STATUS_TRANSITIONS.get(old_status, []):
        db.close()
        return redirect(url_for("authority_case", case_id=case_id))

    created_at = current_time()

    db.execute(
        """UPDATE complaints SET status=?
           WHERE case_id=? AND organization_id=?""",
        (new_status, case_id, authority["organization_id"])
    )

    db.execute(
        """INSERT INTO case_events
           (case_id,event,description,created_at)
           VALUES(?,?,?,?)""",
        (
            case_id,
            "Status Changed",
            f"Status changed from {old_status} to {new_status} by authority.",
            created_at
        )
    )

    if complaint_data["user_id"]:
        create_notification(
            db,
            complaint_data["user_id"],
            case_id,
            "status_change",
            "Case Status Updated",
            f"Your case {case_id} status changed from "
            f"{old_status} to {new_status}."
        )

    db.commit()
    db.close()

    return redirect(url_for("authority_case", case_id=case_id))


# =========================================================
# AUTHORITY MESSAGE
# =========================================================

@app.route("/authority/case/<case_id>/message", methods=["POST"])
def authority_send_message(case_id):
    if not authority_session():
        return redirect(url_for("home"))

    case_id = case_id.strip().upper()
    message = request.form.get("message", "").strip()

    if not message or len(message) > 5000:
        return redirect(url_for("authority_case", case_id=case_id))

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("home"))

    complaint_data = db.execute(
        """SELECT status,user_id FROM complaints
           WHERE case_id=? AND organization_id=?""",
        (case_id, authority["organization_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    if complaint_data["status"] == "Closed":
        db.close()
        return redirect(url_for("authority_case", case_id=case_id))

    created_at = current_time()

    db.execute(
        """INSERT INTO case_messages
           (case_id,sender_role,sender_user_id,message,created_at)
           VALUES(?,?,?,?,?)""",
        (
            case_id, "authority",
            session["user_id"], message, created_at
        )
    )

    db.execute(
        """INSERT INTO case_events
           (case_id,event,description,created_at)
           VALUES(?,?,?,?)""",
        (
            case_id,
            "Authority Response",
            "The authority added a response to the case.",
            created_at
        )
    )

    if complaint_data["user_id"]:
        create_notification(
            db,
            complaint_data["user_id"],
            case_id,
            "authority_message",
            "New Authority Message",
            f"The authority sent a new message for case {case_id}."
        )

    db.commit()
    db.close()

    return redirect(url_for("authority_case", case_id=case_id))


# =========================================================
# IDENTITY DISCLOSURE
# =========================================================

@app.route("/authority/case/<case_id>/reveal-identity", methods=["POST"])
def reveal_identity(case_id):
    if not authority_session():
        return redirect(url_for("home"))

    case_id = case_id.strip().upper()
    reason = request.form.get("reason", "").strip()

    if not reason or len(reason) > 1000:
        return redirect(url_for("authority_case", case_id=case_id))

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("home"))

    complaint_data = db.execute(
        """SELECT privacy_mode FROM complaints
           WHERE case_id=? AND organization_id=?""",
        (case_id, authority["organization_id"])
    ).fetchone()

    if not complaint_data:
        db.close()
        return "Case not found", 404

    if complaint_data["privacy_mode"] != "confidential":
        db.close()
        return redirect(url_for("authority_case", case_id=case_id))

    existing = db.execute(
        "SELECT id FROM identity_disclosures WHERE case_id=? LIMIT 1",
        (case_id,)
    ).fetchone()

    if not existing:
        created_at = current_time()

        db.execute(
            """INSERT INTO identity_disclosures
               (case_id,disclosed_by,reason,created_at)
               VALUES(?,?,?,?)""",
            (case_id, session["user_id"], reason, created_at)
        )

        db.execute(
            """INSERT INTO case_events
               (case_id,event,description,created_at)
               VALUES(?,?,?,?)""",
            (
                case_id,
                "Identity Disclosed",
                "Complainant identity was disclosed to an authorized authority.",
                created_at
            )
        )

    db.commit()
    db.close()

    return redirect(url_for("authority_case", case_id=case_id))


# =========================================================
# VERIFICATION
# =========================================================

@app.route("/verification", methods=["GET", "POST"])
def verification():
    if not logged_in() or session.get("role") != "user":
        return redirect(url_for("login"))

    db = get_db()

    organizations = db.execute(
        "SELECT id,name,sector FROM organizations ORDER BY name"
    ).fetchall()

    existing = db.execute(
        """SELECT v.*,o.name organization_name
           FROM verifications v
           JOIN organizations o ON v.organization_id=o.id
           WHERE v.user_id=?
           ORDER BY v.id DESC""",
        (session["user_id"],)
    ).fetchall()

    if request.method == "POST":
        organization_id = request.form.get(
            "organization_id", ""
        ).strip()

        method = request.form.get(
            "verification_method", ""
        ).strip()

        if not organization_id or not method:
            db.close()
            return render_template(
                "verification.html",
                organizations=organizations,
                verifications=existing,
                error="Select an organization and verification method."
            )

        organization = db.execute(
            "SELECT id,name FROM organizations WHERE id=?",
            (organization_id,)
        ).fetchone()

        if not organization:
            db.close()
            return render_template(
                "verification.html",
                organizations=organizations,
                verifications=existing,
                error="Invalid organization selected."
            )

        pending = db.execute(
            """SELECT id FROM verifications
               WHERE user_id=? AND organization_id=?
               AND verification_status='Pending'""",
            (session["user_id"], organization_id)
        ).fetchone()

        if pending:
            db.close()
            return render_template(
                "verification.html",
                organizations=organizations,
                verifications=existing,
                error="A verification request is already pending."
            )

        created_at = current_time()

        db.execute(
            """INSERT INTO verifications
               (user_id,organization_id,verification_method,
                verification_status,verified_at,created_at)
               VALUES(?,?,?,?,?,?)""",
            (
                session["user_id"],
                organization_id,
                method,
                "Pending",
                None,
                created_at
            )
        )

        request_id = db.execute(
            "SELECT last_insert_rowid()"
        ).fetchone()[0]

        authorities = db.execute(
            """SELECT id FROM users
               WHERE role='authority' AND organization_id=?""",
            (organization_id,)
        ).fetchall()

        for authority in authorities:
            create_notification(
                db,
                authority["id"],
                None,
                "verification_request",
                "New Verification Request",
                f"A user submitted verification request #{request_id}."
            )

        db.commit()
        db.close()

        return redirect(url_for("verification"))

    db.close()

    return render_template(
        "verification.html",
        organizations=organizations,
        verifications=existing
    )


@app.route("/authority/verifications")
def authority_verifications():
    if not authority_session():
        return redirect(url_for("home"))

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("login"))

    verifications = db.execute(
        """SELECT v.id,v.user_id,v.verification_method,
                  v.verification_status,v.verified_at,v.created_at,
                  u.username,o.name organization_name,
                  iv.full_name,iv.email,iv.phone
           FROM verifications v
           JOIN users u ON v.user_id=u.id
           JOIN organizations o ON v.organization_id=o.id
           LEFT JOIN identity_vault iv ON v.user_id=iv.user_id
           WHERE v.organization_id=?
           ORDER BY
             CASE WHEN v.verification_status='Pending' THEN 0 ELSE 1 END,
             v.id DESC""",
        (authority["organization_id"],)
    ).fetchall()

    db.close()

    return render_template(
        "authority_verifications.html",
        verifications=verifications
    )


@app.route(
    "/authority/verifications/<int:verification_id>/status",
    methods=["POST"]
)
def authority_update_verification(verification_id):
    if not authority_session():
        return redirect(url_for("home"))

    new_status = request.form.get("status", "").strip()

    if new_status not in {"Verified", "Rejected"}:
        return redirect(url_for("authority_verifications"))

    db = get_db()
    authority = get_authority(db)

    if not authority:
        db.close()
        return redirect(url_for("login"))

    verification = db.execute(
        """SELECT id,user_id,organization_id,verification_status
           FROM verifications
           WHERE id=? AND organization_id=?""",
        (verification_id, authority["organization_id"])
    ).fetchone()

    if not verification:
        db.close()
        return "Verification request not found", 404

    if verification["verification_status"] != "Pending":
        db.close()
        return redirect(url_for("authority_verifications"))

    verified_at = current_time() if new_status == "Verified" else None

    db.execute(
        """UPDATE verifications
           SET verification_status=?,verified_at=?
           WHERE id=? AND organization_id=?""",
        (
            new_status,
            verified_at,
            verification_id,
            authority["organization_id"]
        )
    )

    title = (
        "Verification Approved"
        if new_status == "Verified"
        else "Verification Rejected"
    )

    message = (
        "Your verification request has been approved."
        if new_status == "Verified"
        else "Your verification request was rejected."
    )

    create_notification(
        db,
        verification["user_id"],
        None,
        "verification_update",
        title,
        message
    )

    db.commit()
    db.close()

    return redirect(url_for("authority_verifications"))


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/notifications", endpoint="notifications")
@app.route("/notifications", endpoint="notifications_page")
def notifications_page():
    if not logged_in():
        return redirect(url_for("login"))

    check_escalation_agent()

    user_id = session["user_id"]
    role = session.get("role")

    db = get_db()
    notifications = []

    system = db.execute(
        """SELECT id,case_id,notification_type,title,message,
                  created_at,is_read
           FROM notifications WHERE user_id=?
           ORDER BY id DESC""",
        (user_id,)
    ).fetchall()

    for item in system:
        notifications.append({
            "id": item["id"],
            "case_id": item["case_id"],
            "notification_type": item["notification_type"],
            "title": item["title"],
            "message": item["message"],
            "created_at": item["created_at"],
            "sender": "System",
            "source": "system",
            "is_read": item["is_read"]
        })

    if role == "user":
        messages = db.execute(
            """SELECT m.id,m.case_id,m.message,m.created_at,c.category
               FROM case_messages m JOIN complaints c
                 ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.user_id=? AND m.sender_role='authority'
                 AND m.id>COALESCE(r.last_read_message_id,0)
               ORDER BY m.id DESC""",
            (user_id, user_id)
        ).fetchall()

        for item in messages:
            notifications.append({
                "id": item["id"],
                "case_id": item["case_id"],
                "notification_type": "message",
                "title": "New Authority Message",
                "message": item["message"],
                "created_at": item["created_at"],
                "category": item["category"],
                "sender": "Authority",
                "source": "message",
                "is_read": 0
            })

    elif role == "authority":
        authority = get_authority(db)

        if authority:
            messages = db.execute(
                """SELECT m.id,m.case_id,m.message,m.created_at,c.category
                   FROM case_messages m JOIN complaints c
                     ON m.case_id=c.case_id
                   LEFT JOIN message_reads r
                     ON r.case_id=m.case_id AND r.user_id=?
                   WHERE c.organization_id=?
                     AND m.sender_role='complainant'
                     AND m.id>COALESCE(r.last_read_message_id,0)
                   ORDER BY m.id DESC""",
                (user_id, authority["organization_id"])
            ).fetchall()

            for item in messages:
                notifications.append({
                    "id": item["id"],
                    "case_id": item["case_id"],
                    "notification_type": "message",
                    "title": "New Complainant Message",
                    "message": item["message"],
                    "created_at": item["created_at"],
                    "category": item["category"],
                    "sender": "Complainant",
                    "source": "message",
                    "is_read": 0
                })

    db.close()
    notifications.sort(key=lambda x: x["created_at"], reverse=True)

    return render_template(
        "notifications.html",
        notifications=notifications
    )


@app.route("/notifications/read/<int:notification_id>", methods=["POST"])
def mark_notification_read(notification_id):
    if not logged_in():
        return redirect(url_for("login"))

    db = get_db()

    notification = db.execute(
        "SELECT case_id FROM notifications WHERE id=? AND user_id=?",
        (notification_id, session["user_id"])
    ).fetchone()

    db.execute(
        """UPDATE notifications SET is_read=1
           WHERE id=? AND user_id=?""",
        (notification_id, session["user_id"])
    )

    db.commit()
    db.close()

    if notification and notification["case_id"]:
        if session.get("role") == "authority":
            return redirect(
                url_for(
                    "authority_case",
                    case_id=notification["case_id"]
                )
            )

        return redirect(
            url_for(
                "my_complaint_case",
                case_id=notification["case_id"]
            )
        )

    return redirect(url_for("notifications_page"))


@app.route("/notifications/mark-all-read", methods=["POST"])
def mark_all_notifications_read():
    if not logged_in():
        return redirect(url_for("login"))

    mark_all_notifications_read_for_user(
        session["user_id"],
        session.get("role")
    )

    return redirect(url_for("notifications_page"))


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    init_db()
    app.run(debug=True)