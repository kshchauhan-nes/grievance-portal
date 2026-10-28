# Project Status — Grievance Portal

**Last updated:** October 29, 2026

## Current Status

- Flask + SQLite grievance portal implemented for School, Hospital, and NCC sections.
- Demo deployed on PythonAnywhere: https://deploynes.pythonanywhere.com/
- **Latest GitHub revision:** `ffa46a4` on `development` (ignore Python virtual environment directory).
- **GitHub Actions at `ffa46a4`: PASS.** Both backend regression tests and the configured live homepage smoke test completed successfully. The smoke test confirms an HTTPS 200 response with non-empty HTML; it does not exercise authenticated workflows.
- **Latest reported local test result:** 100 tests passed. The separate GitHub Actions test suite also passed on the latest revision.
- **Manually verified on the live demo:** complaint submission and case ID display; complainant complaint history and case timeline; authority login/access and a case status update; manual escalation-check command/result.
- **Production configuration checks completed:** shell-loaded environment reports `APP_ENV=production`, a non-empty `SECRET_KEY`, and `COOKIE_SECURE` defaults to `1`; the WSGI file explicitly sets production mode, loads `/home/deploynes/.config/grievance-portal.env`, and sets `COOKIE_SECURE=1`. The site loads over HTTPS and Python compilation passed. Secret strength/rotation, all runtime settings, and a full deployment security audit have not been established.
- These checks are a demo smoke test, not comprehensive browser, accessibility, privacy-edge-case, or production-security sign-off.

## Remaining Work

### Security and privacy before real use

- [ ] Rotate legacy/demo authority passwords and confirm only intended authority accounts exist (requires access to the live database/account setup).
- [ ] Review deployed organization-scoped authorization, CSRF protections, error handling, logging, per-process login throttling, and identity-disclosure controls.
- [ ] Verify database backup, migration, restore, and rollback procedures without risking live data.
- [ ] Review secret strength/uniqueness and session settings without exposing secret values.
- [ ] Complete independent security review and load testing before accepting real or sensitive grievances.

### Accessibility and functional verification

- [ ] Test key flows in supported browsers at desktop and mobile widths.
- [ ] Check keyboard-only navigation, focus visibility, labels, validation/error announcements, contrast, and screen-reader behavior.
- [ ] Test registration/login, complainant workflows, authority permissions, status transitions, messaging/read state, notifications, verification, identity disclosure, exports, and escalation edge cases.
- [ ] Test unauthorized cross-organization access and invalid/missing case IDs in the deployed environment.

### Operations and deployment

- [x] Configure the WSGI environment file path and production cookie flag; confirm HTTPS responds.
- [x] Confirm the latest GitHub Actions backend and live homepage smoke checks pass at `ffa46a4`.
- [ ] Confirm PythonAnywhere is pulled to `ffa46a4` or newer and reload after any later code deployment. GitHub changes do not automatically deploy.
- [ ] Establish a reliable recurring escalation schedule independent of user traffic.
- [ ] Document and test deployment/reload and database recovery procedures.

## Escalation Limitation

The rule-based lazy escalation check is triggered by eligible logged-in requests and is throttled using in-memory state **per application process**. It is opportunistic: without an eligible request, a check may not run when a case reaches its threshold. Multiple worker processes have independent throttle state. This is **not a background scheduler** and does not guarantee timely escalation. For operational use, configure an external scheduler or dedicated worker to run `python -m flask --app app run-escalation` at a defined interval; account for multi-worker coordination. The current PythonAnywhere free-tier setup does not provide the recurring task capability the user reported needing.

## Important Notes

- Escalation rules create alerts/notifications; they do not automatically change case status and are not AI-powered.
- GitHub Actions does not automatically deploy the application.
- Do not store production secrets, credentials, database files, or real user data in the repository.
- AI features remain proposals only; no AI integration is implemented.
