import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class CLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-coach-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"), HERMES_HOME=str(self.root / "profile"))

    def run_cli(self, *args, ok=True, data=True, input=None):
        command = [sys.executable, "-m", "task_coach"]
        if data:
            command += ["--data-dir", str(self.data)]
        result = subprocess.run(command + list(args), env=self.env, text=True, input=input, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def test_reads_help_and_default_paths_do_not_initialize(self):
        result = subprocess.run([sys.executable, "-m", "task_coach", "--help"], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        for command in (("list",), ("show", "1"), ("search", "sample"), ("export",)):
            error = self.run_cli(*command, ok=False)
            self.assertIn("init", error.stderr)
            self.assertFalse(self.data.exists())
        self.run_cli("init", data=False)
        self.assertTrue((self.root / "profile" / "task-coach" / "config.json").exists())
        self.assertFalse(self.data.exists())

    def test_add_show_search_export_persistence(self):
        self.run_cli("init")
        title = "sample '); DROP TABLE tasks; --"
        task = self.run_cli("add", title, "--notes", "first\nsecond", "--priority", "high", "--due", "2031-04-05")
        self.assertGreater(task["id"], 0)
        self.assertEqual(task["notes"], "first\nsecond")
        self.assertEqual(task["status"], "open")
        self.assertEqual(self.run_cli("show", str(task["id"])), task)
        self.assertEqual(self.run_cli("search", "DROP TABLE"), [task])
        self.assertEqual(self.run_cli("search", "missing"), [])
        self.assertEqual(self.run_cli("list"), [task])
        self.assertEqual(self.run_cli("export"), [task])
        self.assertEqual(self.run_cli("add", "another")["id"], task["id"] + 1)

    def test_update_done_snooze_preserve_history(self):
        self.run_cli("init")
        task = self.run_cli("add", "original", "--notes", "keep me")
        key = str(task["id"])
        changed = self.run_cli("update", key, "--title", "changed", "--status", "cancelled", "--priority", "low")
        self.assertEqual(changed["notes"], "keep me")
        self.assertEqual(changed["created_at"], task["created_at"])
        self.assertEqual(changed["status"], "cancelled")
        self.assertEqual(changed["title"], "changed")
        done = self.run_cli("done", key)
        self.assertEqual(done["status"], "done")
        self.assertEqual(self.run_cli("done", key), done)
        snoozed = self.run_cli("snooze", key, "2031-04-05T12:30:00+02:00")
        self.assertEqual(snoozed["snoozed_until"], "2031-04-05T12:30:00+02:00")
        self.assertEqual(snoozed["notes"], "keep me")
        self.assertEqual(self.run_cli("show", key), snoozed)

    def test_invalid_task_inputs_have_no_side_effects(self):
        self.run_cli("init")
        task = self.run_cli("add", "valid", "--due", "2031-04-05T12:00:00Z")
        before = (self.data / "tasks.sqlite3").read_bytes()
        invalid = [("add", "  "), ("add", "x", "--priority", "urgent"), ("add", "x", "--due", "2031-02-30"), ("add", "x", "--due", "2031-04-05T12:00:00"), ("update", "1", "--title", ""), ("update", "1", "--status", "unknown"), ("snooze", "1", "2031-04-05"), ("snooze", "1", "2031-04-05T12:00:00"), ("show", "999"), ("done", "999"), ("update", "999", "--title", "other")]
        for args in invalid:
            with self.subTest(args=args):
                self.run_cli(*args, ok=False)
                self.assertEqual((self.data / "tasks.sqlite3").read_bytes(), before)
        self.assertEqual(self.run_cli("show", "1"), task)

    def test_setup_flags_and_rerun_preservation(self):
        config = self.run_cli("setup", "--timezone", "Europe/Paris", "--weekdays", "mon,wed,fri", "--notification-start", "09:00", "--notification-end", "17:00", "--max-unanswered-followups", "3", "--min-followup-interval", "30", "--max-followup-interval", "60", "--destination", "opaque-target")["config"]
        self.assertEqual(config["timezone"], "Europe/Paris")
        self.assertEqual(config["weekdays"], ["mon", "wed", "fri"])
        self.assertEqual(config["max_unanswered_followups"], 3)
        self.assertEqual(config["min_followup_interval"], 30)
        self.assertFalse(config["automation_enabled"])
        task = self.run_cli("add", "survives setup")
        self.assertEqual(self.run_cli("setup")["config"], config)
        self.assertEqual(self.run_cli("init")["config"], config)
        self.run_cli("setup", "--timezone", "UTC", ok=False)
        self.assertEqual(self.run_cli("setup")["config"], config)
        updated = self.run_cli("setup", "--update", "--timezone", "UTC")["config"]
        self.assertEqual(updated["timezone"], "UTC")
        self.assertEqual(updated["destination"], "opaque-target")
        self.assertEqual(self.run_cli("list"), [task])

    def test_setup_validation_precedes_writes(self):
        invalid = [("--timezone", "Invalid/Zone"), ("--weekdays", "mon,bogus"), ("--weekdays", ""), ("--weekdays", "mon,mon"), ("--notification-start", "25:00"), ("--notification-start", "18:00"), ("--notification-end", "09:00"), ("--max-unanswered-followups", "-1"), ("--max-unanswered-followups", "21"), ("--min-followup-interval", "0"), ("--min-followup-interval", "121"), ("--max-followup-interval", "1441"), ("--notification-end", "09:30", "--max-unanswered-followups", "3"), ("--destination", " ")]
        for flags in invalid:
            with self.subTest(flags=flags):
                self.run_cli("setup", *flags, ok=False)
                self.assertFalse(self.data.exists())
        self.run_cli("setup")
        before = (self.data / "config.json").read_bytes()
        self.run_cli("setup", "--update", "--timezone", "Invalid/Zone", ok=False)
        self.assertEqual((self.data / "config.json").read_bytes(), before)

    def test_interactive_setup_and_cancel(self):
        answers = "Europe/Paris\nmon,tue\n10:00\n16:00\n1\n20\n40\n\n"
        config = self.run_cli("setup", "--interactive", input=answers)["config"]
        self.assertEqual(config["timezone"], "Europe/Paris")
        self.assertEqual(config["weekdays"], ["mon", "tue"])
        self.assertEqual(config["notification_start"], "10:00")
        self.assertEqual(config["max_followup_interval"], 40)
        self.data = self.root / "cancelled"
        self.run_cli("setup", "--interactive", input="", ok=False)
        self.assertFalse(self.data.exists())

    def test_symlink_paths_are_rejected(self):
        target = self.root / "target"
        target.write_text("unchanged")
        self.data.mkdir()
        for name in ("tasks.sqlite3", "config.json"):
            path = self.data / name
            path.symlink_to(target)
            for command in ("init", "setup", "list"):
                self.run_cli(command, ok=False)
            self.assertEqual(target.read_text(), "unchanged")
            self.assertFalse((self.data / ("config.json" if name == "tasks.sqlite3" else "tasks.sqlite3")).exists())
            path.unlink()
        self.data.rmdir()
        self.data.symlink_to(self.root / "missing", target_is_directory=True)
        self.run_cli("init", ok=False)
        self.assertFalse((self.root / "missing").exists())

    def test_state_errors_are_reported_without_writes(self):
        self.run_cli("init")
        config_path = self.data / "config.json"
        store = self.data / "tasks.sqlite3"
        original = config_path.read_bytes()
        for bad in ("{", "[]", "null", '{}', '{"timezone": "UTC"}'):
            config_path.write_text(bad)
            before = store.read_bytes()
            for command in (("list",), ("add", "no write"), ("setup",)):
                self.run_cli(*command, ok=False)
                self.assertEqual(store.read_bytes(), before)
        config_path.write_bytes(original)
        store.write_text("not a database")
        for command in (("list",), ("add", "no write"), ("setup", "--update", "--timezone", "Europe/Paris")):
            self.run_cli(*command, ok=False)
            self.assertEqual(config_path.read_bytes(), original)
        self.data = self.root / "not-directory"
        self.data.write_text("file")
        self.run_cli("init", ok=False)

    def test_large_ids_are_clean_input_errors(self):
        self.run_cli("init")
        for command in ("show", "done", "update", "snooze"):
            args = [command, "99999999999999999999999999"]
            if command == "snooze":
                args.append("2031-04-05T12:00:00Z")
            self.run_cli(*args, ok=False)

    def test_xdg_and_home_fallback_paths(self):
        self.env.pop("HERMES_HOME", None)
        self.env["XDG_DATA_HOME"] = str(self.root / "xdg")
        self.run_cli("init", data=False)
        self.assertTrue((self.root / "xdg" / "task-coach" / "config.json").exists())
        self.env.pop("XDG_DATA_HOME")
        self.env["HOME"] = str(self.root / "home")
        self.run_cli("init", data=False)
        self.assertTrue((self.root / "home" / ".local" / "share" / "task-coach" / "config.json").exists())

    def test_empty_xdg_data_home_falls_back_to_home_not_cwd(self):
        self.env.pop("HERMES_HOME", None)
        self.env["XDG_DATA_HOME"] = ""
        home = self.root / "home"
        self.env["HOME"] = str(home)
        cwd = self.root / "cwd"
        cwd.mkdir()
        result = subprocess.run(
            [sys.executable, "-m", "task_coach", "init"],
            env=self.env, cwd=cwd, text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        directory = home / ".local" / "share" / "task-coach"
        self.assertTrue((directory / "config.json").is_file())
        self.assertTrue((directory / "tasks.sqlite3").is_file())
        self.assertFalse((cwd / "task-coach").exists())

    def test_setup_help_documents_defaults(self):
        result = subprocess.run([sys.executable, "-m", "task_coach", "setup", "--help"], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0)
        for text in ("UTC", "09:00", "17:00", "30", "120", "minutes", "disabled"):
            self.assertIn(text, result.stdout)
        self.assertFalse(self.data.exists())

    def test_incompatible_store_is_not_silently_accepted(self):
        import sqlite3
        self.run_cli("init")
        path = self.data / "tasks.sqlite3"
        path.unlink()
        from contextlib import closing
        with closing(sqlite3.connect(path)) as db:
            db.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, unrelated TEXT)")
        path.chmod(0o600)
        config = (self.data / "config.json").read_bytes()
        self.run_cli("setup", "--update", "--timezone", "Europe/Paris", ok=False)
        self.assertEqual((self.data / "config.json").read_bytes(), config)
        self.run_cli("list", ok=False)

    def test_setup_repairs_only_dedicated_storage_permissions(self):
        self.run_cli("init")
        paths = (self.data, self.data / "tasks.sqlite3", self.data / "config.json")
        unrelated = self.data / "unrelated.txt"
        unrelated.write_text("untouched")
        unrelated.chmod(0o644)
        self.root.chmod(0o755)
        for command in ("init", "setup"):
            with self.subTest(command=command):
                for path in paths:
                    path.chmod(0o777 if path.is_dir() else 0o666)
                before = [(path.read_bytes(), path.stat().st_mtime_ns) for path in paths[1:]]
                self.run_cli("setup", "--update", "--timezone", "Invalid/Zone", ok=False)
                self.assertEqual([path.stat().st_mode & 0o777 for path in paths], [0o777, 0o666, 0o666])
                self.run_cli(command)
                self.assertEqual([path.stat().st_mode & 0o777 for path in paths], [0o700, 0o600, 0o600])
                self.assertEqual([(path.read_bytes(), path.stat().st_mtime_ns) for path in paths[1:]], before)
                self.assertEqual(self.root.stat().st_mode & 0o777, 0o755)
                self.assertEqual(unrelated.stat().st_mode & 0o777, 0o644)

    def test_non_setup_commands_reject_unsafe_storage_without_repair(self):
        self.run_cli("init")
        paths = (self.data, self.data / "tasks.sqlite3", self.data / "config.json")
        for unsafe in paths:
            with self.subTest(path=unsafe.name):
                unsafe.chmod(0o777 if unsafe.is_dir() else 0o666)
                before = [(path.stat().st_mode, path.stat().st_mtime_ns) for path in paths]
                contents = [path.read_bytes() for path in paths[1:]]
                for command in (("list",), ("add", "must not write")):
                    error = self.run_cli(*command, ok=False)
                    self.assertIn("permission", error.stderr)
                    self.assertEqual([(path.stat().st_mode, path.stat().st_mtime_ns) for path in paths], before)
                    self.assertEqual([path.read_bytes() for path in paths[1:]], contents)
                unsafe.chmod(0o700 if unsafe.is_dir() else 0o600)

    def test_hardlinked_storage_is_rejected_without_changing_other_paths(self):
        self.run_cli("init")
        for name in ("tasks.sqlite3", "config.json"):
            path = self.data / name
            other = self.root / (name + ".linked")
            other.hardlink_to(path)
            path.chmod(0o644)
            before = (path.read_bytes(), path.stat().st_mode, path.stat().st_mtime_ns)
            for command in (("init",), ("setup",), ("add", "no write")):
                self.run_cli(*command, ok=False)
                self.assertEqual((other.read_bytes(), other.stat().st_mode, other.stat().st_mtime_ns), before)
            other.unlink()
            path.chmod(0o600)

    def test_same_named_incompatible_columns_are_rejected_without_writes(self):
        import sqlite3
        from contextlib import closing

        self.run_cli("init")
        path = self.data / "tasks.sqlite3"
        config_path = self.data / "config.json"
        valid = "id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL, due TEXT, snoozed_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
        schemas = [valid.replace("id INTEGER PRIMARY KEY AUTOINCREMENT", replacement) for replacement in ("id TEXT", "id INTEGER", "id TEXT PRIMARY KEY", "id INTEGER PRIMARY KEY DESC")]
        schemas += [valid.replace("title TEXT NOT NULL", "title TEXT"), valid.replace("notes TEXT NOT NULL", "notes INTEGER NOT NULL"), valid.replace("status TEXT NOT NULL", "status TEXT NOT NULL DEFAULT 'done'")]
        for schema in schemas:
            with self.subTest(schema=schema):
                path.unlink()
                with closing(sqlite3.connect(path)) as db:
                    db.execute("CREATE TABLE tasks (" + schema + ")")
                    db.commit()
                path.chmod(0o600)
                before = [(p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in (path, config_path)]
                for command in (("init",), ("setup", "--update", "--timezone", "Europe/Paris"), ("add", "must not write")):
                    error = self.run_cli(*command, ok=False)
                    self.assertIn("incompatible task store schema", error.stderr)
                    self.assertEqual([(p.read_bytes(), p.stat().st_mode, p.stat().st_mtime_ns) for p in (path, config_path)], before)

    def test_repeated_mutations_return_identical_rows_without_database_writes(self):
        self.run_cli("init")
        self.run_cli("add", "original")
        store = self.data / "tasks.sqlite3"
        commands = (("update", "1", "--title", "changed", "--notes", "note", "--due", "2031-04-05", "--priority", "high", "--status", "cancelled"), ("snooze", "1", "2031-04-05T12:30:00+02:00"), ("done", "1"))
        for command in commands:
            with self.subTest(command=command[0]):
                row = self.run_cli(*command)
                before = (store.read_bytes(), store.stat().st_mtime_ns)
                self.assertEqual(self.run_cli(*command), row)
                self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
                self.assertEqual(self.run_cli("show", "1"), row)

    def test_explicit_init_empty_persistent_store(self):
        result = self.run_cli("init")
        self.assertEqual(result["config"]["timezone"], "UTC")
        self.assertEqual(self.run_cli("list"), [])
        self.assertTrue((self.data / "tasks.sqlite3").is_file())
        self.assertTrue((self.data / "config.json").is_file())
        self.assertEqual(self.data.stat().st_mode & 0o777, 0o700)
        for name in ("tasks.sqlite3", "config.json"):
            self.assertEqual((self.data / name).stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
