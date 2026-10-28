# Project Status — Grievance Portal

**Last updated:** October 29, 2026

## Current Status

- Flask + SQLite grievance portal implemented for School, Hospital, and NCC sections.
- Demo deployed on PythonAnywhere: https://deploynes.pythonanywhere.com/
- **Application-code revision:** `ffa46a4` on `development`; later commits update documentation only. The current branch's documentation updates are at `90c4e29`.
- **GitHub Actions: PASS.** Both backend regression tests and the configured live homepage smoke test passed in [run 40755780759](https://github.com/kshchauhan-nes/grievance-portal/actions/runs/40755780759) on commit `90c4e29`; subsequent changes are documentation-only. The smoke test confirms an HTTPS 200 response with non-empty HTML; it does not exercise authenticated workflows.
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
- [x] Confirm the latest GitHub Actions backend and live homepage smoke checks pass at documentation commit `90c4e29` (application code remains `ffa46a4`).
- [ ] Confirm PythonAnywhere is pulled to the latest `development` revision and reload after any later application-code deployment. Documentation-only updates do not require a web-app reload. GitHub changes do not automatically deploy.
- [ ] Establish a reliable recurring escalation schedule independent of user traffic.
- [ ] Document and test deployment/reload and database recovery procedures.

## Escalation Limitation

The rule-based lazy escalation check is triggered by eligible logged-in requests and is throttled using in-memory state **per application process**. It is opportunistic: without an eligible request, a check may not run when a case reaches its threshold. Multiple worker processes have independent throttle state. This is **not a background scheduler** and does not guarantee timely escalation. For operational use, configure an external scheduler or dedicated worker to run `python -m flask --app app run-escalation` at a defined interval; account for multi-worker coordination. The current PythonAnywhere free-tier setup does not provide the recurring task capability the user reported needing.

## Important Notes

- Escalation rules create alerts/notifications; they do not automatically change case status and are not AI-powered.
- GitHub Actions does not automatically deploy the application.
- Do not store production secrets, credentials, database files, or real user data in the repository.
- AI features remain proposals only; no AI integration is implemented.
