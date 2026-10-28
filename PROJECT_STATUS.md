# Project Status — Grievance Portal

**Last updated:** October 28, 2026

## Current Status

- Flask + SQLite grievance portal implemented.
- Application deployed and accessible on PythonAnywhere: https://deploynes.pythonanywhere.com/
- Automated backend tests and GitHub Actions workflow configured.
- Latest reported local test result: 100 tests passed.
- GitHub Actions workflow checks Python compilation and backend tests.
- Live smoke testing is optional and requires the `LIVE_BASE_URL` repository variable.

## Remaining Work

- Verify production configuration and rotate demo or legacy authority passwords.
- Perform browser-based functional and accessibility testing.
- Review deployment security and error handling.
- Verify the live smoke test and confirm deployment behavior after future updates.

## Important Notes

- The escalation system uses predefined rules; it is not AI-powered.
- GitHub Actions does not automatically deploy the application.
- Do not store production secrets or credentials in the repository.
