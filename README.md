# General Grievance Portal

A Flask + SQLite web application for submitting and tracking grievances across three sections: **School, Hospital, and NCC**. It includes complainant accounts, organization-scoped authority accounts, case timelines, messaging, notifications, manual verification, controlled identity disclosure, inactivity escalation alerts, dashboard filters, CSV export, and reports.

> **Project status:** The application has been deployed to PythonAnywhere, and automated backend tests are configured in GitHub Actions. Browser layout, accessibility, responsive-design, and production security checks are still outstanding. AI features are proposed only; no AI integration is implemented.
## Live Demo

**Hosted application:** https://deploynes.pythonanywhere.com/

The application is hosted on PythonAnywhere. Do not submit real or sensitive personal information through the demo until production security and privacy checks have been completed.
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
| `ESCALATION_INTERVAL_SECONDS` | Interval for the opportunistic escalation check; defaults to 600. Set to `0` to disable the lazy check and run the CLI command on a schedule. |
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

**Deployment warning:** existing databases may retain legacy seeded authority passwords. Reset every known/default authority password before deployment and confirm that only intended authority accounts exist. Do not expose demo credentials publicly.
## Continuous Integration

GitHub Actions runs automated checks on pushes and pull requests targeting the `development` branch, and can also be started manually.

The workflow:
- Checks Python syntax in `app.py` and `tests/`.
- Runs the backend unit-test suite using Python 3.12.
- Optionally checks the deployed homepage when the repository variable `LIVE_BASE_URL` is configured.

The live smoke test checks that the homepage responds over HTTPS with a successful status and non-empty HTML. It does **not** verify login, complaint submission, authorization, or other application workflows.

A successful CI run is evidence that the configured checks passed; it does not automatically deploy new code to PythonAnywhere.
## Tests

Run from the project root with the virtual environment active:

```bash
python -W error::ResourceWarning -m unittest discover -s tests -t .
```

The migration tests use Git history to reconstruct the legacy schema from commit `d8f2fd3`. A source-only ZIP without `.git` cannot run that historical migration test; it may be skipped. To verify migration coverage, run the tests in the full Git repository with the required history available. Do not interpret a skipped migration test as a pass.

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

The agent is rule-based; it creates alerts and notifications but does not automatically change case status. The lazy check and login throttle use in-process memory, so their timing/state is not shared between multiple worker processes. For multi-worker deployment, replace these with shared storage or a single scheduled worker before relying on them operationally.

## Privacy and verification notes

- Verification is **manual**. The application does not upload or automatically inspect identity documents, and it does not send verification emails.
- Identity disclosure for confidential cases requires verification for the same organization, a sufficiently detailed reason, and creates an audit event and complainant notification.
- Review the disclosure and verification workflows with the organization before real personal data is entered.
- CSV export intentionally excludes complaint text and identity fields, but exported files should still be handled as sensitive operational data.

## Security and deployment checklist

- [ ] Set a strong, private `SECRET_KEY` and `APP_ENV=production`.
- [ ] Serve only behind HTTPS and set secure cookies appropriately.
- [ ] Rotate all legacy/demo authority passwords and remove accounts not needed.
- [ ] Back up and test database migration/restore procedures.
- [ ] Run the full test suite in the actual Git repository.
- [ ] Complete browser, accessibility, and responsive-layout checks.
- [ ] Configure a production WSGI server and process manager; do not use Flask's development server in production.
- [ ] Review logging, backups, retention, authorization, rate limiting, and organizational privacy requirements.
- [ ] Load-test and security-review the application before handling real cases.
- [ ] Do not commit `.env`, database files, user data, or credentials.

## Current limitations

- Browser visual and accessibility checks are outstanding.
- Login throttling and lazy escalation timing are per-process, not shared across workers.
The application is live on PythonAnywhere. Production WSGI configuration and security settings still require verification.
- Inline styles/scripts remain in several templates; the current Content Security Policy allows inline content for compatibility.
- AI features are not implemented. See [`docs/AI_PROPOSAL.md`](docs/AI_PROPOSAL.md).
