"""Synthetic recurrence calendar and snapshot isolation tests; no live messages."""
import unittest
from datetime import datetime, timezone
import random
import test_core_coaching as fixtures


class CalendarTests(unittest.TestCase):
    def test_historical_plain_snapshot_matches_after_explicit_migration(self):
        from task_coach import recurrence
        snapshot = dict(id=1, title='Original', status='open')
        migrated = dict(snapshot, repeat_interval=None, cycle_id=None, last_completion=None)
        self.assertTrue(hasattr(recurrence, 'same_snapshot'), 'historical plain snapshots need compatibility')
        self.assertTrue(recurrence.same_snapshot(snapshot, migrated))
        self.assertFalse(recurrence.same_snapshot(snapshot, dict(migrated, cycle_id='a'*32)))

    def test_initial_due_is_an_eligibility_gate_in_local_timezone(self):
        from task_coach.coaching import choose_task
        task = dict(id=1, status='open', priority='normal', due='2024-03-10', snoozed_until=None, repeat_interval='3 months', cycle_id='a'*32)
        before = datetime.fromisoformat('2024-03-10T07:59:00+00:00')
        self.assertIsNone(choose_task([task], before, 'America/Los_Angeles', random.Random(0)))
        after = datetime.fromisoformat('2024-03-10T08:00:00+00:00')
        self.assertEqual(choose_task([task], after, 'America/Los_Angeles', random.Random(0)), task)
        task['due'] = '2024-03-10T12:00:00-07:00'
        self.assertIsNone(choose_task([task], after, 'America/Los_Angeles', random.Random(0)))

    def test_calendar_month_clamp_leap_year_and_dst(self):
        from task_coach.recurrence import next_due
        for completed, repeat, expected in [('2024-01-31', '1 month', '2024-02-29'), ('2023-01-31', '1 month', '2023-02-28'), ('2024-02-29', '12 months', '2025-02-28'), ('2024-01-31', '3 months', '2024-04-30'), ('2024-03-09T02:30:00-08:00', '1 day', '2024-03-10T03:30:00-07:00'), ('2024-11-02T01:30:00-07:00', '1 day', '2024-11-03T01:30:00-07:00')]:
            with self.subTest(completed=completed):
                self.assertEqual(next_due(completed, repeat, 'America/Los_Angeles'), expected)


