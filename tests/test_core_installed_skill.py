"""Exercise only a copied skill, never an import from the checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "skills" / "task-coach"


class InstalledSkillTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task coach bundle ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = self.root / "installed skills" / "task-coach"
        shutil.copytree(SOURCE, self.skill, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.cwd = self.root / "unrelated cwd"
        self.cwd.mkdir()
        # Deliberately omit PATH, PYTHONPATH and all real profile/home variables.
        self.env = {"HOME": str(self.root / "fake home"),
                    "HERMES_HOME": str(self.root / "fake profile"),
                    "XDG_DATA_HOME": str(self.root / "fake xdg"),
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}

    def invoke(self, *args, ok=True, input=""):
        result = subprocess.run(
            [sys.executable, "-I", "-B", str(self.skill / "scripts" / "task-coach.py"), *args],
            cwd=self.cwd, env=self.env, input=input, text=True, capture_output=True,
        )
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("Traceback", result.stderr)
        return result

    def cli(self, *args, **kwargs):
        return json.loads(self.invoke(*args, **kwargs).stdout)

    def test_flag_setup_lifecycle_survives_reinstall_and_relocation(self):
        self.invoke("list", ok=False)
        self.assertFalse((self.root / "fake profile").exists())
        config = self.cli("setup", "--timezone", "Europe/Paris", "--weekdays", "mon,wed,fri",
                          "--notification-start", "10:00", "--notification-end", "16:00",
                          "--max-unanswered-followups", "1", "--min-followup-interval", "20",
                          "--max-followup-interval", "40")["config"]
        self.assertEqual(config["timezone"], "Europe/Paris")
        self.assertFalse(config["automation_enabled"])
        self.assertEqual(self.cli("list"), [])
        task = self.cli("add", "Fictional task", "--notes", "one small step", "--priority", "high", "--due", "2031-04-05")
        key = str(task["id"])
        self.assertEqual(self.cli("show", key), task)
        self.assertEqual(self.cli("search", "Fictional"), [task])
        changed = self.cli("update", key, "--title", "Revised task", "--notes", "next step", "--status", "cancelled")
        self.assertEqual(changed["status"], "cancelled")
        snoozed = self.cli("snooze", key, "2031-04-05T12:30:00+02:00")
        self.assertEqual(snoozed["due"], task["due"])
        done = self.cli("done", key)
        self.assertEqual(done["status"], "done")
        self.assertEqual(self.cli("done", key), done)
        self.assertEqual(self.cli("export"), [done])
        store = self.root / "fake profile" / "task-coach"
        before = {p.name: p.read_bytes() for p in store.iterdir()}
        shutil.rmtree(self.skill)
        shutil.copytree(SOURCE, self.skill)
        relocated = self.root / "relocated skills" / "task coach"
        relocated.parent.mkdir()
        shutil.move(str(self.skill), str(relocated))
        self.skill = relocated
        self.assertEqual(self.cli("setup")["config"], config)
        self.assertEqual(self.cli("show", key), done)
        self.assertEqual({p.name: p.read_bytes() for p in store.iterdir()}, before)
        self.assertFalse(any(p.suffix in (".json", ".sqlite3") for p in self.skill.rglob("*")))
        self.assertFalse(any(self.cwd.iterdir()))

    def test_optional_interactive_setup_and_default_storage_are_isolated(self):
        self.env.pop("HERMES_HOME")
        config = self.cli("setup", "--interactive", input="UTC\nmon,tue\n10:00\n16:00\n1\n20\n40\n\n")["config"]
        self.assertEqual(config["weekdays"], ["mon", "tue"])
        self.assertTrue((self.root / "fake xdg" / "task-coach" / "config.json").is_file())
        self.env.pop("XDG_DATA_HOME")
        self.cli("init")
        self.assertEqual(self.cli("list"), [])
        self.assertTrue((self.root / "fake home" / ".local" / "share" / "task-coach" / "config.json").is_file())
        explicit = self.root / "explicit data"
        self.cli("--data-dir", str(explicit), "setup")
        self.assertTrue((explicit / "config.json").is_file())

    def test_unsupported_python_exits_before_importing_runtime(self):
        # Simulate an older interpreter; a missing runtime proves the guard runs first.
        shutil.rmtree(self.skill / "scripts" / "task_coach")
        script = self.skill / "scripts" / "task-coach.py"
        code = "import runpy, sys; sys.version_info = (3, 10, 0); runpy.run_path(sys.argv[1], run_name='__main__')"
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(script)],
                                env=self.env, cwd=self.cwd, text=True, capture_output=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Python 3.11 or newer", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.root / "fake profile").exists())

    def test_copied_skill_help_needs_no_install_or_initialization(self):
        result = self.invoke("--help")
        self.assertIn("setup", result.stdout)
        self.assertIn("automation remains disabled", self.invoke("setup", "--help").stdout)
        self.assertFalse((self.root / "fake profile").exists())
        self.assertFalse((self.root / "fake home").exists())
        self.assertFalse((self.root / "fake xdg").exists())
        self.assertFalse(any(p.is_symlink() for p in self.skill.rglob("*")))


if __name__ == "__main__":
    unittest.main()
