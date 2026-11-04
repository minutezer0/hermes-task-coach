"""Local-first fixtures; no installed skill or real transport is used."""
import unittest
from datetime import datetime, timezone
from pathlib import Path
import test_core_driver as fixtures

BINDING = fixtures.BINDING


class LocalFirstTest(unittest.TestCase):
    setUp = fixtures.RuntimeTest.setUp
    cli = fixtures.RuntimeTest.cli
    engine = fixtures.RuntimeTest.engine

    def runtime(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        runtime.coach.rng = __import__('random').Random(1)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        self.assertTrue(hasattr(runtime, 'upgrade_local_first'), 'explicit local-first upgrade missing')
        runtime.upgrade_local_first(confirm=True, now='2030-01-07T08:00:00Z')
        return runtime

    def sender(self):
        fake = Path(self.temp.name) / 'fictional-sender'
        counter = Path(self.temp.name) / 'fictional-send-count'
        fake.write_text('#!/usr/bin/env python3\nimport json\nfrom pathlib import Path\np=Path(' + repr(str(counter)) + ')\nn=int(p.read_text())+1 if p.exists() else 100\np.write_text(str(n))\nprint(json.dumps({"success":True,"message_id":str(n)}))\n')
        fake.chmod(0o700)
        return str(fake)

    def test_stored_route_authorization_is_validated_before_local_scheduling(self):
        import copy
        from task_coach.driver import Driver
        runtime = self.runtime()
        valid = runtime.status()
        for change in ({'platform': 'unsupported'}, {'destination': 'discord:999'}, {'bot_id': ''}):
            with self.subTest(change=change):
                state = copy.deepcopy(valid)
                state['route'].update(change)
                with self.assertRaises(ValueError):
                    Driver.validate_state(state)

    def test_optional_history_never_guesses_between_accepted_tasks(self):
        from test_core_clarification import ClarificationTest
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history, drafts = [], []
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            draft = runtime.draft(event['token'], 'Fictional ' + str(n), now=event['slot'])
            runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
            history.insert(0, ClarificationTest.message(self, str(100+n), event['slot'], draft['body'], bot=True))
            drafts.append(draft)
        now = root['next_tasks'][0]['events'][0]['slot']
        history.insert(0, ClarificationTest.message(self, '200', now))
        runtime.confirm(drafts[0]['token'], drafts[0]['fence'], ClarificationTest.pages(self, history, now), now=now)
        result = runtime.engagement(BINDING, ClarificationTest.pages(self, history, now), now=now)
        self.assertFalse(result['engaged'])
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertFalse(runtime.status().get('clarifications'), 'new local-first ambiguity should ask conversationally, not install a hold')
        history[0]['message_reference'] = None
        result = runtime.engagement(BINDING, ClarificationTest.pages(self, history, now), now=now)
        self.assertFalse(result['engaged'], 'known unthreaded is not explicit task selection')

    def test_optional_observe_verifies_accepted_anchor_and_scopes_reply(self):
        from datetime import timedelta
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        draft = runtime.draft(events[0]['token'], 'Fictional opener', now=events[0]['slot'])
        runtime.dispatch(events[0]['token'], draft['fence'], hermes=self.sender(), now=events[0]['slot'])
        followup = runtime.draft(events[1]['token'], 'Fictional followup', now=events[1]['slot'])
        anchor_time = (datetime.fromisoformat(events[0]['slot']) + timedelta(seconds=1)).isoformat()
        messages = [dict(id='200', content='skip for now', timestamp=events[1]['slot'], author=dict(id=BINDING['owner'], bot=False), attachments=[]),
                    dict(id='100', content='Fictional opener', timestamp=anchor_time, author=dict(id='456', bot=True), attachments=[])]
        pages = [dict(binding=BINDING, channel_id='123', before=None, observed_at=events[1]['slot'], result=dict(messages=messages))]
        evidence = runtime.observe(events[1]['token'], followup['fence'], pages, now=events[1]['slot'])
        self.assertTrue(evidence['engaged'])
        self.assertEqual(runtime.row(events[0]['token'], draft['fence'])['state'], 'confirmed')
        self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(self.cli('show', '1')['status'], 'open')

    def test_timeout_scopes_attempt_without_retry_storm(self):
        from unittest.mock import patch
        import subprocess
        original = subprocess.run
        attempted = []
        def timeout_first(command, **kwargs):
            attempted.append(command)
            if len(attempted) == 1:
                raise subprocess.TimeoutExpired(command, 45)
            return original(command, **kwargs)
        with patch('task_coach.driver.subprocess.run', side_effect=timeout_first):
            self.test_uncertain_a_does_not_block_b_or_retry()
        self.assertEqual(len(attempted), 2)

    def test_legacy_clarification_audit_survives_optin_and_rollover(self):
        from test_core_clarification import ClarificationTest
        helper = ClarificationTest()
        helper.data = self.data
        helper.cli = self.cli
        runtime, history, drafts, now = helper.fixture()
        history.insert(0, helper.message('200', now))
        result = runtime.engagement(BINDING, helper.pages(history, now), now=now)
        self.assertEqual(result['error'], 'ambiguous-engagement')
        before = runtime.status()
        runtime.upgrade_local_first(confirm=True, now=now)
        runtime.preflight(now='2030-01-08T08:00:00Z')
        after = runtime.status()
        self.assertEqual(after['outbox'], before['outbox'])
        self.assertEqual(after['clarifications'], before['clarifications'])
        self.assertEqual(runtime.coach.status()['episode']['day'], '2030-01-08')
        self.assertTrue(runtime.local_first())

    def test_legacy_shared_reply_refused_before_engine_mutation(self):
        from test_core_clarification import ClarificationTest
        from task_coach import clarification
        from task_coach.driver import Driver
        helper = ClarificationTest()
        helper.data, helper.cli = self.data, self.cli
        runtime, history, drafts, now = helper.fixture()
        history.insert(0, helper.message('200', now))
        runtime.engagement(BINDING, helper.pages(history, now), now=now)
        with runtime.transaction() as state:
            clarification.activity(state, [helper.message('201', now)])
        runtime.upgrade_local_first(confirm=True, now=now)
        runtime.preflight(now='2030-01-08T08:00:00Z')
        first = runtime.coach.status()['episode']['events'][0]
        event, next_now = first['token'], first['slot']
        draft = runtime.draft(event, 'Fictional next day', now=next_now)
        fake = Path(self.temp.name) / 'new-opener'
        fake.write_text('#!/usr/bin/env python3\nprint(\'{"success":true,"message_id":"999"}\')\n')
        fake.chmod(0o700)
        runtime.dispatch(event, draft['fence'], hermes=str(fake), now=next_now)
        before = runtime.coach.status()
        audit = runtime.status()
        from concurrent.futures import ThreadPoolExecutor
        def refuse(_):
            with self.assertRaises(ValueError):
                Driver(self.data).record_engagement(binding=BINDING, owner=BINDING['owner'], message_id='201',
                    event_token=event, task_id=draft['task']['id'], cycle_id=draft['task'].get('cycle_id'),
                    intent='skip-for-now', now=next_now)
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(refuse, range(2)))
        refuse(2)  # Restarted retry remains nonmutating.
        self.assertEqual(runtime.coach.status(), before)
        self.assertEqual(runtime.status(), audit)
        # A contradictory cross-record ledger is refused on load, before engine writes.
        import copy, json, sqlite3
        from contextlib import closing
        bad = copy.deepcopy(audit)
        request = dict(binding=BINDING, owner=BINDING['owner'], message_id='201', event_token=event,
                       task_id=draft['task']['id'], cycle_id=draft['task'].get('cycle_id'), intent='engaged')
        bad['engagements'] = {'201': dict(request=request, recorded_at=next_now,
            result=dict(engaged=True, task_id=draft['task']['id'], event_token=event,
                        provenance='agent-mediated-explicit-intent'))}
        Driver.validate_state(audit)
        with self.assertRaises(ValueError):
            Driver.validate_state(bad)
        with closing(sqlite3.connect(Path(self.data) / 'outbox.sqlite3')) as db:
            db.execute('UPDATE runtime SET value=? WHERE id=1', (json.dumps(bad),))
            db.commit()
        refuse(3)
        self.assertEqual(runtime.coach.status(), before)

    def test_local_followup_final_authorization_keeps_actual_spacing_guard(self):
        from datetime import timedelta
        self.cli('setup', '--update', '--min-followup-interval', '30', '--max-followup-interval', '30')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        draft = runtime.draft(events[0]['token'], 'Fictional opener', now=events[0]['slot'])
        runtime.dispatch(events[0]['token'], draft['fence'], hermes=self.sender(), now=events[0]['slot'])
        draft = runtime.draft(events[1]['token'], 'Fictional followup', now=events[1]['slot'])
        self.assertTrue(runtime.coach.tick(now=events[1]['slot'], binding=BINDING, expected_token=events[1]['token'])['wakeAgent'])
        with self.assertRaises(ValueError):
            runtime.authorize(draft, now=datetime.fromisoformat(events[1]['slot']) + timedelta(seconds=1))

    def test_dispatch_refreshes_actual_spacing_at_transport_boundary(self):
        from datetime import timedelta
        from unittest.mock import patch
        self.cli('setup', '--update', '--min-followup-interval', '30', '--max-followup-interval', '30')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        opener = runtime.draft(events[0]['token'], 'Fictional opener', now=events[0]['slot'])
        sender = self.sender()
        runtime.dispatch(opener['token'], opener['fence'], hermes=sender, now=events[0]['slot'])
        followup = runtime.draft(events[1]['token'], 'Fictional followup', now=events[1]['slot'])
        slot = datetime.fromisoformat(events[1]['slot'])
        with patch('task_coach.driver.datetime') as clock:
            clock.now.side_effect = [slot, slot, slot + timedelta(seconds=1), slot + timedelta(seconds=1)]
            result = runtime.dispatch(followup['token'], followup['fence'], hermes=sender)
        self.assertEqual((Path(self.temp.name) / 'fictional-send-count').read_text(), '100')
        self.assertIn('spacing', result['uncertain'])

    def test_spacing_expiry_stops_only_affected_sequence(self):
        from datetime import timedelta
        self.cli('setup', '--update', '--max-tasks-per-window', '2', '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        first = root['events'][0]
        draft = runtime.draft(first['token'], 'Fictional opener', now=first['slot'])
        runtime.dispatch(first['token'], draft['fence'], hermes=self.sender(), now=first['slot'])
        followup = root['events'][1]
        now = datetime.fromisoformat(followup['slot']) + timedelta(minutes=1)
        draft = runtime.draft(followup['token'], 'Fictional followup', now=now)
        with self.assertRaises(ValueError):
            runtime.dispatch(followup['token'], draft['fence'], hermes=self.sender(), now=now)
        b = root['next_tasks'][0]['events'][0]
        self.assertTrue(runtime.preflight(now=b['slot'])['wakeAgent'])

    def test_late_native_acceptance_does_not_globally_stop_b(self):
        from unittest.mock import patch
        from datetime import timedelta
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        event = root['events'][0]
        start = datetime.fromisoformat(event['expires']) - timedelta(seconds=1)
        accepted = start + timedelta(seconds=45)
        draft = runtime.draft(event['token'], 'Fictional opener', now=start)
        with patch('task_coach.driver.datetime') as clock:
            clock.now.side_effect = [start, start, start, accepted]
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender())
        self.assertEqual(result['state'], 'accepted')
        b = root['next_tasks'][0]['events'][0]
        self.assertTrue(runtime.preflight(now=b['slot'])['wakeAgent'])

    def test_native_acceptance_clock_is_response_not_invocation(self):
        from unittest.mock import patch
        from datetime import timedelta
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        start = datetime.fromisoformat(event['slot'])
        accepted = start + timedelta(seconds=45)
        with patch('task_coach.driver.datetime') as clock:
            clock.now.side_effect = [start, start, start, accepted]
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender())
        self.assertEqual(result['acceptance']['receipt']['delivered_at'], accepted.isoformat())

    def test_old_cycle_acceptance_and_inbound_cannot_affect_due_new_cycle(self):
        self.cli('done', '1')
        task = self.cli('add', 'Fictional recurring task', '--repeat', '1 day', '--due', '2024-01-01')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        first = events[0]
        draft = runtime.draft(first['token'], 'Fictional recurring opener', now=first['slot'])
        sent = runtime.dispatch(first['token'], draft['fence'], hermes=self.sender(), now=first['slot'])
        advanced = self.cli('done', str(task['id']), '--completed-at', '2024-01-02', '--expected-cycle', task['cycle_id'], '--completion-id', 'fictional-completion')
        self.assertEqual(advanced['due'], '2024-01-03')
        with self.assertRaises(ValueError):
            runtime.record_engagement(binding=BINDING, owner=BINDING['owner'], message_id='200',
                event_token=first['token'], task_id=task['id'], cycle_id=task['cycle_id'], intent='skip-for-now', now=first['slot'])
        self.assertIsNone(runtime.context(BINDING, reply_to_message_id='100'))
        with self.assertRaises(ValueError):
            runtime.draft(events[1]['token'], 'Stale cycle followup', now=events[1]['slot'])
        self.assertEqual(runtime.status()['outbox'][first['token']]['acceptance'], sent['acceptance'])
        self.assertEqual(self.cli('show', str(task['id'])), advanced)

    def test_replayed_native_id_is_uncertain_not_poisoned_acceptance(self):
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        fake = Path(self.temp.name) / 'replayed-id-sender'
        fake.write_text('#!/usr/bin/env python3\nprint(\'{"success":true,"message_id":"100"}\')\n')
        fake.chmod(0o700)
        for event in events[:2]:
            draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
            result = runtime.dispatch(event['token'], draft['fence'], hermes=str(fake), now=event['slot'])
        self.assertEqual(result['state'], 'sending')
        self.assertIn('uncertain', result)
        self.assertNotIn('acceptance', result)

    def test_local_first_guards_and_competing_dispatch_are_preserved(self):
        from concurrent.futures import ThreadPoolExecutor
        from task_coach.driver import Driver
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        sender = self.sender()
        def dispatch(_):
            try:
                return Driver(self.data).dispatch(event['token'], draft['fence'], hermes=sender, now=event['slot'])['state']
            except ValueError:
                return 'refused'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(dispatch, range(2)))
        self.assertEqual(outcomes.count('accepted'), 1, outcomes)
        self.assertEqual((Path(self.temp.name) / 'fictional-send-count').read_text(), '100')

    def test_local_first_completed_snoozed_cancelled_pause_and_window_guards(self):
        for guard in ('done', 'snooze', 'cancel', 'pause', 'window'):
            with self.subTest(guard=guard):
                self.setUp()
                runtime = self.runtime()
                runtime.preflight(now='2030-01-07T08:00:00Z')
                event = runtime.coach.status()['episode']['events'][0]
                draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
                task = str(draft['task']['id'])
                now = event['slot']
                if guard == 'done':
                    self.cli('done', task)
                elif guard == 'snooze':
                    self.cli('snooze', task, '2031-01-01T00:00:00Z')
                elif guard == 'cancel':
                    self.cli('update', task, '--status', 'cancelled')
                elif guard == 'pause':
                    runtime.coach.pause(True)
                else:
                    now = '2030-01-07T23:59:00Z'
                with self.assertRaises(ValueError):
                    runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=now)
                self.assertFalse((Path(self.temp.name) / 'fictional-send-count').exists())

    def test_pause_after_authorize_is_rechecked_at_locked_send_boundary(self):
        from unittest.mock import patch
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        original = runtime.authorize
        def authorize_then_pause(*args, **kwargs):
            result = original(*args, **kwargs)
            runtime.coach.pause(True)
            return result
        with patch.object(runtime, 'authorize', side_effect=authorize_then_pause):
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        self.assertIn('uncertain', result)
        self.assertFalse((Path(self.temp.name) / 'fictional-send-count').exists())

    def test_local_first_documentation_contract(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('README.md', 'skills/task-coach/SKILL.md', 'skills/task-coach/references/native-runtime.md', 'skills/task-coach/references/coaching.md'):
            text = (root / name).read_text()
            with self.subTest(path=name):
                self.assertIn('upgrade-local-first', text)
                self.assertIn('record-engagement', text)
                self.assertIn('Unknown/unrecorded replies', text)
                self.assertIn('capabilities', text)

    def test_trusted_identity_cannot_be_retargeted_by_optional_history(self):
        from test_core_clarification import ClarificationTest
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history, drafts = [], []
        sender = self.sender()
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            draft = runtime.draft(event['token'], 'Fictional ' + str(n), now=event['slot'])
            runtime.dispatch(event['token'], draft['fence'], hermes=sender, now=event['slot'])
            history.insert(0, ClarificationTest.message(self, str(100+n), event['slot'], draft['body'], bot=True))
            runtime.confirm(event['token'], draft['fence'], ClarificationTest.pages(self, history, event['slot']), now=event['slot'])
            drafts.append(draft)
        now = history[0]['timestamp']
        first = drafts[0]
        runtime.record_engagement(binding=BINDING, owner=BINDING['owner'], message_id='200',
            event_token=first['token'], task_id=first['task']['id'], cycle_id=first['task'].get('cycle_id'), intent='engaged', now=now)
        reply = ClarificationTest.message(self, '200', now)
        reply['message_reference'] = {'message_id': '101', 'channel_id': '123'}
        history.insert(0, reply)
        before = runtime.coach.status()
        result = runtime.engagement(BINDING, ClarificationTest.pages(self, history, now), now=now)
        self.assertFalse(result['engaged'])
        self.assertEqual(runtime.coach.status(), before)

    def test_history_identity_cannot_be_retargeted_by_trusted_inbound(self):
        from test_core_clarification import ClarificationTest
        from task_coach.driver import Driver
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history, drafts = [], []
        sender = self.sender()
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            draft = runtime.draft(event['token'], 'Fictional ' + str(n), now=event['slot'])
            runtime.dispatch(event['token'], draft['fence'], hermes=sender, now=event['slot'])
            history.insert(0, ClarificationTest.message(self, str(100+n), event['slot'], draft['body'], bot=True))
            runtime.confirm(event['token'], draft['fence'], ClarificationTest.pages(self, history, event['slot']), now=event['slot'])
            drafts.append(draft)
        now = history[0]['timestamp']
        reply = ClarificationTest.message(self, '200', now)
        reply['message_reference'] = {'message_id': '100', 'channel_id': '123'}
        history.insert(0, reply)
        pages = ClarificationTest.pages(self, history, now)
        first = runtime.engagement(BINDING, pages, now=now)
        self.assertTrue(first['engaged'])
        before = runtime.coach.status()
        b = drafts[1]
        with self.assertRaises(ValueError):
            Driver(self.data).record_engagement(binding=BINDING, owner=BINDING['owner'], message_id='200',
                event_token=b['token'], task_id=b['task']['id'], cycle_id=b['task'].get('cycle_id'), intent='engaged', now=now)
        self.assertEqual(runtime.coach.status(), before)
        self.assertEqual(runtime.engagement(BINDING, pages, now=now), first)
        self.assertEqual(runtime.status()['engagements']['200']['result']['provenance'], 'captured-owner-history')
        a = drafts[0]
        same = dict(binding=BINDING, owner=BINDING['owner'], message_id='200', event_token=a['token'],
                    task_id=a['task']['id'], cycle_id=a['task'].get('cycle_id'), intent='engaged', now=now)
        self.assertEqual(runtime.record_engagement(**same), runtime.status()['engagements']['200']['result'])
        reply['message_reference']['message_id'] = '101'
        conflicting = runtime.engagement(BINDING, ClarificationTest.pages(self, history, now), now=now)
        self.assertFalse(conflicting['engaged'])
        self.assertEqual(runtime.coach.status(), before)

    def test_trusted_engagement_idempotence_and_owner_guards(self):
        import copy
        from task_coach.driver import Driver
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        args = dict(binding=BINDING, owner=BINDING['owner'], message_id='200', event_token=event['token'],
                    task_id=draft['task']['id'], cycle_id=draft['task'].get('cycle_id'), intent='engaged', now=event['slot'])
        with self.assertRaises(ValueError):
            runtime.record_engagement(**dict(args, owner='wrong-owner'))
        first = runtime.record_engagement(**args)
        self.assertEqual(runtime.record_engagement(**args), first)
        with self.assertRaises(ValueError):
            runtime.record_engagement(**dict(args, intent='skip-for-now'))
        bad = copy.deepcopy(runtime.status())
        bad['engagements']['200']['result']['task_id'] = 999
        with self.assertRaises(ValueError):
            Driver.validate_state(bad)

    def test_local_first_generated_prompt_has_no_history_dependency(self):
        runtime = self.runtime()
        plan = runtime.native_plan('/fictional/profile', python='/usr/bin/python3', helper='/fictional/skill/scripts/task-coach.py', hermes='/fictional/bin/hermes')
        prompt = plan['cron_argv'][4]
        self.assertIn('OPTIONAL', prompt)
        self.assertIn('[CRON_FAILURE]', prompt)
        self.assertIn('hosted connector', prompt)
        self.assertIn('record-engagement', plan['inbound_instruction'])

    def test_cli_explicit_upgrade_and_capability_report(self):
        runtime = self.runtime()
        report = self.cli('runtime', 'capabilities', '--history-availability', 'unavailable', '--history-error', 'fictional missing tool')
        self.assertEqual(report['history']['state'], 'unavailable')
        self.assertTrue(report['degraded'])
        self.assertEqual(self.cli('runtime', 'upgrade-local-first', '--confirm-upgrade'), {'after_day': None})

    def test_acceptance_metadata_is_validated(self):
        import copy
        from task_coach.driver import Driver
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        valid = runtime.status()
        Driver.validate_state(valid)
        for change in ({'provenance': 'independently-verified'}, {'receipt': {}}):
            state = copy.deepcopy(valid)
            state['outbox'][event['token']]['acceptance'].update(change)
            with self.assertRaises(ValueError):
                Driver.validate_state(state)

    def test_new_metadata_validation_refuses_malformed_policy(self):
        from task_coach.driver import Driver
        runtime = self.runtime()
        state = runtime.status()
        state['local_first'] = {'after_day': 'not-a-day'}
        with self.assertRaises(ValueError):
            Driver.validate_state(state)

    def test_legacy_upgrade_preserves_day_and_allows_next_day(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        old = runtime.coach.status()['episode']
        event = old['events'][0]
        draft = runtime.draft(event['token'], 'Legacy fictional send', now=event['slot'])
        runtime.dispatch(event['token'], draft['fence'], hermes='/nonexistent-fictional-sender', now=event['slot'])
        outbox = runtime.status()['outbox']
        old = runtime.coach.status()['episode']
        runtime.upgrade_local_first(confirm=True, now=event['slot'])
        self.assertEqual(runtime.coach.status()['episode'], old)
        self.assertFalse(runtime.local_first())
        self.assertTrue(runtime.capabilities()['history_required'])
        runtime.preflight(now='2030-01-08T08:00:00Z')
        self.assertTrue(runtime.local_first())
        self.assertEqual(runtime.status()['outbox'], outbox)
        self.assertEqual(runtime.coach.status()['episode']['day'], '2030-01-08')

    def test_acceptance_journal_recovers_after_engine_record_crash(self):
        from unittest.mock import patch
        from task_coach.driver import Driver
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        event = events[0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        with patch.object(runtime.coach, 'reconcile', side_effect=RuntimeError('fictional crash')):
            with self.assertRaises(RuntimeError):
                runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        restarted = Driver(self.data)
        prepared = restarted.preflight(now=events[1]['slot'])
        self.assertTrue(prepared['wakeAgent'], prepared)
        self.assertEqual(prepared['intent']['event_token'], events[1]['token'])
        self.assertEqual(restarted.coach.status()['deliveries'], 1)

    def test_ambiguity_does_not_block_local_followup(self):
        from test_core_clarification import ClarificationTest
        self.cli('setup', '--update', '--max-tasks-per-window', '2', '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Fictional B')
        runtime = self.runtime()
        runtime.coach.rng = __import__('random').Random(1)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history = []
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            draft = runtime.draft(event['token'], 'Fictional ' + str(n), now=event['slot'])
            runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
            history.insert(0, ClarificationTest.message(self, str(100+n), event['slot'], draft['body'], bot=True))
            runtime.confirm(event['token'], draft['fence'], ClarificationTest.pages(self, history, event['slot']), now=event['slot'])
        followup = root['next_tasks'][0]['events'][1]
        history.insert(0, ClarificationTest.message(self, '200', followup['slot']))
        result = runtime.engagement(BINDING, ClarificationTest.pages(self, history, followup['slot']), now=followup['slot'])
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertTrue(runtime.preflight(now=followup['slot'])['wakeAgent'])

    def test_optional_confirm_enriches_without_changing_acceptance(self):
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        sent = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        with self.assertRaises(ValueError):
            runtime.confirm(event['token'], draft['fence'], [], now=event['slot'])
        self.assertEqual(runtime.row(event['token'], draft['fence']), sent)
        page = dict(binding=BINDING, channel_id='123', observed_at=event['slot'], before=None,
                    result=dict(messages=[dict(id='100', content='Fictional opener', timestamp=event['slot'], author=dict(id='456', bot=True), attachments=[])]))
        receipt = runtime.confirm(event['token'], draft['fence'], [page], now=event['slot'])
        self.assertEqual(receipt['message_id'], '100')
        verified = runtime.row(event['token'], draft['fence'])
        self.assertEqual(verified['state'], 'confirmed')
        self.assertEqual(verified['acceptance'], sent['acceptance'])
        self.assertEqual(runtime.coach.status()['deliveries'], 1)

    def test_history_capability_reports_unknown_absent_error_and_available(self):
        runtime = self.runtime()
        self.assertTrue(hasattr(runtime, 'capabilities'), 'caller capability contract missing')
        self.assertEqual(runtime.capabilities()['history']['state'], 'unknown')
        self.assertEqual(runtime.capabilities(history_available=False)['history']['state'], 'unavailable')
        error = runtime.capabilities(history_available=True, history_error='fictional failure')
        self.assertEqual(error['history']['state'], 'unavailable')
        self.assertTrue(error['degraded'])
        self.assertEqual(runtime.capabilities(history_available=True)['history']['state'], 'available')
        self.assertTrue(error['local_first'])

    def test_uncertain_a_does_not_block_b_or_retry(self):
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional task B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        a, b = root['events'][0], root['next_tasks'][0]['events'][0]
        draft = runtime.draft(a['token'], 'Fictional A', now=a['slot'])
        fake = Path(self.temp.name) / 'failing-sender'
        fake.write_text('#!/usr/bin/env python3\nraise SystemExit(1)\n')
        fake.chmod(0o700)
        failed = runtime.dispatch(a['token'], draft['fence'], hermes=str(fake), now=a['slot'])
        self.assertIn('uncertain', failed)
        prepared = runtime.preflight(now=b['slot'])
        self.assertTrue(prepared['wakeAgent'], prepared)
        self.assertEqual(prepared['intent']['event_token'], b['token'])
        draft_b = runtime.draft(b['token'], 'Fictional B', now=b['slot'])
        self.assertEqual(runtime.dispatch(b['token'], draft_b['fence'], hermes=self.sender(), now=b['slot'])['state'], 'accepted')
        with self.assertRaises(ValueError):
            runtime.dispatch(a['token'], draft['fence'], hermes=self.sender(), now=b['slot'])

    def test_skip_a_does_not_block_b_without_history(self):
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Fictional task B')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        a, b = root, root['next_tasks'][0]
        event = a['events'][0]
        draft = runtime.draft(event['token'], 'Fictional A', now=event['slot'])
        runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        self.assertTrue(hasattr(runtime, 'record_engagement'), 'trusted inbound record missing')
        result = self.cli('runtime', 'record-engagement', '--binding', __import__('json').dumps(BINDING),
            '--owner', BINDING['owner'], '--message-id', '200', '--event-token', event['token'],
            '--task-id', str(a['task_id']), '--intent', 'skip-for-now')
        self.assertTrue(result['engaged'])
        self.assertEqual(self.cli('show', str(a['task_id']))['status'], 'open')
        event_b = b['events'][0]
        self.assertTrue(runtime.capabilities(history_available=False)['degraded'])
        self.assertTrue(runtime.capabilities(history_available=True, history_error='fictional history failure')['degraded'])
        draft_b = runtime.draft(event_b['token'], 'Fictional B', now=event_b['slot'])
        result = runtime.dispatch(event_b['token'], draft_b['fence'], hermes=self.sender(), now=event_b['slot'])
        self.assertEqual(result['state'], 'accepted')
        with self.assertRaises(ValueError):
            runtime.dispatch(event_b['token'], draft_b['fence'], hermes=self.sender(), now=event_b['slot'])
        self.assertEqual((Path(self.temp.name) / 'fictional-send-count').read_text(), '101')

    def test_followup_without_history_is_bounded(self):
        self.cli('setup', '--update', '--min-followup-interval', '30', '--max-followup-interval', '120')
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        events = runtime.coach.status()['episode']['events']
        self.assertGreater(len(events), 1)
        for event in events[:2]:
            draft = runtime.draft(event['token'], 'Fictional check-in', now=event['slot'])
            result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
            self.assertEqual(result['state'], 'accepted', result)
        self.assertEqual(runtime.coach.status()['deliveries'], 2)

    def test_positive_send_is_durable_accepted_without_history(self):
        runtime = self.runtime()
        runtime.preflight(now='2030-01-07T08:00:00Z')
        event = runtime.coach.status()['episode']['events'][0]
        draft = runtime.draft(event['token'], 'Fictional opener', now=event['slot'])
        result = runtime.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(result['acceptance']['provenance'], 'native-send-response')
        self.assertEqual(runtime.coach.status()['deliveries'], 1)
        self.assertIsNotNone(runtime.context(BINDING, reply_to_message_id='100'))
        from task_coach.driver import Driver
        restarted = Driver(self.data)
        self.assertEqual(restarted.status()['outbox'][event['token']], result)
        with self.assertRaises(ValueError):
            restarted.dispatch(event['token'], draft['fence'], hermes=self.sender(), now=event['slot'])
