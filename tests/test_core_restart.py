"""Restart tests use private synthetic SQLite stores, never a live route."""
import contextlib
import io
import json
import unittest

from test_core_driver import BINDING
import test_core_coaching as fixtures
from task_coach.driver import Driver
from task_coach.cli import main


class RestartTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli
    engine = fixtures.EngineTest.engine
    now = '2030-01-07T12:00:30Z'

    def configured(self):
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        return runtime

    def stopped_empty(self, runtime):
        self.cli('done', '1')
        runtime.preflight(now='2030-01-07T08:00:00Z')
        self.cli('add', 'Current synthetic task')
        return runtime.coach.status()

    def test_replans_current_task_and_only_future_slots_without_sending(self):
        runtime = self.configured()
        before = self.stopped_empty(runtime)
        tasks = (self.data / 'tasks.sqlite3').read_bytes()
        config = (self.data / 'config.json').read_bytes()
        outbox = runtime.status()
        result = runtime.restart(confirm=True, now=self.now)
        after = runtime.coach.status()
        self.assertIs(result['restarted'], True)
        self.assertIs(result['wakeAgent'], False)
        self.assertEqual(result['previous_stop'], 'task-unavailable')
        self.assertEqual(result['episode'], after['episode'])
        self.assertEqual(after['episode']['task_id'], 2)
        self.assertIsNone(after['episode']['stopped'])
        self.assertEqual(after['episode']['day'], '2030-01-07')
        self.assertTrue(after['episode']['events'])
        from task_coach.coaching import instant
        for event in after['episode']['events']:
            self.assertGreater(instant(event['slot']), instant(self.now))
            self.assertLess(event['slot'][11:16], '17:00')
            self.assertEqual(event['state'], 'planned')
        self.assertEqual(after['message_ids'], before['message_ids'])
        self.assertEqual(after['evidence_ids'], before['evidence_ids'])
        self.assertEqual(runtime.status(), outbox)
        self.assertEqual((self.data / 'tasks.sqlite3').read_bytes(), tasks)
        self.assertEqual((self.data / 'config.json').read_bytes(), config)

    def test_restart_refuses_ineligible_episode_without_mutation(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        base = runtime.coach.status()
        import copy
        cases = [('missing', None, False, self.now),
                 ('active', dict(base['episode'], stopped=None), False, self.now),
                 ('paused', base['episode'], True, self.now),
                 ('yesterday', dict(base['episode'], day='2030-01-06'), False, self.now),
                 ('tomorrow', dict(base['episode'], day='2030-01-08'), False, self.now),
                 ('regressed', base['episode'], False, '2030-01-07T07:59:00Z')]
        for name, episode, paused, now in cases:
            with self.subTest(case=name):
                with runtime.coach.transaction() as state:
                    state.update({k: copy.deepcopy(base[k]) for k in state})
                    state.update(episode=copy.deepcopy(episode), paused=paused)
                before = runtime.coach.status()
                with self.assertRaises(ValueError):
                    runtime.restart(confirm=True, now=now)
                self.assertEqual(runtime.coach.status(), before)

    def test_restart_refuses_any_prior_event_even_unclaimed_plans(self):
        runtime = self.configured()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        slot = event['slot']
        for kind in ('planned', 'claimed', 'delivered', 'failed'):
            with self.subTest(kind=kind):
                with runtime.coach.transaction() as state:
                    first = dict(event)
                    state['episode']['events'] = [first]
                    state['episode']['stopped'] = 'paused'
                    if kind != 'planned':
                        first.update(state=kind, claimed_at=slot)
                    if kind == 'delivered':
                        import hashlib
                        receipt = dict(event_token=first['token'], binding=BINDING, message_id='100', cursor='100', delivered_at=slot)
                        first['receipt'] = receipt
                        state['message_ids'] = [hashlib.sha256(json.dumps([BINDING, '100'], sort_keys=True).encode()).hexdigest()]
                before = runtime.coach.status()
                with self.assertRaisesRegex(ValueError, 'prior events'):
                    runtime.restart(confirm=True, now=slot)
                self.assertEqual(runtime.coach.status(), before)

    def test_restart_refuses_nonempty_outbox_without_changing_audit(self):
        runtime = self.configured()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        row = runtime.draft(event['token'], 'Synthetic old draft', now=event['slot'])
        # Simulate an older-day journal still present beside today's empty stop.
        with runtime.coach.transaction() as state:
            state['episode']['events'] = []
            state['episode']['stopped'] = 'task-unavailable'
            state['last_tick'] = '2030-01-07T08:00:00Z'
        for kind in ('draft', 'sending', 'uncertain', 'confirmed'):
            with self.subTest(kind=kind):
                with runtime.transaction() as state:
                    current = dict(row)
                    if kind != 'draft':
                        current.update(state='sending', attempted_at=event['slot'])
                    if kind == 'uncertain':
                        current['uncertain'] = 'Synthetic timeout'
                    if kind == 'confirmed':
                        current.update(state='confirmed', receipt=dict(event_token=event['token'], binding=BINDING, message_id='100', cursor='100', delivered_at=event['slot']))
                    state['outbox'][event['token']] = current
                before, audit = runtime.coach.status(), runtime.status()
                with self.assertRaisesRegex(ValueError, 'outbox'):
                    runtime.restart(confirm=True, now=self.now)
                self.assertEqual(runtime.coach.status(), before)
                self.assertEqual(runtime.status(), audit)

    def test_restart_requires_valid_confirmed_matching_route(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        route = runtime.status()['route']
        import copy
        import json
        import sqlite3
        from contextlib import closing
        valid = runtime.status()
        for invalid in (None, dict(route, destination='discord:999'), dict(route, bot_id=BINDING['owner']), dict(route, platform='other'), dict(route, binding=dict(BINDING, owner='different-owner'))):
            with self.subTest(route=invalid):
                # Corrupt persisted input directly: normal default-policy writes
                # now reject invalid routes before they can be stored.
                malformed = dict(valid, route=copy.deepcopy(invalid))
                with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
                    db.execute('UPDATE runtime SET value=?', (json.dumps(malformed),))
                    db.commit()
                before = runtime.coach.status()
                audit = (self.data / 'outbox.sqlite3').read_bytes()
                with self.assertRaises(ValueError):
                    runtime.restart(confirm=True, now=self.now)
                self.assertEqual(runtime.coach.status(), before)
                self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), audit)

    def test_restart_refuses_without_current_task_or_future_window(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        self.cli('done', '2')
        before = runtime.coach.status()
        with self.assertRaisesRegex(ValueError, 'eligible task or future slots'):
            runtime.restart(confirm=True, now=self.now)
        self.assertEqual(runtime.coach.status(), before)
        self.cli('add', 'Another synthetic task')
        for now in ('2030-01-07T16:59:30Z', '2030-01-07T17:00:00Z'):
            with self.subTest(now=now):
                with self.assertRaisesRegex(ValueError, 'eligible task or future slots'):
                    runtime.restart(confirm=True, now=now)
                self.assertEqual(runtime.coach.status(), before)

    def test_restart_does_not_rewrite_runtime_journal(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        path = self.data / 'outbox.sqlite3'
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        runtime.restart(confirm=True, now=self.now)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_cli_confirmation_uses_real_today_and_has_no_clock_override(self):
        import subprocess
        import sys
        from datetime import datetime, timezone
        from task_coach.coaching import instant
        self.cli('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri,sat,sun', '--notification-start', '00:00', '--notification-end', '23:59')
        now = datetime.now(timezone.utc)
        if now.hour == 23 and now.minute >= 58:
            self.skipTest('no future UTC minute in synthetic all-day window')
        runtime = self.configured()
        self.cli('done', '1')
        runtime.preflight()
        self.cli('add', 'Current synthetic task')
        command = [sys.executable, '-I', '-B', str(fixtures.SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'runtime', 'restart']
        bad = subprocess.run(command + ['--confirm-restart', '--now', self.now], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        result = subprocess.run(command + ['--confirm-restart'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload['restarted'])
        self.assertEqual(payload['episode']['day'], now.date().isoformat())
        self.assertGreater(instant(payload['episode']['events'][0]['slot']), now)
        before = runtime.coach.status()
        again = subprocess.run(command + ['--confirm-restart'], capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('already-stopped', again.stderr)
        self.assertEqual(runtime.coach.status(), before)

    def test_concurrent_restarts_have_one_winner_and_no_claims(self):
        import concurrent.futures
        import threading
        runtime = self.configured()
        self.stopped_empty(runtime)
        barrier = threading.Barrier(3)
        def restart():
            barrier.wait(timeout=10)
            try:
                return Driver(self.data).restart(confirm=True, now=self.now)['restarted']
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(restart) for _ in range(2)]
            barrier.wait(timeout=10)
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [False, True])
        episode = runtime.coach.status()['episode']
        self.assertTrue(all(e['state'] == 'planned' for e in episode['events']))
        self.assertEqual(runtime.status()['outbox'], {})

    def test_preparing_or_claiming_cannot_race_empty_restart(self):
        import concurrent.futures
        import threading
        runtime = self.configured()
        self.stopped_empty(runtime)
        barrier = threading.Barrier(4)
        def operation(kind):
            driver = Driver(self.data)
            barrier.wait(timeout=10)
            if kind == 'restart':
                return driver.restart(confirm=True, now=self.now)
            if kind == 'prepare':
                return driver.preflight(now=self.now)
            return driver.coach.tick(now=self.now, binding=BINDING, expected_token='stale-token')
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            futures = [pool.submit(operation, kind) for kind in ('restart', 'prepare', 'tick')]
            barrier.wait(timeout=10)
            results = [f.result(timeout=20) for f in futures]
        self.assertTrue(results[0]['restarted'])
        self.assertFalse(results[1]['wakeAgent'])
        self.assertFalse(results[2]['wakeAgent'])
        episode = runtime.coach.status()['episode']
        self.assertTrue(all(e['state'] == 'planned' for e in episode['events']))
        slot, token = episode['events'][0]['slot'], episode['events'][0]['token']
        before = runtime.status()
        with self.assertRaises(ValueError):
            runtime.draft('stale-token', 'Synthetic stale draft', now=slot)
        with self.assertRaises(ValueError):
            runtime.dispatch('stale-token', 'stale-fence', hermes='/nonexistent', now=slot)
        self.assertEqual(runtime.status(), before)
        row = runtime.draft(token, 'Current synthetic draft', now=slot)
        with self.assertRaisesRegex(ValueError, 'stale fence'):
            runtime.dispatch(token, 'wrong-fence', hermes='/nonexistent', now=slot)
        self.assertEqual(runtime.row(token, row['fence'])['state'], 'draft')

    def test_restart_without_episode_database_does_not_create_one(self):
        runtime = self.configured()
        before = sorted(p.name for p in self.data.iterdir())
        with self.assertRaisesRegex(ValueError, 'already-stopped'):
            runtime.restart(confirm=True, now=self.now)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), before)

    def test_restart_uses_changed_preferences_and_preserves_replay_records(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        with runtime.coach.transaction() as state:
            state['evidence_ids'] = ['synthetic-earlier-snapshot']
            state['message_ids'] = ['a' * 64]
            state['recent'] = [1]
        self.cli('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri,sat,sun', '--notification-start', '14:00', '--notification-end', '15:00', '--max-unanswered-followups', '0')
        saved = runtime.coach.config()
        result = runtime.restart(confirm=True, now=self.now)
        self.assertEqual(result['episode']['config'], saved)
        self.assertEqual(result['episode']['task_id'], 2)
        self.assertEqual(len(result['episode']['events']), 1)
        event = result['episode']['events'][0]
        self.assertGreaterEqual(event['slot'][11:16], '14:00')
        self.assertLess(event['slot'][11:16], '15:00')
        state = runtime.coach.status()
        self.assertEqual(state['evidence_ids'], ['synthetic-earlier-snapshot'])
        self.assertEqual(state['message_ids'], ['a' * 64])
        self.assertEqual(state['recent'], [1, 2])

    def test_timezone_change_cannot_make_another_local_day_restartable(self):
        runtime = self.configured()
        self.stopped_empty(runtime)
        self.cli('setup', '--update', '--timezone', 'Pacific/Kiritimati')
        before = runtime.coach.status()
        with self.assertRaisesRegex(ValueError, 'today in both'):
            runtime.restart(confirm=True, now=self.now)
        self.assertEqual(runtime.coach.status(), before)

    def test_unconfigured_restart_does_not_initialize_runtime_storage(self):
        runtime = Driver(self.data)
        before = sorted(p.name for p in self.data.iterdir())
        with self.assertRaisesRegex(ValueError, 'setup not confirmed'):
            runtime.restart(confirm=True, now=self.now)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), before)

    def test_confirmation_required_api_and_cli(self):
        runtime = self.configured()
        before = self.stopped_empty(runtime)
        self.assertTrue(hasattr(runtime, 'restart'), 'explicit restart API missing')
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            runtime.restart(now=self.now)
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = main(['--data-dir', str(self.data), 'runtime', 'restart'])
        self.assertNotEqual(code, 0)
        self.assertIn('confirmation', output.getvalue())
        self.assertEqual(runtime.coach.status(), before)
