# Project Status — Grievance Portal

**Last updated:** October 29, 2026

## Current Status

- Flask + SQLite grievance portal implemented for School, Hospital, and NCC sections.
- Demo deployed on PythonAnywhere: https://deploynes.pythonanywhere.com/
- **GitHub `development` revision:** `838d476` (README scheduler documentation update; follow the branch head for the exact current SHA). The branch now includes a one-shot escalation runner and its tests. PythonAnywhere's currently deployed revision has not been independently verified, and no production files or scheduled tasks were changed.
- **GitHub Actions: PASS.** Backend regression tests and the live homepage smoke test, including the new live security-header assertions, passed in [run 40756370843](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40756370843) on commit `ceb9d89`. A later documentation-triggered run is in progress; its live homepage smoke job has passed, while its backend suite has not yet completed. The smoke test does not exercise authenticated workflows.
- **Latest reported local test result:** 100 tests passed. The separate GitHub Actions test suite also passed on the latest revision.
- **Manually verified on the live demo:** complaint submission and case ID display; complainant complaint history and case timeline; authority login/access and a case status update; manual escalation-check command/result.
- **Production configuration checks completed:** runtime inspection reported production mode, a configured secret key (value not displayed), secure cookies enabled, HttpOnly enabled, and SameSite `Lax`; the WSGI file loads `/home/deploynes/.config/grievance-portal.env` and sets `COOKIE_SECURE=1`. The site loads over HTTPS and Python compilation passed. Secret strength/uniqueness and a full deployment security audit have not been established.
- **Operations confirmed by user:** demo/authority passwords were changed; a timestamped SQLite backup was created at `/home/deploynes/backups/grievance-portal/complaints-20261028-192938.db`, size 143,360 bytes, with `PRAGMA integrity_check` returning `ok`. Restore testing has not been done.
- These checks are a demo smoke test, not comprehensive browser, accessibility, privacy-edge-case, or production-security sign-off.

## Remaining Work

### Security and privacy before real use

- [x] User confirmed demo/authority password changes.
- [ ] Confirm only intended authority accounts exist before real use.
- [ ] Review deployed organization-scoped authorization, CSRF protections, error handling, logging, per-process login throttling, and identity-disclosure controls.
- [x] Create a production database backup and pass SQLite integrity check.
- [ ] Verify restore, migration, and rollback procedures using a separate copy.
- [x] Confirm runtime secret-key presence and session cookie flags without exposing secret values.
- [ ] Review secret strength/uniqueness and complete an independent security review.
- [ ] Complete independent security review and load testing before accepting real or sensitive grievances.

### Accessibility and functional verification

- [ ] Test key flows in supported browsers at desktop and mobile widths.
- [ ] Check keyboard-only navigation, focus visibility, labels, validation/error announcements, contrast, and screen-reader behavior.
- [ ] Test registration/login, complainant workflows, authority permissions, status transitions, messaging/read state, notifications, verification, identity disclosure, exports, and escalation edge cases.
- [ ] Test unauthorized cross-organization access and invalid/missing case IDs in the deployed environment.

### Operations and deployment

- [x] Configure the WSGI environment file path and production cookie flag; confirm HTTPS responds.
- [x] Confirm GitHub Actions backend regression tests and live homepage/security-header smoke checks passed at commit `ceb9d89` (application code remains `ffa46a4`).
- [x] Confirm the live security-header assertions pass in workflow run [40756370843](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40756370843) on commit `ceb9d89`.
- [ ] Confirm PythonAnywhere is pulled to the latest `development` revision and reload after any later application-code deployment. Documentation-only updates do not require a web-app reload. GitHub changes do not automatically deploy.
- [ ] Confirm the PythonAnywhere account's scheduled-task entitlement in the Tasks tab; current platform rules say newer free accounts have no scheduled tasks, older free accounts retain one daily task, and paid plans support hourly/daily tasks.
- [x] Add a one-shot escalation runner with production env validation, a non-blocking filesystem lock, and failure logging; add automated tests for environment loading, command invocation, failures, and lock contention.
- [ ] Run the new runner tests in CI and on a safe test setup; review the production environment-file syntax before using the runner.
- [ ] Establish a reliable recurring escalation schedule independent of user traffic, if the account plan supports it.
- [ ] Document and test deployment/reload and database recovery procedures.

## Escalation Limitation

The rule-based lazy escalation check is triggered by eligible logged-in requests and is throttled using in-memory state **per application process**. It is opportunistic and is **not a background scheduler**. PythonAnywhere's current plan rules provide no scheduled tasks for newer free accounts, one daily task for older free accounts created before the cutoff, and hourly/daily tasks on paid plans. `scripts/run_escalation.py` is a one-shot runner that loads the production env file, enforces production mode and secure cookies, takes a non-blocking filesystem lock, logs failures, and invokes the CLI command. It does not schedule itself; no PythonAnywhere task, external service, or production configuration has been created or changed. See `docs/ESCALATION_SCHEDULING.md`. Its lock coordinates runner instances on the same host only and does not lock out request-triggered lazy checks.

## Important Notes

- Escalation rules create alerts/notifications; they do not automatically change case status and are not AI-powered.
- GitHub Actions does not automatically deploy the application.
- Do not store production secrets, credentials, database files, or real user data in the repository.
- AI features remain proposals only; no AI integration is implemented.
