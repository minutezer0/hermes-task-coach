"""Fresh runtime preference ordering; synthetic CLI stores only, never live data."""
import contextlib
import io
import json
import os
import sqlite3
import unittest
from contextlib import closing

import test_core_coaching as fixtures
from task_coach.cli import main

ROUTE = dict(binding=dict(owner='owner-test', profile='profile-test', account='account-test',
                          chat='123', thread='none'), platform='discord',
             destination='discord:123', channel_id='123', bot_id='456')
ROUTE_JSON = json.dumps(ROUTE)
OUTBOX = 'outbox.sqlite3'


class FreshPreferenceTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli

    def run_cli(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(['--data-dir', str(self.data), *args])
        return code, out.getvalue(), err.getvalue()

    def snapshot(self):
        return {name: ((self.data / name).read_bytes(), (self.data / name).stat().st_mtime_ns)
                for name in ('config.json', 'tasks.sqlite3')}

    def configure(self):
        code, out, err = self.run_cli('runtime', 'configure', '--route', ROUTE_JSON, '--confirm-setup')
        self.assertEqual((code, err), (0, ''))
        return json.loads(out)

    def outbox(self):
        return self.data / OUTBOX

    def test_history_disable_before_configure_refuses_cleanly_then_saves_after(self):
        before = self.snapshot()
        for attempt in (1, 2):
            code, out, err = self.run_cli('runtime', 'history-preference', '--disable')
            self.assertEqual(code, 2, f'attempt {attempt}: {err}')
            self.assertIn('runtime setup not confirmed', err)
            self.assertEqual(out, '')
            self.assertFalse(self.outbox().exists(),
                             'a refused preference write must not create outbox.sqlite3')
            self.assertEqual(self.snapshot(), before)

        code, out, err = self.run_cli('runtime', 'history-preference', '--enable',
                                      '--confirm-history', '--route', ROUTE_JSON)
        self.assertEqual(code, 2, err)
        self.assertIn('runtime setup not confirmed', err)
        self.assertFalse(self.outbox().exists())

        self.assertTrue(self.configure()['configured'])
        self.assertEqual(json.loads(self.run_cli('runtime', 'status')[1])['route'], ROUTE)

        code, out, err = self.run_cli('runtime', 'history-preference', '--disable')
        self.assertEqual((code, err), (0, ''))
        disabled = json.loads(out)
        self.assertEqual((disabled['enabled'], disabled['route']), (False, ROUTE))
        self.assertEqual(json.loads(self.run_cli('runtime', 'history-preference')[1]), disabled)

        code, out, err = self.run_cli('runtime', 'history-preference', '--enable',
                                      '--confirm-history', '--route', ROUTE_JSON)
        self.assertEqual((code, err), (0, ''))
        enabled = json.loads(out)
        self.assertTrue(enabled['enabled'])
        self.assertEqual(json.loads(self.run_cli('runtime', 'history-preference')[1]), enabled)
        self.assertEqual(self.snapshot(), before)

    def test_smart_snooze_before_configure_refuses_cleanly_then_saves_after(self):
        before = self.snapshot()
        for switch in ('--enable', '--disable'):
            for attempt in (1, 2):
                code, out, err = self.run_cli('runtime', 'smart-snooze', switch)
                self.assertEqual(code, 2, f'{switch} attempt {attempt}: {err}')
                self.assertIn('runtime setup not confirmed', err)
                self.assertEqual(out, '')
                self.assertFalse(self.outbox().exists(),
                                 'a refused preference write must not create outbox.sqlite3')
                self.assertEqual(self.snapshot(), before)

        self.configure()
        for switch, expected in (('--enable', True), ('--disable', False)):
            code, out, err = self.run_cli('runtime', 'smart-snooze', switch)
            self.assertEqual((code, err), (0, ''))
            self.assertEqual(json.loads(out), {'enabled': expected})
            readback = json.loads(self.run_cli('runtime', 'smart-snooze')[1])
            self.assertEqual(readback, {'enabled': expected})
        self.assertEqual(self.snapshot(), before)

    def test_existing_zero_byte_runtime_recovers_on_configure_without_deletion(self):
        # A v1.0.1 failed history write left this artifact; no state was committed.
        path = self.outbox()
        path.write_bytes(b'')
        os.chmod(path, 0o600)
        before = self.snapshot()
        stamp = path.stat().st_mtime_ns
        for args in (('runtime', 'history-preference', '--disable'),
                     ('runtime', 'smart-snooze', '--enable')):
            code, out, err = self.run_cli(*args)
            self.assertEqual(code, 2, err)
            self.assertIn('runtime setup not confirmed', err)
            self.assertEqual(path.read_bytes(), b'')
            self.assertEqual(path.stat().st_mtime_ns, stamp)

        self.configure()
        self.assertGreater(path.stat().st_size, 0)
        self.assertEqual(json.loads(self.run_cli('runtime', 'status')[1])['route'], ROUTE)
        self.assertEqual(self.snapshot(), before)

    def test_pre_route_writes_refuse_on_an_initialized_unconfigured_runtime(self):
        # status is a permitted read that initializes a valid route-less runtime.
        self.assertIsNone(json.loads(self.run_cli('runtime', 'status')[1])['route'])
        path = self.outbox()
        self.assertGreater(path.stat().st_size, 0)
        before = path.read_bytes(), path.stat().st_mtime_ns
        for args in (('runtime', 'history-preference', '--disable'),
                     ('runtime', 'smart-snooze', '--enable'),
                     ('runtime', 'smart-snooze', '--disable')):
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertIn('runtime setup not confirmed', err)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.configure()
        self.assertEqual(json.loads(self.run_cli('runtime', 'status')[1])['route'], ROUTE)

    def test_history_enable_on_initialized_unconfigured_runtime_reports_setup(self):
        # status is a permitted read that initializes a valid route-less runtime.
        self.assertIsNone(json.loads(self.run_cli('runtime', 'status')[1])['route'])
        path = self.outbox()
        before = path.read_bytes(), path.stat().st_mtime_ns
        for args in (('runtime', 'history-preference', '--enable',
                      '--confirm-history', '--route', ROUTE_JSON),
                     ('runtime', 'history-preference', '--enable')):
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertIn('runtime setup not confirmed', err)
                self.assertNotIn('requires explicit confirmation', err)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.configure()
        self.assertEqual(json.loads(self.run_cli('runtime', 'status')[1])['route'], ROUTE)

    def test_zero_byte_runtime_with_journal_sidecar_refuses_and_keeps_main(self):
        # A sidecar may still hold state, so bare-zero recovery must not treat
        # the main file as an uncommitted initialization.
        path = self.outbox()
        journal = self.data / (OUTBOX + '-journal')
        calls = [('runtime', 'history-preference', '--disable'),
                 ('runtime', 'smart-snooze', '--enable'),
                 ('runtime', 'configure', '--route', ROUTE_JSON, '--confirm-setup')]
        for args in calls:
            with self.subTest(args=args):
                path.write_bytes(b'')
                os.chmod(path, 0o600)
                journal.write_bytes(b'synthetic journal sidecar, not a valid header')
                os.chmod(journal, 0o600)
                before = path.read_bytes(), path.stat().st_ino, path.stat().st_mode
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertIn('task-coach: error:', err)
                self.assertEqual(out, '')
                # SQLite may remove or roll back the sidecar while validating it;
                # only the main artifact is promised byte-for-byte unchanged.
                self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mode), before)

    def test_non_sqlite_runtime_is_refused_and_unmodified(self):
        path = self.outbox()
        path.write_bytes(b'not a sqlite database\n' * 16)
        os.chmod(path, 0o600)
        files = self.snapshot()
        before = path.read_bytes(), path.stat().st_ino, path.stat().st_mode
        calls = [('runtime', 'history-preference', '--disable'),
                 ('runtime', 'smart-snooze', '--enable'),
                 ('runtime', 'configure', '--route', ROUTE_JSON, '--confirm-setup')]
        for args in calls:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertIn('file is not a database', err)
                self.assertEqual(out, '')
                self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mode), before)
                self.assertEqual([item.name for item in self.data.glob(OUTBOX + '*')], [OUTBOX])
        self.assertEqual(self.snapshot(), files)

    def test_recovered_bare_zero_runtime_keeps_inode_and_mode(self):
        path = self.outbox()
        path.write_bytes(b'')
        os.chmod(path, 0o600)
        inode, mode = path.stat().st_ino, path.stat().st_mode
        self.configure()
        info = path.stat()
        self.assertEqual((info.st_ino, info.st_mode), (inode, mode))
        self.assertGreater(info.st_size, 0)
        self.assertEqual(json.loads(self.run_cli('runtime', 'status')[1])['route'], ROUTE)

    def test_malformed_existing_runtime_stays_refused_and_unmodified(self):
        path = self.outbox()
        with closing(sqlite3.connect(path)) as db:
            db.execute('CREATE TABLE unexpected(value)')
            db.execute('PRAGMA user_version=1')
            db.commit()
        os.chmod(path, 0o600)
        files = self.snapshot()
        before = path.read_bytes(), path.stat().st_mtime_ns
        calls = [('runtime', 'history-preference', '--disable'),
                 ('runtime', 'smart-snooze', '--enable'),
                 ('runtime', 'configure', '--route', ROUTE_JSON, '--confirm-setup')]
        for args in calls:
            with self.subTest(args=args):
                code, out, err = self.run_cli(*args)
                self.assertEqual(code, 2, err)
                self.assertIn('incompatible runtime schema', err)
                self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(self.snapshot(), files)


if __name__ == '__main__':
    unittest.main()
