"""One-check-in preparation uses only fictional local stores and transport."""
import unittest
import test_core_restart as fixtures
from task_coach.coaching import instant


class LiveTest(unittest.TestCase):
    setUp = fixtures.RestartTest.setUp
    cli = fixtures.RestartTest.cli
    configured = fixtures.RestartTest.configured
    now = '2030-01-07T12:00:30Z'

    def test_real_cli_requires_explicit_test_permission_and_has_no_clock_override(self):
        import subprocess
        import sys
        from datetime import datetime, timezone
        runtime = self.configured()
        self.cli('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri,sat,sun', '--notification-start', '00:00', '--notification-end', '23:59')
        now = datetime.now(timezone.utc)
        if now.hour == 23 and now.minute == 59:
            self.skipTest('outside synthetic all-day window')
        command = [sys.executable, '-I', '-B', str(fixtures.fixtures.SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'runtime', 'prepare-test']
        import json
        denied = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('confirmation required', denied.stderr)
        bad = subprocess.run(command + ['--confirm-test', '--now', self.now], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)
        accepted = subprocess.run(command + ['--confirm-test'], capture_output=True, text=True)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertTrue(json.loads(accepted.stdout)['test_prepared'])
        self.assertEqual(runtime.status()['outbox'], {})
        again = subprocess.run(command + ['--confirm-test'], capture_output=True, text=True)
        self.assertNotEqual(again.returncode, 0)
        self.assertIn('existing episode', again.stderr)

    def test_refusals_preserve_existing_plans_pause_and_audit(self):
        import copy
        runtime = self.configured()
        runtime.coach.status()
        base = runtime.coach.status()
        with self.assertRaisesRegex(ValueError, 'confirmation'):
            runtime.prepare_test(now=self.now)
        for now in ('2030-01-07T08:59:59Z', '2030-01-07T17:00:00Z', '2030-01-06T12:00:00Z'):
            with self.subTest(now=now), self.assertRaisesRegex(ValueError, 'allowed day'):
                runtime.prepare_test(confirm=True, now=now)
            self.assertEqual(runtime.coach.status(), base)
        runtime.coach.pause(True)
        before = runtime.coach.status()
        with self.assertRaisesRegex(ValueError, 'globally paused'):
            runtime.prepare_test(confirm=True, now=self.now)
        self.assertEqual(runtime.coach.status(), before)
        runtime.coach.pause(False)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        active = runtime.coach.status()
        for stopped in (None, 'paused', 'owner-engaged', 'unconfirmed-delivery'):
            with runtime.coach.transaction() as state:
                state['episode'] = copy.deepcopy(active['episode'])
                state['episode']['stopped'] = stopped
            before = runtime.coach.status()
            with self.assertRaisesRegex(ValueError, 'existing episode'):
                runtime.prepare_test(confirm=True, now=self.now)
            self.assertEqual(runtime.coach.status(), before)

    def test_test_uses_normal_dispatch_readback_and_reply_stop(self):
        runtime = self.configured()
        episode = runtime.prepare_test(confirm=True, now=self.now)['episode']
        token = episode['events'][0]['token']
        with self.assertRaises(ValueError):
            runtime.draft('stale-token', 'Synthetic test', now=self.now)
        draft = runtime.draft(token, 'Synthetic test', now=self.now)
        with self.assertRaisesRegex(ValueError, 'stale fence'):
            runtime.dispatch(token, 'wrong-fence', hermes='/nonexistent', now=self.now)
        import sys
        fake = self.data.parent / 'fictional-transport'
        fake.write_text('#!' + sys.executable + '\nprint(\'{"success":true,"message_id":"100"}\')\n')
        fake.chmod(0o700)
        row = runtime.dispatch(token, draft['fence'], hermes=str(fake), now=self.now)
        self.assertEqual(row['state'], 'sending')
        self.assertEqual(runtime.coach.status()['deliveries'], 0)
        with self.assertRaises(ValueError):
            runtime.confirm(token, draft['fence'], [], now=self.now)
        with self.assertRaises(ValueError):
            runtime.dispatch(token, draft['fence'], hermes=str(fake), now=self.now)
        binding = row['route']['binding']
        page = dict(binding=binding, channel_id='123', observed_at=self.now, before=None,
                    result=dict(messages=[dict(id='100', content='Synthetic test', timestamp=self.now, author=dict(id='456', bot=True), attachments=[])]))
        receipt = runtime.confirm(token, draft['fence'], [page], now=self.now)
        self.assertEqual(receipt['message_id'], '100')
        self.assertEqual(runtime.coach.status()['deliveries'], 1)
        self.assertFalse(runtime.preflight(now=self.now)['wakeAgent'])
        page['result']['messages'].insert(0, dict(id='101', content='Synthetic reply', timestamp=self.now, author=dict(id=binding['owner'], bot=False), attachments=[]))
        self.assertTrue(runtime.engagement(binding, [page], now=self.now)['engaged'])
        self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(runtime.context(binding)['task']['title'], 'Synthetic task')
        self.assertEqual(self.cli('show', '1')['status'], 'open')

    def test_uncertain_test_is_never_retried_or_prepared_again(self):
        runtime = self.configured()
        token = runtime.prepare_test(confirm=True, now=self.now)['episode']['events'][0]['token']
        row = runtime.draft(token, 'Synthetic uncertain test', now=self.now)
        attempted = runtime.dispatch(token, row['fence'], hermes='/nonexistent-fictional-transport', now=self.now)
        self.assertIn('uncertain', attempted)
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            runtime.dispatch(token, row['fence'], hermes='/nonexistent', now=self.now)
        with self.assertRaisesRegex(ValueError, 'outbox'):
            runtime.prepare_test(confirm=True, now=self.now)
        self.assertEqual(runtime.status()['outbox'][token], attempted)

    def test_concurrent_test_preparation_has_one_winner(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from task_coach.driver import Driver
        runtime = self.configured()
        barrier = Barrier(3)
        def prepare():
            barrier.wait(timeout=10)
            try:
                return Driver(self.data).prepare_test(confirm=True, now=self.now)['test_prepared']
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(prepare) for _ in range(2)]
            barrier.wait(timeout=10)
            self.assertEqual(sorted(f.result(timeout=20) for f in futures), [False, True])
        self.assertEqual(len(runtime.coach.status()['episode']['events']), 1)
        self.assertEqual(runtime.status()['outbox'], {})

    def test_fresh_refused_test_does_not_leave_partial_engine_database(self):
        runtime = self.configured()
        before = sorted(p.name for p in self.data.iterdir())
        with self.assertRaisesRegex(ValueError, 'allowed day'):
            runtime.prepare_test(confirm=True, now='2030-01-07T08:00:00Z')
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), before)
        self.assertTrue(runtime.prepare_test(confirm=True, now=self.now)['test_prepared'])

    def test_route_task_clock_and_window_end_guards(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        before = sorted(p.name for p in self.data.iterdir())
        with self.assertRaisesRegex(ValueError, 'setup not confirmed'):
            runtime.prepare_test(confirm=True, now=self.now)
        self.assertEqual(sorted(p.name for p in self.data.iterdir()), before)
        runtime = self.configured()
        route = runtime.status()['route']
        with runtime.transaction() as state:
            state['route'] = dict(route, destination='discord:999')
        with self.assertRaisesRegex(ValueError, 'exact Discord'):
            runtime.prepare_test(confirm=True, now=self.now)
        with runtime.transaction() as state:
            state['route'] = route
        self.cli('done', '1')
        with self.assertRaisesRegex(ValueError, 'eligible task'):
            runtime.prepare_test(confirm=True, now=self.now)
        self.assertFalse((self.data / 'coach.sqlite3').exists())
        self.cli('add', 'Current fictional task')
        with runtime.coach.transaction() as state:
            state['last_tick'] = '2030-01-07T16:59:00Z'
        with self.assertRaisesRegex(ValueError, 'clock regressed'):
            runtime.prepare_test(confirm=True, now=self.now)
        result = runtime.prepare_test(confirm=True, now='2030-01-07T16:59:59Z')
        self.assertEqual(result['episode']['events'][0]['expires'], '2030-01-07T17:00:00+00:00')

    def test_concurrent_normal_planner_never_has_its_tokens_replaced(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from task_coach.driver import Driver
        runtime = self.configured()
        barrier = Barrier(3)
        def operation(test):
            driver = Driver(self.data)
            barrier.wait(timeout=10)
            try:
                return driver.prepare_test(confirm=True, now=self.now) if test else driver.preflight(now=self.now)
            except ValueError:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            test, normal = pool.submit(operation, True), pool.submit(operation, False)
            barrier.wait(timeout=10)
            result, prepared = test.result(timeout=20), normal.result(timeout=20)
        episode = runtime.coach.status()['episode']
        if result is not None:
            self.assertEqual(episode, result['episode'])
        else:
            self.assertNotIn('purpose', episode)
        if prepared['wakeAgent']:
            self.assertEqual(prepared['intent']['event_token'], episode['events'][0]['token'])
        self.assertTrue(all(e['state'] == 'planned' for e in episode['events']))

    def test_runtime_lock_blocks_test_until_route_write_is_committed(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from task_coach.driver import Driver
        runtime = self.configured()
        started = Event()
        def prepare():
            started.set()
            with self.assertRaisesRegex(ValueError, 'route fields'):
                Driver(self.data).prepare_test(confirm=True, now=self.now)
        with ThreadPoolExecutor(max_workers=1) as pool:
            with runtime.transaction() as state:
                future = pool.submit(prepare)
                self.assertTrue(started.wait(timeout=10))
                self.assertFalse(future.done())
                state['route'] = None
            future.result(timeout=20)
        self.assertFalse((self.data / 'coach.sqlite3').exists())

    def test_prepares_exactly_one_due_check_in_without_sending(self):
        runtime = self.configured()
        before = runtime.status()
        result = runtime.prepare_test(confirm=True, now=self.now)
        self.assertTrue(result['test_prepared'])
        self.assertFalse(result['wakeAgent'])
        episode = runtime.coach.status()['episode']
        self.assertEqual(episode['purpose'], 'one-check-in-test')
        self.assertEqual(len(episode['events']), 1)
        event = episode['events'][0]
        self.assertEqual(event['state'], 'planned')
        self.assertLessEqual(instant(event['slot']), instant(self.now))
        self.assertGreater(instant(event['expires']), instant(self.now))
        self.assertEqual(runtime.status(), before)
        self.assertEqual(runtime.preflight(now=self.now)['intent']['event_token'], event['token'])
        with self.assertRaises(ValueError):
            runtime.prepare_test(confirm=True, now=self.now)
        self.assertEqual(runtime.coach.status()['episode'], episode)
