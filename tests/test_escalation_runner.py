import fcntl
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock

from scripts.run_escalation import read_env_file, run_once


class EscalationRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.python = self.project / ".venv" / "bin" / "python"
        self.python.parent.mkdir(parents=True)
        self.python.write_text("# test executable placeholder\n", encoding="utf-8")
        self.env_file = self.root / "production.env"
        self.env_file.write_text(
            'APP_ENV="development"\n'
            'COOKIE_SECURE=0\n'
            'SECRET_KEY="test-secret-value"\n'
            f'DATABASE_PATH="{self.root / "live.db"}"\n',
            encoding="utf-8",
        )
        self.log_file = self.root / "logs" / "escalation.log"
        self.lock_file = self.root / "run" / "escalation.lock"
        self.command = Mock(
            return_value=subprocess.CompletedProcess(
                args=["python"], returncode=0, stdout="Escalation check complete.\n",
                stderr=""
            )
        )

    def tearDown(self):
        self.temp.cleanup()

    def run_runner(self, **overrides):
        args = {
            "env_file": self.env_file,
            "log_file": self.log_file,
            "lock_file": self.lock_file,
            "project_dir": self.project,
            "python_executable": self.python,
            "subprocess_run": self.command,
        }
        args.update(overrides)
        return run_once(**args)

    def test_loads_production_environment_and_runs_cli_from_project(self):
        self.assertEqual(self.run_runner(), 0)
        args, kwargs = self.command.call_args
        self.assertEqual(
            args[0],
            [str(self.python), "-m", "flask", "--app", "app", "run-escalation"],
        )
        self.assertEqual(kwargs["cwd"], str(self.project))
        self.assertEqual(kwargs["env"]["APP_ENV"], "production")
        self.assertEqual(kwargs["env"]["COOKIE_SECURE"], "1")
        self.assertEqual(kwargs["env"]["SECRET_KEY"], "test-secret-value")
        self.assertEqual(kwargs["env"]["DATABASE_PATH"], str(self.root / "live.db"))
        self.assertEqual(kwargs["timeout"], 300)
        self.assertIn("completed successfully", self.log_file.read_text())
        self.assertEqual(self.log_file.stat().st_mode & 0o777, 0o600)

    def test_missing_secret_fails_closed_and_logs_failure(self):
        self.env_file.write_text("APP_ENV=production\n", encoding="utf-8")
        self.assertEqual(self.run_runner(), 1)
        self.command.assert_not_called()
        self.assertIn("SECRET_KEY is missing", self.log_file.read_text())

    def test_relative_database_path_fails_closed(self):
        self.env_file.write_text(
            "SECRET_KEY=present\nDATABASE_PATH=complaints.db\n",
            encoding="utf-8",
        )
        self.assertEqual(self.run_runner(), 1)
        self.command.assert_not_called()
        self.assertIn("DATABASE_PATH must be an absolute path", self.log_file.read_text())

    def test_shell_secret_does_not_replace_missing_file_secret(self):
        self.env_file.write_text("DATABASE_PATH=" + str(self.root / "live.db") + "\\n",
                                encoding="utf-8")
        with unittest.mock.patch.dict(os.environ, {"SECRET_KEY": "inherited-secret"}):
            self.assertEqual(self.run_runner(), 1)
        self.command.assert_not_called()
        self.assertIn("SECRET_KEY is missing from the production environment file",
                      self.log_file.read_text())

    def test_nonzero_command_exit_is_logged_and_returned(self):
        self.command.return_value = subprocess.CompletedProcess(
            args=["python"], returncode=7, stdout="", stderr="database unavailable"
        )
        self.assertEqual(self.run_runner(), 7)
        log = self.log_file.read_text()
        self.assertIn("database unavailable", log)
        self.assertIn("failed with exit code 7", log)

    def test_lock_contention_skips_second_run(self):
        self.lock_file.parent.mkdir(parents=True)
        with self.lock_file.open("a", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertEqual(self.run_runner(), 0)
            self.command.assert_not_called()
        self.assertIn("another escalation run holds the lock", self.log_file.read_text())

    def test_env_parser_does_not_execute_shell_expressions(self):
        env = self.root / "literal.env"
        env.write_text(
            'SECRET_KEY="literal value"\n'
            'VALUE=$(touch /tmp/should-not-exist)\n'
            '# ignored\n',
            encoding="utf-8",
        )
        parsed = read_env_file(env)
        self.assertEqual(parsed["SECRET_KEY"], "literal value")
        self.assertEqual(parsed["VALUE"], "$(touch /tmp/should-not-exist)")

    def test_malformed_env_entry_is_rejected(self):
        env = self.root / "malformed.env"
        env.write_text("NOT AN ASSIGNMENT\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Invalid environment entry"):
            read_env_file(env)


if __name__ == "__main__":
    unittest.main()
