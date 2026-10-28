# General Grievance Portal

A Flask + SQLite web application for submitting and tracking grievances across three sections: **School, Hospital, and NCC**. It includes complainant accounts, organization-scoped authority accounts, case timelines, messaging, notifications, manual verification, controlled identity disclosure, inactivity escalation alerts, dashboard filters, CSV export, and reports.

> **Project status:** Demo deployed on PythonAnywhere. The latest verified application-code revision is `ffa46a4`; later commits update documentation only. GitHub Actions run [40755780759](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40755780759) passed both the backend regression suite and configured live homepage smoke test on commit `90c4e29`. The reported local backend suite has 100 passing tests, and selected workflows have been manually verified. Production security, accessibility, and operational verification are not complete. AI features are proposals only; no AI integration is implemented.

## Live Demo

**Hosted application:** https://deploynes.pythonanywhere.com/

This is an evaluation demo, not a production grievance-handling service. Do not submit real or sensitive personal information until security, privacy, backup, and operational checks are complete.

### Manually verified live workflows

- Complaint submission and display of a case ID.
- Complainant complaint history and case timeline.
- Authority login/access and a case status update.
- Manual escalation-check command/result.

These manual checks are not a comprehensive automated end-to-end suite and do not establish that every browser, role, privacy edge case, or deployment setting is verified.

## Requirements

- Python 3.10 or newer (Python 3.12 recommended)
- `pip`
- A modern browser

## Local setup (Linux Mint / Ubuntu)

From the extracted project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m flask --app app init-db
python -m flask --app app run
```

Open `http://127.0.0.1:5000`. Stop the development server with `Ctrl+C`.

The application does not automatically load `.env`. Export environment variables in the shell or configure them in your process manager. `.env.example` documents supported settings; do not commit a real `.env` file.

## Configuration

| Variable | Purpose |
|---|---|
| `APP_ENV` | `development` by default; use `production` for production-mode checks. |
| `SECRET_KEY` | Required when `APP_ENV=production`. Generate a random value with `python -c "import secrets; print(secrets.token_hex(32))"`. Keep it private. |
| `DATABASE_PATH` | SQLite database path; defaults to `complaints.db`. |
| `SEED_AUTHORITY_PASSWORD` | Optional password used only when creating demo authority accounts that do not already exist. Use a strong value and do not reuse a real password. |
| `COOKIE_SECURE` | Set to `1` when serving over HTTPS. Defaults to on in production mode. |
| `ESCALATION_INTERVAL_SECONDS` | Minimum interval between opportunistic escalation checks in a single application process; defaults to 600. Set to `0` to disable the lazy check and use the CLI command from an external scheduler. |
| `FLASK_DEBUG` | Set to `1` only for local development if you run `python app.py`. Never enable the debugger in production. |

Example for a local development shell:

```bash
export APP_ENV=development
export DATABASE_PATH="$PWD/complaints.db"
python -m flask --app app init-db
python -m flask --app app run
```

## Authority accounts

Create an authority account interactively (the command prompts for a password):

```bash
python -m flask --app app create-authority school_reviewer School
```

Valid sections are `School`, `Hospital`, and `NCC`.

Reset an existing account password:

```bash
python -m flask --app app reset-password school_reviewer
```

Existing databases may retain legacy seeded authority passwords. Reset any known/default passwords and confirm only intended authority accounts exist before real use. Do not expose demo credentials publicly.

## Continuous Integration

GitHub Actions runs on pushes and pull requests targeting `development`, and can be started manually.

The workflow:
- Checks Python syntax in `app.py` and `tests/`.
- Runs the backend unit-test suite using Python 3.12.
- Checks the deployed homepage when the `LIVE_BASE_URL` repository variable is configured.

