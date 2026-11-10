"""Fictional production-path Smart Snooze regression tests."""
import unittest
import test_core_local_first as fixtures
BINDING = fixtures.BINDING


class SmartSnoozeTest(unittest.TestCase):
    setUp = fixtures.LocalFirstTest.setUp
    cli = fixtures.LocalFirstTest.cli
    engine = fixtures.LocalFirstTest.engine
    runtime = fixtures.LocalFirstTest.runtime
    sender = fixtures.LocalFirstTest.sender

    def accepted(self, enabled=True):
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional second task')
        runtime = self.runtime()
        runtime.smart_snooze(enabled=enabled)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        event = root['events'][0]
        row = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        runtime.dispatch(row['token'], row['fence'], hermes=self.sender(), now=event['slot'])
        return runtime, root, row

    def start(self, runtime, row, now, message_id='inbound-start', intent='start-work'):
        return runtime.record_engagement(binding=BINDING, owner=BINDING['owner'],
            message_id=message_id, event_token=row['token'], task_id=row['task']['id'],
            cycle_id=row['task'].get('cycle_id'), intent=intent, now=now)

    def test_start_work_holds_followups_and_other_task_without_task_mutation(self):
        runtime, root, row = self.accepted()
        from pathlib import Path
        before = {p.name: p.read_bytes() for p in Path(self.data).iterdir()
                  if p.name in ('tasks.sqlite3', 'config.json')}
        self.start(runtime, row, root['events'][0]['slot'])
        for event in root['events'][1:] + root['next_tasks'][0]['events']:
            result = runtime.preflight(now=event['slot'])
            self.assertFalse(result['wakeAgent'])
            self.assertEqual(result['reason'], 'smart-snooze')
        hold = runtime.status()['smart_snooze_hold']
        self.assertEqual(hold['message_id'], 'inbound-start')
        self.assertEqual(hold['task_id'], row['task']['id'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in Path(self.data).iterdir() if p.name in before})

    def test_runtime_commit_failure_cannot_leave_engine_only_start_work(self):
        from contextlib import contextmanager
        from unittest.mock import patch
        runtime, root, row = self.accepted()
        before = runtime.coach.status()
        transaction = runtime.transaction
        @contextmanager
        def fail_commit(*args, **kwargs):
            with transaction(*args, **kwargs) as state:
                yield state
                raise RuntimeError('fictional crash before runtime commit')
        with patch.object(runtime, 'transaction', fail_commit):
            with self.assertRaises(RuntimeError):
                self.start(runtime, row, root['events'][0]['slot'])
        self.assertEqual(runtime.coach.status(), before)
        self.assertNotIn('smart_snooze_hold', runtime.status())

    def test_status_explains_active_and_expired_hold(self):
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        status = runtime.status(now=root['events'][0]['slot'])
        self.assertEqual(status['notification_policy']['reason'], 'smart-snooze')
        self.assertTrue(status['notification_policy']['active'])
        expired = runtime.status(now='2030-01-08T08:00:00Z')
        self.assertFalse(expired['notification_policy']['active'])

    def test_off_start_work_accepts_reply_from_old_window_without_hold(self):
        runtime, root, row = self.accepted(enabled=False)
        self.assertTrue(self.start(runtime, row, '2030-01-08T10:00:00Z')['engaged'])
        self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')
        self.assertFalse(runtime.status().get('smart_snooze_hold'))

    def test_hold_survives_clock_regression(self):
        from datetime import datetime, timedelta
        runtime, root, row = self.accepted()
        slot = datetime.fromisoformat(root['events'][0]['slot'])
        self.start(runtime, row, slot)
        self.assertEqual(runtime.preflight(now=slot-timedelta(seconds=1))['reason'], 'smart-snooze')

    def test_disable_reenable_old_identity_never_recreates_or_reinterprets_hold(self):
        runtime, root, row = self.accepted()
        now = root['events'][0]['slot']
        first = self.start(runtime, row, now)
        runtime.smart_snooze(enabled=False)
        runtime.smart_snooze(enabled=True)
        self.assertEqual(first, self.start(runtime, row, now))
        self.assertNotIn('smart_snooze_hold', runtime.status())
        with self.assertRaises(ValueError):
            self.start(runtime, row, now, intent='engaged')
        event = root['next_tasks'][0]['events'][0]
        self.assertTrue(runtime.preflight(now=event['slot'])['wakeAgent'])

    def test_start_work_while_off_cannot_be_retroactive(self):
        runtime, root, row = self.accepted(enabled=False)
        now = root['events'][0]['slot']
        self.start(runtime, row, now)
        runtime.smart_snooze(enabled=True)
        self.start(runtime, row, now)
        self.assertNotIn('smart_snooze_hold', runtime.status())
        event = root['next_tasks'][0]['events'][0]
        draft = runtime.draft(event['token'], 'Fictional B opener', now=event['slot'])
        self.assertEqual(runtime.dispatch(draft['token'], draft['fence'], hermes=self.sender(), now=event['slot'])['state'], 'accepted')

    def test_engaged_and_skip_never_hold_other_tasks(self):
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'], intent='engaged')
        self.start(runtime, row, root['events'][0]['slot'], intent='skip-for-now', message_id='skip')
        self.assertNotIn('smart_snooze_hold', runtime.status())
        self.assertTrue(runtime.preflight(now=root['next_tasks'][0]['events'][0]['slot'])['wakeAgent'])

    def test_completion_does_not_release_hold_or_create_one(self):
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        hold = runtime.status()['smart_snooze_hold']
        self.cli('done', str(row['task']['id']))
        self.assertEqual(runtime.status()['smart_snooze_hold'], hold)
        self.assertEqual(runtime.preflight(now=root['next_tasks'][0]['events'][0]['slot'])['reason'], 'smart-snooze')

    def test_restart_next_window_ignores_expired_hold_without_cleanup(self):
        from task_coach.driver import Driver
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        restarted = Driver(self.data)
        self.assertEqual(restarted.preflight(now=root['events'][0]['slot'])['reason'], 'smart-snooze')
        result = restarted.preflight(now='2030-01-08T08:00:00Z')
        self.assertNotEqual(result.get('reason'), 'smart-snooze')
        self.assertEqual(restarted.coach.status()['episode']['day'], '2030-01-08')
        self.assertNotIn('smart_snooze_hold', restarted.status())
        self.start(restarted, row, '2030-01-08T08:00:00Z')
        self.assertNotIn('smart_snooze_hold', restarted.status())

    def test_concurrent_identical_and_conflicting_inbound_ids(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from task_coach.driver import Driver
        runtime, root, row = self.accepted()
        barrier = Barrier(2)
        def incoming(intent):
            barrier.wait(timeout=10)
            try:
                return self.start(Driver(self.data), row, root['events'][0]['slot'], intent=intent)
            except ValueError:
                return 'conflict'
        with ThreadPoolExecutor(max_workers=2) as pool:
            same = list(pool.map(incoming, ['start-work', 'start-work']))
        self.assertEqual(same[0], same[1])
        with ThreadPoolExecutor(max_workers=2) as pool:
            conflict = list(pool.map(incoming, ['start-work', 'engaged']))
        self.assertEqual(conflict.count('conflict'), 1)
        self.assertEqual(len(runtime.status()['engagements']), 1)

    def test_hold_arriving_after_authorize_blocks_real_dispatch_boundary(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from unittest.mock import patch
        from task_coach.driver import Driver
        from pathlib import Path
        runtime, root, row = self.accepted()
        event = root['next_tasks'][0]['events'][0]
        draft = runtime.draft(event['token'], 'Fictional B opener', now=event['slot'])
        barrier = Barrier(2)
        authorize = runtime.authorize
        def wait_after_authorize(*args, **kwargs):
            result = authorize(*args, **kwargs)
            barrier.wait(timeout=10)
            barrier.wait(timeout=10)
            return result
        def incoming():
            barrier.wait(timeout=10)
            self.start(Driver(self.data), row, event['slot'])
            barrier.wait(timeout=10)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(incoming)
            with patch.object(runtime, 'authorize', wait_after_authorize):
                result = runtime.dispatch(draft['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
            future.result(timeout=10)
        self.assertIn('smart-snooze', result['uncertain'])
        self.assertEqual((Path(self.temp.name) / 'fictional-send-count').read_text(), '100')

    def test_malformed_hold_rejected_preserving_all_store_bytes_and_mtimes(self):
        import json, sqlite3
        from contextlib import closing
        from pathlib import Path
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        with closing(sqlite3.connect(Path(self.data) / 'outbox.sqlite3')) as db:
            state = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
            state['smart_snooze_hold']['expires'] = 'not-an-expiry'
            db.execute('UPDATE runtime SET value=?', (json.dumps(state),))
            db.commit()
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(self.data).iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            runtime.preflight(now=root['events'][0]['slot'])
        with self.assertRaises(ValueError):
            self.start(runtime, row, root['events'][0]['slot'])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(self.data).iterdir() if p.is_file()})

    def test_native_plan_mandatory_recording_and_release_guidance(self):
        from pathlib import Path
        runtime = self.runtime()
        plan = runtime.native_plan(str(Path(self.temp.name)/'fictional-profile'), python='/usr/bin/python3',
            helper='/fictional/task-coach.py', hermes='/fictional/hermes')
        self.assertIn('start-work', plan['inbound_instruction'])
        self.assertIn('BEFORE', plan['inbound_instruction'])
        self.assertIn('smart-snooze', plan['cron_argv'][4])
        root = Path(__file__).resolve().parents[1]
        self.assertIn('version = "0.1.0rc10"', (root/'pyproject.toml').read_text())
        for path in ('README.md', 'skills/task-coach/SKILL.md', 'skills/task-coach/references/native-runtime.md'):
            text = (root/path).read_text()
            self.assertIn('Smart Snooze', text)
            self.assertIn('runtime smart-snooze', text)
        skill = (root/'skills/task-coach/SKILL.md').read_text()
        self.assertIn('0.1.0-rc.10', skill)
        self.assertIn('hermes sessions refresh-prompts --session ID --json', skill)

    def test_hold_admitted_after_preflight_prevents_claim(self):
        from unittest.mock import patch
        from task_coach.driver import Driver
        runtime, root, row = self.accepted()
        event = root['next_tasks'][0]['events'][0]
        draft = runtime.draft(event['token'], 'Fictional B opener', now=event['slot'])
        preflight = runtime.preflight
        def hold_after_preflight(**kwargs):
            result = preflight(**kwargs)
            self.start(Driver(self.data), row, event['slot'])
            return result
        with patch.object(runtime, 'preflight', hold_after_preflight), patch.object(runtime.coach, 'tick', wraps=runtime.coach.tick) as tick:
            with self.assertRaises(ValueError):
                runtime.dispatch(draft['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        self.assertTrue(all(call.kwargs.get('prepare_only') for call in tick.call_args_list))

    def test_dst_windows_expire_at_absolute_local_end_and_weekdays_remain_fenced(self):
        from datetime import datetime
        from task_coach.driver import Driver
        from task_coach.coaching import window_minutes
        for day, expected_end in [('2030-03-10', '2030-03-10T11:00:00+00:00'), ('2030-11-03', '2030-11-03T12:00:00+00:00')]:
            with self.subTest(day=day):
                from pathlib import Path
                import random
                data = Path(self.temp.name)/day
                from task_coach.cli import main
                from contextlib import redirect_stdout
                import io
                with redirect_stdout(io.StringIO()):
                    self.assertEqual(main(['--data-dir', str(data), 'setup', '--timezone', 'America/Los_Angeles', '--notification-start', '00:00', '--notification-end', '04:00', '--weekdays', 'sun']), 0)
                    self.assertEqual(main(['--data-dir', str(data), 'add', 'Fictional DST task']), 0)
                runtime = Driver(data)
                runtime.coach.rng = random.Random(1)
                runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
                runtime.smart_snooze(enabled=True)
                start = window_minutes(day, runtime.coach.config())[0]
                runtime.prepare_test(confirm=True, now=start)
                event = runtime.coach.status()['episode']['events'][0]
                row = runtime.draft(event['token'], 'Fictional DST opener', now=start)
                runtime.dispatch(row['token'], row['fence'], hermes=self.sender(), now=start)
                self.start(runtime, row, start)
                self.assertEqual(runtime.status()['smart_snooze_hold']['expires'], expected_end)
                self.assertNotEqual(runtime.preflight(now=expected_end).get('reason'), 'smart-snooze')
                self.assertNotIn('smart_snooze_hold', runtime.status())

    def test_old_runtime_missing_preference_remains_off_and_unknown_fields_refuse(self):
        from task_coach.driver import Driver
        import copy
        runtime = self.runtime()
        with runtime.transaction() as state:
            state.pop('smart_snooze_enabled', None)
        self.assertEqual(runtime.smart_snooze(), {'enabled': False})
        with runtime.transaction(readonly=True) as state:
            good = copy.deepcopy(state)
        Driver.validate_state(good)
        for value in (1, None, 'false', []):
            bad = dict(good, smart_snooze_enabled=value)
            with self.assertRaises(ValueError):
                Driver.validate_state(bad)
        with self.assertRaises(ValueError):
            Driver.validate_state(dict(good, smart_snooze_typo=True))

    def test_hold_preserves_receipts_and_rejects_prospective_audit_before_engine_changes(self):
        from unittest.mock import patch
        runtime, root, row = self.accepted()
        before = runtime.coach.status()
        original = runtime.validate_state
        def reject_prospective(state):
            original(state)
            if state.get('engagements'):
                raise ValueError('fictional prospective audit rejection')
        with patch.object(runtime, 'validate_state', reject_prospective):
            with self.assertRaises(ValueError):
                self.start(runtime, row, root['events'][0]['slot'])
        self.assertEqual(runtime.coach.status(), before)
        self.assertEqual(runtime.row(row['token'], row['fence'])['state'], 'accepted')
        self.assertFalse(runtime.status().get('engagements'))

    def test_legacy_clarification_retry_dispatch_is_held(self):
        import test_core_clarification_retry as retry
        from datetime import timedelta
        from task_coach.coaching import instant
        helper = retry.RetryTest()
        helper.data, helper.cli = self.data, self.cli
        runtime, history, drafts, now, pending = helper.held()
        runtime.smart_snooze(enabled=True)
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        self.assertTrue(offered['wakeAgent'])
        draft = runtime.draft(offered['intent']['event_token'], 'Fictional clarification', now=due)
        self.start(runtime, drafts[0], due)
        self.assertEqual(runtime.preflight(now=due)['reason'], 'smart-snooze')
        with self.assertRaises(ValueError):
            runtime.dispatch(draft['token'], draft['fence'], hermes=self.sender(), now=due)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'draft')

    def test_disable_does_not_replay_due_suppressed_opportunity(self):
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        due = root['next_tasks'][0]['events'][0]['slot']
        self.assertEqual(runtime.preflight(now=due)['reason'], 'smart-snooze')
        runtime.smart_snooze(enabled=False, now=due)
        self.assertFalse(runtime.preflight(now=due)['wakeAgent'])

    def test_start_work_after_followup_uses_same_window_expiry(self):
        runtime, root, opener = self.accepted()
        event = root['events'][1]
        row = runtime.draft(event['token'], 'Fictional followup', now=event['slot'])
        runtime.dispatch(row['token'], row['fence'], hermes=self.sender(), now=event['slot'])
        self.start(runtime, row, event['slot'])
        self.assertEqual(runtime.preflight(now=event['slot'])['reason'], 'smart-snooze')
        self.assertEqual(runtime.status()['smart_snooze_hold']['expires'], '2030-01-07T17:00:00+00:00')

    def test_crash_after_atomic_audit_hold_recovers_engine_stop_without_renewal(self):
        from unittest.mock import patch
        from task_coach.driver import Driver
        runtime, root, row = self.accepted()
        with patch.object(runtime, '_reconcile_start_work', side_effect=RuntimeError('fictional second-phase crash')):
            with self.assertRaises(RuntimeError):
                self.start(runtime, row, root['events'][0]['slot'])
        hold = runtime.status()['smart_snooze_hold']
        self.assertIsNone(runtime.coach.status()['episode']['stopped'])
        restarted = Driver(self.data)
        self.assertEqual(restarted.preflight(now=root['events'][0]['slot'])['reason'], 'smart-snooze')
        self.assertEqual(restarted.coach.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(restarted.status()['smart_snooze_hold'], hold)

    def test_snooze_cancel_delete_do_not_release_window_hold(self):
        import sqlite3
        from contextlib import closing
        from pathlib import Path
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        hold = runtime.status()['smart_snooze_hold']
        self.cli('snooze', str(row['task']['id']), '2030-01-09T12:00:00Z')
        self.assertEqual(runtime.status()['smart_snooze_hold'], hold)
        self.cli('update', str(row['task']['id']), '--status', 'cancelled')
        self.assertEqual(runtime.status()['smart_snooze_hold'], hold)
        # Deletion has no public CLI; simulate an external task writer in this
        # fictional store, without introducing a new product lifecycle command.
        with closing(sqlite3.connect(Path(self.data)/'tasks.sqlite3')) as db:
            db.execute('DELETE FROM tasks WHERE id=?', (row['task']['id'],))
            db.commit()
        self.assertEqual(runtime.preflight(now=root['next_tasks'][0]['events'][0]['slot'])['reason'], 'smart-snooze')
        self.assertEqual(runtime.status()['smart_snooze_hold'], hold)

    def test_hold_snapshot_validation_rejects_config_route_and_source_tampering(self):
        import copy
        from task_coach.driver import Driver
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        with runtime.transaction(readonly=True) as state:
            good = copy.deepcopy(state)
        Driver.validate_state(good)
        for field, value in [('expires', '2030-01-07T20:00:00Z'), ('message_id', 'missing'), ('task_id', 999),
                             ('config', dict(good['smart_snooze_hold']['config'], timezone='Unknown/Zone')),
                             ('route', dict(good['route'], destination='discord:999'))]:
            bad = copy.deepcopy(good)
            bad['smart_snooze_hold'][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                Driver.validate_state(bad)

    def test_malformed_current_config_refuses_before_hold_recovery_writes(self):
        from pathlib import Path
        runtime, root, row = self.accepted()
        self.start(runtime, row, root['events'][0]['slot'])
        config = Path(self.data)/'config.json'
        config.write_text('{"timezone":"Unknown/Zone"}')
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(self.data).iterdir() if p.is_file()}
        with self.assertRaises(ValueError):
            runtime.preflight(now=root['events'][0]['slot'])
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in Path(self.data).iterdir() if p.is_file()})

    def test_preference_cli_default_and_disable_readback(self):
        runtime = self.runtime()
        self.assertIs(runtime.status().get('smart_snooze_enabled'), False)
        self.assertEqual(self.cli('runtime', 'smart-snooze'), {'enabled': False})
        self.assertEqual(self.cli('runtime', 'smart-snooze', '--enable'), {'enabled': True})
        self.assertTrue(runtime.status()['smart_snooze_enabled'])
        self.assertEqual(self.cli('runtime', 'smart-snooze', '--disable'), {'enabled': False})
        self.assertFalse(runtime.status()['smart_snooze_enabled'])


if __name__ == '__main__':
    unittest.main()
