"""General Grievance Portal.

Flask + SQLite grievance management for School, Hospital and NCC sections.
See README.md for configuration, migration and test instructions.
"""

import csv
import hmac
import io
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from functools import wraps

import click
from flask import (
    Flask, Response, abort, flash, g, redirect, render_template,
    request, session, url_for
)
from werkzeug.security import check_password_hash, generate_password_hash


# =========================================================
# CONFIGURATION
# =========================================================

APP_ENV = os.environ.get("APP_ENV", "development").strip().lower()
IS_PRODUCTION = APP_ENV == "production"

app = Flask(__name__)

_secret_key = os.environ.get("SECRET_KEY", "").strip()

if not _secret_key:
    if IS_PRODUCTION:
        raise RuntimeError(
            "SECRET_KEY must be set when APP_ENV=production."
        )
    # Development only: random per process. Sessions reset on restart.
    _secret_key = secrets.token_hex(32)

app.secret_key = _secret_key

app.config.update(
    DATABASE=os.environ.get("DATABASE_PATH", "complaints.db"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=(
        os.environ.get("COOKIE_SECURE", "1" if IS_PRODUCTION else "0") == "1"
    ),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    MAX_CONTENT_LENGTH=64 * 1024
)

MIN_DISCLOSURE_REASON = 20
MAX_DISCLOSURE_REASON = 1000
MAX_MESSAGE_LENGTH = 2000
MAX_DESCRIPTION_LENGTH = 10000
MIN_DESCRIPTION_LENGTH = 10
MIN_PASSWORD_LENGTH = 8

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^[0-9+()\-\s]{7,20}$")
CASE_ID_RE = re.compile(r"^[A-Z0-9-]{3,30}$")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

SECTOR_CATEGORIES = {
    "NCC": [
        "Training concern", "Attendance concern", "Unfair treatment",
        "Misuse of authority", "Harassment or intimidation",
        "Disciplinary concern", "Camp-related concern",
        "Administrative concern", "Other"
    ],
    "School": [
        "Academic concern", "Teacher / Staff concern", "Student concern",
        "Unfair treatment", "Harassment or intimidation",
        "Disciplinary concern", "Infrastructure / Facilities",
        "Administrative concern", "Other"
    ],
    "Hospital": [
        "Medical service concern", "Doctor / Staff concern",
        "Patient service", "Unfair treatment",
        "Harassment or intimidation", "Waiting time",
        "Infrastructure / Facilities", "Administrative concern", "Other"
    ]
}

# Verification is MANUAL. No document is uploaded or machine-checked, and
# no email is sent. "proves" states exactly what an approval means.
VERIFICATION_METHODS = {
    "Institutional ID": {
        "reference_label": "ID / registration number",
        "proves": (
            "An authority of the organization compared the ID or "
            "registration number you entered with the organization's own "
            "records and found a matching member. It does not validate any "
            "document (none is uploaded)."
        )
    },
    "Official Email": {
        "reference_label": "Official email address",
        "proves": (
            "An authority found this address in the organization's own "
            "directory. No confirmation email is sent, so it does not prove "
            "you control the mailbox."
        )
    },
    "Staff Confirmation": {
        "reference_label": "Name and role of a staff member who knows you",
        "proves": (
            "An authority of the organization confirmed with the named "
            "person that you are associated with the organization. It "
            "depends on that person's word."
        )
    }
}
MAX_REFERENCE_LENGTH = 100
MAX_REVIEW_NOTE_LENGTH = 300

PRIORITIES = ["Low", "Normal", "High", "Urgent"]
PRIORITY_RANK = {name: index for index, name in enumerate(PRIORITIES)}
CASES_PER_PAGE = 20
COMPLAINT_TYPES = {"Individual", "Group"}
PRIVACY_MODES = {"confidential", "identified"}


# =========================================================
# DATABASE
# =========================================================

def get_db():
    db = sqlite3.connect(app.config["DATABASE"], timeout=10)
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


BASE_TABLES = [
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
        created_at TEXT NOT NULL)""",

    """CREATE TABLE IF NOT EXISTS schema_migrations(
        version INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at TEXT NOT NULL)"""
]


def table_columns(db, table):
    return {
        row["name"] for row in db.execute(f"PRAGMA table_info({table})")
    }


def add_column(db, table, column, definition):
    if column not in table_columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def migration_1_legacy_columns(db):
    """Columns added by earlier versions of the portal."""
    add_column(db, "complaints", "user_id", "INTEGER")
    add_column(
        db, "complaints", "privacy_mode",
        "TEXT NOT NULL DEFAULT 'confidential'"
    )
    add_column(db, "complaints", "organization_id", "INTEGER")


def migration_2_indexes(db):
    for statement in [
        "CREATE INDEX IF NOT EXISTS idx_complaints_user ON complaints(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_complaints_org ON complaints(organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_complaints_status ON complaints(status)",
        "CREATE INDEX IF NOT EXISTS idx_events_case ON case_events(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_case ON case_messages(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(user_id,is_read)",
        "CREATE INDEX IF NOT EXISTS idx_disclosures_case ON identity_disclosures(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_alerts_case ON escalation_alerts(case_id)",
        "CREATE INDEX IF NOT EXISTS idx_verifications_user_org ON verifications(user_id,organization_id)",
        "CREATE INDEX IF NOT EXISTS idx_verifications_org_status ON verifications(organization_id,verification_status)"
    ]:
        db.execute(statement)


def migration_3_verification_review(db):
    """Reference detail and review audit fields for verifications."""
    add_column(db, "verifications", "reference_detail", "TEXT")
    add_column(db, "verifications", "reviewed_by", "INTEGER")
    add_column(db, "verifications", "reviewed_at", "TEXT")
    add_column(db, "verifications", "review_note", "TEXT")

    try:
        db.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS idx_verifications_one_pending
               ON verifications(user_id,organization_id)
               WHERE verification_status='Pending'"""
        )
    except sqlite3.IntegrityError:
        # Existing duplicate pending rows: keep data untouched. The route
        # still refuses new duplicates.
        pass


def migration_4_alert_action(db):
    """Separate recommended next action on escalation alerts."""
    add_column(db, "escalation_alerts", "recommended_action", "TEXT")


