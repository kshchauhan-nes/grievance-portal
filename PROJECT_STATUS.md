# Project Status — Grievance Portal

**Last updated:** October 29, 2026

## Current Status

- Flask + SQLite grievance portal implemented for School, Hospital, and NCC sections.
- Demo deployed and accessible on PythonAnywhere: https://deploynes.pythonanywhere.com/
- Automated backend tests and the GitHub Actions workflow are configured.
- **Latest reported local test result:** 100 tests passed. This is a reported local run; it does not by itself certify the hosted deployment.
- GitHub Actions checks Python compilation and the backend test suite. The live homepage smoke test is optional and requires the `LIVE_BASE_URL` repository variable; it checks only an HTTPS response, successful status, and non-empty HTML.
- **Manually verified on the live demo:** complaint submission and case ID display; complainant complaint history and case timeline; authority login/access and a case status update; manual escalation-check command/result.
- These manual checks are a limited workflow smoke test, not comprehensive browser, accessibility, privacy-edge-case, or production-security sign-off.

## Remaining Work

### Production security and privacy

- [ ] Verify production `APP_ENV`, secret key management, HTTPS, secure cookies, session settings, and PythonAnywhere WSGI/process configuration.
- [ ] Rotate any legacy/demo authority passwords and verify only intended authority accounts exist.
- [ ] Review organization-scoped authorization, CSRF protections, error handling, logging, rate limiting, and privacy/identity-disclosure controls in the deployed environment.
- [ ] Verify database backup, migration, restore, and rollback procedures without risking the live database.
- [ ] Complete a security review and load testing before real or sensitive grievances are accepted.

### Accessibility and functional verification

- [ ] Test key flows in supported browsers at desktop and mobile widths.
- [ ] Check keyboard-only navigation, focus visibility, labels, validation/error announcements, contrast, and screen-reader behavior.
- [ ] Retest registration/login, complainant workflows, authority permissions, status transitions, messaging/read state, notifications, verification, identity disclosure, exports, and escalation edge cases.
- [ ] Verify behavior for unauthorized cross-organization access and invalid or missing case IDs.

### Deployment verification and operations

- [ ] Confirm the exact deployed revision matches the intended GitHub branch/commit and document the PythonAnywhere reload procedure.
- [ ] Run/confirm the configured GitHub Actions checks and optional live homepage smoke test after deployment; remember that CI does not deploy automatically.
- [ ] Establish an operational escalation schedule and verify it independently of user traffic.

## Escalation Limitation

The rule-based lazy escalation check is triggered by eligible logged-in requests and is throttled using in-memory state **per application process**. It is opportunistic: without an eligible request, a check may not run when a case reaches its threshold. Multiple worker processes have independent throttle state. This is **not a background scheduler** and does not guarantee timely escalation. For operational use, configure an external scheduler or dedicated worker to run `python -m flask --app app run-escalation` at a defined interval; account for multi-worker coordination.

## Important Notes

- Escalation rules create alerts/notifications; they do not automatically change case status and are not AI-powered.
- GitHub Actions does not automatically deploy the application.
- Do not store production secrets, credentials, database files, or real user data in the repository.
- AI features remain proposals only; no AI integration is implemented.
