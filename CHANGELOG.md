# Changelog

This changelog describes the changes reported for the current work-in-progress snapshot. Verify each item against the actual repository and test output before treating it as a release record.

## Unreleased — Grievance Portal hardening and workflow improvements

### Security and validation
- Added CSRF checks for POST requests and token fields to form templates.
- Added environment-based secret configuration, secure cookie settings, security headers, production secret enforcement, and disabled-by-default debug mode.
- Tightened registration, case input, message, status, and priority validation.
- Added login-attempt throttling and tests for unauthorized, cross-user, and cross-organization access.
- Added generic error pages and flash-message partials.

### Identity and verification
- Restricted confidential identity disclosure to complainants verified for the same organization.
- Required a disclosure reason of at least 20 characters and recorded disclosure events.
- Added complainant notification when identity is disclosed.
- Added manual verification methods, reference details, review audit fields, duplicate-request prevention, and minimized personal data in authority review lists.

### Escalation and case management
- Reworked the rule-based inactivity escalation process, including throttling, deduplication, a CLI command, and recommended next actions.
- Kept escalation alerts from resetting the inactivity timer and prevented the agent from changing case status automatically.
- Added dashboard search, filters, sorting, pagination, priority, overdue flags, CSV export, and organization-scoped reports.
- Added actor attribution to relevant timeline events.

### Testing and documentation
- Added unit/integration tests for dashboard, security, identity disclosure, verification, escalation, and migration behaviour.
- Added `requirements.txt`, `.env.example`, `PROJECT_STATUS.md`, `README.md`, this changelog, and `docs/AI_PROPOSAL.md`.
- Added `verify_local.sh` to automate local dependency setup, syntax compilation, and test execution. AI application code remains intentionally out of scope.

### Known limitations
- Visual browser and accessibility review remains outstanding.
- Login throttling and lazy escalation timers are process-local.
- Production WSGI deployment has not been verified.
- Historical migration tests require the original Git commit history and cannot be fully verified from a source-only ZIP alone.