def migration_5_reporting(db):
    """Priority, resolution time and actor attribution for reporting."""
    add_column(db, "complaints", "priority", "TEXT NOT NULL DEFAULT 'Normal'")
    add_column(db, "complaints", "resolved_at", "TEXT")
    add_column(db, "case_events", "actor_user_id", "INTEGER")

    # Backfill resolution time from the existing status history.
    db.execute(
        """UPDATE complaints SET resolved_at=(
               SELECT MIN(e.created_at) FROM case_events e
               WHERE e.case_id=complaints.case_id
                 AND e.event='Status Changed'
                 AND e.description LIKE '% to Resolved by authority.')
           WHERE resolved_at IS NULL AND status IN('Resolved','Closed')"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_complaints_created ON complaints(created_at)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_events_actor ON case_events(actor_user_id)"
    )


MIGRATIONS = [
    (1, "legacy complaint columns", migration_1_legacy_columns),
    (2, "lookup indexes", migration_2_indexes),
    (3, "verification reference and review audit",
     migration_3_verification_review),
    (4, "escalation alert recommended action", migration_4_alert_action),
    (5, "priority, resolution time, event actors", migration_5_reporting)
]


def apply_migrations(db):
    applied = {
        row["version"] for row in
        db.execute("SELECT version FROM schema_migrations")
    }

    for version, description, function in MIGRATIONS:
        if version in applied:
            continue
        function(db)
        db.execute(
            """INSERT INTO schema_migrations(version,description,applied_at)
               VALUES(?,?,?)""",
            (version, description, current_time())
        )


def normalize_organizations(db):
    now = current_time()

    if not db.execute("SELECT id FROM organizations LIMIT 1").fetchone():
        db.executemany(
            "INSERT INTO organizations(name,sector,created_at) VALUES(?,?,?)",
            [("School", "School", now),
             ("Hospital", "Hospital", now),
             ("NCC", "NCC", now)]
        )
        return

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

    for name, sector in [("School", "School"),
                         ("Hospital", "Hospital"),
                         ("NCC", "NCC")]:
        if not db.execute(
            "SELECT id FROM organizations WHERE sector=? LIMIT 1",
            (sector,)
        ).fetchone():
            db.execute(
                "INSERT INTO organizations(name,sector,created_at) VALUES(?,?,?)",
                (name, sector, now)
            )


def backfill_complaint_organizations(db):
    for prefix, sector in [("SCH", "School"),
                           ("HOS", "Hospital"),
                           ("NCC", "NCC")]:
        db.execute(
            """UPDATE complaints SET organization_id=(
                   SELECT id FROM organizations WHERE sector=? LIMIT 1)
               WHERE organization_id IS NULL AND case_id LIKE ?""",
            (sector, prefix + "-%")
        )


SEEDED_AUTHORITIES = [
    ("school_authority", "School"),
    ("hospital_authority", "Hospital"),
    ("ncc_authority", "NCC")
]


def seed_authorities(db):
    """Create demo authority accounts only when SEED_AUTHORITY_PASSWORD is
    set. Existing accounts keep their password; only the organization link
    is repaired."""
    seed_password = os.environ.get("SEED_AUTHORITY_PASSWORD", "")
    can_create = len(seed_password) >= 10

    if seed_password and not can_create:
        print(
            "SEED_AUTHORITY_PASSWORD ignored: use at least 10 characters.",
            file=sys.stderr
        )

    for username, sector in SEEDED_AUTHORITIES:
        org = db.execute(
            "SELECT id FROM organizations WHERE sector=? LIMIT 1",
            (sector,)
        ).fetchone()

        if not org:
            continue

        existing = db.execute(
            "SELECT id FROM users WHERE username=?", (username,)
        ).fetchone()

        if existing:
            db.execute(
                """UPDATE users SET organization_id=?
                   WHERE username=? AND role='authority'""",
                (org["id"], username)
            )
        elif can_create:
            db.execute(
                """INSERT INTO users
                   (username,password_hash,role,organization_id,created_at)
                   VALUES(?,?,?,?,?)""",
                (
                    username,
                    generate_password_hash(seed_password),
                    "authority",
                    org["id"],
                    current_time()
                )
            )


def init_db():
    """Create or upgrade the schema. Never drops or resets data."""
    with closing(get_db()) as db:
        for statement in BASE_TABLES:
            db.execute(statement)

        apply_migrations(db)
        normalize_organizations(db)
        backfill_complaint_organizations(db)
        seed_authorities(db)
        db.commit()


_READY_DATABASES = set()


@app.before_request
def ensure_database():
    path = app.config["DATABASE"]
    if path not in _READY_DATABASES:
        init_db()
        _READY_DATABASES.add(path)


# =========================================================
# SECURITY: CSRF, HEADERS, ERRORS, LOGIN THROTTLE
# =========================================================

def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def csrf_protect():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        sent = request.form.get("csrf_token", "") or \
            request.headers.get("X-CSRF-Token", "")
        expected = session.get("_csrf", "")

        if not expected or not sent or not hmac.compare_digest(
            sent.encode("utf-8"), expected.encode("utf-8")
        ):
            abort(400, description="csrf")


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; img-src 'self' data:; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
    )

    if IS_PRODUCTION and app.config["SESSION_COOKIE_SECURE"]:
        response.headers.setdefault(
            "Strict-Transport-Security",
            "max-age=31536000; includeSubDomains"
        )

    if "user_id" in session:
        response.headers["Cache-Control"] = "no-store"

    return response


ERROR_MESSAGES = {
    400: ("Request could not be completed",
          "The form expired or was invalid. Go back, refresh the page and try again."),
    403: ("Access denied", "You do not have permission to view this page."),
    404: ("Page not found", "The page or case you requested was not found."),
    405: ("Method not allowed", "This action is not allowed here."),
    413: ("Request too large", "The submitted data was too large."),
    500: ("Something went wrong", "An unexpected error occurred. Please try again later.")
}


def render_error(error, code):
    title, message = ERROR_MESSAGES.get(code, ERROR_MESSAGES[500])
    return render_template(
        "error.html", code=code, title=title, message=message
    ), code


for _code in ERROR_MESSAGES:
    app.register_error_handler(
        _code, lambda error, code=_code: render_error(error, code)
    )

_LOGIN_FAILURES = {}
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES = 5


def _login_key(username):
    return (request.remote_addr or "unknown", username.lower())


def login_is_blocked(username):
    key = _login_key(username)
    now = time.time()
    attempts = [
        stamp for stamp in _LOGIN_FAILURES.get(key, [])
        if now - stamp < LOGIN_WINDOW_SECONDS
    ]

    if attempts:
        _LOGIN_FAILURES[key] = attempts
    else:
        _LOGIN_FAILURES.pop(key, None)

    return len(attempts) >= LOGIN_MAX_FAILURES


def record_login_failure(username):
    if len(_LOGIN_FAILURES) > 10000:
        _LOGIN_FAILURES.clear()
    _LOGIN_FAILURES.setdefault(_login_key(username), []).append(time.time())


def clear_login_failures(username):
    _LOGIN_FAILURES.pop(_login_key(username), None)


DUMMY_PASSWORD_HASH = generate_password_hash(secrets.token_hex(8))


# =========================================================
# INPUT HELPERS
# =========================================================

def clean_text(value, max_length=None, multiline=False):
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = CONTROL_CHARS_RE.sub("", value)

    if multiline:
        value = "\n".join(line.rstrip() for line in value.split("\n"))
        value = re.sub(r"\n{3,}", "\n\n", value).strip()
    else:
        value = " ".join(value.split())

    if max_length is not None and len(value) > max_length:
        return value[:max_length + 1]

    return value


def to_int(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def normalize_case_id(case_id):
    case_id = (case_id or "").strip().upper()
    if not CASE_ID_RE.match(case_id):
        abort(404)
    return case_id


def valid_incident_date(value):
    if not value:
        return True
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False
    return parsed <= date.today()


# =========================================================
# ACCESS HELPERS
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


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def user_required(view):
    """Complainant (role 'user') routes."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return redirect(url_for("login"))
        if session.get("role") != "user":
            if session.get("role") == "authority":
                return redirect(url_for("authority_dashboard"))
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def authority_required(view):
    """Authority routes. Loads the authority row into g.authority."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not authority_session():
            return redirect(url_for("home"))

        with closing(get_db()) as db:
            authority = get_authority(db)

        if not authority or not authority["organization_id"]:
            session.clear()
            return redirect(url_for("login"))

        g.authority = authority
        return view(*args, **kwargs)
    return wrapper


def create_notification(db, user_id, case_id, notification_type, title, message):
    db.execute(
        """INSERT INTO notifications
           (user_id,case_id,notification_type,title,message,is_read,created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (user_id, case_id, notification_type, title, message, 0, current_time())
    )


def notify_organization_authorities(
    db, organization_id, case_id, notification_type, title, message
):
    for authority in db.execute(
        """SELECT id FROM users
           WHERE role='authority' AND organization_id=?""",
        (organization_id,)
    ).fetchall():
        create_notification(
            db, authority["id"], case_id,
            notification_type, title, message
        )


def add_case_event(
    db, case_id, event, description, created_at=None, actor_id=None
):
    db.execute(
        """INSERT INTO case_events
           (case_id,event,description,created_at,actor_user_id)
           VALUES(?,?,?,?,?)""",
        (case_id, event, description, created_at or current_time(), actor_id)
    )


def get_case_unread_count(case_id, user_id, role):
    sender = {"user": "authority", "authority": "complainant"}.get(role)
    if not sender:
        return 0

    with closing(get_db()) as db:
        row = db.execute(
            """SELECT COUNT(*) count FROM case_messages m
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE m.case_id=? AND m.sender_role=?
                 AND m.id>COALESCE(r.last_read_message_id,0)""",
            (user_id, case_id, sender)
        ).fetchone()

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


ESCALATION_ALERT_EVENT = "Escalation Agent Alert"
# Events that are not case progress and must not reset the inactivity timer.
NON_ACTIVITY_EVENTS = (ESCALATION_ALERT_EVENT, "Priority Updated")

# Lazy runs are throttled to at most one per interval per process. Set
# ESCALATION_INTERVAL_SECONDS=0 to disable lazy runs and rely on the
# `flask --app app run-escalation` command (for example from cron).
ESCALATION_INTERVAL_SECONDS = int(
    os.environ.get("ESCALATION_INTERVAL_SECONDS", "600")
)
_LAST_ESCALATION_RUN = {}


def fetch_activity_rows(db, case_id=None, organization_id=None):
    """Open cases with their latest non-alert activity (shared by the
    escalation agent and the dashboard overdue calculation)."""
    statuses = tuple(ESCALATION_RULES)
    query = f"""
        SELECT c.case_id,c.status,c.user_id,c.organization_id,c.created_at,
               (SELECT MAX(e.id) FROM case_events e
                 WHERE e.case_id=c.case_id
                   AND e.event NOT IN (?,?)) last_event_id,
               (SELECT MAX(e.created_at) FROM case_events e
                 WHERE e.case_id=c.case_id
                   AND e.event NOT IN (?,?)) last_event_at,
               (SELECT MAX(m.created_at) FROM case_messages m
                 WHERE m.case_id=c.case_id) last_message_at
        FROM complaints c
        WHERE c.status IN ({",".join("?" for _ in statuses)})
          AND c.status!='Closed'"""
    params = [*NON_ACTIVITY_EVENTS, *NON_ACTIVITY_EVENTS, *statuses]

    if case_id:
        query += " AND c.case_id=?"
        params.append(case_id)

    if organization_id:
        query += " AND c.organization_id=?"
        params.append(organization_id)

    return db.execute(query, params).fetchall()


def inactive_hours(row, now):
    stamps = [
        parse_time(value) for value in (
            row["last_event_at"], row["last_message_at"], row["created_at"]
        )
    ]
    stamps = [stamp for stamp in stamps if stamp]
    latest = max(stamps) if stamps else now
    return (now - latest).total_seconds() / 3600


def run_escalation_agent(db, case_id=None, now=None):
    """Create inactivity alerts. Never changes a complaint's status.

    Inactivity is measured from the latest case event other than an
    escalation alert, or the latest message, whichever is newer, so alerts
    never reset the timer. One alert exists per (case, status, last
    activity event); the UNIQUE constraint prevents duplicates. Closed
    cases are ignored. Returns the number of alerts created.
    """
    now = now or datetime.now()
    created_alerts = 0

    for complaint in fetch_activity_rows(db, case_id=case_id):
        threshold, action = ESCALATION_RULES[complaint["status"]]

        if inactive_hours(complaint, now) < threshold:
            continue

        alert_type = (
            complaint["status"].lower().replace(" ", "_")
            + "_inactivity_" + str(complaint["last_event_id"] or 0)
        )
        reason = (
            f"Case remained in {complaint['status']} for more than "
            f"{threshold} hours without new activity."
        )
        created_at = now.strftime("%Y-%m-%d %H:%M:%S")

        cursor = db.execute(
            """INSERT OR IGNORE INTO escalation_alerts
               (case_id,alert_type,status,reason,recommended_action,created_at)
               VALUES(?,?,?,?,?,?)""",
            (complaint["case_id"], alert_type, complaint["status"],
             reason, action, created_at)
        )

        if not cursor.rowcount:
            continue  # alert already exists for this inactivity period

        created_alerts += 1

        add_case_event(
            db, complaint["case_id"], ESCALATION_ALERT_EVENT,
            f"{reason} Recommended next action: {action}", created_at
        )

        if complaint["user_id"]:
            create_notification(
                db, complaint["user_id"], complaint["case_id"],
                "escalation_alert", "Escalation Alert",
                f"Case {complaint['case_id']} has remained in "
                f"{complaint['status']} for more than {threshold} hours "
                f"without activity. The responsible authority has been alerted."
            )

        notify_organization_authorities(
            db, complaint["organization_id"], complaint["case_id"],
            "escalation_alert", "Escalation Agent Alert",
            f"Case {complaint['case_id']} exceeded the "
            f"{threshold}-hour activity threshold while in "
            f"{complaint['status']}. {action}"
        )

    return created_alerts


def check_escalation_agent(case_id=None, now=None):
    with closing(get_db()) as db:
        created = run_escalation_agent(db, case_id, now)
        db.commit()
    return created


def run_escalation_if_due():
    """Throttled lazy trigger. Failures never break the request."""
    if ESCALATION_INTERVAL_SECONDS <= 0:
        return

    path = app.config["DATABASE"]
    now = time.time()

    if now - _LAST_ESCALATION_RUN.get(path, 0) < ESCALATION_INTERVAL_SECONDS:
        return

    _LAST_ESCALATION_RUN[path] = now

    try:
        check_escalation_agent()
    except sqlite3.Error as error:
        app.logger.warning("Escalation run skipped: %s", error)


@app.before_request
def lazy_escalation():
    if logged_in() and request.endpoint not in (None, "static"):
        run_escalation_if_due()


# =========================================================
# NOTIFICATIONS
# =========================================================

def get_unread_message_count(user_id, role):
    with closing(get_db()) as db:
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
            return 0

    return row["count"]


def get_unread_system_notification_count(user_id):
    with closing(get_db()) as db:
        row = db.execute(
            "SELECT COUNT(*) count FROM notifications WHERE user_id=? AND is_read=0",
            (user_id,)
        ).fetchone()

    return row["count"]


def get_total_unread_notification_count(user_id, role):
    return (
        get_unread_message_count(user_id, role)
        + get_unread_system_notification_count(user_id)
    )


def unread_message_rows(db, user_id, role, limit=None):
    """Unread messages shown as notifications for the given role."""
    limit_sql = f" LIMIT {int(limit)}" if limit else ""

    if role == "user":
        return db.execute(
            """SELECT m.id,m.case_id,m.message,m.created_at,c.category
               FROM case_messages m JOIN complaints c
                 ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.user_id=? AND m.sender_role='authority'
                 AND m.id>COALESCE(r.last_read_message_id,0)
               ORDER BY m.id DESC""" + limit_sql,
            (user_id, user_id)
        ).fetchall(), "Authority", "New Authority Message"

    if role == "authority":
        authority = get_authority(db, user_id)
        if not authority:
            return [], "", ""

        return db.execute(
            """SELECT m.id,m.case_id,m.message,m.created_at,c.category
               FROM case_messages m JOIN complaints c
                 ON m.case_id=c.case_id
               LEFT JOIN message_reads r
                 ON r.case_id=m.case_id AND r.user_id=?
               WHERE c.organization_id=? AND m.sender_role='complainant'
                 AND m.id>COALESCE(r.last_read_message_id,0)
               ORDER BY m.id DESC""" + limit_sql,
            (user_id, authority["organization_id"])
        ).fetchall(), "Complainant", "New Complainant Message"

    return [], "", ""


@app.context_processor
def inject_notification_count():
    empty = {
        "unread_message_count": 0,
        "total_notification_count": 0,
        "unread_system_notification_count": 0,
        "notifications": []
    }

    if not logged_in():
        return empty

    user_id = session["user_id"]
    role = session.get("role")

    notifications = []

    with closing(get_db()) as db:
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

        rows, sender, title = unread_message_rows(db, user_id, role, 10)

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

    notifications.sort(key=lambda x: x["created_at"], reverse=True)
    total = get_total_unread_notification_count(user_id, role)

    return {
        "unread_message_count": total,
        "total_notification_count": total,
        "unread_system_notification_count":
            get_unread_system_notification_count(user_id),
        "notifications": notifications[:10]
    }


def upsert_read_marker(db, case_id, user_id, message_id):
    db.execute(
        """INSERT INTO message_reads
           (case_id,user_id,last_read_message_id,updated_at)
           VALUES(?,?,?,?)
           ON CONFLICT(case_id,user_id) DO UPDATE SET
           last_read_message_id=excluded.last_read_message_id,
           updated_at=excluded.updated_at""",
        (case_id, user_id, message_id, current_time())
    )


def mark_case_messages_read(case_id, user_id, role):
    sender = {"user": "authority", "authority": "complainant"}.get(role)
    if not sender:
        return

    with closing(get_db()) as db:
        latest = db.execute(
            """SELECT MAX(id) message_id FROM case_messages
               WHERE case_id=? AND sender_role=?""",
            (case_id, sender)
        ).fetchone()

        if latest["message_id"]:
            upsert_read_marker(db, case_id, user_id, latest["message_id"])
            db.commit()


def mark_case_notifications_read(case_id, user_id):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE notifications SET is_read=1 WHERE case_id=? AND user_id=?",
            (case_id, user_id)
        )
        db.commit()


