# PROJECT_STATUS

Last updated: 2026-10-22. Project: General Grievance Portal. Intended branch: `development`.

## Package integrity and verification status

- This is a source-only work-in-progress package assembled from the uploaded ZIP plus documentation and a local verification helper.
- The ZIP excludes `.git`, database files, virtual environments, and secrets.
- A companion Git bundle advertises commit `919a3bdd63f0ba4a95c162bbfe64130de371eaf8` on `development`, but a fresh clone attempt in the review environment failed while traversing a parent object. Do not merge that bundle until it verifies against a known-good local repository.
- `python3 -m compileall -q app.py tests` passed in the review environment.
- The full test suite was **not run here** because Flask was not installed and dependency installation timed out. Claude previously reported 93 tests passing; rerun locally before relying on that result.
- Browser visual, accessibility, responsive-layout, and production deployment checks remain outstanding.

## Features in this source snapshot

- Flask + SQLite; sections: School, Hospital, NCC.
- User and organization-scoped authority roles.
- Registration/login, complaint submission/tracking, case timeline, messaging, notifications.
- Manual verification and controlled identity disclosure.
- Rule-based inactivity escalation that creates alerts but does not automatically change case status.
- Dashboard search/filter/sort/pagination, priority, overdue flags, CSV export, and reports.
- Additive/versioned database migrations; migration tests require Git history.
- CSRF protection, production secret enforcement, cookie flags, security headers, validation, and login throttling.

## Known limitations

- Login throttling and lazy-escalation timing are process-local, not shared between workers.
- Manual verification does not upload or automatically inspect documents and does not send verification emails.
- Existing databases may retain legacy seeded authority passwords. Reset all known/default authority passwords before deployment.
- Browser layout/accessibility checks and production WSGI deployment have not been verified.
- AI features are not implemented. See `docs/AI_PROPOSAL.md`.

## Next steps

1. Keep the existing project and database backup untouched.
2. Extract this ZIP into a separate staging directory.
3. Run `./verify_local.sh` with internet access so pip can install Flask. Review test output, especially skipped migration tests.
4. Start the app locally and inspect dashboard, reports, verification, disclosure, and error pages in a browser.
5. Verify migration on a copy of a real legacy database, not the only database copy.
6. Only after checks pass, transfer the validated files into the main repository and commit them. Do not merge the companion Git bundle until its object history verifies in the target repository.
7. Get explicit approval before implementing any AI feature.