**Latest recorded run:** [GitHub Actions run 40755780759](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40755780759), commit `90c4e29`; both backend tests and the live homepage smoke test passed. The live smoke test checks HTTPS, HTTP 200, HTML content type, and a non-empty response. It does not verify login, complaint submission, authorization, or other application workflows. Check the [Actions history](https://github.com/kshchauhan-nes/grievance-portal/actions) for the current run and commit.

GitHub Actions does not automatically deploy new code to PythonAnywhere.

## Tests

Run from the project root with the virtual environment active:

```bash
python -W error::ResourceWarning -m unittest discover -s tests -t .
```

**Latest reported local result:** 100 tests passed (reported October 2026). GitHub Actions also passed its backend test suite in [run 40755780759](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40755780759).

Migration tests use Git history to reconstruct the legacy schema from commit `d8f2fd3`. A source-only ZIP without `.git` cannot run that historical migration test; it may be skipped. To verify migration coverage, run tests in the full Git repository with required history available. Do not interpret a skipped migration test as a pass.

## Database backup and migration

Before upgrading an existing installation, stop the application and make a separate backup of the database:

```bash
cp -a "$DATABASE_PATH" "${DATABASE_PATH}.backup-$(date +%Y%m%d-%H%M%S)"
```

If `DATABASE_PATH` is unset, the default file is `complaints.db` in the project directory. Confirm the backup exists and has a plausible non-zero size before continuing.

Then activate the intended environment and run:

```bash
python -m flask --app app init-db
```

The migration approach is intended to be additive and repeatable; nevertheless, test upgrades against a copy of the real database first. Never test migrations against the only copy of production data.

### Rollback

1. Stop the application.
2. Restore the pre-upgrade database backup to the configured database path.
3. Restore the prior application source/version.
4. Start the prior version and verify login, case tracking, messaging, and dashboard access.

Do not assume rolling back code alone reverses database changes. Keep the backup until rollback and integrity checks are complete.

## Escalation agent

Run a one-time inactivity check with:

```bash
python -m flask --app app run-escalation
```

The agent is rule-based; it creates alerts and notifications but does not automatically change case status.

**Scheduling limitation:** the lazy escalation check is triggered only by eligible logged-in requests. It is throttled using in-memory state per application process, so it is opportunistic rather than time-guaranteed. If no eligible request arrives, the check may not run when a threshold is reached. Different worker processes maintain independent throttle state. It is **not a background scheduler** and must not be relied on for timely operational escalation. Use an external scheduler or dedicated worker to invoke the CLI command at a defined interval, with shared coordination if running multiple workers.

## Privacy and verification notes

- Verification is **manual**. The application does not upload or automatically inspect identity documents, and it does not send verification emails.
- Identity disclosure for confidential cases requires verification for the same organization, a sufficiently detailed reason, and creates an audit event and complainant notification.
- Review disclosure and verification workflows with the organization before real personal data is entered.
- CSV export intentionally excludes complaint text and identity fields, but exported files should still be handled as sensitive operational data.

## Security and deployment checklist

The following checks have been confirmed so far: the shell-loaded environment reports `APP_ENV=production` and a configured (non-empty) `SECRET_KEY`; the WSGI file explicitly loads the environment file and sets `COOKIE_SECURE=1`; the site loads over HTTPS; Python syntax compilation passed; and the latest GitHub Actions backend and live homepage smoke tests passed. The user confirmed demo/authority password changes and created a timestamped SQLite backup whose integrity check returned `ok`. Production secret strength/uniqueness, backup restore testing, full deployed authorization/privacy review, and accessibility have **not** been independently confirmed.

- [x] Production mode, secret-key presence, secure-cookie flag, HTTPS response, and WSGI environment-file path checked.
- [x] GitHub Actions backend regression tests and live homepage smoke test passed at `ffa46a4`.
- [x] User confirmed demo/authority password changes. Review and remove any unused accounts before real use.
- [ ] Confirm organization-scoped authorization and identity-disclosure behavior in the deployed environment.
- [x] Create a production database backup and confirm SQLite integrity (`ok`).
- [ ] Test restore and migration procedures against a separate copy, not the live database.
- [ ] Review deployed CSRF protection, session settings, error handling, logging, and login rate limiting.
- [ ] Complete browser-based functional, accessibility, keyboard, screen-reader, and responsive-layout checks.
- [ ] Verify the deployed revision after the latest GitHub change and document the PythonAnywhere reload/recovery procedure.
- [ ] Review logging, backups, retention, and organizational privacy requirements.
- [ ] Load-test and obtain a security review before handling real cases.
- [ ] Never commit `.env`, database files, user data, or credentials.

## Current limitations

- Browser-based visual, responsive, and accessibility checks remain outstanding.
- The user confirmed demo/authority password changes and a valid production database backup; restore testing remains outstanding.
- Login throttling and lazy escalation timing are per-process, not shared across workers; lazy escalation is request-triggered and is not a background scheduler.
- Inline styles/scripts remain in several templates; the current Content Security Policy allows inline content for compatibility.
- GitHub Actions does not automatically deploy the application.
- AI features are not implemented. See [`docs/AI_PROPOSAL.md`](docs/AI_PROPOSAL.md).