def mark_all_notifications_read_for_user(user_id, role):
    with closing(get_db()) as db:
        db.execute(
            "UPDATE notifications SET is_read=1 WHERE user_id=?",
            (user_id,)
        )

        sender = {"user": "authority", "authority": "complainant"}.get(role)
        cases = []

        if role == "user":
            cases = db.execute(
                "SELECT case_id FROM complaints WHERE user_id=?",
                (user_id,)
            ).fetchall()
        elif role == "authority":
            authority = get_authority(db, user_id)
            if authority:
                cases = db.execute(
                    "SELECT case_id FROM complaints WHERE organization_id=?",
                    (authority["organization_id"],)
                ).fetchall()

        if sender:
            for case in cases:
                latest = db.execute(
                    """SELECT MAX(id) message_id FROM case_messages
                       WHERE case_id=? AND sender_role=?""",
                    (case["case_id"], sender)
                ).fetchone()

                if latest["message_id"]:
                    upsert_read_marker(
                        db, case["case_id"], user_id, latest["message_id"]
                    )

        db.commit()


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
        full_name = clean_text(request.form.get("full_name"), 100)
        email = clean_text(request.form.get("email"), 120)
        phone = clean_text(request.form.get("phone"), 20)
        username = clean_text(request.form.get("username"), 50)
        password = request.form.get("password", "")
        organization_id = to_int(request.form.get("organization_id"))

        if not full_name or not username or not password or not organization_id:
            error = "Full name, username, password and organization are required."
        elif len(full_name) > 100:
            error = "Full name is too long."
        elif not USERNAME_RE.match(username):
            error = ("Username must contain 3-50 letters, numbers, "
                     "dots, dashes or underscores.")
        elif not MIN_PASSWORD_LENGTH <= len(password) <= 128:
            error = (f"Password must contain {MIN_PASSWORD_LENGTH}-128 "
                     "characters.")
        elif email and (len(email) > 120 or not EMAIL_RE.match(email)):
            error = "Enter a valid email address."
        elif phone and not PHONE_RE.match(phone):
            error = "Enter a valid phone number."
        else:
            with closing(get_db()) as db:
                org = db.execute(
                    "SELECT id FROM organizations WHERE id=?",
                    (organization_id,)
                ).fetchone()

                if not org:
                    error = "Invalid organization selected."
                else:
                    try:
                        cursor = db.execute(
                            """INSERT INTO users
                               (username,password_hash,role,
                                organization_id,created_at)
                               VALUES(?,?,?,?,?)""",
                            (username, generate_password_hash(password),
                             "user", organization_id, current_time())
                        )

                        db.execute(
                            """INSERT INTO identity_vault
                               (user_id,full_name,email,phone,created_at)
                               VALUES(?,?,?,?,?)""",
                            (cursor.lastrowid, full_name,
                             email, phone, current_time())
                        )

                        db.commit()
                        return redirect(url_for("login"))

                    except sqlite3.IntegrityError:
                        db.rollback()
                        error = "Username already exists."

    with closing(get_db()) as db:
        organizations = db.execute(
            "SELECT * FROM organizations ORDER BY name"
        ).fetchall()

    return render_template(
        "register.html", organizations=organizations, error=error
    )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        username = clean_text(request.form.get("username"), 50)
        password = request.form.get("password", "")

        if login_is_blocked(username):
            error = "Too many failed attempts. Try again in 15 minutes."
        else:
            with closing(get_db()) as db:
                user = db.execute(
                    "SELECT * FROM users WHERE username=?", (username,)
                ).fetchone()

            password_ok = check_password_hash(
                user["password_hash"] if user else DUMMY_PASSWORD_HASH,
                password
            )

            if user and password_ok:
                clear_login_failures(username)
                session.clear()
                session.permanent = True
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]

                if user["role"] == "authority":
                    return redirect(url_for("authority_dashboard"))

                return redirect(url_for("home"))

            record_login_failure(username)
            error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("home"))


