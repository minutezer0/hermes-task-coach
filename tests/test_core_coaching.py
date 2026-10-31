"""Synthetic deterministic engine tests; no external adapter or personal data."""
from datetime import datetime, timezone
import importlib.util
import contextlib
import io
import json
import tempfile
from pathlib import Path
import random
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/task-coach/scripts'
sys.path.insert(0, str(SCRIPTS))


class SelectionTest(unittest.TestCase):
    def test_selection_filters_and_weights_current_tasks(self):
        spec = importlib.util.find_spec('task_coach.coaching')
        self.assertIsNotNone(spec, 'proactive engine module is missing')
        from task_coach.coaching import choose_task, task_weight
        now = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)
        def task(key, **kw):
            return dict(id=key, status='open', priority='normal', due=None, snoozed_until=None, **kw)
        tasks = [task(1), task(2)]
        self.assertEqual(choose_task(tasks, now, 'UTC', random.Random(1), [1])['id'], 2)
        self.assertIsNone(choose_task([dict(tasks[0], status='done'), dict(tasks[1], snoozed_until='2031-01-01T00:00:00Z')], now, 'UTC', random.Random(1)))
        normal = task_weight(tasks[0], now, 'UTC')
        self.assertGreater(normal, 0)
        self.assertGreater(task_weight(dict(tasks[0], priority='high'), now, 'UTC'), normal)
        self.assertLess(task_weight(dict(tasks[0], priority='low'), now, 'UTC'), normal)
        for due in ('2030-01-08', '2030-01-01', '2030-01-08T00:00:00+04:00'):
            self.assertGreater(task_weight(dict(tasks[0], due=due), now, 'UTC'), normal)
        # Local midnight in Tokyo is already past; UTC midnight is not.
        due = dict(tasks[0], due='2030-01-08')
        instant = datetime(2030, 1, 7, 20, tzinfo=timezone.utc)
        self.assertGreater(task_weight(due, instant, 'Asia/Tokyo'), task_weight(due, instant, 'UTC'))
        self.assertEqual(choose_task(tasks[:1], now, 'UTC', random.Random(1), [1])['id'], 1)
        counts = {1: 0, 2: 0}
        rng = random.Random(20)
        weighted = [dict(tasks[0], priority='high'), dict(tasks[1], priority='low')]
        for _ in range(1000):
            counts[choose_task(weighted, now, 'UTC', rng)['id']] += 1
        self.assertGreater(counts[1], counts[2] * 2)


BINDING = dict(owner="synthetic-owner", profile="synthetic-profile", account="synthetic-account", chat="synthetic-chat", thread="synthetic-thread")


class EngineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='coach-synthetic-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / 'data'
        self.cli('init')
        self.cli('add', 'Synthetic task')

    def cli(self, *args):
        from task_coach.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(['--data-dir', str(self.data), *args])
        self.assertEqual(result, 0)
        return json.loads(output.getvalue())

    def engine(self, seed=1):
        from task_coach import coaching
        self.assertTrue(hasattr(coaching, 'Coach'), 'durable coaching engine is missing')
        return coaching.Coach(self.data, rng=random.Random(seed))

    def test_plan_persists_once_in_separate_private_database(self):
        before = (self.data / 'tasks.sqlite3').read_bytes()
        coach = self.engine()
        now = datetime(2030, 1, 7, 8, tzinfo=timezone.utc)
        self.assertFalse(coach.tick(now=now, binding=BINDING)['wakeAgent'])
        plan = coach.status()['episode']
        self.assertEqual(plan['day'], '2030-01-07')
        self.assertEqual(plan['task_id'], 1)
        self.assertGreaterEqual(len(plan['events']), 1)
        self.assertLessEqual(len(plan['events']), 3)
        for event in plan['events']:
            slot = datetime.fromisoformat(event['slot'])
            self.assertTrue(9 <= slot.hour < 17)
            self.assertEqual(event['state'], 'planned')
        self.engine(999).tick(now=now, binding=BINDING)
        self.assertEqual(self.engine().status()['episode'], plan)
        self.assertEqual(before, (self.data / 'tasks.sqlite3').read_bytes())
        self.assertEqual((self.data / 'coach.sqlite3').stat().st_mode & 0o777, 0o600)

    def prepare(self):
        self.cli('setup', '--update', '--min-followup-interval', '1', '--max-followup-interval', '1')
        engine = self.engine()
        engine.tick(now=datetime(2030, 1, 7, 8, tzinfo=timezone.utc), binding=BINDING)
        return engine, engine.status()['episode']['events']

    def receipt(self, event):
        return dict(event_token=event['token'], binding=BINDING, message_id='opaque-' + event['token'], cursor='cursor-' + event['token'], delivered_at=event['slot'])

    def evidence(self, previous, now):
        return dict(binding=BINDING, event_token=previous['token'], message_id='opaque-' + previous['token'], cursor='cursor-' + previous['token'], snapshot_id='snapshot-' + previous['token'], observed_at=now.isoformat(), complete=True, engaged=False, error=None)

    def test_claim_is_not_delivery_receipt_gates_followups_and_cap(self):
        engine, events = self.prepare()
        self.assertEqual(len(events), 3)
        for index, event in enumerate(events):
            now = datetime.fromisoformat(event['slot'])
            result = engine.tick(now=now, binding=BINDING, evidence=self.evidence(events[index-1], now) if index else None)
            self.assertTrue(result['wakeAgent'], 'due slot must atomically emit an intent')
            self.assertEqual(result['intent']['event_token'], event['token'])
            self.assertEqual(engine.status()['deliveries'], index)
            self.assertEqual(engine.status()['episode']['events'][index]['state'], 'claimed')
            duplicate = self.engine(99).tick(now=now, binding=BINDING)
            self.assertFalse(duplicate['wakeAgent'])
            receipt = self.receipt(event)
            self.assertEqual(engine.acknowledge(receipt, now=now)['state'], 'delivered')
            self.assertEqual(engine.acknowledge(receipt, now=now)['state'], 'delivered')
            self.assertEqual(engine.status()['deliveries'], index+1)
        self.assertFalse(engine.tick(now=now, binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['deliveries'], 3)

    def test_task_reread_stops_daily_episode_even_if_reopened(self):
        engine, events = self.prepare()
        self.cli('done', '1')
        now = datetime.fromisoformat(events[0]['slot'])
        self.assertFalse(engine.tick(now=now, binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'task-unavailable')
        self.cli('update', '1', '--status', 'open')
        self.assertFalse(engine.tick(now=now, binding=BINDING)['wakeAgent'])

    def test_config_or_binding_change_stops_not_replans(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        changed = dict(BINDING, thread='different-thread')
        self.assertFalse(engine.tick(now=now, binding=changed)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'configuration-changed')
        self.assertEqual(engine.status()['episode']['events'], events)
        (self.data / 'coach.sqlite3').unlink()  # synthetic independent case
        engine, events = self.prepare()
        self.cli('setup', '--update', '--destination', 'different-route')
        self.assertFalse(engine.tick(now=datetime.fromisoformat(events[0]['slot']), binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'configuration-changed')

    def test_explicit_pause_resume_does_not_revive_episode(self):
        engine, events = self.prepare()
        self.assertTrue(hasattr(engine, 'pause'), 'durable engine controls are missing')
        engine.pause(True)
        engine.pause(False)
        self.assertFalse(engine.status()['paused'])
        self.assertEqual(engine.status()['episode']['stopped'], 'paused')
        self.assertFalse(engine.tick(now=datetime.fromisoformat(events[0]['slot']), binding=BINDING)['wakeAgent'])

    def test_explicit_owner_engagement_stops_without_completing_task(self):
        engine, events = self.prepare()
        self.assertTrue(hasattr(engine, 'stop'), 'bound owner-engagement stop is missing')
        with self.assertRaises(ValueError):
            engine.stop(events[0]['token'], dict(BINDING, owner='other-owner'))
        engine.stop(events[0]['token'], BINDING)
        self.assertFalse(engine.tick(now=datetime.fromisoformat(events[0]['slot']), binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(self.cli('show', '1')['status'], 'open')

    def test_coach_cli_controls_and_isolated_preview(self):
        import subprocess
        launcher = SCRIPTS / 'task-coach.py'
        def run(*args):
            return subprocess.run([sys.executable, '-I', '-B', str(launcher), '--data-dir', str(self.data), 'coach', *args], text=True, capture_output=True)
        status = run('status')
        self.assertEqual(status.returncode, 0, 'coach CLI is missing: ' + status.stderr)
        self.assertEqual(json.loads(status.stdout)['transport'], 'external-bridge-required')
        before = (self.data / 'coach.sqlite3').read_bytes()
        result = run('preview', '--at', '2030-01-07T08:00:00Z', '--seed', '1', '--binding', json.dumps(BINDING))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['preview'])
        self.assertEqual((self.data / 'coach.sqlite3').read_bytes(), before)
        self.assertTrue(json.loads(run('pause').stdout)['paused'])
        self.assertFalse(json.loads(run('resume').stdout)['paused'])
        quiet = json.loads(run('tick').stdout)
        self.assertFalse(quiet['wakeAgent'])
        rejected = run('tick', '--at', '2030-01-07T10:00:00Z')
        self.assertNotEqual(rejected.returncode, 0)
        self.assertNotIn('Traceback', rejected.stderr)

    def test_failed_send_stops_remainder_and_never_counts_as_delivery(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=now, binding=BINDING)
        self.assertTrue(hasattr(engine, 'failed'), 'explicit negative delivery outcome is missing')
        engine.failed(events[0]['token'], BINDING)
        self.assertEqual(engine.status()['deliveries'], 0)
        self.assertEqual(engine.status()['episode']['events'][0]['state'], 'failed')
        self.assertFalse(engine.tick(now=datetime.fromisoformat(events[1]['slot']), binding=BINDING)['wakeAgent'])
        with self.assertRaises(ValueError):
            engine.acknowledge(self.receipt(events[0]), now=now)

    def test_malformed_versioned_state_is_error_without_traceback_or_reset(self):
        import sqlite3
        import subprocess
        engine, _ = self.prepare()
        with contextlib.closing(sqlite3.connect(self.data / 'coach.sqlite3')) as db:
            state = engine.status()
            for field in ('transport', 'deliveries'):
                state.pop(field)
            state['episode'] = {}
            db.execute('UPDATE state SET value=?', (json.dumps(state),))
            db.commit()
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'coach', 'status'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr, 'malformed episode escaped schema validation')
        self.assertIn('invalid coaching state', result.stderr)

    def test_missing_wrong_stale_incomplete_or_replayed_history_suppresses(self):
        from datetime import timedelta
        changes = [None, {'binding': dict(BINDING, owner='not-owner')}, {'binding': dict(BINDING, chat='not-chat')}, {'binding': dict(BINDING, profile='not-profile')}, {'binding': dict(BINDING, account='not-account')}, {'binding': dict(BINDING, thread='not-thread')}, {'complete': False}, {'complete': 1}, {'error': 'history unavailable'}, {'engaged': True}, {'cursor': 'wrong-cursor'}, {'event_token': 'wrong-event'}, {'message_id': 'wrong-message'}, {'snapshot_id': ''}, {'observed_at': 'bad-date'}, {'drop': 'complete'}, {'replay': True}, {'stale': True}, {'future': True}]
        for change in changes:
            with self.subTest(change=change):
                if (self.data / 'coach.sqlite3').exists():
                    (self.data / 'coach.sqlite3').unlink()
                engine, events = self.prepare()
                first = datetime.fromisoformat(events[0]['slot'])
                engine.tick(now=first, binding=BINDING)
                engine.acknowledge(self.receipt(events[0]), now=first)
                now = datetime.fromisoformat(events[1]['slot'])
                evidence = self.evidence(events[0], now)
                if change is None:
                    evidence = None
                elif 'drop' in change:
                    evidence.pop(change['drop'])
                elif 'replay' in change:
                    with engine.transaction() as state:
                        state['evidence_ids'].append(evidence['snapshot_id'])
                elif 'stale' in change:
                    evidence['observed_at'] = (now - timedelta(seconds=61)).isoformat()
                elif 'future' in change:
                    evidence['observed_at'] = (now + timedelta(seconds=1)).isoformat()
                else:
                    evidence.update(change)
                result = engine.tick(now=now, binding=BINDING, evidence=evidence)
                self.assertFalse(result['wakeAgent'])
                self.assertIsNotNone(engine.status()['episode']['stopped'])
                self.assertFalse(engine.tick(now=now, binding=BINDING, evidence=self.evidence(events[0], now))['wakeAgent'])
                self.assertEqual(engine.status()['deliveries'], 1)

    def test_unconfirmed_claim_expiry_suppresses_and_late_ack_rejected(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        with self.assertRaises(ValueError):
            engine.acknowledge(self.receipt(events[1]), now=now)
        engine.tick(now=now, binding=BINDING)
        wrong = dict(self.receipt(events[0]), binding=dict(BINDING, owner='other-owner'))
        with self.assertRaises(ValueError):
            engine.acknowledge(wrong, now=now)
        later = datetime.fromisoformat(events[1]['slot'])
        self.assertFalse(engine.tick(now=later, binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'unconfirmed-delivery')
        self.assertEqual(engine.status()['deliveries'], 0)
        with self.assertRaises(ValueError):
            engine.acknowledge(self.receipt(events[0]), now=later)

    def test_missed_slot_is_not_caught_up_and_day_rollover_selects_alternative(self):
        engine, events = self.prepare()
        missed = datetime.fromisoformat(events[0]['expires'])
        self.assertFalse(engine.tick(now=missed, binding=BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'missed-slot')
        self.cli('add', 'Second synthetic task')
        engine.tick(now=datetime(2030, 1, 8, 8, tzinfo=timezone.utc), binding=BINDING)
        self.assertEqual(engine.status()['episode']['day'], '2030-01-08')
        self.assertEqual(engine.status()['episode']['task_id'], 2)
        self.assertFalse(engine.tick(now=datetime(2030, 1, 8, 17, tzinfo=timezone.utc), binding=BINDING)['wakeAgent'])
        engine.tick(now=datetime(2030, 1, 12, 12, tzinfo=timezone.utc), binding=BINDING)
        self.assertEqual(engine.status()['episode']['events'], [])

    def test_no_eligible_tasks_does_not_invent_daily_episode(self):
        for action in ('done', 'cancelled', 'snoozed', 'missing'):
            with self.subTest(action=action):
                if (self.data / 'coach.sqlite3').exists():
                    (self.data / 'coach.sqlite3').unlink()
                self.cli('update', '1', '--status', 'open')
                if action == 'done':
                    self.cli('done', '1')
                elif action == 'cancelled':
                    self.cli('update', '1', '--status', 'cancelled')
                elif action == 'snoozed':
                    self.cli('snooze', '1', '2031-01-01T00:00:00Z')
                elif action == 'missing':
                    import sqlite3
                    with contextlib.closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
                        db.execute('DELETE FROM tasks')
                        db.commit()
                engine = self.engine()
                self.assertFalse(engine.tick(now=datetime(2030, 1, 7, 12, tzinfo=timezone.utc), binding=BINDING)['wakeAgent'])
                self.assertEqual(engine.status()['episode']['events'], [])

    def test_concurrent_ticks_claim_once(self):
        from concurrent.futures import ThreadPoolExecutor
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        with ThreadPoolExecutor(max_workers=12) as pool:
            results = list(pool.map(lambda _: self.engine().tick(now=now, binding=BINDING), range(24)))
        self.assertEqual(sum(r['wakeAgent'] for r in results), 1)
        self.assertEqual(engine.status()['deliveries'], 0)

    def test_dst_real_slots_cover_gap_and_both_fold_occurrences(self):
        from task_coach.coaching import window_minutes
        from task_coach.cli import DEFAULT_CONFIG
        from zoneinfo import ZoneInfo
        config = dict(DEFAULT_CONFIG, timezone='America/New_York', weekdays=['sun'], notification_start='01:00', notification_end='04:00')
        spring = window_minutes('2024-03-10', config)
        fall = window_minutes('2024-11-03', config)
        self.assertEqual(len(spring), 120)
        self.assertEqual(len(fall), 240)
        self.assertFalse(any(t.astimezone(ZoneInfo(config['timezone'])).hour == 2 for t in spring))
        folds = [t.astimezone(ZoneInfo(config['timezone'])) for t in fall if t.astimezone(ZoneInfo(config['timezone'])).strftime('%H:%M') == '01:30']
        self.assertEqual(len(folds), 2)
        self.assertNotEqual(folds[0].utcoffset(), folds[1].utcoffset())
        self.cli('setup', '--update', '--timezone', config['timezone'], '--weekdays', 'sun', '--notification-start', '01:00', '--notification-end', '04:00')
        for day in ('2024-03-10', '2024-11-03'):
            result = self.engine().preview(binding=BINDING, now=day+'T00:00:00Z', seed=1)
            for event in result['episode']['events']:
                local = datetime.fromisoformat(event['slot']).astimezone(ZoneInfo(config['timezone']))
                self.assertTrue('01:00' <= local.strftime('%H:%M') < '04:00')

    def test_tick_error_final_json_is_fail_closed_for_scheduler(self):
        import subprocess
        (self.data / 'config.json').write_text('{broken synthetic config')
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'coach', 'tick'], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertTrue(result.stdout.strip(), 'scheduler errors must emit explicit quiet JSON')
        self.assertIs(json.loads(result.stdout.splitlines()[-1])['wakeAgent'], False)

    def test_timezone_edit_cannot_escape_stop_by_changing_local_day(self):
        engine, _ = self.prepare()
        self.cli('setup', '--update', '--timezone', 'Pacific/Kiritimati')
        now = datetime(2030, 1, 7, 23, tzinfo=timezone.utc)
        result = engine.tick(now=now, binding=BINDING)
        self.assertFalse(result['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'configuration-changed')
        self.assertEqual(engine.status()['episode']['day'], '2030-01-07')

    def test_actual_delivery_time_not_claim_time_controls_followup_spacing(self):
        from datetime import timedelta
        engine, events = self.prepare()
        slot = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=slot, binding=BINDING)
        sent = slot + timedelta(seconds=30)
        receipt = dict(self.receipt(events[0]), delivered_at=sent.isoformat())
        engine.acknowledge(receipt, now=sent)
        second = datetime.fromisoformat(events[1]['slot'])
        early = engine.tick(now=second, binding=BINDING, evidence=self.evidence(events[0], second))
        self.assertFalse(early['wakeAgent'], 'scheduled slots must not bypass actual message spacing')
        due = second + timedelta(seconds=30)
        result = engine.tick(now=due, binding=BINDING, evidence=self.evidence(events[0], due))
        self.assertTrue(result['wakeAgent'])

    def test_message_receipt_replay_is_rejected_across_daily_rollover(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=now, binding=BINDING)
        old_receipt = self.receipt(events[0])
        engine.acknowledge(old_receipt, now=now)
        engine.tick(now=datetime(2030, 1, 8, 8, tzinfo=timezone.utc), binding=BINDING)
        next_event = engine.status()['episode']['events'][0]
        later = datetime.fromisoformat(next_event['slot'])
        engine.tick(now=later, binding=BINDING)
        with self.assertRaises(ValueError, msg='opaque message IDs must not be recycled as new receipts'):
            engine.acknowledge(dict(self.receipt(next_event), message_id=old_receipt['message_id']), now=later)
        self.assertEqual(engine.status()['deliveries'], 0)

    def test_uncertain_task_data_is_a_clean_fail_closed_error(self):
        import sqlite3
        import subprocess
        with contextlib.closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
            db.execute("UPDATE tasks SET priority='invalid-synthetic-priority'")
            db.commit()
        result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'coach', 'tick', '--binding', json.dumps(BINDING)], text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('Traceback', result.stderr)
        self.assertIs(json.loads(result.stdout.splitlines()[-1])['wakeAgent'], False)

    def test_backward_clock_does_not_reopen_an_earlier_local_day(self):
        engine, events = self.prepare()
        engine.tick(now=datetime(2030, 1, 8, 8, tzinfo=timezone.utc), binding=BINDING)
        engine.tick(now=datetime.fromisoformat(events[0]['slot']), binding=BINDING)
        state = engine.status()
        self.assertEqual(state['episode']['day'], '2030-01-08', 'clock rollback must not reroll an old day')
        self.assertEqual(state['episode']['stopped'], 'clock-regressed')

    def test_coach_storage_security_and_incompatible_version_fail_closed(self):
        import os
        import sqlite3
        engine, _ = self.prepare()
        path = self.data / 'coach.sqlite3'
        path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'permissions'):
            engine.status()
        path.chmod(0o600)
        linked = self.data / 'synthetic-hardlink'
        os.link(path, linked)
        with self.assertRaisesRegex(ValueError, 'hardlinked'):
            engine.status()
        linked.unlink()
        moved = self.data / 'synthetic-backup'
        path.rename(moved)
        path.symlink_to(moved)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            engine.status()
        path.unlink()
        moved.rename(path)
        sidecar = self.data / 'coach.sqlite3-journal'
        sidecar.symlink_to(path)
        with self.assertRaisesRegex(ValueError, 'symlink'):
            engine.status()
        sidecar.unlink()
        with contextlib.closing(sqlite3.connect(path)) as db:
            db.execute('PRAGMA user_version=999')
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, 'incompatible'):
            engine.status()
        self.assertEqual(path.read_bytes(), before)

    def test_snooze_cancel_and_missing_selected_task_stop_before_dispatch(self):
        import sqlite3
        for action in ('snooze', 'cancel', 'missing'):
            with self.subTest(action=action):
                if (self.data / 'coach.sqlite3').exists():
                    (self.data / 'coach.sqlite3').unlink()
                engine, events = self.prepare()
                if action == 'snooze':
                    self.cli('snooze', '1', '2031-01-01T00:00:00Z')
                elif action == 'cancel':
                    self.cli('update', '1', '--status', 'cancelled')
                else:
                    with contextlib.closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
                        db.execute('DELETE FROM tasks')
                        db.commit()
                self.assertFalse(engine.tick(now=datetime.fromisoformat(events[0]['slot']), binding=BINDING)['wakeAgent'])
                self.assertEqual(engine.status()['episode']['stopped'], 'task-unavailable')
                if action == 'snooze':
                    self.cli('snooze', '1', '2029-01-01T00:00:00Z')
                elif action == 'cancel':
                    self.cli('update', '1', '--status', 'open')

    def test_disallowed_day_does_not_consume_a_task_selection(self):
        engine = self.engine()
        result = engine.tick(now=datetime(2030, 1, 12, 12, tzinfo=timezone.utc), binding=BINDING)
        self.assertFalse(result['wakeAgent'])
        self.assertIsNone(engine.status()['episode']['task_id'])
        self.assertEqual(engine.status()['recent'], [])

    def test_first_state_creation_is_safe_for_concurrent_workers(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        barrier = threading.Barrier(24)
        def read(_):
            barrier.wait()
            return self.engine().status()
        with ThreadPoolExecutor(max_workers=24) as pool:
            statuses = list(pool.map(read, range(24)))
        self.assertEqual(len(statuses), 24)
        self.assertTrue(all(s['episode'] is None for s in statuses))

    def test_incompatible_coach_schema_is_rejected_without_mutation(self):
        import sqlite3
        engine = self.engine()
        valid = engine.status()
        valid.pop('transport')
        valid.pop('deliveries')
        path = self.data / 'coach.sqlite3'
        cases = [
            ('id TEXT, value TEXT', [('1', json.dumps(valid)), ('2', 'malformed-synthetic')]),
            ('id INTEGER CHECK(id=1), value TEXT NOT NULL', [(1, json.dumps(valid))]),
            ('id TEXT PRIMARY KEY CHECK(id=1), value TEXT NOT NULL', [('1', json.dumps(valid))]),
            ('id INTEGER PRIMARY KEY CHECK(id=1), value BLOB NOT NULL', [(1, json.dumps(valid))]),
            ('id INTEGER PRIMARY KEY, value TEXT NOT NULL', [(1, json.dumps(valid))]),
            ('id INTEGER PRIMARY KEY CHECK(id=1), value TEXT', [(1, json.dumps(valid))]),
            ('id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL', [(1, json.dumps(valid)), (2, 'malformed-synthetic')]),
            ('id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL', []),
        ]
        for columns, rows in cases:
            with self.subTest(columns=columns, rows=len(rows)):
                path.unlink()
                with contextlib.closing(sqlite3.connect(path)) as db:
                    db.execute('PRAGMA user_version=1')
                    db.execute('CREATE TABLE state (' + columns + ')')
                    db.execute('PRAGMA ignore_check_constraints=ON')
                    db.executemany('INSERT INTO state VALUES (?, ?)', rows)
                    db.commit()
                path.chmod(0o600)
                before = path.read_bytes(), path.stat().st_mtime_ns
                files = sorted(p.name for p in self.data.iterdir())
                for operation in (engine.status, lambda: engine.pause(True)):
                    with self.assertRaisesRegex(ValueError, 'coaching state'):
                        operation()
                    self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
                    self.assertEqual(sorted(p.name for p in self.data.iterdir()), files)

    def test_utc_overflow_timestamps_fail_closed_in_all_consumers(self):
        import argparse
        import sqlite3
        import subprocess
        from task_coach.cli import due_value
        from task_coach.coaching import instant, task_weight
        for value in ('0001-01-01T00:00:00+01:00', '9999-12-31T23:59:59-01:00'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    instant(value)
                with self.assertRaises(argparse.ArgumentTypeError):
                    due_value(value)
                with self.assertRaises(argparse.ArgumentTypeError):
                    due_value(value, aware_only=True)
                engine, events = self.prepare()
                first = datetime.fromisoformat(events[0]['slot'])
                engine.tick(now=first, binding=BINDING)
                with self.assertRaises(ValueError):
                    engine.acknowledge(dict(self.receipt(events[0]), delivered_at=value), now=first)
                engine.acknowledge(self.receipt(events[0]), now=first)
                second = datetime.fromisoformat(events[1]['slot'])
                result = engine.tick(now=second, binding=BINDING, evidence=dict(self.evidence(events[0], second), observed_at=value))
                self.assertIs(result['wakeAgent'], False)
                (self.data / 'coach.sqlite3').unlink()
                for column in ('due', 'snoozed_until'):
                    with contextlib.closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
                        db.execute('UPDATE tasks SET due=NULL, snoozed_until=NULL')
                        db.execute('UPDATE tasks SET ' + column + '=?', (value,))
                        db.commit()
                    result = subprocess.run([sys.executable, '-I', '-B', str(SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'coach', 'tick', '--binding', json.dumps(BINDING)], text=True, capture_output=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertNotIn('Traceback', result.stderr)
                    self.assertIs(json.loads(result.stdout.splitlines()[-1])['wakeAgent'], False)
                with contextlib.closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
                    db.execute('UPDATE tasks SET due=NULL, snoozed_until=NULL')
                    db.commit()
                if (self.data / 'coach.sqlite3').exists():
                    (self.data / 'coach.sqlite3').unlink()
        task = dict(priority='normal', due='0001-01-01')
        with self.assertRaises(ValueError):
            task_weight(task, datetime(2030, 1, 7, tzinfo=timezone.utc), 'Asia/Tokyo')

    def corrupt_state(self, change):
        import sqlite3
        path = self.data / 'coach.sqlite3'
        with contextlib.closing(sqlite3.connect(path)) as db:
            state = json.loads(db.execute('SELECT value FROM state').fetchone()[0])
            change(state)
            db.execute('UPDATE state SET value=?', (json.dumps(state),))
            db.commit()
        return path.read_bytes(), path.stat().st_mtime_ns

    def test_claimed_followup_requires_consumed_evidence_bookkeeping(self):
        engine, events = self.prepare()
        first = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=first, binding=BINDING)
        engine.acknowledge(self.receipt(events[0]), now=first)
        second = datetime.fromisoformat(events[1]['slot'])
        engine.tick(now=second, binding=BINDING, evidence=self.evidence(events[0], second))
        before = self.corrupt_state(lambda s: s.update(evidence_ids=[]))
        with self.assertRaisesRegex(ValueError, 'invalid coaching state'):
            engine.tick(now=second, binding=BINDING)
        path = self.data / 'coach.sqlite3'
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_delivered_receipt_requires_replay_hash_bookkeeping(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=now, binding=BINDING)
        engine.acknowledge(self.receipt(events[0]), now=now)
        before = self.corrupt_state(lambda s: s.update(message_ids=[]))
        with self.assertRaisesRegex(ValueError, 'invalid coaching state'):
            engine.status()
        path = self.data / 'coach.sqlite3'
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_failed_event_cannot_be_reactivated_or_reclaimed(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=now, binding=BINDING)
        engine.failed(events[0]['token'], BINDING)
        before = self.corrupt_state(lambda s: s['episode'].update(stopped=None))
        with self.assertRaisesRegex(ValueError, 'invalid coaching state'):
            engine.tick(now=now, binding=BINDING)
        path = self.data / 'coach.sqlite3'
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
