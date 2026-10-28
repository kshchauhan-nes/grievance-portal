#!/usr/bin/env python3
"""Run the Grievance Portal escalation CLI once, with production safeguards.

This script does not schedule itself. Invoke it from a supported recurring
scheduler (for example, a PythonAnywhere hourly task on a plan that supports
scheduled tasks) or run it manually.
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Callable, Mapping, Sequence


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ENV_FILE = Path.home() / ".config" / "grievance-portal.env"
DEFAULT_LOG_FILE = Path.home() / "logs" / "grievance-portal-escalation.log"
DEFAULT_LOCK_FILE = Path.home() / ".config" / "grievance-portal-escalation.lock"
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=value or export KEY=value lines without executing shell."""
    values: dict[str, str] = {}
    for number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid environment entry on line {number}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not ENV_KEY_RE.fullmatch(key):
            raise ValueError(f"Invalid environment key on line {number}")
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or not value.endswith(quote):
                raise ValueError(f"Unclosed quoted value on line {number}")
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key] = value
    return values


def make_logger(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"grievance_escalation_runner_{id(log_path)}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.handlers.clear()
    handler = logging.FileHandler(log_path, encoding="utf-8")
    try:
        os.chmod(log_path, 0o600)
    except OSError:
        handler.close()
        raise
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def run_once(
    *,
    env_file: Path = DEFAULT_ENV_FILE,
    log_file: Path = DEFAULT_LOG_FILE,
    lock_file: Path = DEFAULT_LOCK_FILE,
    project_dir: Path = PROJECT_DIR,
    python_executable: Path | None = None,
    subprocess_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> int:
    """Run one locked CLI invocation; return its exit code."""
    logger = make_logger(log_file)
    try:
        if not env_file.is_file():
            raise FileNotFoundError(f"Production environment file not found: {env_file}")

        env = os.environ.copy()
        env.update(read_env_file(env_file))
        # A scheduled job must not accidentally inherit a development mode.
        env["APP_ENV"] = "production"
        env["COOKIE_SECURE"] = "1"
        env.setdefault("DATABASE_PATH", str(project_dir / "complaints.db"))

        if not env.get("SECRET_KEY", "").strip():
            raise ValueError("SECRET_KEY is missing from the production environment")
        if not Path(env["DATABASE_PATH"]).is_absolute():
            raise ValueError("DATABASE_PATH must be an absolute path for scheduled runs")

        python = python_executable or (project_dir / ".venv" / "bin" / "python")
        if not python.is_file():
            raise FileNotFoundError(f"Project virtualenv Python not found: {python}")

        lock_file.parent.mkdir(parents=True, exist_ok=True)
        with lock_file.open("a", encoding="utf-8") as lock_handle:
            os.chmod(lock_file, 0o600)
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                logger.info("Skipped: another escalation run holds the lock")
                return 0

            command: Sequence[str] = (
                str(python), "-m", "flask", "--app", "app", "run-escalation"
            )
            logger.info("Escalation run started")
            try:
                result = subprocess_run(
                    command,
                    cwd=str(project_dir),
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                    timeout=300,
                )
            except Exception:
                logger.exception("Escalation command could not complete")
                return 1

            if result.stdout.strip():
                logger.info("Command output: %s", result.stdout.strip())
            if result.stderr.strip():
                log_method = logger.error if result.returncode else logger.warning
                log_method("Command stderr: %s", result.stderr.strip())

            if result.returncode:
                logger.error("Escalation command failed with exit code %s", result.returncode)
                return result.returncode

            logger.info("Escalation run completed successfully")
            return 0
    except Exception:
        logger.exception("Escalation runner failed before command completion")
        return 1
    finally:
        for handler in logger.handlers[:]:
            handler.flush()
            handler.close()
            logger.removeHandler(handler)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK_FILE)
    parser.add_argument("--project-dir", type=Path, default=PROJECT_DIR)
    args = parser.parse_args(argv)
    return run_once(
        env_file=args.env_file,
        log_file=args.log_file,
        lock_file=args.lock_file,
        project_dir=args.project_dir,
    )


if __name__ == "__main__":
    sys.exit(main())