# =========================================================
# COMPLAINT
# =========================================================

@app.route("/complaint", methods=["GET", "POST"])
@user_required
def complaint():
    with closing(get_db()) as db:
        organizations = db.execute(
            "SELECT id,name,sector FROM organizations ORDER BY name"
        ).fetchall()

    if request.method == "GET":
        return render_template("complaint.html", organizations=organizations)

    complaint_type = clean_text(
        request.form.get("complaint_type", "Individual"), 20
    ) or "Individual"
    organization_id = to_int(request.form.get("organization_id"))
    institution = clean_text(request.form.get("institution"), 150)
    unit = clean_text(request.form.get("unit"), 150)
    category = clean_text(request.form.get("category"), 100)
    incident_date = clean_text(request.form.get("incident_date"), 10)
    description = clean_text(
        request.form.get("description"), MAX_DESCRIPTION_LENGTH,
        multiline=True
    )
    privacy_mode = clean_text(request.form.get("privacy_mode"), 20).lower()

    def error_page(message):
        return render_template(
            "complaint.html", organizations=organizations, error=message
        )

    if privacy_mode not in PRIVACY_MODES:
        return error_page("Please select a valid privacy preference.")
    if complaint_type not in COMPLAINT_TYPES:
        return error_page("Please select a valid complaint type.")
    if not organization_id:
        return error_page("Please select a section.")
    if not institution:
        return error_page("Institution name is required.")
    if len(institution) > 150 or len(unit) > 150:
        return error_page("Institution or unit name is too long.")
    if not category:
        return error_page("Please select a category.")
    if not valid_incident_date(incident_date):
        return error_page("Incident date must be a valid date, not in the future.")
    if len(description) < MIN_DESCRIPTION_LENGTH:
        return error_page(
            f"Please describe the complaint in at least "
            f"{MIN_DESCRIPTION_LENGTH} characters."
        )
    if len(description) > MAX_DESCRIPTION_LENGTH:
        return error_page("Complaint description is too long.")

    with closing(get_db()) as db:
        organization = db.execute(
            "SELECT id,name,sector FROM organizations WHERE id=?",
            (organization_id,)
        ).fetchone()

        if not organization:
            return error_page("Invalid section selected.")

        if category not in SECTOR_CATEGORIES.get(organization["sector"], []):
            return error_page("Please select a category for this section.")

        prefix = {
            "School": "SCH", "Hospital": "HOS", "NCC": "NCC"
        }.get(organization["sector"], "GEN")

        while True:
            case_id = prefix + "-" + secrets.token_hex(4).upper()
            if not db.execute(
                "SELECT id FROM complaints WHERE case_id=?", (case_id,)
            ).fetchone():
                break

        created_at = current_time()

        db.execute(
            """INSERT INTO complaints
               (case_id,complaint_type,institution,unit,category,
                incident_date,description,status,created_at,user_id,
                privacy_mode,organization_id)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (case_id, complaint_type, institution, unit, category,
             incident_date, description, "Submitted", created_at,
             session["user_id"], privacy_mode, organization["id"])
        )

        add_case_event(
            db, case_id, "Complaint Submitted",
            "The grievance was successfully submitted through the portal.",
            created_at
        )

        notify_organization_authorities(
            db, organization["id"], case_id, "new_complaint",
            "New Grievance Submitted",
            f"A new grievance {case_id} was submitted."
        )

        db.commit()

    return render_template("confirmation.html", case_id=case_id)


# =========================================================
# TRACK / MY COMPLAINTS
# =========================================================

@app.route("/track", methods=["GET", "POST"])
@login_required
def track():
    complaint_data = None
    events = []
    error = None

    if request.method == "POST":
        case_id = clean_text(request.form.get("case_id"), 30).upper()

        if not case_id:
            error = "Please enter a Case ID."
        elif not CASE_ID_RE.match(case_id):
            error = "No case found with that Case ID."
        else:
            with closing(get_db()) as db:
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

    return render_template(
        "track.html", complaint=complaint_data, events=events, error=error
    )


@app.route("/my-complaints")
@user_required
def my_complaints():
    with closing(get_db()) as db:
        complaints = db.execute(
            """SELECT c.*,o.name organization_name
               FROM complaints c LEFT JOIN organizations o
                 ON c.organization_id=o.id
               WHERE c.user_id=? ORDER BY c.created_at DESC""",
            (session["user_id"],)
        ).fetchall()

    result = []
    for row in complaints:
        data = dict(row)
        data["unread_count"] = get_case_unread_count(
            data["case_id"], session["user_id"], "user"
        )
        result.append(data)

    return render_template("my_complaints.html", complaints=result)


def fetch_case_timeline(db, case_id, descending=False):
    order = "DESC" if descending else "ASC"
    events = db.execute(
        f"""SELECT event,description,created_at
            FROM case_events WHERE case_id=? ORDER BY id {order}""",
        (case_id,)
    ).fetchall()

    messages = db.execute(
        "SELECT * FROM case_messages WHERE case_id=? ORDER BY id",
        (case_id,)
    ).fetchall()

    alerts = db.execute(
        """SELECT alert_type,status,reason,recommended_action,created_at
           FROM escalation_alerts WHERE case_id=? ORDER BY id DESC""",
        (case_id,)
    ).fetchall()

    return events, messages, alerts


@app.route("/my-complaints/<case_id>")
@user_required
def my_complaint_case(case_id):
    case_id = normalize_case_id(case_id)

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT c.*,o.name organization_name,o.sector
               FROM complaints c LEFT JOIN organizations o
                 ON c.organization_id=o.id
               WHERE c.case_id=? AND c.user_id=?""",
            (case_id, session["user_id"])
        ).fetchone()

        if not complaint_data:
            abort(404)

        events, messages, alerts = fetch_case_timeline(db, case_id)

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
@user_required
def complainant_send_message(case_id):
    case_id = normalize_case_id(case_id)
    message = clean_text(
        request.form.get("message"), MAX_MESSAGE_LENGTH, multiline=True
    )
    back = redirect(url_for("my_complaint_case", case_id=case_id))

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT status,organization_id FROM complaints
               WHERE case_id=? AND user_id=?""",
            (case_id, session["user_id"])
        ).fetchone()

        if not complaint_data:
            abort(404)

        if not message:
            flash("Message cannot be empty.", "error")
            return back

        if len(message) > MAX_MESSAGE_LENGTH:
            flash("Message is too long.", "error")
            return back

        if complaint_data["status"] == "Closed":
            flash("This case is closed. Messages are disabled.", "error")
            return back

        created_at = current_time()

        db.execute(
            """INSERT INTO case_messages
               (case_id,sender_role,sender_user_id,message,created_at)
               VALUES(?,?,?,?,?)""",
            (case_id, "complainant", session["user_id"], message, created_at)
        )

        add_case_event(
            db, case_id, "Complainant Response",
            "The complainant added a response to the case.", created_at,
            session["user_id"]
        )

        notify_organization_authorities(
            db, complaint_data["organization_id"], case_id,
            "complainant_message", "New Complainant Message",
            f"The complainant added a new message to case {case_id}."
        )

        db.commit()

    return back


# =========================================================
# AUTHORITY DASHBOARD
# =========================================================

def format_duration(hours):
    if hours is None:
        return "n/a"
    if hours < 1:
        return f"{round(hours * 60)} min"
    if hours < 48:
        return f"{hours:.1f} h"
    return f"{hours / 24:.1f} days"


app.jinja_env.filters["duration"] = format_duration


def parse_case_filters(args):
    """Validate dashboard / export query parameters."""
    filters = {
        "q": re.sub(r"[^A-Z0-9-]", "", (args.get("q") or "").upper())[:30],
        "status": (args.get("status") or "").strip(),
        "category": clean_text(args.get("category"), 100),
        "priority": (args.get("priority") or "").strip(),
        "date_from": (args.get("date_from") or "").strip(),
        "date_to": (args.get("date_to") or "").strip(),
        "overdue": args.get("overdue") == "1",
        "sort": (args.get("sort") or "newest").strip(),
        "page": max(to_int(args.get("page")) or 1, 1)
    }
    problems = []

    if filters["status"] not in STATUS_TRANSITIONS:
        filters["status"] = ""
    if filters["priority"] not in PRIORITY_RANK:
        filters["priority"] = ""
    if filters["sort"] not in {"newest", "oldest", "priority", "overdue"}:
        filters["sort"] = "newest"

    for key in ("date_from", "date_to"):
        value = filters[key]
        if value:
            try:
                datetime.strptime(value, "%Y-%m-%d")
            except ValueError:
                filters[key] = ""
                problems.append("Dates must use the YYYY-MM-DD format.")

    if (filters["date_from"] and filters["date_to"]
            and filters["date_from"] > filters["date_to"]):
        filters["date_from"] = filters["date_to"] = ""
        problems.append("The start date must not be after the end date.")

    return filters, sorted(set(problems))


def query_organization_cases(db, organization_id, filters, user_id=None):
    """Cases of one organization matching the filters, with overdue data."""
    where = ["c.organization_id=?"]
    params = [organization_id]

    if filters["q"]:
        where.append("c.case_id LIKE ?")
        params.append("%" + filters["q"] + "%")
    if filters["status"]:
        where.append("c.status=?")
        params.append(filters["status"])
    if filters["category"]:
        where.append("c.category=?")
        params.append(filters["category"])
    if filters["priority"]:
        where.append("c.priority=?")
        params.append(filters["priority"])
    if filters["date_from"]:
        where.append("c.created_at>=?")
        params.append(filters["date_from"] + " 00:00:00")
    if filters["date_to"]:
        where.append("c.created_at<=?")
        params.append(filters["date_to"] + " 23:59:59")

    rows = db.execute(
        "SELECT c.* FROM complaints c WHERE " + " AND ".join(where)
        + " ORDER BY c.created_at DESC, c.id DESC",
        params
    ).fetchall()

    now = datetime.now()
    overdue = {}
    for row in fetch_activity_rows(db, organization_id=organization_id):
        threshold = ESCALATION_RULES[row["status"]][0]
        hours = inactive_hours(row, now)
        overdue[row["case_id"]] = (hours >= threshold, hours)

    cases = []
    for row in rows:
        data = dict(row)
        is_overdue, hours = overdue.get(row["case_id"], (False, None))
        data["overdue"] = is_overdue
        data["inactive_hours"] = hours
        cases.append(data)

    if filters["overdue"]:
        cases = [case for case in cases if case["overdue"]]

    if filters["sort"] == "oldest":
        cases.sort(key=lambda case: (case["created_at"], case["id"]))
    elif filters["sort"] == "priority":
        cases.sort(key=lambda case: (
            -PRIORITY_RANK.get(case["priority"], 1), case["created_at"]
        ))
    elif filters["sort"] == "overdue":
        cases.sort(key=lambda case: (
            not case["overdue"], -(case["inactive_hours"] or 0)
        ))

    return cases


@app.route("/authority/dashboard")
@authority_required
def authority_dashboard():
    org_id = g.authority["organization_id"]
    filters, problems = parse_case_filters(request.args)

    for problem in problems:
        flash(problem, "error")

    with closing(get_db()) as db:
        organization = db.execute(
            "SELECT name,sector FROM organizations WHERE id=?", (org_id,)
        ).fetchone()

        def count(where, params=()):
            return db.execute(
                "SELECT COUNT(*) count FROM complaints "
                "WHERE organization_id=? " + where,
                (org_id,) + params
            ).fetchone()["count"]

        total = count("")
        pending = count("AND status IN('Submitted','Under Review')")
        in_progress = count("AND status='In Progress'")
        resolved = count("AND status IN('Resolved','Closed')")
        escalated = count("AND status='Escalated'")

        categories = [
            row["category"] for row in db.execute(
                """SELECT DISTINCT category FROM complaints
                   WHERE organization_id=? ORDER BY category""",
                (org_id,)
            ).fetchall()
        ]

        cases = query_organization_cases(db, org_id, filters)
        all_open = fetch_activity_rows(db, organization_id=org_id)

    now = datetime.now()
    overdue_total = sum(
        1 for row in all_open
        if inactive_hours(row, now) >= ESCALATION_RULES[row["status"]][0]
    )

    matched = len(cases)
    pages = max((matched + CASES_PER_PAGE - 1) // CASES_PER_PAGE, 1)
    filters["page"] = min(filters["page"], pages)
    start = (filters["page"] - 1) * CASES_PER_PAGE
    page_cases = cases[start:start + CASES_PER_PAGE]

    for data in page_cases:
        data["unread_count"] = get_case_unread_count(
            data["case_id"], session["user_id"], "authority"
        )

    stats = {
        "total": total, "pending": pending, "in_progress": in_progress,
        "resolved": resolved, "escalated": escalated,
        "overdue": overdue_total
    }

    base_args = {
        key: value for key, value in request.args.items()
        if key != "page" and value
    }

    return render_template(
        "authority_dashboard.html",
        complaints=page_cases,
        organization_name=organization["name"] if organization else "Organization",
        sector=organization["sector"] if organization else "",
        stats=stats,
        total=total,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved,
        filters=filters,
        categories=categories,
        statuses=list(STATUS_TRANSITIONS),
        priorities=PRIORITIES,
        matched=matched,
        page=filters["page"],
        pages=pages,
        base_args=base_args,
        filters_active=any(
            filters[key] for key in
            ("q", "status", "category", "priority",
             "date_from", "date_to", "overdue")
        )
    )


def csv_safe(value):
    """Neutralize spreadsheet formula injection in exported text."""
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


@app.route("/authority/export.csv")
@authority_required
def authority_export():
    """CSV of the filtered case list. Contains no complainant identity and
    no complaint text, to keep exported data minimal."""
    org_id = g.authority["organization_id"]
    filters, _ = parse_case_filters(request.args)

    with closing(get_db()) as db:
        cases = query_organization_cases(db, org_id, filters)
        resolution = {
            row["case_id"]: row["resolved_at"] for row in db.execute(
                """SELECT case_id,resolved_at FROM complaints
                   WHERE organization_id=?""", (org_id,)
            ).fetchall()
        }

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "case_id", "status", "priority", "category", "institution",
        "unit", "incident_date", "submitted_at", "resolved_at",
        "resolution_hours", "privacy_mode", "overdue",
        "hours_since_activity"
    ])

    for case in cases:
        resolved_at = resolution.get(case["case_id"])
        created = parse_time(case["created_at"])
        resolved = parse_time(resolved_at)
        hours = (
            round((resolved - created).total_seconds() / 3600, 1)
            if created and resolved else ""
        )
        writer.writerow([
            csv_safe(value) for value in (
                case["case_id"], case["status"], case["priority"],
                case["category"], case["institution"], case["unit"],
                case["incident_date"], case["created_at"],
                resolved_at or "", hours, case["privacy_mode"],
                "yes" if case["overdue"] else "no",
                round(case["inactive_hours"], 1)
                if case["inactive_hours"] is not None else ""
            )
        ])

    filename = "cases-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".csv"
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


def median(values):
    values = sorted(values)
    if not values:
        return None
    middle = len(values) // 2
    if len(values) % 2:
        return values[middle]
    return (values[middle - 1] + values[middle]) / 2


@app.route("/authority/reports")
@authority_required
def authority_reports():
    org_id = g.authority["organization_id"]
    now = datetime.now()

    with closing(get_db()) as db:
        organization = db.execute(
            "SELECT name FROM organizations WHERE id=?", (org_id,)
        ).fetchone()

        def grouped(column, order):
            return db.execute(
                f"""SELECT {column} label,COUNT(*) total FROM complaints
                    WHERE organization_id=? GROUP BY {column} {order}""",
                (org_id,)
            ).fetchall()

        by_status_raw = {r["label"]: r["total"] for r in grouped("status", "")}
        by_status = [
            (name, by_status_raw.get(name, 0)) for name in STATUS_TRANSITIONS
        ]
        by_priority_raw = {
            r["label"]: r["total"] for r in grouped("priority", "")
        }
        by_priority = [
            (name, by_priority_raw.get(name, 0)) for name in PRIORITIES
        ]
        by_category = [
            (r["label"], r["total"])
            for r in grouped("category", "ORDER BY COUNT(*) DESC, category")
        ]

        months = [
            (r["label"], r["total"]) for r in db.execute(
                """SELECT substr(created_at,1,7) label,COUNT(*) total
                   FROM complaints WHERE organization_id=?
                   GROUP BY substr(created_at,1,7)
                   ORDER BY label DESC LIMIT 6""",
                (org_id,)
            ).fetchall()
        ][::-1]

        resolution_hours = []
        for row in db.execute(
            """SELECT created_at,resolved_at FROM complaints
               WHERE organization_id=? AND resolved_at IS NOT NULL""",
            (org_id,)
        ).fetchall():
            created, resolved = (
                parse_time(row["created_at"]), parse_time(row["resolved_at"])
            )
            if created and resolved and resolved >= created:
                resolution_hours.append(
                    (resolved - created).total_seconds() / 3600
                )

        response_hours = []
        for row in db.execute(
            """SELECT c.created_at,
                      (SELECT MIN(e.created_at) FROM case_events e
                        WHERE e.case_id=c.case_id
                          AND e.event IN('Authority Response','Status Changed'))
                      first_response
               FROM complaints c WHERE c.organization_id=?""",
            (org_id,)
        ).fetchall():
            created, first = (
                parse_time(row["created_at"]), parse_time(row["first_response"])
            )
            if created and first and first >= created:
                response_hours.append((first - created).total_seconds() / 3600)

        overdue_cases = []
        for row in fetch_activity_rows(db, organization_id=org_id):
            hours = inactive_hours(row, now)
            threshold = ESCALATION_RULES[row["status"]][0]
            if hours >= threshold:
                overdue_cases.append({
                    "case_id": row["case_id"], "status": row["status"],
                    "hours": hours, "threshold": threshold
                })
        overdue_cases.sort(key=lambda item: -item["hours"])

        workload = db.execute(
            """SELECT u.username,
                      SUM(e.event='Status Changed') status_changes,
                      SUM(e.event='Authority Response') responses,
                      SUM(e.event='Identity Disclosed') disclosures,
                      COUNT(*) total
               FROM case_events e
               JOIN users u ON u.id=e.actor_user_id
               JOIN complaints c ON c.case_id=e.case_id
               WHERE u.role='authority' AND c.organization_id=?
               GROUP BY u.id ORDER BY total DESC""",
            (org_id,)
        ).fetchall()

        open_cases = db.execute(
            """SELECT COUNT(*) count FROM complaints
               WHERE organization_id=? AND status!='Closed'""",
            (org_id,)
        ).fetchone()["count"]
        total = db.execute(
            "SELECT COUNT(*) count FROM complaints WHERE organization_id=?",
            (org_id,)
        ).fetchone()["count"]

    def summary(values):
        if not values:
            return None
        return {
            "count": len(values),
            "average": sum(values) / len(values),
            "median": median(values),
            "slowest": max(values)
        }

    return render_template(
        "authority_reports.html",
        organization_name=organization["name"] if organization else "",
        total=total,
        open_cases=open_cases,
        by_status=by_status,
        by_priority=by_priority,
        by_category=by_category,
        months=months,
        resolution=summary(resolution_hours),
        first_response=summary(response_hours),
        overdue_cases=overdue_cases,
        workload=workload
    )


# =========================================================
# AUTHORITY CASE
# =========================================================

def complainant_verified_for_org(db, user_id, organization_id):
    return db.execute(
        """SELECT id FROM verifications
           WHERE user_id=? AND organization_id=?
             AND verification_status='Verified' LIMIT 1""",
        (user_id, organization_id)
    ).fetchone() is not None


@app.route("/authority/case/<case_id>")
@authority_required
def authority_case(case_id):
    case_id = normalize_case_id(case_id)
    organization_id = g.authority["organization_id"]

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT c.*,o.name organization_name,o.sector
               FROM complaints c LEFT JOIN organizations o
                 ON c.organization_id=o.id
               WHERE c.case_id=? AND c.organization_id=?""",
            (case_id, organization_id)
        ).fetchone()

        if not complaint_data:
            abort(404)

        identity = None
        disclosure = None
        identity_hidden = True
        can_reveal_identity = False
        reveal_blocked_reason = ""

        def load_identity():
            if not complaint_data["user_id"]:
                return None
            return db.execute(
                """SELECT full_name,email,phone FROM identity_vault
                   WHERE user_id=?""",
                (complaint_data["user_id"],)
            ).fetchone()

        if complaint_data["privacy_mode"] == "identified":
            identity_hidden = False
            identity = load_identity()

        elif complaint_data["privacy_mode"] == "confidential":
            disclosure = db.execute(
                """SELECT d.reason,d.created_at,u.username disclosed_by_name
                   FROM identity_disclosures d
                   LEFT JOIN users u ON u.id=d.disclosed_by
                   WHERE d.case_id=? ORDER BY d.id LIMIT 1""",
                (case_id,)
            ).fetchone()

            if disclosure:
                identity_hidden = False
                identity = load_identity()
            elif not complaint_data["user_id"]:
                reveal_blocked_reason = "No complainant account is linked to this case."
            elif not complainant_verified_for_org(
                db, complaint_data["user_id"], organization_id
            ):
                reveal_blocked_reason = (
                    "The complainant is not verified for this organization. "
                    "Identity cannot be disclosed until verification is approved."
                )
            else:
                can_reveal_identity = True

        events, messages, alerts = fetch_case_timeline(
            db, case_id, descending=True
        )

    mark_case_messages_read(case_id, session["user_id"], "authority")
    mark_case_notifications_read(case_id, session["user_id"])

    return render_template(
        "authority_case.html",
        complaint=complaint_data,
        events=events,
        messages=messages,
        identity=identity,
        identity_hidden=identity_hidden,
        disclosure=disclosure,
        can_reveal_identity=can_reveal_identity,
        reveal_blocked_reason=reveal_blocked_reason,
        min_disclosure_reason=MIN_DISCLOSURE_REASON,
        priorities=PRIORITIES,
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
@authority_required
def authority_update_status(case_id):
    case_id = normalize_case_id(case_id)
    new_status = clean_text(request.form.get("status"), 30)
    organization_id = g.authority["organization_id"]
    back = redirect(url_for("authority_case", case_id=case_id))

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT case_id,status,user_id FROM complaints
               WHERE case_id=? AND organization_id=?""",
            (case_id, organization_id)
        ).fetchone()

        if not complaint_data:
            abort(404)

        old_status = complaint_data["status"]

        if new_status not in STATUS_TRANSITIONS.get(old_status, []):
            flash(
                f"Cannot change status from {old_status} to "
                f"{new_status or 'that value'}.", "error"
            )
            return back

        created_at = current_time()

        db.execute(
            """UPDATE complaints SET status=?,
                   resolved_at=CASE WHEN ?='Resolved' THEN ? ELSE resolved_at END
               WHERE case_id=? AND organization_id=?""",
            (new_status, new_status, created_at, case_id, organization_id)
        )

        add_case_event(
            db, case_id, "Status Changed",
            f"Status changed from {old_status} to {new_status} by authority.",
            created_at, session["user_id"]
        )

        if complaint_data["user_id"]:
            create_notification(
                db, complaint_data["user_id"], case_id, "status_change",
                "Case Status Updated",
                f"Your case {case_id} status changed from "
                f"{old_status} to {new_status}."
            )

        db.commit()

    return back


@app.route("/authority/case/<case_id>/priority", methods=["POST"])
@authority_required
def authority_update_priority(case_id):
    case_id = normalize_case_id(case_id)
    priority = clean_text(request.form.get("priority"), 20)
    organization_id = g.authority["organization_id"]
    back = redirect(url_for("authority_case", case_id=case_id))

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT status,priority FROM complaints
               WHERE case_id=? AND organization_id=?""",
            (case_id, organization_id)
        ).fetchone()

        if not complaint_data:
            abort(404)

        if priority not in PRIORITY_RANK:
            flash("Choose a valid priority.", "error")
            return back

        if complaint_data["status"] == "Closed":
            flash("Priority cannot change on a closed case.", "error")
            return back

        if priority != complaint_data["priority"]:
            db.execute(
                """UPDATE complaints SET priority=?
                   WHERE case_id=? AND organization_id=?""",
                (priority, case_id, organization_id)
            )
            # Priority is internal triage: the shared timeline entry does
            # not state the value.
            add_case_event(
                db, case_id, "Priority Updated",
                "The authority updated the handling priority of the case.",
                None, session["user_id"]
            )
            db.commit()

    flash("Priority updated.", "success")
    return back


