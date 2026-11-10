"""Per-task day preferences through storage, selection and the native send boundary."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sqlite3
import sys
import unittest
from unittest.mock import patch

import test_cli_core as cli_fixtures
import test_core_coaching as engine_fixtures
import test_core_local_first as runtime_fixtures
import test_core_installed_skill as installed_fixtures

from task_coach.cli import LEGACY_DDL, RECURRENCE_DDL, main
from task_coach.coaching import eligible, choose_task, instant, sequences
from task_coach.recurrence import same_snapshot
from test_core_driver import BINDING

ALL_DAYS = 'mon,tue,wed,thu,fri,sat,sun'


class DayCLI(unittest.TestCase):
    setUp = cli_fixtures.CLITest.setUp
    run_cli = cli_fixtures.CLITest.run_cli

    def old_store(self, version):
        self.run_cli('setup', '--weekdays', 'mon,wed,sat')
        path = self.data / 'tasks.sqlite3'
        path.unlink()
        with closing(sqlite3.connect(path)) as db:
            db.execute(LEGACY_DDL if version == 0 else RECURRENCE_DDL)
            db.execute(f'PRAGMA user_version={version}')
            db.execute("INSERT INTO tasks (id,title,notes,priority,status,created_at,updated_at) VALUES (7,'Keep task','Keep notes','high','open','2024-01-01T00:00:00Z','2024-01-01T00:00:00Z')")
            db.commit()
        path.chmod(0o600)
        return path

    def test_default_seven_days_and_saved_subsets_survive_setup(self):
        self.assertEqual(self.run_cli('init')['config']['weekdays'], ALL_DAYS.split(','))
        for days in ('mon,tue,wed,thu,fri', 'sat,sun', 'mon,wed,sat'):
            with self.subTest(days=days):
                self.run_cli('setup', '--update', '--weekdays', days)
                before = (self.data/'config.json').read_bytes()
                self.assertEqual(self.run_cli('setup')['config']['weekdays'], days.split(','))
                self.assertEqual((self.data/'config.json').read_bytes(), before)
                self.assertEqual(self.run_cli('add', 'Default task')['check_in_days'], 'all')

    def test_round_trip_and_explicit_edit_preserve_other_fields(self):
        self.run_cli('init')
        for value in ('weekdays', 'weekends', 'all'):
            task = self.run_cli('add', 'Day task', '--check-in-days', value)
            key = str(task['id'])
            self.assertEqual(task['check_in_days'], value)
            self.assertEqual(self.run_cli('show', key), task)
            for command in ('list', 'search', 'export'):
                args = (command, 'Day') if command == 'search' else (command,)
                self.assertIn(task, self.run_cli(*args))
            changed = self.run_cli('update', key, '--check-in-days', 'weekends')
            self.assertEqual(changed['check_in_days'], 'weekends')
            for field in task.keys() - {'updated_at', 'check_in_days'}:
                self.assertEqual(changed[field], task[field])
            self.assertEqual(self.run_cli('update', key, '--check-in-days', 'weekends'), changed)
            self.run_cli('setup', '--update', '--weekdays', 'mon,wed,sat')
            self.assertEqual(self.run_cli('show', key), changed)

    def test_bad_values_refuse_without_writes(self):
        self.run_cli('init')
        self.run_cli('add', 'Keep')
        before = (self.data/'tasks.sqlite3').read_bytes()
        for value in ('weekday', 'both', '', 'mon,wed', 'ALL'):
            for args in (('add', 'Bad'), ('update', '1')):
                self.run_cli(*args, '--check-in-days', value, ok=False)
                self.assertEqual((self.data/'tasks.sqlite3').read_bytes(), before)

    def test_old_versions_read_all_without_migration_and_upgrade_explicitly(self):
        for version in (0, 1):
            with self.subTest(version=version):
                self.data = self.root / f'v{version}'
                store = self.old_store(version)
                before = (store.read_bytes(), store.stat().st_mtime_ns)
                task = self.run_cli('show', '7')
                self.assertEqual(task['check_in_days'], 'all')
                for command in (('list',), ('export',), ('search', 'Keep'), ('coach', 'preview', '--binding', json.dumps(engine_fixtures.BINDING), '--at', '2030-01-07T12:00:00Z')):
                    self.run_cli(*command)
                self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
                for args in (('add', 'Refused'), ('update', '7')):
                    error = self.run_cli(*args, '--check-in-days', 'weekends', ok=False)
                    self.assertIn('migrate', error.stderr)
                    self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
                config = (self.data/'config.json').read_bytes()
                self.assertEqual(self.run_cli('migrate'), {'version': 2})
                migrated = self.run_cli('show', '7')
                self.assertTrue(same_snapshot(task, migrated))
                self.assertEqual((self.data/'config.json').read_bytes(), config)
                before = (store.read_bytes(), store.stat().st_mtime_ns)
                self.run_cli('migrate')
                self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)
                self.assertEqual(self.run_cli('update', '7', '--check-in-days', 'weekends')['check_in_days'], 'weekends')

    def test_version_one_recurrence_and_old_writes_remain_supported(self):
        store = self.old_store(1)
        task = self.run_cli('update', '7', '--repeat', '1 week', '--due', '2024-01-01')
        self.run_cli('add', 'Legacy all', '--check-in-days', 'all')
        self.run_cli('migrate')
        self.assertEqual(self.run_cli('show', '7'), task)
        done = self.run_cli('done', '7', '--completed-at', '2024-01-08', '--expected-cycle', task['cycle_id'], '--completion-id', 'fictional-completion')
        self.assertEqual(done['due'], '2024-01-15')
        self.assertEqual(done['check_in_days'], 'all')

    def test_v1_migration_failure_rolls_back(self):
        import contextlib
        import io
        from task_coach import cli
        store = self.old_store(1)
        before = store.read_bytes()
        validate = cli.validate_store
        def reject_new(db):
            validate(db)
            if db.execute('PRAGMA user_version').fetchone()[0] == 2:
                raise ValueError('synthetic v2 failure')
        with patch.object(cli, 'validate_store', side_effect=reject_new), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--data-dir', str(self.data), 'migrate']), 2)
        self.assertEqual(store.read_bytes(), before)
        self.assertEqual(self.run_cli('show', '7')['check_in_days'], 'all')

    def test_bad_persisted_preference_refuses_without_mutation(self):
        self.run_cli('init')
        self.run_cli('add', 'Keep')
        store = self.data/'tasks.sqlite3'
        with closing(sqlite3.connect(store)) as db:
            db.execute("UPDATE tasks SET check_in_days='sometimes'")
            db.commit()
        before = (store.read_bytes(), store.stat().st_mtime_ns)
        for command in ('list', 'migrate', 'init'):
            self.run_cli(command, ok=False)
            self.assertEqual((store.read_bytes(), store.stat().st_mtime_ns), before)

    def test_migration_preserves_historical_draft_and_engine(self):
        from task_coach.driver import Driver
        self.old_store(1)
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional pre-upgrade draft', now=event['slot'])
        with runtime.transaction() as state:
            state['outbox'][event['token']]['task'].pop('check_in_days')
        names = ('config.json', 'coach.sqlite3', 'outbox.sqlite3')
        before = {name: ((self.data/name).read_bytes(), (self.data/name).stat().st_mtime_ns) for name in names}
        self.run_cli('migrate')
        self.assertEqual({name: ((self.data/name).read_bytes(), (self.data/name).stat().st_mtime_ns) for name in names}, before)
        import subprocess
        response = subprocess.CompletedProcess([], 0, stdout='{"success":true,"message_id":"100"}', stderr='')
        with patch('task_coach.driver.subprocess.run', return_value=response):
            result = runtime.dispatch(event['token'], draft['fence'], hermes='/fictional/hermes', now=event['slot'])
        self.assertEqual(result['state'], 'accepted')


class DayEngine(unittest.TestCase):
    setUp = engine_fixtures.EngineTest.setUp
    cli = engine_fixtures.EngineTest.cli
    engine = engine_fixtures.EngineTest.engine

    def test_selection_all_days_and_timezones_ignores_overdue_weight(self):
        task = self.cli('show', '1')
        for zone in ('UTC', 'America/Vancouver', 'Asia/Tokyo'):
            for n in range(7):
                now = datetime(2030, 1, 7, tzinfo=timezone.utc) + timedelta(days=n)
                from zoneinfo import ZoneInfo
                weekend = now.astimezone(ZoneInfo(zone)).weekday() >= 5
                for days in ('weekdays', 'weekends', 'all'):
                    candidate = dict(task, check_in_days=days, due='2020-01-01', priority='high')
                    allowed = days == 'all' or (days == 'weekends') == weekend
                    with self.subTest(zone=zone, now=now, days=days):
                        self.assertEqual(eligible(candidate, now, zone), allowed)
                        self.assertEqual(choose_task([candidate], now, zone, random.Random(1)) is not None, allowed)
        self.assertTrue(eligible({k: v for k, v in task.items() if k != 'check_in_days'}, now))

    def test_plans_intersect_task_days_with_global_days(self):
        self.cli('update', '1', '--check-in-days', 'weekdays')
        weekend = self.cli('add', 'Weekend task', '--check-in-days', 'weekends')
        every = self.cli('add', 'All task')
        self.cli('setup', '--update', '--max-tasks-per-window', '10', '--min-followup-interval', '1', '--max-followup-interval', '1')
        for global_days in (ALL_DAYS, 'mon,tue,wed,thu,fri', 'sat,sun', 'mon,wed,sat'):
            self.cli('setup', '--update', '--weekdays', global_days)
            for day, name, expected in (('2030-01-07', 'mon', {1, every['id']}), ('2030-01-12', 'sat', {weekend['id'], every['id']}), ('2030-01-13', 'sun', {weekend['id'], every['id']})):
                plan = self.engine().preview(binding=engine_fixtures.BINDING, now=day+'T08:00:00Z', seed=1)['episode']
                actual = {s['task_id'] for s in sequences(plan) if s['task_id'] is not None}
                self.assertEqual(actual, expected if name in global_days.split(',') else set())

    def test_pending_engine_followup_stops_after_day_edit(self):
        self.cli('setup', '--update', '--min-followup-interval', '1', '--max-followup-interval', '1')
        self.cli('update', '1', '--check-in-days', 'weekdays')
        engine = self.engine()
        engine.local_first = True
        engine.tick(now='2030-01-07T08:00:00Z', binding=engine_fixtures.BINDING)
        events = engine.status()['episode']['events']
        self.assertGreater(len(events), 1)
        self.assertTrue(engine.tick(now=events[0]['slot'], binding=engine_fixtures.BINDING)['wakeAgent'])
        engine.acknowledge(dict(event_token=events[0]['token'], binding=engine_fixtures.BINDING, message_id='fictional', cursor='fictional', delivered_at=events[0]['slot']), now=events[0]['slot'])
        self.cli('update', '1', '--check-in-days', 'weekends')
        blocked = engine.tick(now=events[1]['slot'], binding=engine_fixtures.BINDING)
        self.assertFalse(blocked['wakeAgent'])
        self.assertEqual(blocked['reason'], 'task-unavailable')
        self.cli('update', '1', '--check-in-days', 'all')
        self.assertFalse(engine.tick(now=events[1]['slot'], binding=engine_fixtures.BINDING)['wakeAgent'])

    def test_recurrence_due_and_task_days_both_apply(self):
        task = self.cli('add', 'Weekly', '--repeat', '1 week', '--due', '2030-01-08', '--check-in-days', 'weekends')
        for now, expected in (('2030-01-05', False), ('2030-01-08', False), ('2030-01-12', True)):
            self.assertEqual(eligible(task, instant(now+'T12:00:00Z')), expected)
        done = self.cli('done', str(task['id']), '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', 'fictional')
        self.assertEqual(done['check_in_days'], 'weekends')

    def test_snapshot_defaults_only_missing_days_to_all(self):
        task = self.cli('show', '1')
        old = {k: v for k, v in task.items() if k != 'check_in_days'}
        self.assertTrue(same_snapshot(old, task))
        self.assertFalse(same_snapshot(old, dict(task, check_in_days='weekends')))
        self.assertFalse(same_snapshot(dict(task, check_in_days=None), task))

    def test_dst_folds_and_local_weekend_boundary(self):
        task = dict(self.cli('show', '1'), check_in_days='weekends')
        for now, allowed in (('2026-11-01T08:30:00Z', True),
                             ('2026-11-01T09:30:00Z', True),
                             ('2026-11-02T07:59:00Z', True),
                             ('2026-11-02T08:00:00Z', False)):
            self.assertEqual(eligible(task, instant(now), 'America/Los_Angeles'), allowed)


class DayRuntime(unittest.TestCase):
    setUp = runtime_fixtures.LocalFirstTest.setUp
    cli = runtime_fixtures.LocalFirstTest.cli
    runtime = runtime_fixtures.LocalFirstTest.runtime
    sender = runtime_fixtures.LocalFirstTest.sender

    def planned(self, days='weekdays', date='2030-01-07'):
        self.cli('setup', '--update', '--min-followup-interval', '1', '--max-followup-interval', '1')
        self.cli('update', '1', '--check-in-days', days)
        runtime = self.runtime()
        runtime.preflight(now=date+'T08:00:00Z')
        return runtime, runtime.coach.status()['episode']['events']

    def test_allowed_weekend_opener_and_followup_use_same_preference(self):
        runtime, events = self.planned('weekends', '2030-01-12')
        self.assertGreater(len(events), 1)
        for event in events[:2]:
            draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
            self.assertEqual(result['state'], 'accepted')
        self.assertEqual(runtime.coach.status()['deliveries'], 2)

    def test_stale_draft_refuses_day_edit_even_if_new_days_allow_today(self):
        runtime, events = self.planned()
        event = events[0]
        draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
        self.cli('update', '1', '--check-in-days', 'all')
        with patch('task_coach.driver.subprocess.run') as send, self.assertRaises(ValueError):
            runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        send.assert_not_called()

    def test_followup_refuses_changed_days_after_drafting(self):
        runtime, events = self.planned()
        first = runtime.draft(events[0]['token'], 'Fictional opener', now=events[0]['slot'])
        runtime.dispatch(first['token'], first['fence'], hermes=self.sender(), now=events[0]['slot'])
        follow = runtime.draft(events[1]['token'], 'Fictional followup', now=events[1]['slot'])
        self.cli('update', '1', '--check-in-days', 'weekends')
        with patch('task_coach.driver.subprocess.run') as send, self.assertRaises(ValueError):
            runtime.dispatch(follow['token'], follow['fence'], hermes=self.sender(), now=events[1]['slot'])
        send.assert_not_called()
        self.assertEqual(runtime.coach.status()['deliveries'], 1)

    def test_final_send_boundary_rechecks_days_after_claim(self):
        runtime, events = self.planned()
        event = events[0]
        draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
        # Introduce a task edit after authorization, before the refreshed final guard.
        original = runtime.authorize
        def edit_after_authorization(*args, **kwargs):
            result = original(*args, **kwargs)
            self.cli('update', '1', '--check-in-days', 'weekends')
            return result
        with patch.object(runtime, 'authorize', side_effect=edit_after_authorization), patch('task_coach.driver.subprocess.run') as send:
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        send.assert_not_called()
        self.assertEqual(result['state'], 'sending')
        self.assertIn('task or event changed at send boundary', result['uncertain'])

    def test_one_checkin_test_respects_task_days(self):
        self.cli('update', '1', '--check-in-days', 'weekends')
        runtime = self.runtime()
        with self.assertRaisesRegex(ValueError, 'eligible task'):
            runtime.prepare_test(confirm=True, now='2030-01-07T12:00:00Z')
        self.assertIsNone(runtime.coach.status()['episode'])
        self.assertTrue(runtime.prepare_test(confirm=True, now='2030-01-12T12:00:00Z')['test_prepared'])


class CopiedDays(unittest.TestCase):
    setUp = installed_fixtures.InstalledSkillTest.setUp
    invoke = installed_fixtures.InstalledSkillTest.invoke
    cli = installed_fixtures.InstalledSkillTest.cli

    def test_copied_bundle_persists_days_and_filters_weekdays(self):
        self.assertEqual(self.cli('init')['config']['weekdays'], ALL_DAYS.split(','))
        task = self.cli('add', 'Fictional garden', '--check-in-days', 'weekends')
        self.assertEqual(task['check_in_days'], 'weekends')
        args = ('coach', 'preview', '--binding', json.dumps(engine_fixtures.BINDING))
        self.assertIsNone(self.cli(*args, '--at', '2030-01-07T12:00:00Z')['episode']['task_id'])
        self.assertEqual(self.cli(*args, '--at', '2030-01-12T12:00:00Z')['episode']['task_id'], task['id'])


class DayClarification(unittest.TestCase):
    setUp = engine_fixtures.EngineTest.setUp
    cli = engine_fixtures.EngineTest.cli

    def test_legacy_retry_respects_every_candidates_current_days(self):
        import test_core_clarification_retry as retry_fixtures
        from task_coach import clarification
        helper = retry_fixtures.RetryTest()
        helper.data = self.data
        helper.cli = self.cli
        runtime, history, drafts, now, pending = helper.held()
        runtime.preflight(now=now)
        event = runtime.status()['clarification_retry']['events'][0]
        ready = runtime.preflight(now=event['slot'])
        self.assertTrue(ready['wakeAgent'])
        selected = ready['task']['id']
        other = next(c['task']['id'] for c in pending['candidates'] if c['task']['id'] != selected)
        self.cli('update', str(other), '--check-in-days', 'weekends')
        self.assertFalse(clarification.current_days(runtime, [pending], instant(event['slot'])))
        self.assertFalse(runtime.preflight(now=event['slot'])['wakeAgent'])
        self.assertEqual(runtime.status()['clarifications'][pending['id']], pending)
