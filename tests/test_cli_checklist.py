"""Checklist reads and marker-only note edits; fictional stores only."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills" / "task-coach" / "scripts"


class ChecklistCLITest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="task-coach-checklist-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
                        PYTHONPATH=str(SCRIPTS), HERMES_HOME=str(self.root / "profile"))
        self.run_cli("init")

    def run_cli(self, *args, ok=True):
        command = [sys.executable, "-m", "task_coach", "--data-dir", str(self.data), *args]
        result = subprocess.run(command, env=self.env, text=True, capture_output=True)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        return result


class ChecklistReadTest(ChecklistCLITest):
    def test_show_indexes_items_and_counts_checked(self):
        notes = ("- [ ] call plumber\n"
                 "- [x] buy paint\n"
                 "* [X] measure\n"
                 "- [ ] call plumber\n"
                 "Not a task line\n")
        task = self.run_cli("add", "Renovation", "--notes", notes)
        checklist = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual(checklist["id"], task["id"])
        self.assertEqual(checklist["checked"], 2)
        self.assertEqual(checklist["total"], 4)
        self.assertEqual(checklist["notes_digest"], hashlib.sha256(notes.encode()).hexdigest())
        self.assertEqual([item["index"] for item in checklist["items"]], [1, 2, 3, 4])
        self.assertEqual([item["checked"] for item in checklist["items"]], [False, True, True, False])
        self.assertEqual([item["text"] for item in checklist["items"]],
                         ["call plumber", "buy paint", "measure", "call plumber"])
        self.assertEqual(self.run_cli("show", str(task["id"])), task)

    ADDRESS_NOTES = ("[x] Bank\n"
                     "[x] Chase Bank\n"
                     "[ ] Credit card\n"
                     "[x] Cell\n"
                     "[x] MS account\n"
                     "[ ] Work\n"
                     "[ ] Doctor\n"
                     "[ ] Dentist\n"
                     "[x] SAIT\n"
                     "[ ] Sun Life\n"
                     "[x] waterhouse")

    def test_bare_checkboxes_report_items_and_progress(self):
        task = self.run_cli("add", "Errands", "--notes", self.ADDRESS_NOTES)
        checklist = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual(checklist["notes_digest"],
                         hashlib.sha256(self.ADDRESS_NOTES.encode()).hexdigest())
        self.assertEqual(checklist["checked"], 6)
        self.assertEqual(checklist["total"], 11)
        self.assertEqual([item["index"] for item in checklist["items"]], list(range(1, 12)))
        self.assertEqual([item["checked"] for item in checklist["items"]],
                         [True, True, False, True, True, False, False, False, True, False, True])
        self.assertEqual([item["text"] for item in checklist["items"]],
                         ["Bank", "Chase Bank", "Credit card", "Cell", "MS account", "Work",
                          "Doctor", "Dentist", "SAIT", "Sun Life", "waterhouse"])
        self.assertEqual(self.run_cli("show", str(task["id"])), task)

    def test_bare_and_bulleted_forms_mix_outside_fences(self):
        notes = ("[ ] bare\n"
                 "- [x] bulleted\n"
                 "   [X] three spaces\n"
                 "    [ ] four spaces\n"
                 "```\n[ ] fenced bare\n- [ ] fenced bullet\n```\n"
                 "~~~\n[x] tilde fenced\n~~~\n"
                 "[ ]no separator\n"
                 "Paragraph with [ ] bracket\n"
                 "* [ ] star\n")
        task = self.run_cli("add", "Mixed forms", "--notes", notes)
        checklist = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual(checklist["total"], 4)
        self.assertEqual([item["text"] for item in checklist["items"]],
                         ["bare", "bulleted", "three spaces", "star"])
        self.assertEqual([item["checked"] for item in checklist["items"]],
                         [False, True, True, False])

    def test_only_clear_markdown_task_lines_count(self):
        notes = ("Plan:\n"
                 "```\n- [ ] fenced example\n```\n"
                 "~~~text\n- [x] tilde fenced\n~~~\n"
                 "    - [ ] four-space code\n"
                 "- [] missing marker space\n"
                 "- [ ]no text separator\n"
                 "1. [ ] ordered item\n"
                 "   - [ ] three-space item\n"
                 "  - [ ] nested item\n"
                 "```\n- [ ] reopened fence\n```\n")
        task = self.run_cli("add", "Mixed notes", "--notes", notes)
        checklist = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual(checklist["total"], 2)
        self.assertEqual([item["text"] for item in checklist["items"]],
                         ["three-space item", "nested item"])
        self.assertEqual([item["checked"] for item in checklist["items"]], [False, False])


class ChecklistMutationTest(ChecklistCLITest):
    NOTES = ("Header  \r\n"
             "\tkeep this tab\n"
             "- [ ] same label\n"
             "  - [x] same label  \n"
             "Paragraph with [ ] bracket\n"
             "```\n- [ ] fenced\n```\r\n"
             "- [X] last\r\n"
             "tail without newline")

    def test_check_and_uncheck_change_only_the_marker(self):
        task = self.run_cli("add", "Preservation", "--notes", self.NOTES)
        original = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual((original["checked"], original["total"]), (2, 3))
        checked = self.run_cli("checklist", "check", str(task["id"]), "1",
                               "--expected-notes-digest", original["notes_digest"])
        expected_checked = self.NOTES.replace("- [ ] same label", "- [x] same label", 1)
        self.assertEqual(checked["checked"], 3)
        self.assertEqual(checked["total"], 3)
        self.assertEqual([item["checked"] for item in checked["items"]], [True, True, True])
        after_check = self.run_cli("show", str(task["id"]))
        self.assertEqual(after_check["notes"], expected_checked)
        self.assertEqual(checked["notes_digest"], hashlib.sha256(expected_checked.encode()).hexdigest())
        for field in ("title", "priority", "status", "due", "snoozed_until", "created_at",
                      "repeat_interval", "cycle_id", "last_completion", "check_in_days"):
            self.assertEqual(after_check[field], task[field], field)

        unchecked = self.run_cli("checklist", "uncheck", str(task["id"]), "3",
                                 "--expected-notes-digest", checked["notes_digest"])
        expected_unchecked = expected_checked.replace("- [X] last", "- [ ] last", 1)
        self.assertEqual([item["checked"] for item in unchecked["items"]], [True, True, False])
        self.assertEqual(self.run_cli("show", str(task["id"]))["notes"], expected_unchecked)

    def test_bare_checkbox_check_and_uncheck_change_only_the_marker(self):
        notes = ("[x] Bank\r\n"
                 "[ ] Credit card\n"
                 "  [X] Passport  \n"
                 "- [ ] bulleted\n"
                 "keep [ ] bracket\n")
        task = self.run_cli("add", "Bare preservation", "--notes", notes)
        original = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual((original["checked"], original["total"]), (2, 4))
        checked = self.run_cli("checklist", "check", str(task["id"]), "2",
                               "--expected-notes-digest", original["notes_digest"])
        expected_checked = notes.replace("[ ] Credit card", "[x] Credit card", 1)
        self.assertEqual((checked["checked"], checked["total"]), (3, 4))
        self.assertEqual([item["checked"] for item in checked["items"]],
                         [True, True, True, False])
        stored = self.run_cli("show", str(task["id"]))
        self.assertEqual(stored["notes"], expected_checked)
        self.assertTrue(stored["notes"].startswith("[x] Bank\r\n"))
        self.assertIn("  [X] Passport  \n", stored["notes"])
        self.assertIn("- [ ] bulleted\n", stored["notes"])

        unchecked = self.run_cli("checklist", "uncheck", str(task["id"]), "3",
                                 "--expected-notes-digest", checked["notes_digest"])
        expected_unchecked = expected_checked.replace("[X] Passport", "[ ] Passport", 1)
        self.assertEqual((unchecked["checked"], unchecked["total"]), (2, 4))
        self.assertEqual([item["checked"] for item in unchecked["items"]],
                         [True, True, False, False])
        self.assertEqual(self.run_cli("show", str(task["id"]))["notes"], expected_unchecked)

    def test_duplicate_check_of_current_state_writes_nothing(self):
        task = self.run_cli("add", "Idempotent", "--notes", "- [ ] one\n- [x] two\n")
        original = self.run_cli("checklist", "show", str(task["id"]))
        checked = self.run_cli("checklist", "check", str(task["id"]), "1",
                               "--expected-notes-digest", original["notes_digest"])
        store = self.data / "tasks.sqlite3"
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        self.assertEqual(self.run_cli("checklist", "check", str(task["id"]), "1",
                                      "--expected-notes-digest", checked["notes_digest"]), checked)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
        self.assertEqual(self.run_cli("checklist", "show", str(task["id"])), checked)

    def test_uppercase_checked_and_plain_unchecked_are_already_current(self):
        upper = self.run_cli("add", "Upper", "--notes", "- [X] done\n")
        view = self.run_cli("checklist", "show", str(upper["id"]))
        store = self.data / "tasks.sqlite3"
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        self.assertEqual(self.run_cli("checklist", "check", str(upper["id"]), "1",
                                      "--expected-notes-digest", view["notes_digest"]), view)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
        self.assertEqual(self.run_cli("show", str(upper["id"]))["notes"], "- [X] done\n")

        plain = self.run_cli("add", "Plain", "--notes", "- [ ] open\n")
        view = self.run_cli("checklist", "show", str(plain["id"]))
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        self.assertEqual(self.run_cli("checklist", "uncheck", str(plain["id"]), "1",
                                      "--expected-notes-digest", view["notes_digest"]), view)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)


class ChecklistGuardTest(ChecklistCLITest):
    def setUp(self):
        super().setUp()
        self.task = self.run_cli("add", "Guards", "--notes", "intro\n- [ ] a\n- [x] b\n")

    def test_stale_notes_digest_refuses_without_writes(self):
        original = self.run_cli("checklist", "show", str(self.task["id"]))
        self.run_cli("update", str(self.task["id"]), "--notes", "intro\n- [ ] a\n- [x] b\n- [ ] c\n")
        store = self.data / "tasks.sqlite3"
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        error = self.run_cli("checklist", "check", str(self.task["id"]), "1",
                             "--expected-notes-digest", original["notes_digest"], ok=False)
        self.assertIn("notes changed since checklist read", error.stderr)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)

    def test_bare_checkbox_stale_digest_refuses_without_writes(self):
        task = self.run_cli("add", "Bare guards", "--notes", "[ ] a\n[x] b\n")
        original = self.run_cli("checklist", "show", str(task["id"]))
        self.assertEqual((original["checked"], original["total"]), (1, 2))
        changed = "[ ] a\n[x] b\n[ ] c\n"
        self.run_cli("update", str(task["id"]), "--notes", changed)
        store = self.data / "tasks.sqlite3"
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        error = self.run_cli("checklist", "check", str(task["id"]), "1",
                             "--expected-notes-digest", original["notes_digest"], ok=False)
        self.assertIn("notes changed since checklist read", error.stderr)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
        self.assertEqual(self.run_cli("show", str(task["id"]))["notes"], changed)

    def test_invalid_tokens_and_indexes_refuse_without_writes(self):
        digest = self.run_cli("checklist", "show", str(self.task["id"]))["notes_digest"]
        store = self.data / "tasks.sqlite3"
        cases = [
            (("checklist", "check", str(self.task["id"]), "1", "--expected-notes-digest", "not-a-digest"), "invalid expected notes digest"),
            (("checklist", "check", str(self.task["id"]), "1", "--expected-notes-digest", digest.upper()), "invalid expected notes digest"),
            (("checklist", "check", str(self.task["id"]), "0", "--expected-notes-digest", digest), "index out of range"),
            (("checklist", "check", str(self.task["id"]), "3", "--expected-notes-digest", digest), "index out of range"),
            (("checklist", "uncheck", str(self.task["id"]), "0", "--expected-notes-digest", digest), "index out of range"),
            (("checklist", "uncheck", str(self.task["id"]), "3", "--expected-notes-digest", digest), "index out of range"),
            (("checklist", "check", "999", "1", "--expected-notes-digest", digest), "task not found"),
        ]
        for args, message in cases:
            with self.subTest(args=args):
                before = (store.read_bytes(), store.stat().st_mtime_ns)
                error = self.run_cli(*args, ok=False)
                self.assertIn(message, error.stderr)
                self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
                self.assertEqual(self.run_cli("show", str(self.task["id"]))["notes"], "intro\n- [ ] a\n- [x] b\n")
        error = self.run_cli("checklist", "check", str(self.task["id"]), "1", ok=False)
        self.assertIn("--expected-notes-digest", error.stderr)

    def test_show_is_read_only_and_empty_notes_report_zero(self):
        store = self.data / "tasks.sqlite3"
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        self.assertEqual(self.run_cli("checklist", "show", str(self.task["id"]))["total"], 2)
        self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
        empty = self.run_cli("add", "No list")
        checklist = self.run_cli("checklist", "show", str(empty["id"]))
        self.assertEqual((checklist["checked"], checklist["total"], checklist["items"]), (0, 0, []))
        self.assertEqual(checklist["notes_digest"], hashlib.sha256(b"").hexdigest())
        error = self.run_cli("checklist", "check", str(empty["id"]), "1",
                             "--expected-notes-digest", checklist["notes_digest"], ok=False)
        self.assertIn("index out of range", error.stderr)


class ChecklistLifecycleSafetyTest(ChecklistCLITest):
    def test_checking_items_never_changes_task_lifecycle(self):
        notes = "- [ ] one\n- [ ] two\n"
        recurring = self.run_cli("add", "Water plants", "--notes", notes,
                                 "--repeat", "1 month", "--due", "2027-01-31")
        view = self.run_cli("checklist", "show", str(recurring["id"]))
        final = self.run_cli("checklist", "check", str(recurring["id"]), "2",
                             "--expected-notes-digest", view["notes_digest"])
        self.assertEqual((final["checked"], final["total"]), (1, 2))
        refreshed = self.run_cli("show", str(recurring["id"]))
        for field in ("status", "due", "repeat_interval", "cycle_id", "last_completion"):
            self.assertEqual(refreshed[field], recurring[field], field)
        self.assertEqual(refreshed["status"], "open")

        plain = self.run_cli("add", "Plain", "--notes", notes)
        self.run_cli("done", str(plain["id"]))
        done = self.run_cli("show", str(plain["id"]))
        view = self.run_cli("checklist", "show", str(plain["id"]))
        self.run_cli("checklist", "check", str(plain["id"]), "1",
                     "--expected-notes-digest", view["notes_digest"])
        after = self.run_cli("show", str(plain["id"]))
        for field in ("status", "due", "snoozed_until", "repeat_interval", "cycle_id", "last_completion"):
            self.assertEqual(after[field], done[field], field)

        cancelled = self.run_cli("add", "Cancelled", "--notes", notes)
        cancelled = self.run_cli("update", str(cancelled["id"]), "--status", "cancelled")
        view = self.run_cli("checklist", "show", str(cancelled["id"]))
        self.run_cli("checklist", "check", str(cancelled["id"]), "1",
                     "--expected-notes-digest", view["notes_digest"])
        self.assertEqual(self.run_cli("show", str(cancelled["id"]))["status"], "cancelled")

        snoozed = self.run_cli("add", "Snoozed", "--notes", notes)
        snoozed = self.run_cli("snooze", str(snoozed["id"]), "2031-04-05T12:30:00+02:00")
        view = self.run_cli("checklist", "show", str(snoozed["id"]))
        self.run_cli("checklist", "uncheck", str(snoozed["id"]), "1",
                     "--expected-notes-digest", view["notes_digest"])
        self.assertEqual(self.run_cli("show", str(snoozed["id"])), snoozed)

    def test_bare_checkbox_check_never_completes_a_recurring_task(self):
        notes = "[ ] one\n[ ] two"
        task = self.run_cli("add", "Bare recurring", "--notes", notes,
                            "--repeat", "1 month", "--due", "2027-01-31")
        view = self.run_cli("checklist", "show", str(task["id"]))
        final = self.run_cli("checklist", "check", str(task["id"]), "2",
                             "--expected-notes-digest", view["notes_digest"])
        self.assertEqual((final["checked"], final["total"]), (1, 2))
        refreshed = self.run_cli("show", str(task["id"]))
        for field in ("status", "due", "snoozed_until", "repeat_interval", "cycle_id", "last_completion"):
            self.assertEqual(refreshed[field], task[field], field)
        self.assertEqual(refreshed["notes"], "[ ] one\n[x] two")

    def test_check_waits_for_the_task_store_lock(self):
        task = self.run_cli("add", "Locked", "--notes", "- [ ] one\n")
        digest = self.run_cli("checklist", "show", str(task["id"]))["notes_digest"]
        fd = os.open(self.data, os.O_RDONLY | os.O_DIRECTORY)
        process = None
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            process = subprocess.Popen(
                [sys.executable, "-m", "task_coach", "--data-dir", str(self.data),
                 "checklist", "check", str(task["id"]), "1",
                 "--expected-notes-digest", digest],
                env=self.env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with self.assertRaises(subprocess.TimeoutExpired,
                                   msg="checklist writer committed while the store lock was held"):
                process.communicate(timeout=0.4)
        finally:
            os.close(fd)
        stdout, stderr = process.communicate(timeout=10)
        self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(json.loads(stdout)["checked"], 1)


if __name__ == "__main__":
    unittest.main()