# =========================================================
# AUTHORITY MESSAGE
# =========================================================

@app.route("/authority/case/<case_id>/message", methods=["POST"])
@authority_required
def authority_send_message(case_id):
    case_id = normalize_case_id(case_id)
    message = clean_text(
        request.form.get("message"), MAX_MESSAGE_LENGTH, multiline=True
    )
    organization_id = g.authority["organization_id"]
    back = redirect(url_for("authority_case", case_id=case_id))

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT status,user_id FROM complaints
               WHERE case_id=? AND organization_id=?""",
            (case_id, organization_id)
        ).fetchone()

        if not complaint_data:
            abort(404)

        if not message:
            flash("Message cannot be empty.", "error")
            return back

        if len(message) > MAX_MESSAGE_LENGTH:
            flash("Message is too long.", "error")
            return back

        if complaint_data["status"] == "Closed":
            flash("This case is closed. Messages are disabled.", "error")
            return back

        created_at = current_time()

        db.execute(
            """INSERT INTO case_messages
               (case_id,sender_role,sender_user_id,message,created_at)
               VALUES(?,?,?,?,?)""",
            (case_id, "authority", session["user_id"], message, created_at)
        )

        add_case_event(
            db, case_id, "Authority Response",
            "The authority added a response to the case.", created_at,
            session["user_id"]
        )

        if complaint_data["user_id"]:
            create_notification(
                db, complaint_data["user_id"], case_id, "authority_message",
                "New Authority Message",
                f"The authority sent a new message for case {case_id}."
            )

        db.commit()

    return back


# =========================================================
# IDENTITY DISCLOSURE
#
# Policy: a confidential identity may be disclosed only when
#   1. the case belongs to the authority's organization,
#   2. the complainant is Verified for that organization,
#   3. a case-specific reason of at least 20 characters is given,
#   4. no disclosure exists yet for the case.
# Every disclosure is recorded, added to the case timeline and
# notified to the complainant together with the stated reason.
# =========================================================

@app.route("/authority/case/<case_id>/reveal-identity", methods=["POST"])
@authority_required
def reveal_identity(case_id):
    case_id = normalize_case_id(case_id)
    reason = clean_text(
        request.form.get("reason"), MAX_DISCLOSURE_REASON, multiline=True
    )
    organization_id = g.authority["organization_id"]
    back = redirect(url_for("authority_case", case_id=case_id))

    with closing(get_db()) as db:
        complaint_data = db.execute(
            """SELECT privacy_mode,user_id FROM complaints
               WHERE case_id=? AND organization_id=?""",
            (case_id, organization_id)
        ).fetchone()

        if not complaint_data:
            abort(404)

        if complaint_data["privacy_mode"] != "confidential":
            flash("This complaint is not confidential.", "error")
            return back

        if len(reason) < MIN_DISCLOSURE_REASON:
            flash(
                f"Give a case-specific reason of at least "
                f"{MIN_DISCLOSURE_REASON} characters.", "error"
            )
            return back

        if len(reason) > MAX_DISCLOSURE_REASON:
            flash("Reason is too long.", "error")
            return back

        if not complaint_data["user_id"]:
            flash("No complainant account is linked to this case.", "error")
            return back

        if not complainant_verified_for_org(
            db, complaint_data["user_id"], organization_id
        ):
            flash(
                "Disclosure blocked: the complainant is not verified "
                "for this organization.", "error"
            )
            return back

        db.execute("BEGIN IMMEDIATE")

        if db.execute(
            "SELECT id FROM identity_disclosures WHERE case_id=? LIMIT 1",
            (case_id,)
        ).fetchone():
            db.rollback()
            flash("Identity was already disclosed for this case.", "error")
            return back

        created_at = current_time()

        db.execute(
            """INSERT INTO identity_disclosures
               (case_id,disclosed_by,reason,created_at)
               VALUES(?,?,?,?)""",
            (case_id, session["user_id"], reason, created_at)
        )

        add_case_event(
            db, case_id, "Identity Disclosed",
            "Complainant identity was disclosed to the handling "
            "organization's authority. Reason recorded.",
            created_at, session["user_id"]
        )

        create_notification(
            db, complaint_data["user_id"], case_id, "identity_disclosed",
            "Your Identity Was Disclosed",
            f"The authority handling case {case_id} disclosed your identity. "
            f"Stated reason: {reason}"
        )

        db.commit()

    flash("Identity disclosed. The complainant has been notified.", "success")
    return back


# =========================================================
# VERIFICATION
# =========================================================

@app.route("/verification", methods=["GET", "POST"])
@user_required
def verification():
    with closing(get_db()) as db:
        organizations = db.execute(
            "SELECT id,name,sector FROM organizations ORDER BY name"
        ).fetchall()

        def page(error=None):
            requests_ = db.execute(
                """SELECT v.*,o.name organization_name
                   FROM verifications v
                   JOIN organizations o ON v.organization_id=o.id
                   WHERE v.user_id=?
                   ORDER BY v.id DESC""",
                (session["user_id"],)
            ).fetchall()

            return render_template(
                "verification.html",
                organizations=organizations,
                verifications=requests_,
                methods=VERIFICATION_METHODS,
                error=error
            )

        if request.method == "POST":
            organization_id = to_int(request.form.get("organization_id"))
            method = clean_text(request.form.get("verification_method"), 60)
            reference = clean_text(
                request.form.get("reference_detail"), MAX_REFERENCE_LENGTH + 1
            )

            if not organization_id or not method:
                return page("Select an organization and verification method.")

            if method not in VERIFICATION_METHODS:
                return page("Select a valid verification method.")

            if not 3 <= len(reference) <= MAX_REFERENCE_LENGTH:
                label = VERIFICATION_METHODS[method]["reference_label"]
                return page(
                    f"Enter your {label.lower()} "
                    f"(3-{MAX_REFERENCE_LENGTH} characters)."
                )

            organization = db.execute(
                "SELECT id,name FROM organizations WHERE id=?",
                (organization_id,)
            ).fetchone()

            if not organization:
                return page("Invalid organization selected.")

            if db.execute(
                """SELECT id FROM verifications
                   WHERE user_id=? AND organization_id=?
                   AND verification_status='Pending'""",
                (session["user_id"], organization_id)
            ).fetchone():
                return page("A verification request is already pending.")

            if complainant_verified_for_org(
                db, session["user_id"], organization_id
            ):
                return page("You are already verified for this organization.")

            try:
                cursor = db.execute(
                    """INSERT INTO verifications
                       (user_id,organization_id,verification_method,
                        reference_detail,verification_status,
                        verified_at,created_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (session["user_id"], organization_id, method,
                     reference, "Pending", None, current_time())
                )
            except sqlite3.IntegrityError:
                db.rollback()
                return page("A verification request is already pending.")

            notify_organization_authorities(
                db, organization_id, None, "verification_request",
                "New Verification Request",
                f"A user submitted verification request #{cursor.lastrowid}."
            )

            db.commit()
            return redirect(url_for("verification"))

        return page()


