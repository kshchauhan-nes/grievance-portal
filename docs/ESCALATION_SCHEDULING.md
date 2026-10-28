# Escalation scheduling and operations

## Current finding

The portal has a Flask CLI command, `python -m flask --app app run-escalation`, which performs one escalation check. The existing lazy hook is not a scheduler: it runs only on eligible logged-in requests, uses per-process in-memory throttling, and can skip checks indefinitely when no eligible traffic arrives.

PythonAnywhere's current plan rules distinguish free accounts created before 2026-01-15 (2026-01-08 in the EU system) from newer free accounts. Older free accounts retain one daily scheduled task; newer free accounts have no scheduled tasks. Paid plans support recurring hourly or daily tasks. Confirm the Tasks tab and actual account plan before relying on this. The repository update does not create a PythonAnywhere task or change production configuration.

## Runner added to the repository

`scripts/run_escalation.py` is a one-shot runner intended to be invoked by a supported scheduler or manually. It:

- Reads `~/.config/grievance-portal.env` (or an explicitly supplied file) without executing it as shell code.
- Forces `APP_ENV=production` and `COOKIE_SECURE=1`, requires a non-empty `SECRET_KEY`, and requires an absolute `DATABASE_PATH` (defaulting to the project `complaints.db` if unset).
- Runs the project's `.venv/bin/python -m flask --app app run-escalation` from the repository directory.
- Takes a non-blocking filesystem lock to skip overlapping runner invocations.
- Writes timestamps, output, and failures to a private log file (mode 0600), returning a non-zero exit status on failure.

The environment parser supports simple `KEY=value`, optional `export KEY=value`, comments, and matching outer quotes. It does not execute shell expressions, expand variables, or support multiline values. Confirm that the existing production environment file uses this supported syntax before configuring a task. The runner uses the same environment-file path as the WSGI configuration but is a separate process; it does not inherit the WSGI worker's memory.

## Suggested command on a plan with hourly scheduled tasks

After confirming the plan supports hourly tasks and testing the runner manually, use this as the task command:

```bash
/home/deploynes/grievance-portal/.venv/bin/python /home/deploynes/grievance-portal/scripts/run_escalation.py --env-file /home/deploynes/.config/grievance-portal.env --log-file /home/deploynes/logs/grievance-portal-escalation.log --lock-file /home/deploynes/.config/grievance-portal-escalation.lock --project-dir /home/deploynes/grievance-portal
```

Select hourly recurrence in PythonAnywhere's Tasks tab. This command is a proposal only; no task has been created. On a plan without scheduled tasks, it will run only when manually invoked and does not provide periodic execution.

Before enabling recurrence:

1. Verify the task uses the intended project virtual environment and the same persistent `DATABASE_PATH` as the web application.
2. Confirm the environment file format is supported and permissions restrict access to secrets.
3. Run the command manually once and inspect the log without sharing secrets or case data.
4. Confirm a successful run in the log and check that the live web app remains healthy.
5. Decide whether to disable request-triggered checks by setting `ESCALATION_INTERVAL_SECONDS=0` only after the scheduled runner is confirmed operational. This is a production configuration change and is not performed by this repository change.

## Limits and operational notes

- A scheduler invokes this runner; the runner itself does not schedule future executions.
- A free account without scheduled-task access cannot get automatic periodic runs from this repository alone. Realistic options are upgrading to a plan with hourly tasks or separately approving a secure external scheduler/worker. No external service or endpoint is created here.
- The lock prevents concurrent invocations of this runner on the same host/filesystem. It does not lock out the existing request-triggered lazy hook in web workers, nor does it coordinate across different hosts.
- Alert uniqueness/deduplication is enforced by the application database, but the runner lock is not a distributed lock.
- Hourly scheduling gives an approximate maximum one-hour wait before a scheduled check starts, plus scheduler delay and command duration; it is not a hard real-time guarantee.
- The escalation agent creates alerts and notifications; it does not automatically change case status.
- Logs can contain exception messages. Keep them private, monitor disk usage, and apply retention/rotation appropriate to the host.
- A scheduled task can fail because of an unavailable database, malformed environment file, missing virtualenv, permissions, or resource limits. Review the log and task status; do not treat absence of an alert as proof that the command ran.
- Tests cover environment validation, CLI invocation arguments, failure logging, and lock contention. They do not prove the PythonAnywhere scheduler itself is enabled or that the production task has run.
