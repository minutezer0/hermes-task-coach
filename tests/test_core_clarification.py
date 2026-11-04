"""Clarification is runtime bookkeeping, never premature task engagement."""
import copy
import json
import sys
import unittest
import test_core_coaching as fixtures
from test_core_driver import BINDING, persist_legacy_runtime
from task_coach.driver import Driver


class ClarificationTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli

    def fixture(self):
        self.cli('setup', '--update', '--max-tasks-per-window', '2',
                 '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Second fictional task')
        runtime = Driver(self.data)
        runtime.coach.rng = __import__('random').Random(1)
        persist_legacy_runtime(runtime)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history, drafts = [], []
        sender = self.data.parent / 'sender'
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            now = event['slot']
            draft = runtime.draft(event['token'], 'Fictional check-in ' + str(n), now=now)
            sender.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(dict(success=True, message_id=str(100+n)))) + ')\n')
            sender.chmod(0o700)
            runtime.dispatch(event['token'], draft['fence'], hermes=str(sender), now=now)
            history.insert(0, self.message(str(100+n), now, draft['body'], bot=True))
            runtime.confirm(event['token'], draft['fence'], self.pages(history, now), now=now)
            drafts.append(draft)
        return runtime, history, drafts, now

    def message(self, identifier, now, content='I made progress', *, bot=False, **extra):
        return dict(id=identifier, timestamp=now, content=content, attachments=[],
                    author=dict(id='456' if bot else BINDING['owner'], bot=bot), **extra)

    def pages(self, history, now):
        return [dict(binding=BINDING, channel_id='123', before=None, observed_at=now,
                     result=dict(messages=copy.deepcopy(history), count=len(history)))]

    def test_ambiguous_batch_holds_without_mutating_any_candidate(self):
        runtime, history, drafts, now = self.fixture()
        before = runtime.coach.status()
        # One clear message in the same batch must not partially engage A.
        history[:0] = [self.message('104', now), self.message('103', now,
            message_reference=dict(message_id='100', channel_id='123'))]
        result = runtime.engagement(BINDING, self.pages(history, now), now=now)
        self.assertEqual(runtime.coach.status(), before,
                         'ambiguity must be detected before any candidate is stopped')
        self.assertEqual(result['error'], 'ambiguous-engagement')
        pending = result['clarifications']
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['message']['id'], '104')
        self.assertEqual({c['task']['id'] for c in pending[0]['candidates']},
                         {draft['task']['id'] for draft in drafts})
        self.assertEqual(Driver(self.data).preflight(now=now)['reason'], 'pending-clarification')
        self.assertIsNone(runtime.coach.status()['episode']['window_stopped'])
        self.assertNotIn('message_reference', history[0])

    def test_observe_hold_blocks_dispatch_and_cannot_suppress_clear_batch_target(self):
        runtime, history, drafts, now = self.fixture()
        followup = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = followup['slot']
        draft = runtime.draft(followup['token'], 'Fictional followup', now=now)
        before = runtime.coach.status()
        history[:0] = [self.message('104', now), self.message('103', now,
            message_reference=dict(message_id='101', channel_id='123'))]
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        self.assertEqual(runtime.coach.status(), before)
        self.assertFalse(evidence['complete'])
        self.assertFalse(evidence['engaged'])
        with self.assertRaises(ValueError):
            Driver(self.data).dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=now)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'draft')
        self.assertEqual(runtime.preflight(now=now)['reason'], 'pending-clarification')

    def test_last_authorization_rechecks_hold_after_claim(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Fictional followup', now=now)
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        self.assertTrue(runtime.coach.tick(binding=BINDING, now=now, evidence=evidence,
                                         expected_token=event['token'])['wakeAgent'])
        history.insert(0, self.message('104', now))
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        with self.assertRaisesRegex(ValueError, 'clarification'):
            runtime.authorize(runtime.row(event['token'], draft['fence']), now=now)

    def test_invalid_clarification_state_fails_closed(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        state = runtime.status()
        for invalid in ([], {'bad': pending}, {pending['id']: dict(pending, state='ignored')},
                        {pending['id']: dict(pending, candidates=[])},
                        {pending['id']: dict(pending, surprise=True)}):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                Driver.validate_state(dict(state, clarifications=invalid))

    def test_context_and_new_ambiguity_exclude_unavailable_candidates(self):
        runtime, history, drafts, now = self.fixture()
        self.cli('done', str(drafts[0]['task']['id']))
        context = runtime.context(BINDING)
        self.assertIsNotNone(context)
        self.assertEqual(context['task_id'], drafts[1]['task']['id'])
        history.insert(0, self.message('104', now))
        result = runtime.engagement(BINDING, self.pages(history, now), now=now)
        self.assertTrue(result['engaged'])
        self.assertEqual(result['context']['task_id'], drafts[1]['task']['id'])

    def test_resolution_does_not_catch_up_a_slot_that_became_due_during_hold(self):
        from datetime import timedelta
        from task_coach.coaching import instant
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        slot = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]['slot']
        later = (instant(slot) + timedelta(minutes=1)).isoformat()
        history.insert(0, self.message('105', later, 'The first task'))
        runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, later), now=later)
        result = Driver(self.data).preflight(now=later)
        self.assertFalse(result['wakeAgent'], result)
        self.assertEqual(result['reason'], 'clarification-missed-opportunity')
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_cli_and_native_plan_expose_explicit_selection_not_reply_metadata(self):
        import subprocess
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        result = runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        capture = self.data.parent / 'capture.json'
        capture.write_text(json.dumps(self.pages(history, now)))
        command = [sys.executable, '-I', '-B', str(fixtures.SCRIPTS / 'task-coach.py'),
            '--data-dir', str(self.data), 'runtime', 'resolve-clarification', '--binding', json.dumps(BINDING),
            '--clarification-id', pending['id'], '--task-id', str(drafts[0]['task']['id']),
            '--selection-message-id', '105', '--pages-file', str(capture)]
        done = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), result)
        instruction = runtime.native_plan('/fictional/profile', python='/usr/bin/python3',
            helper='/fictional/helper', hermes='/fictional/hermes')['inbound_instruction']
        for text in ('resolve-clarification', 'candidate titles', 'normal inbound', 'before changing task data'):
            self.assertIn(text, instruction)
        again = runtime.engagement(BINDING, self.pages(history, now), now=now)
        self.assertTrue(again['engaged'], again)
        self.assertEqual(again['context']['task_id'], drafts[0]['task']['id'])

    def test_hold_racing_final_authorization_prevents_network_call(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Fictional followup', now=now)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        test = self
        class RacingDriver(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                history.insert(0, test.message('104', now.isoformat()))
                Driver(test.data).engagement(BINDING, test.pages(history, now.isoformat()), now=now)
                return True
        sent = RacingDriver(self.data).dispatch(draft['token'], draft['fence'],
            hermes=str(self.data.parent / 'sender'), now=now)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('clarification', sent['uncertain'])

    def test_crash_after_engine_commit_keeps_durable_choice_and_hold(self):
        from contextlib import contextmanager
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The second task'))
        args = dict(binding=BINDING, clarification_id=pending['id'], task_id=drafts[1]['task']['id'],
                    selection_message_id='105', pages=self.pages(history, now), now=now)
        transaction = runtime.coach._transaction
        @contextmanager
        def crash_after_commit():
            with transaction() as state:
                yield state
                stopped = state['episode']['next_tasks'][0]['stopped']
            if stopped == 'owner-engaged':
                raise RuntimeError('simulated process death after engine commit')
        runtime.coach._transaction = crash_after_commit
        with self.assertRaisesRegex(RuntimeError, 'simulated process death'):
            runtime.resolve_clarification(**args)
        self.assertEqual(Driver(self.data).preflight(now=now)['reason'], 'pending-clarification')
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            Driver(self.data).resolve_clarification(**dict(args, task_id=drafts[0]['task']['id']))
        result = Driver(self.data).resolve_clarification(**args)
        self.assertEqual(result['context']['task_id'], drafts[1]['task']['id'])
        self.assertEqual(Driver(self.data).pending_clarifications(BINDING), [])

    def test_concurrent_conflicting_choices_attribute_only_one_candidate(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'An explicit choice'))
        barrier = threading.Barrier(2)
        def resolve(task_id):
            barrier.wait(timeout=5)
            try:
                return Driver(self.data).resolve_clarification(binding=BINDING, clarification_id=pending['id'],
                    task_id=task_id, selection_message_id='105', pages=self.pages(history, now), now=now)
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(resolve, [d['task']['id'] for d in drafts]))
        successes = [r for r in results if isinstance(r, dict)]
        self.assertEqual(len(successes), 1, results)
        self.assertIn('conflicting', next(r for r in results if isinstance(r, str)))
        stored = runtime.status()['clarifications'][pending['id']]
        self.assertEqual(stored['message'], pending['message'])
        self.assertEqual(stored['candidates'], pending['candidates'])
        self.assertEqual(stored['result'], successes[0])

    def test_invalid_captures_and_stale_candidate_leave_every_task_untouched(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The second task'))
        args = dict(binding=BINDING, clarification_id=pending['id'], task_id=drafts[1]['task']['id'],
                    selection_message_id='105', pages=self.pages(history, now), now=now)
        invalid = []
        for change in ('original', 'owner', 'stale'):
            pages = self.pages(history, now)
            if change == 'original':
                pages[0]['result']['messages'][1]['content'] = 'Edited original'
            elif change == 'owner':
                pages[0]['result']['messages'][0]['author']['id'] = 'stranger'
            else:
                pages[0]['observed_at'] = '2030-01-07T08:00:00Z'
            invalid.append(pages)
        before = runtime.coach.status(), self.cli('list')
        for pages in invalid:
            with self.assertRaises(ValueError):
                runtime.resolve_clarification(**dict(args, pages=pages))
            self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        self.cli('done', str(drafts[1]['task']['id']))
        before = runtime.coach.status(), self.cli('list')
        with self.assertRaisesRegex(ValueError, 'no longer valid'):
            runtime.resolve_clarification(**args)
        self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        self.assertEqual(runtime.pending_clarifications(BINDING), [pending])

    def test_unselected_future_followup_still_dispatches_after_selection(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        self.assertTrue(runtime.preflight(now=now)['wakeAgent'])
        draft = runtime.draft(event['token'], 'Still about the second task', now=now)
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        self.assertTrue(evidence['complete'])
        self.assertFalse(evidence['engaged'])
        sender = self.data.parent / 'sender'
        sender.write_text('#!' + sys.executable + '\nprint(\'{"success": true, "message_id": "106"}\')\n')
        sent = runtime.dispatch(draft['token'], draft['fence'], hermes=str(sender), now=now)
        self.assertEqual(sent['candidate_id'], '106')
        history.insert(0, self.message('106', now, draft['body'], bot=True))
        receipt = runtime.confirm(draft['token'], draft['fence'], self.pages(history, now), now=now)
        self.assertEqual(receipt['message_id'], '106')
        self.assertEqual(runtime.coach.status()['deliveries'], 3)
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_legacy_ambiguous_window_is_never_revived(self):
        from task_coach.coaching import window_stop
        runtime, history, drafts, now = self.fixture()
        with runtime.coach.transaction() as state:
            window_stop(state['episode'], 'ambiguous-engagement')
        before = runtime.coach.status()
        self.assertEqual(Driver(self.data).preflight(now=now)['reason'], 'ambiguous-engagement')
        self.assertEqual(runtime.coach.status()['episode'], before['episode'])

    def test_resolution_preserves_pause_and_failure(self):
        from task_coach.coaching import window_stop
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The second task'))
        with runtime.coach.transaction() as state:
            state['paused'] = True
            window_stop(state['episode'], 'failed-delivery')
        runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[1]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        self.assertTrue(runtime.coach.status()['paused'])
        self.assertEqual(runtime.coach.status()['episode']['window_stopped'], 'failed-delivery')
        self.assertFalse(runtime.preflight(now=now)['wakeAgent'])

    def test_restarted_resolution_uses_actual_release_time_for_no_catchup(self):
        from contextlib import contextmanager
        from datetime import timedelta
        from task_coach.coaching import instant
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        args = dict(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'],
                    selection_message_id='105', pages=self.pages(history, now), now=now)
        transaction, calls = runtime.coach._transaction, []
        @contextmanager
        def interrupt():
            with transaction() as state:
                yield state
            calls.append(True)
            if len(calls) == 2:
                raise RuntimeError('interrupted resolution')
        runtime.coach._transaction = interrupt
        with self.assertRaises(RuntimeError):
            runtime.resolve_clarification(**args)
        slot = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]['slot']
        later = (instant(slot) + timedelta(minutes=1)).isoformat()
        Driver(self.data).resolve_clarification(**dict(args, now=later))
        self.assertEqual(Driver(self.data).preflight(now=later)['reason'], 'clarification-missed-opportunity')

    def test_inflight_history_does_not_turn_selection_into_another_hold(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        self.assertEqual(runtime.pending_clarifications(BINDING), [pending])
        runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertTrue(runtime.engagement(BINDING, self.pages(history, now), now=now)['engaged'])

    def test_retained_open_tasks_are_not_replaced_by_latest_episode_guess(self):
        runtime, history, drafts, now = self.fixture()
        later = '2030-01-08T08:00:00Z'
        runtime.coach.prepare(binding=BINDING, now=later)
        self.assertIsNone(runtime.context(BINDING))
        history.insert(0, self.message('104', later))
        result = runtime.engagement(BINDING, self.pages(history, later), now=later)
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertEqual(result['clarifications'], [])
        self.assertFalse(runtime.pending_clarifications(BINDING))
        self.assertTrue(runtime.local_first())

    def test_resolved_hold_racing_final_boundary_still_forbids_catchup(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Fictional followup', now=now)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        test = self
        class RacingDriver(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                stamp = now.isoformat()
                history.insert(0, test.message('104', stamp))
                driver = Driver(test.data)
                pending = driver.engagement(BINDING, test.pages(history, stamp), now=now)['clarifications'][0]
                history.insert(0, test.message('105', stamp, 'The first task'))
                driver.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
                    task_id=drafts[0]['task']['id'], selection_message_id='105', pages=test.pages(history, stamp), now=now)
                return True
        sent = RacingDriver(self.data).dispatch(draft['token'], draft['fence'],
            hermes=str(self.data.parent / 'sender'), now=now)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('clarification-missed-opportunity', sent['uncertain'])

    def test_fresh_resolution_through_real_cli_parser(self):
        from datetime import datetime
        from unittest.mock import patch
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The second task'))
        path = self.data.parent / 'selection-pages.json'
        path.write_text(json.dumps(self.pages(history, now)))
        with patch('task_coach.driver.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat(now)
            result = self.cli('runtime', 'resolve-clarification', '--binding', json.dumps(BINDING),
                '--clarification-id', pending['id'], '--task-id', str(drafts[1]['task']['id']),
                '--selection-message-id', '105', '--pages-file', str(path))
        self.assertEqual(result['provenance'], 'explicit-owner-selection')
        self.assertEqual(result['context']['task_id'], drafts[1]['task']['id'])
        self.assertEqual(runtime.coach.status()['episode']['next_tasks'][0]['stopped'], 'owner-engaged')

    def test_resolution_does_not_clear_uncertain_delivery(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Fictional uncertain followup', now=now)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=now)
        journal = runtime.row(draft['token'], draft['fence'])
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
            task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertEqual(runtime.row(draft['token'], draft['fence']), journal)
        self.assertEqual(runtime.preflight(now=now)['reason'], 'unconfirmed-delivery')

    def test_wall_clock_release_cutoff_is_not_frozen_at_command_start(self):
        from unittest.mock import patch
        from datetime import timedelta
        from task_coach.coaching import instant
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The first task'))
        slot = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]['slot']
        later = instant(slot) + timedelta(minutes=1)
        with patch('task_coach.driver.datetime') as clock:
            clock.now.side_effect = [instant(now)] + [later] * 10
            runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'],
                task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now))
        result = runtime.preflight(now=later)
        self.assertFalse(result['wakeAgent'], result)
        self.assertEqual(result['reason'], 'clarification-missed-opportunity')

    def test_explicit_selection_is_guarded_idempotent_and_preserves_other_task(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        result = runtime.engagement(BINDING, self.pages(history, now), now=now)
        pending = result['clarifications'][0]
        before = runtime.coach.status()
        receipts = {k: v.get('receipt') for k, v in runtime.status()['outbox'].items()}
        history.insert(0, self.message('105', now, 'I mean ' + drafts[0]['task']['title']))
        args = dict(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'],
                    selection_message_id='105', pages=self.pages(history, now), now=now)
        for changes in (dict(task_id=999), dict(binding=dict(BINDING, owner='stranger')),
                        dict(selection_message_id='104'), dict(selection_message_id='999')):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                Driver(self.data).resolve_clarification(**dict(args, **changes))
            self.assertEqual(runtime.coach.status(), before)
            self.assertEqual(runtime.pending_clarifications(BINDING), [pending])
        resolved = Driver(self.data).resolve_clarification(**args)
        self.assertEqual(resolved['context']['task_id'], drafts[0]['task']['id'])
        self.assertEqual(resolved['provenance'], 'explicit-owner-selection')
        self.assertEqual(runtime.coach.status()['episode']['stopped'], before['episode']['stopped'] or 'owner-engaged')
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        self.assertEqual(Driver(self.data).resolve_clarification(**args), resolved)
        with self.assertRaises(ValueError):
            Driver(self.data).resolve_clarification(**dict(args, task_id=drafts[1]['task']['id']))
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertEqual({k: v.get('receipt') for k, v in runtime.status()['outbox'].items()}, receipts)
        # Reobserving the original must use its immutable explicit selection, not re-ask.
        again = runtime.engagement(BINDING, self.pages(history[1:], now), now=now)
        self.assertTrue(again['engaged'])
        self.assertEqual(again['context']['task_id'], drafts[0]['task']['id'])
        self.assertEqual([t['status'] for t in self.cli('list')], ['open', 'open'])