@app.route("/authority/verifications")
@authority_required
def authority_verifications():
    # Data minimization: email and phone are never selected. The full name
    # is shown only after an approval, never for pending or rejected rows.
    with closing(get_db()) as db:
        verifications = db.execute(
            """SELECT v.id,v.user_id,v.verification_method,
                      v.reference_detail,v.verification_status,
                      v.verified_at,v.created_at,v.reviewed_at,
                      v.review_note,u.username,
                      o.name organization_name,
                      CASE WHEN v.verification_status='Verified'
                           THEN iv.full_name END full_name
               FROM verifications v
               JOIN users u ON v.user_id=u.id
               JOIN organizations o ON v.organization_id=o.id
               LEFT JOIN identity_vault iv ON v.user_id=iv.user_id
               WHERE v.organization_id=?
               ORDER BY
                 CASE WHEN v.verification_status='Pending' THEN 0 ELSE 1 END,
                 v.id DESC""",
            (g.authority["organization_id"],)
        ).fetchall()

    return render_template(
        "authority_verifications.html",
        verifications=verifications,
        methods=VERIFICATION_METHODS
    )


@app.route(
    "/authority/verifications/<int:verification_id>/status",
    methods=["POST"]
)
@authority_required
def authority_update_verification(verification_id):
    new_status = clean_text(request.form.get("status"), 20)
    note = clean_text(
        request.form.get("review_note"), MAX_REVIEW_NOTE_LENGTH,
        multiline=True
    )

    if new_status not in {"Verified", "Rejected"}:
        flash("Choose Verify or Reject.", "error")
        return redirect(url_for("authority_verifications"))

    if len(note) > MAX_REVIEW_NOTE_LENGTH:
        flash("Review note is too long.", "error")
        return redirect(url_for("authority_verifications"))

    organization_id = g.authority["organization_id"]

    with closing(get_db()) as db:
        verification_row = db.execute(
            """SELECT id,user_id,organization_id,verification_status
               FROM verifications WHERE id=? AND organization_id=?""",
            (verification_id, organization_id)
        ).fetchone()

        if not verification_row:
            abort(404)

        if verification_row["user_id"] == session["user_id"]:
            abort(403)

        reviewed_at = current_time()
        verified_at = reviewed_at if new_status == "Verified" else None

        # Only a still-pending request can change, even under a race.
        cursor = db.execute(
            """UPDATE verifications
               SET verification_status=?,verified_at=?,reviewed_by=?,
                   reviewed_at=?,review_note=?
               WHERE id=? AND organization_id=?
                 AND verification_status='Pending'""",
            (new_status, verified_at, session["user_id"], reviewed_at,
             note or None, verification_id, organization_id)
        )

        if not cursor.rowcount:
            db.rollback()
            flash("This request was already reviewed.", "error")
            return redirect(url_for("authority_verifications"))

        approved = new_status == "Verified"
        message = (
            "Your verification request has been approved."
            if approved else "Your verification request was rejected."
        )
        if note:
            message += f" Note from reviewer: {note}"

        create_notification(
            db, verification_row["user_id"], None, "verification_update",
            "Verification Approved" if approved else "Verification Rejected",
            message
        )

        db.commit()

    flash(
        "Request approved." if approved else "Request rejected.", "success"
    )
    return redirect(url_for("authority_verifications"))


