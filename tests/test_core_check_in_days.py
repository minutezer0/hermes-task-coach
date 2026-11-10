"""Per-task day preferences through storage, selection and the native send boundary."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import sqlite3
import subprocess
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

    def test_owner_can_resolve_weekday_task_clarification_on_weekend(self):
        import test_core_clarification as fixtures
        from test_core_history_fixtures import history_request
        self.cli('update', '1', '--check-in-days', 'weekdays')
        helper = fixtures.ClarificationTest()
        helper.data, helper.cli = self.data, self.cli
        runtime, history, drafts, now = helper.fixture()
        history.insert(0, helper.message('104', now, 'That one'))
        pending = runtime.engagement(BINDING, helper.pages(history, now), now=now,
                                     history_plan=history_request(runtime, 'engagement'))['clarifications'][0]
        later = '2030-01-12T12:00:00Z'
        history.insert(0, helper.message('105', later, 'The weekday task'))
        result = runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=1, selection_message_id='105', pages=helper.pages(history, later), now=later,
            history_plan=history_request(runtime, 'resolve_clarification', selection_message_id='105'))
        self.assertTrue(result['engaged'])
        self.assertEqual(result['context']['task_id'], 1)
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'resolved')

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


class DayReplies(unittest.TestCase):
    setUp = engine_fixtures.EngineTest.setUp
    cli = engine_fixtures.EngineTest.cli
    runtime = runtime_fixtures.LocalFirstTest.runtime
    planned = DayRuntime.planned

    def accepted(self, days='weekends', date='2030-01-13'):
        import subprocess
        runtime, events = self.planned(days, date)
        event = events[0]
        draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
        response = subprocess.CompletedProcess([], 0, stdout='{"success":true,"message_id":"100"}', stderr='')
        with patch('task_coach.driver.subprocess.run', return_value=response):
            self.assertEqual(runtime.dispatch(event['token'], draft['fence'], hermes='/fictional/hermes', now=event['slot'])['state'], 'accepted')
        return runtime, event, draft

    def request(self, event, now, intent='engaged'):
        return dict(binding=BINDING, owner=BINDING['owner'], message_id='200',
                    event_token=event['token'], task_id=1, cycle_id=None, intent=intent, now=now)

    def test_context_and_replies_work_on_excluded_days_and_outside_global_window(self):
        for days, date, later, global_days in (('weekends', '2030-01-13', '2030-01-14T08:00:00Z', 'sat,sun'),
                                              ('weekdays', '2030-01-11', '2030-01-12T20:00:00Z', 'mon,tue,wed,thu,fri')):
            for intent in ('engaged', 'skip-for-now'):
                with self.subTest(days=days, intent=intent):
                    self.data = Path(self.temp.name) / (days + '-' + intent)
                    self.cli('init')
                    self.cli('add', 'Fictional task')
                    self.cli('setup', '--update', '--weekdays', global_days)
                    runtime, event, _ = self.accepted(days, date)
                    class ReplyClock(datetime):
                        @classmethod
                        def now(cls, tz=None):
                            return instant(later).astimezone(tz)
                    with patch('task_coach.driver.datetime', ReplyClock):
                        self.assertEqual(runtime.context(BINDING)['task_id'], 1)
                        self.assertEqual(runtime.context(BINDING, reply_to_message_id='100')['task_id'], 1)
                    request = self.request(event, later, intent)
                    self.assertTrue(runtime.record_engagement(**request)['engaged'])
                    self.assertTrue(runtime.record_engagement(**request)['engaged'])
                    self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')
                    self.assertEqual(self.cli('show', '1')['status'], 'open')
                    self.assertFalse(runtime.preflight(now=later)['wakeAgent'])

    def test_requested_history_recovery_accepts_reply_on_excluded_day(self):
        from test_core_history_fixtures import enable_history, history_request
        runtime, event, draft = self.accepted()
        enable_history(runtime)
        bot = dict(id='100', content=draft['body'], timestamp=event['slot'], author=dict(id='456', bot=True), attachments=[])
        def pages(messages, now):
            return [dict(binding=BINDING, channel_id='123', before=None, observed_at=now, result=dict(messages=messages))]
        runtime.confirm(event['token'], draft['fence'], pages([bot], event['slot']), now=event['slot'],
                        history_plan=history_request(runtime, 'confirm', event['token'], draft['fence']))
        later = '2030-01-14T08:00:00Z'
        owner = dict(id='200', content='Thanks, let’s work on this', timestamp=later, author=dict(id=BINDING['owner'], bot=False), attachments=[])
        result = runtime.engagement(BINDING, pages([owner, bot], later), now=later,
                                    history_plan=history_request(runtime, 'engagement'))
        self.assertTrue(result['engaged'])
        self.assertEqual(result['context']['task_id'], 1)
        self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')

    def test_replies_still_reject_completed_task(self):
        runtime, event, _ = self.accepted()
        self.cli('done', '1')
        with self.assertRaisesRegex(ValueError, 'stale or unavailable'):
            runtime.record_engagement(**self.request(event, '2030-01-14T08:00:00Z'))
        self.assertFalse(runtime.status().get('engagements'))

    def test_start_work_outside_window_does_not_create_smart_snooze_hold(self):
        runtime, event, _ = self.accepted()
        runtime.smart_snooze(enabled=True)
        self.assertTrue(runtime.record_engagement(**self.request(event, '2030-01-14T08:00:00Z', 'start-work'))['engaged'])
        self.assertFalse(runtime.status().get('smart_snooze_hold'))

    def test_reply_after_rollover_preserves_new_plan(self):
        runtime, event, _ = self.accepted()
        self.cli('add', 'Fictional weekday task', '--check-in-days', 'weekdays')
        later = '2030-01-14T08:00:00Z'
        runtime.preflight(now=later)
        plan = runtime.coach.status()['episode']
        self.assertNotEqual(plan['task_id'], 1)
        self.assertTrue(runtime.record_engagement(**self.request(event, later))['engaged'])
        self.assertEqual(runtime.coach.status()['episode'], plan)
        self.assertTrue(runtime.record_engagement(**self.request(event, later))['engaged'])

    def test_start_work_after_rollover_uses_current_window_for_hold(self):
        runtime, event, _ = self.accepted()
        runtime.smart_snooze(enabled=True)
        later = '2030-01-14T12:00:00Z'
        runtime.preflight(now=later)
        self.assertTrue(runtime.record_engagement(**self.request(event, later, 'start-work'))['engaged'])
        hold = runtime.status()['smart_snooze_hold']
        self.assertEqual(hold['day'], '2030-01-14')
        self.assertEqual(hold['expires'], '2030-01-14T17:00:00+00:00')
        self.assertEqual(runtime.preflight(now=later)['reason'], 'smart-snooze')

    def test_delayed_reply_cannot_cross_recurring_task_cycles(self):
        runtime, event, _ = self.accepted()
        task = self.cli('update', '1', '--repeat', '1 day', '--due', '2024-01-01')
        later = '2030-01-14T08:00:00Z'
        runtime.preflight(now=later)
        request = self.request(event, later)
        for cycle in (None, task['cycle_id']):
            with self.subTest(cycle=cycle), self.assertRaises(ValueError):
                runtime.record_engagement(**dict(request, cycle_id=cycle))
        self.assertFalse(runtime.status().get('engagements'))

    def test_cross_window_context_never_guesses_between_tasks(self):
        import subprocess
        runtime, first, _ = self.accepted()
        self.cli('add', 'Fictional weekday task', '--check-in-days', 'weekdays')
        runtime.preflight(now='2030-01-14T08:00:00Z')
        second = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(second['token'], 'Fictional Monday check-in', now=second['slot'])
        response = subprocess.CompletedProcess([], 0, stdout='{"success":true,"message_id":"101"}', stderr='')
        with patch('task_coach.driver.subprocess.run', return_value=response):
            runtime.dispatch(second['token'], draft['fence'], hermes='/fictional/hermes', now=second['slot'])
        self.assertIsNone(runtime.context(BINDING))
        self.assertEqual(runtime.context(BINDING, reply_to_message_id='100')['task_id'], 1)
        self.assertEqual(runtime.context(BINDING, reply_to_message_id='101')['task_id'], 2)
        plan = runtime.coach.status()['episode']
        self.assertTrue(runtime.record_engagement(**self.request(first, second['slot']))['engaged'])
        self.assertEqual(runtime.coach.status()['episode'], plan)


class DayWarnings(unittest.TestCase):
    """A day conflict is reported on stderr but never blocks the requested write."""

    setUp = cli_fixtures.CLITest.setUp
    data: Path
    env: dict

    def run_raw(self, *args):
        command = [sys.executable, '-m', 'task_coach', '--data-dir', str(self.data), *args]
        return subprocess.run(command, env=self.env, text=True, capture_output=True)

    def test_add_keeps_the_task_and_warns_only_for_an_empty_intersection(self):
        self.assertEqual(self.run_raw('init').returncode, 0)
        narrowed = self.run_raw('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri')
        self.assertEqual(narrowed.returncode, 0, narrowed.stderr)
        self.assertEqual(narrowed.stderr, '')
        conflict = self.run_raw('add', 'Fictional weekend chore', '--check-in-days', 'weekends')
        self.assertEqual(conflict.returncode, 0, conflict.stderr)
        self.assertEqual(json.loads(conflict.stdout)['check_in_days'], 'weekends')
        self.assertIn('task 1', conflict.stderr)
        self.assertIn("'weekends'", conflict.stderr)
        self.assertIn("'mon,tue,wed,thu,fri'", conflict.stderr)
        self.assertIn('will not be checked in until they overlap', conflict.stderr)
        for days in ('weekdays', 'all'):
            clean = self.run_raw('add', 'Fictional ' + days, '--check-in-days', days)
            self.assertEqual(clean.returncode, 0, clean.stderr)
            self.assertEqual(clean.stderr, '')
        self.assertEqual(len(json.loads(self.run_raw('list').stdout)), 3)

    def test_update_warns_only_when_the_task_days_change(self):
        self.assertEqual(self.run_raw('init').returncode, 0)
        self.assertEqual(self.run_raw('add', 'Fictional task').returncode, 0)
        narrowed = self.run_raw('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri')
        self.assertEqual(narrowed.stderr, '')
        renamed = self.run_raw('update', '1', '--title', 'Renamed')
        self.assertEqual(renamed.returncode, 0, renamed.stderr)
        self.assertEqual(renamed.stderr, '')
        conflict = self.run_raw('update', '1', '--check-in-days', 'weekends')
        self.assertEqual(conflict.returncode, 0, conflict.stderr)
        self.assertEqual(json.loads(conflict.stdout)['check_in_days'], 'weekends')
        self.assertIn('will not be checked in until they overlap', conflict.stderr)
        repeat = self.run_raw('update', '1', '--check-in-days', 'weekends')
        self.assertEqual(repeat.stderr, '')

    def test_global_day_change_warns_for_open_tasks_only(self):
        self.assertEqual(self.run_raw('init').returncode, 0)
        self.assertEqual(self.run_raw('add', 'Fictional weekend chore', '--check-in-days', 'weekends').stderr, '')
        self.assertEqual(self.run_raw('add', 'Fictional done chore', '--check-in-days', 'weekends').returncode, 0)
        self.assertEqual(self.run_raw('update', '2', '--status', 'done').returncode, 0)
        self.assertEqual(self.run_raw('add', 'Fictional cancelled chore', '--check-in-days', 'weekends').returncode, 0)
        self.assertEqual(self.run_raw('update', '3', '--status', 'cancelled').returncode, 0)
        narrowed = self.run_raw('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri')
        self.assertEqual(narrowed.returncode, 0, narrowed.stderr)
        self.assertIn('task 1', narrowed.stderr)
        self.assertNotIn('task 2', narrowed.stderr)
        self.assertNotIn('task 3', narrowed.stderr)
        repeated = self.run_raw('setup', '--update', '--weekdays', 'mon,tue,wed,thu,fri')
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(repeated.stderr, '')
        untouched = self.run_raw('setup', '--update', '--notification-start', '08:00')
        self.assertEqual(untouched.returncode, 0, untouched.stderr)
        self.assertEqual(untouched.stderr, '')
        widened = self.run_raw('setup', '--update', '--weekdays', 'sat,sun')
        self.assertEqual(widened.returncode, 0, widened.stderr)
        self.assertEqual(widened.stderr, '')

    def test_legacy_store_reads_all_days_without_a_warning(self):
        self.assertEqual(self.run_raw('init').returncode, 0)
        for version, ddl, days in ((0, LEGACY_DDL, 'mon,tue,wed,thu,fri'), (1, RECURRENCE_DDL, 'sat,sun')):
            with self.subTest(version=version):
                store = self.data / 'tasks.sqlite3'
                store.unlink()
                with closing(sqlite3.connect(store)) as db:
                    db.execute(ddl)
                    db.execute('PRAGMA user_version=' + str(version))
                    db.execute("INSERT INTO tasks (id, title, notes, priority, status, created_at, updated_at) "
                               "VALUES (1, 'Legacy task', '', 'normal', 'open', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z')")
                    db.commit()
                store.chmod(0o600)
                narrowed = self.run_raw('setup', '--update', '--weekdays', days)
                self.assertEqual(narrowed.returncode, 0, narrowed.stderr)
                self.assertEqual(narrowed.stderr, '')
                listed = self.run_raw('list')
                self.assertEqual(listed.returncode, 0, listed.stderr)
                self.assertEqual(json.loads(listed.stdout)[0]['check_in_days'], 'all')