class CycleTests(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli
    engine = fixtures.EngineTest.engine

    def receipt_fixture(self):
        from task_coach.driver import Driver
        from test_core_driver import BINDING
        self.cli('update', '1', '--repeat', '1 day', '--due', '2024-01-01')
        engine = self.engine()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        engine.tick(now=datetime(2024, 1, 1, 8, tzinfo=timezone.utc), binding=BINDING)
        event = engine.status()['episode']['events'][0]
        now = datetime.fromisoformat(event['slot'])
        draft = runtime.draft(event['token'], 'Synthetic check-in', now=now)
        engine.tick(now=now, binding=BINDING)
        with runtime.transaction() as state:
            state['outbox'][draft['token']].update(state='sending', attempted_at=now.isoformat(), candidate_id='100')
        page = dict(binding=BINDING, channel_id='123', before=None, observed_at=now.isoformat(), result=dict(messages=[dict(id='100', content='Synthetic check-in', timestamp=now.isoformat(), author=dict(id='456', bot=True), attachments=[])]))
        return runtime, draft, page, now, BINDING

    def test_overdue_single_row_and_shared_budget_never_generate_backlog(self):
        self.cli('update', '1', '--repeat', '3 months', '--due', '2020-01-01')
        for n in range(4):
            self.cli('add', 'Fictional task ' + str(n), '--repeat', '1 week', '--due', '2020-01-01')
        tasks = self.cli('list')
        before = (self.data / 'tasks.sqlite3').read_bytes()
        engine = self.engine()
        for day in (1, 8, 15):
            episode = engine.preview(binding=fixtures.BINDING, now=datetime(2024, 1, day, 8, tzinfo=timezone.utc), seed=day)['episode']
            from task_coach.coaching import sequences
            self.assertLessEqual(len(sequences(episode)), 3)
            self.assertEqual(len({s['task_id'] for s in sequences(episode)}), len(sequences(episode)))
        self.assertEqual(self.cli('list'), tasks)
        self.assertEqual((self.data / 'tasks.sqlite3').read_bytes(), before)

    def test_old_followup_observation_and_draft_refuse_new_due_cycle(self):
        runtime, first, page, now, binding = self.receipt_fixture()
        runtime.confirm(first['token'], first['fence'], [page], now=now)
        followup = runtime.coach.status()['episode']['events'][1]
        later = datetime.fromisoformat(followup['slot'])
        draft = runtime.draft(followup['token'], 'Old followup', now=later)
        task = self.cli('show', '1')
        self.cli('done', '1', '--completed-at', '2023-12-30', '--expected-cycle', task['cycle_id'], '--completion-id', 'old-followup')
        page['observed_at'] = later.isoformat()
        page['result']['messages'].insert(0, dict(id='101', content='Reply to old cycle', timestamp=later.isoformat(), author=dict(id=binding['owner'], bot=False), attachments=[], message_reference=dict(message_id='100', channel_id='123')))
        evidence = runtime.observe(draft['token'], draft['fence'], [page], now=later)
        self.assertFalse(evidence['engaged'])
        with self.assertRaises(ValueError):
            runtime.dispatch(draft['token'], draft['fence'], hermes='/fictional/no-send', now=later)
        self.assertNotEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')

    def test_old_confirm_records_receipt_without_new_cycle_context_or_engagement(self):
        runtime, draft, page, now, binding = self.receipt_fixture()
        task = self.cli('show', '1')
        self.cli('done', '1', '--completed-at', '2023-12-30', '--expected-cycle', task['cycle_id'], '--completion-id', 'first')
        receipt = runtime.confirm(draft['token'], draft['fence'], [page], now=now)
        self.assertEqual(receipt['message_id'], '100')
        self.assertIsNone(runtime.context(binding, reply_to_message_id='100'))
        page['result']['messages'].insert(0, dict(id='101', content='Old reply', timestamp=now.isoformat(), author=dict(id=binding['owner'], bot=False), attachments=[]))
        result = runtime.engagement(binding, [page], now=now, reply_to_message_id='100', inbound_message_id='101')
        self.assertFalse(result['engaged'])
        self.assertIsNone(result['context'])
        self.assertNotEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')

    def test_final_locked_dispatch_rechecks_task_cycle(self):
        from unittest.mock import patch
        runtime, draft, page, now, binding = self.receipt_fixture()
        # Restore only the synthetic pre-send journals for this final-boundary test.
        with runtime.transaction() as state:
            row = state['outbox'][draft['token']]
            row['state'] = 'draft'
            row.pop('attempted_at')
            row.pop('candidate_id')
        with runtime.coach.transaction() as state:
            event = state['episode']['events'][0]
            event['state'] = 'planned'
            event.pop('claimed_at')
        def change_after_authorize(*args, **kwargs):
            task = self.cli('show', '1')
            self.cli('done', '1', '--completed-at', '2023-12-30', '--expected-cycle', task['cycle_id'], '--completion-id', 'racing')
            return True
        with patch.object(runtime, 'authorize', side_effect=change_after_authorize), patch('task_coach.driver.subprocess.run') as send:
            send.return_value.stdout = '{"success": true, "message_id": "100"}'
            send.return_value.returncode = 0
            result = runtime.dispatch(draft['token'], draft['fence'], hermes='/fictional/hermes', now=now)
        send.assert_not_called()
        self.assertIn('uncertain', result)

    def test_clarification_snapshot_cycle_must_match_its_source_receipt(self):
        from test_core_clarification import ClarificationTest
        from test_core_driver import BINDING
        from task_coach.driver import Driver
        self.cli('update', '1', '--repeat', '1 day', '--due', '2024-01-01')
        self.fixture = ClarificationTest.fixture.__get__(self)
        self.message = ClarificationTest.message.__get__(self)
        self.pages = ClarificationTest.pages.__get__(self)
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        state = runtime.status()
        Driver.validate_state(state)
        record = next(iter(state['clarifications'].values()))
        candidate = next(c for c in record['candidates'] if c['task']['id'] == 1)
        candidate['task']['cycle_id'] = 'f' * 32
        with self.assertRaises(ValueError):
            Driver.validate_state(state)

    def test_old_clarification_candidate_blocks_retries_and_resolution(self):
        from test_core_clarification import ClarificationTest
        from test_core_driver import BINDING
        # Set recurrence before snapshots are captured by the existing real driver fixture.
        self.cli('update', '1', '--repeat', '1 day', '--due', '2024-01-01')
        self.fixture = ClarificationTest.fixture.__get__(self)
        self.message = ClarificationTest.message.__get__(self)
        self.pages = ClarificationTest.pages.__get__(self)
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        hold = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        task = self.cli('show', '1')
        self.cli('done', '1', '--completed-at', '2024-01-01', '--expected-cycle', task['cycle_id'], '--completion-id', 'old-held-cycle')
        runtime.preflight(now=now)
        retry = runtime.status()['clarification_retry']['events'][0]
        self.assertFalse(runtime.preflight(now=retry['slot'])['wakeAgent'])
        history.insert(0, self.message('105', retry['slot'], 'First task'))
        with self.assertRaises(ValueError):
            runtime.resolve_clarification(binding=BINDING, clarification_id=hold['id'], task_id=1, selection_message_id='105', pages=self.pages(history, retry['slot']), now=retry['slot'])

    def test_planned_events_cannot_follow_reused_row_even_after_next_due(self):
        self.cli('update', '1', '--repeat', '1 day', '--due', '2024-01-01')
        engine = self.engine()
        engine.tick(now=datetime(2024, 1, 1, 8, tzinfo=timezone.utc), binding=fixtures.BINDING)
        old = engine.status()['episode']
        task = self.cli('show', '1')
        self.cli('done', '1', '--completed-at', '2023-12-30', '--expected-cycle', task['cycle_id'], '--completion-id', 'first')
        slot = datetime.fromisoformat(old['events'][0]['slot'])
        self.assertFalse(engine.tick(now=slot, binding=fixtures.BINDING)['wakeAgent'])
        self.assertEqual(engine.status()['episode']['stopped'], 'task-unavailable')
        self.assertNotEqual(old.get('cycle_id'), self.cli('show', '1')['cycle_id'])