# =========================================================
# NOTIFICATIONS
# =========================================================

@app.route("/notifications", endpoint="notifications")
@app.route("/notifications", endpoint="notifications_page")
@login_required
def notifications_page():
    user_id = session["user_id"]
    role = session.get("role")
    notifications = []

    with closing(get_db()) as db:
        for item in db.execute(
            """SELECT id,case_id,notification_type,title,message,
                      created_at,is_read
               FROM notifications WHERE user_id=?
               ORDER BY id DESC""",
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
                "source": "system",
                "is_read": item["is_read"]
            })

        rows, sender, title = unread_message_rows(db, user_id, role)

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
                "source": "message",
                "is_read": 0
            })

    notifications.sort(key=lambda x: x["created_at"], reverse=True)

    return render_template("notifications.html", notifications=notifications)


@app.route("/notifications/read/<int:notification_id>", methods=["POST"])
@login_required
def mark_notification_read(notification_id):
    with closing(get_db()) as db:
        notification = db.execute(
            "SELECT case_id FROM notifications WHERE id=? AND user_id=?",
            (notification_id, session["user_id"])
        ).fetchone()

        db.execute(
            "UPDATE notifications SET is_read=1 WHERE id=? AND user_id=?",
            (notification_id, session["user_id"])
        )
        db.commit()

    if notification and notification["case_id"]:
        if session.get("role") == "authority":
            return redirect(
                url_for("authority_case", case_id=notification["case_id"])
            )

        return redirect(
            url_for("my_complaint_case", case_id=notification["case_id"])
        )

    return redirect(url_for("notifications_page"))


