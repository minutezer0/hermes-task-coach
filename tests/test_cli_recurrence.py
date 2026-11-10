"""Completion-based recurrence through the real JSON subprocess interface."""
import test_cli_core as fixtures
import unittest
from contextlib import closing
import sqlite3
import concurrent.futures
import json
import subprocess
import sys
import time


class RecurrenceCLI(unittest.TestCase):
    setUp = fixtures.CLITest.setUp
    run_cli = fixtures.CLITest.run_cli
    def test_first_use_concurrent_initializers_do_not_erase_tasks(self):
        code = "import pathlib,time,sys\nfrom task_coach.cli import main\nroot=pathlib.Path(sys.argv[1])\n(root/sys.argv[2]).touch()\ngate=root/'gate'\nwhile not gate.exists(): time.sleep(0.01)\nsys.exit(main(['--data-dir', str(root/'data'), 'init']))"
        children = [subprocess.Popen([sys.executable, '-c', code, str(self.root), 'ready'+str(n)], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for n in range(4)]
        try:
            limit = time.monotonic() + 10
            while not all((self.root / ('ready'+str(n))).exists() for n in range(4)) and time.monotonic() < limit:
                time.sleep(0.01)
            self.assertTrue(all((self.root / ('ready'+str(n))).exists() for n in range(4)))
            (self.root / 'gate').touch()
            for child in children:
                out, err = child.communicate(timeout=15)
                self.assertEqual(child.returncode, 0, err)
                self.assertIn('config', json.loads(out))
            self.run_cli('add', 'Preserved')
            self.run_cli('init')
            self.assertEqual(self.run_cli('list')[0]['title'], 'Preserved')
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate()

    def test_stale_completion_after_removal_does_not_complete_plain_task(self):
        self.run_cli('init')
        task = self.run_cli('add', 'Filter', '--repeat', '1 day', '--due', '2024-01-01')
        removed = self.run_cli('update', '1', '--remove-repeat')
        self.run_cli('done', '1', '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', 'old', ok=False)
        self.assertEqual(self.run_cli('show', '1'), removed)

    def test_unsupported_version_and_malformed_data_refuse_without_mutation(self):
        store = self.data / 'tasks.sqlite3'
        for statement in ('PRAGMA user_version=99', 'PRAGMA user_version=1', "UPDATE tasks SET priority='urgent'"):
            with self.subTest(statement=statement):
                if store.exists():
                    store.unlink()
                self.run_cli('init')
                self.run_cli('add', 'Keep task', '--notes', 'Keep notes', '--priority', 'high')
                with closing(sqlite3.connect(store)) as db:
                    db.execute(statement)
                    db.commit()
                before = (store.read_bytes(), store.stat().st_mtime_ns, sorted(p.name for p in self.data.iterdir()))
                for command in ('list', 'init'):
                    self.run_cli(command, ok=False)
                    self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns, sorted(p.name for p in self.data.iterdir())), before)

    def test_edit_removal_preserves_unrelated_fields_and_guards_status(self):
        self.run_cli('init')
        task = self.run_cli('add', 'Filter', '--notes', 'Keep notes', '--priority', 'high', '--due', '2024-01-01')
        repeated = self.run_cli('update', '1', '--repeat', '3 months')
        for field in ('id', 'title', 'notes', 'priority', 'status', 'due', 'created_at', 'snoozed_until'):
            self.assertEqual(task[field], repeated[field])
        self.run_cli('update', '1', '--status', 'done', ok=False)
        self.run_cli('update', '1', '--status', 'cancelled')
        self.run_cli('update', '1', '--status', 'open', ok=False)
        removed = self.run_cli('update', '1', '--remove-repeat')
        self.assertIsNone(removed['repeat_interval'])
        self.assertEqual(removed['status'], 'cancelled')
        self.assertEqual(removed['due'], task['due'])
        self.assertEqual(self.run_cli('done', '1')['status'], 'done')

    def test_completion_uses_configuration_after_acquiring_shared_lock(self):
        sys.path.insert(0, self.env['PYTHONPATH'])
        from task_coach import cli
        from unittest.mock import patch
        from contextlib import contextmanager, redirect_stdout
        import io
        self.run_cli('init')
        task = self.run_cli('add', 'Filter', '--repeat', '1 month', '--due', '2024-01-01')
        original = cli.task_store_lock
        @contextmanager
        def raced_lock(directory):
            self.run_cli('setup', '--update', '--timezone', 'Asia/Tokyo')
            with original(directory):
                yield
        output = io.StringIO()
        with patch.object(cli, 'task_store_lock', raced_lock), redirect_stdout(output):
            code = cli.main(['--data-dir', str(self.data), 'done', '1', '--completed-at', '2024-01-31T18:30:00Z', '--expected-cycle', task['cycle_id'], '--completion-id', 'raced-timezone'])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['due'], '2024-03-01T03:30:00+09:00')

    def test_valid_guard_rejects_future_date_and_timestamp(self):
        self.run_cli('setup', '--timezone', 'America/Los_Angeles')
        task = self.run_cli('add', 'Filter', '--repeat', '1 month', '--due', '2024-01-01')
        before = (self.data / 'tasks.sqlite3').read_bytes()
        for completed in ('9999-01-01', '9999-01-01T00:00:00Z'):
            error = self.run_cli('done', '1', '--completed-at', completed, '--expected-cycle', task['cycle_id'], '--completion-id', 'future', ok=False)
            self.assertIn('future', error.stderr)
            self.assertEqual((self.data / 'tasks.sqlite3').read_bytes(), before)
        result = self.run_cli('done', '1', '--completed-at', '2024-01-31T18:30:00Z', '--expected-cycle', task['cycle_id'], '--completion-id', 'timestamp')
        self.assertEqual(result['due'], '2024-02-29T10:30:00-08:00')

    def test_versioned_incompatible_ddl_refuses_without_touching_files(self):
        self.run_cli('init')
        sys.path.insert(0, self.env['PYTHONPATH'])
        from task_coach.cli import TASK_DDL
        store = self.data / 'tasks.sqlite3'
        store.unlink()
        with closing(sqlite3.connect(store)) as db:
            db.execute(TASK_DDL.replace('AUTOINCREMENT', 'AUTOINCREMENT CHECK(id > 0)'))
            db.execute('PRAGMA user_version=1')
            db.commit()
        store.chmod(0o600)
        before = (store.read_bytes(), store.stat().st_mtime_ns, sorted(p.name for p in self.data.iterdir()))
        for command in ('list', 'init'):
            self.run_cli(command, ok=False)
            self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns, sorted(p.name for p in self.data.iterdir())), before)

    def test_invalid_and_stale_completions_do_not_write(self):
        self.run_cli('init')
        self.run_cli('add', 'Missing initial due', '--repeat', '1 day', ok=False)
        self.run_cli('add', 'Bad interval', '--repeat', '0 days', '--due', '2024-01-01', ok=False)
        task = self.run_cli('add', 'Filter', '--repeat', '3 months', '--due', '2024-01-01')
        before = (self.data / 'tasks.sqlite3').read_bytes()
        for extra in [(), ('--completed-at', '9999-01-01'), ('--completed-at', '2024-02-30'), ('--completed-at', '2024-01-01', '--expected-cycle', 'stale', '--completion-id', 'a')]:
            self.run_cli('done', '1', *extra, ok=False)
            self.assertEqual((self.data / 'tasks.sqlite3').read_bytes(), before)
        flags = ('done', '1', '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', 'a')
        result = self.run_cli(*flags)
        self.run_cli('done', '1', '--completed-at', '2024-01-02', '--expected-cycle', task['cycle_id'], '--completion-id', 'other', ok=False)
        self.assertEqual(self.run_cli('show', '1'), result)

    def test_adding_recurrence_cannot_create_done_recurring_row(self):
        self.run_cli('init')
        self.run_cli('add', 'Filter', '--due', '2024-01-01')
        self.run_cli('update', '1', '--repeat', '1 day', '--status', 'done', ok=False)
        self.assertIsNone(self.run_cli('show', '1')['repeat_interval'])

    def test_conflicting_concurrent_completions_have_one_winner(self):
        self.run_cli('init')
        task = self.run_cli('add', 'Filter', '--repeat', '1 day', '--due', '2024-01-01')
        def complete(n):
            return subprocess.run([sys.executable, '-m', 'task_coach', '--data-dir', str(self.data), 'done', '1', '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', str(n)], env=self.env, text=True, capture_output=True)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(complete, range(4)))
        self.assertEqual(sum(r.returncode == 0 for r in results), 1)
        self.assertEqual(self.run_cli('show', '1')['due'], '2024-01-02')

    def test_concurrent_completion_only_advances_once(self):
        self.run_cli('init')
        task = self.run_cli('add', 'Water plant', '--repeat', '1 day', '--due', '2024-01-01')
        flags = ('done', str(task['id']), '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', 'watering')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.run_cli(*flags), range(4)))
        self.assertTrue(all(result == results[0] for result in results))
        self.assertEqual(results[0]['due'], '2024-01-02')

    def test_completion_reuses_row_and_retry_survives_restart(self):
        self.run_cli('init')
        task = self.run_cli('add', 'Replace filter', '--repeat', '3 months', '--due', '2024-01-01')
        self.assertTrue(task['cycle_id'])
        self.run_cli('snooze', str(task['id']), '2030-01-01T00:00:00Z')
        flags = ('done', str(task['id']), '--completed-at', '2024-01-31', '--expected-cycle', task['cycle_id'], '--completion-id', 'filter-completion')
        done = self.run_cli(*flags)
        self.assertEqual(done['due'], '2024-04-30')
        self.assertEqual(done['status'], 'open')
        self.assertIsNone(done['snoozed_until'])
        self.assertNotEqual(done['cycle_id'], task['cycle_id'])
        self.assertEqual(self.run_cli(*flags), done)
        self.assertEqual(self.run_cli('list'), [done])