@app.route("/notifications/mark-all-read", methods=["POST"])
@login_required
def mark_all_notifications_read():
    mark_all_notifications_read_for_user(
        session["user_id"], session.get("role")
    )
    return redirect(url_for("notifications_page"))


# =========================================================
# COMMAND LINE
# =========================================================

@app.cli.command("init-db")
def cli_init_db():
    """Create or upgrade the database schema (never drops data)."""
    init_db()
    click.echo("Database is up to date.")


@app.cli.command("create-authority")
@click.argument("username")
@click.argument("sector", type=click.Choice(["School", "Hospital", "NCC"]))
@click.password_option()
def cli_create_authority(username, sector, password):
    """Create an authority account for a section."""
    if not USERNAME_RE.match(username):
        raise click.ClickException("Invalid username.")
    if len(password) < 10:
        raise click.ClickException("Use a password of at least 10 characters.")

    init_db()

    with closing(get_db()) as db:
        org = db.execute(
            "SELECT id FROM organizations WHERE sector=? LIMIT 1", (sector,)
        ).fetchone()

        try:
            db.execute(
                """INSERT INTO users
                   (username,password_hash,role,organization_id,created_at)
                   VALUES(?,?,?,?,?)""",
                (username, generate_password_hash(password),
                 "authority", org["id"], current_time())
            )
            db.commit()
        except sqlite3.IntegrityError:
            raise click.ClickException("Username already exists.")

    click.echo(f"Authority {username} created for {sector}.")


@app.cli.command("reset-password")
@click.argument("username")
@click.password_option()
def cli_reset_password(username, password):
    """Reset a user's or authority's password."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise click.ClickException(
            f"Use at least {MIN_PASSWORD_LENGTH} characters."
        )

    with closing(get_db()) as db:
        cursor = db.execute(
            "UPDATE users SET password_hash=? WHERE username=?",
            (generate_password_hash(password), username)
        )
        db.commit()

    if not cursor.rowcount:
        raise click.ClickException("User not found.")

    click.echo("Password updated.")


@app.cli.command("run-escalation")
def cli_run_escalation():
    """Run the inactivity escalation agent once."""
    init_db()
    check_escalation_agent()
    click.echo("Escalation check complete.")


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    init_db()
    app.run(
        debug=(not IS_PRODUCTION and os.environ.get("FLASK_DEBUG") == "1"),
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000"))
    )
