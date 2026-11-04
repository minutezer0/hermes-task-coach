"""Guarded conversational dismissal, with tool-shaped captures and no task edits."""
from test_core_history_fixtures import enable_history, history_request, history_cli, fictional_clock_command
import copy
import json
import sys
import unittest
from datetime import datetime
from unittest.mock import patch
import test_core_clarification as fixtures
from test_core_driver import BINDING
from task_coach.driver import Driver


class DismissalTest(unittest.TestCase):
    setUp = fixtures.ClarificationTest.setUp
    cli = fixtures.ClarificationTest.cli
    fixture = fixtures.ClarificationTest.fixture
    message = fixtures.ClarificationTest.message
    pages = fixtures.ClarificationTest.pages

    def pending(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        hold = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['clarifications'][0]
        history.insert(0, self.message('105', now, 'Never mind'))
        args = dict(binding=BINDING, clarification_id=hold['id'], dismissal_message_id='105',
                    pages=self.pages(history, now), now=now)
        return runtime, history, drafts, now, hold, args

    def test_dismisses_deleted_original_and_closed_candidates_with_real_author_metadata(self):
        runtime, history, drafts, now, hold, args = self.pending()
        history.pop(1)  # Original may be deleted: it is not the cancellation anchor.
        history[0]['author']['username'] = 'current-owner-name'
        history[-1]['author']['username'] = 'bot-display-name'
        self.cli('done', str(drafts[0]['task']['id']))
        self.cli('update', str(drafts[1]['task']['id']), '--title', 'Changed candidate')
        before = runtime.coach.status(), self.cli('list'), runtime.status()['outbox']
        result = runtime.dismiss_clarification(**dict(args, pages=self.pages(history, now)), history_plan=history_request(runtime, 'dismiss_clarification', **dict(args, pages=self.pages(history, now))))
        self.assertTrue(result['dismissed'])
        self.assertEqual((runtime.coach.status(), self.cli('list'), runtime.status()['outbox']), before)
        self.assertEqual(runtime.pending_clarifications(BINDING), [])

    def test_dismisses_edited_original_deleted_and_snoozed_candidates(self):
        from contextlib import closing
        import sqlite3
        from task_coach.cli import task_store_lock
        runtime, history, drafts, now, hold, args = self.pending()
        history[1]['content'] = 'Original was edited before dismissal'
        with task_store_lock(self.data), closing(sqlite3.connect(self.data / 'tasks.sqlite3')) as db:
            db.execute('DELETE FROM tasks WHERE id=?', (drafts[0]['task']['id'],))
            db.commit()
        self.cli('snooze', str(drafts[1]['task']['id']), '2031-01-01T00:00:00Z')
        before = runtime.coach.status(), self.cli('list'), runtime.status()['outbox']
        self.assertTrue(runtime.dismiss_clarification(**dict(args, pages=self.pages(history, now)), history_plan=history_request(runtime, 'dismiss_clarification', **dict(args, pages=self.pages(history, now))))['dismissed'])
        self.assertEqual((runtime.coach.status(), self.cli('list'), runtime.status()['outbox']), before)
        # Re-observation ignores the edited original and the processed cancellation.
        self.assertFalse(runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['engaged'])
        self.assertEqual(runtime.pending_clarifications(BINDING), [])

    def test_bad_captures_and_bindings_preserve_exact_hold_and_all_state(self):
        from datetime import timedelta
        from task_coach.coaching import instant
        runtime, history, drafts, now, hold, args = self.pending()
        before = runtime.status(), runtime.coach.status(), self.cli('list')
        changes = [dict(binding=dict(BINDING, owner='wrong-owner')),
                   dict(binding=dict(BINDING, chat='wrong-chat')),
                   dict(clarification_id='unknown'), dict(dismissal_message_id='104'),
                   dict(dismissal_message_id='999'), dict(dismissal_message_id=105),
                   dict(now=(instant(now) + timedelta(seconds=61)).isoformat())]
        for kind in ('missing-dismissal', 'wrong-owner', 'bot-owner', 'wrong-route', 'missing-anchor',
                     'wrong-anchor-author', 'wrong-anchor-time', 'wrong-anchor-body', 'old-dismissal'):
            pages = copy.deepcopy(args['pages'])
            messages = pages[0]['result']['messages']
            if kind == 'missing-dismissal':
                messages.pop(0)
                pages[0]['result']['count'] -= 1
            elif kind == 'wrong-owner':
                messages[0]['author']['id'] = 'other-owner'
            elif kind == 'bot-owner':
                messages[0]['author']['bot'] = True
            elif kind == 'wrong-route':
                pages[0]['channel_id'] = 'wrong-channel'
            elif kind == 'missing-anchor':
                messages.pop()
                pages[0]['result']['count'] -= 1
            elif kind == 'wrong-anchor-author':
                messages[-1]['author']['id'] = 'other-bot'
            elif kind == 'wrong-anchor-time':
                messages[-1]['timestamp'] = (instant(messages[-1]['timestamp']) - timedelta(seconds=1)).isoformat()
            elif kind == 'wrong-anchor-body':
                messages[-1]['content'] = 'Not the receipt body'
            else:
                messages[0]['timestamp'] = (instant(now) - timedelta(seconds=1)).isoformat()
            changes.append(dict(pages=pages))
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                runtime.dismiss_clarification(**dict(args, **change), history_plan=history_request(runtime, 'dismiss_clarification', **dict(args, **change)))
            self.assertEqual((runtime.status(), runtime.coach.status(), self.cli('list')), before)

    def test_release_checks_freshness_and_clock_under_lock(self):
        from datetime import timedelta
        from task_coach.coaching import instant
        runtime, history, drafts, now, hold, args = self.pending()
        before = runtime.status()
        for delta in (61, -1):
            with patch('task_coach.driver.datetime') as clock:
                clock.now.side_effect = [instant(now), instant(now) + timedelta(seconds=delta)]
                without_clock = {k: v for k, v in args.items() if k != 'now'}
                with self.assertRaisesRegex(ValueError, 'stale|regressed'):
                    runtime.dismiss_clarification(**without_clock, history_plan=history_request(runtime, 'dismiss_clarification', **without_clock))
            self.assertEqual(runtime.status(), before)

    def test_two_holds_release_only_exact_one_and_do_not_reuse_dismissal(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('104', now), self.message('103', now)]
        holds = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['clarifications']
        self.assertEqual(len(holds), 2)
        history.insert(0, self.message('105', now, 'Dismiss that question'))
        args = dict(binding=BINDING, clarification_id=holds[0]['id'], dismissal_message_id='105',
                    pages=self.pages(history, now), now=now)
        runtime.dismiss_clarification(**args, history_plan=history_request(runtime, 'dismiss_clarification', **args))
        self.assertEqual(runtime.pending_clarifications(BINDING), [holds[1]])
        self.assertEqual(runtime.preflight(now=now)['reason'], 'pending-clarification')
        with self.assertRaisesRegex(ValueError, 'already belongs'):
            runtime.dismiss_clarification(**dict(args, clarification_id=holds[1]['id']), history_plan=history_request(runtime, 'dismiss_clarification', **dict(args, clarification_id=holds[1]['id'])))
        history.insert(0, self.message('106', now, 'Never mind the other question too'))
        runtime.dismiss_clarification(**dict(args, clarification_id=holds[1]['id'],
            dismissal_message_id='106', pages=self.pages(history, now)), history_plan=history_request(runtime, 'dismiss_clarification', **dict(args, clarification_id=holds[1]['id'],
            dismissal_message_id='106', pages=self.pages(history, now))))
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertFalse(runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['engaged'])
        self.assertEqual(len(runtime.status()['clarifications']), 2)

    def test_resolution_rejects_consumed_dismissal_selection_and_original_ids(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('104', now), self.message('103', now)]
        holds = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['clarifications']
        first, second = sorted(holds, key=lambda hold: int(hold['message']['id']), reverse=True)
        history.insert(0, self.message('105', now, 'Never mind'))
        runtime.dismiss_clarification(binding=BINDING, clarification_id=first['id'],
            dismissal_message_id='105', pages=self.pages(history, now), now=now, history_plan=history_request(runtime, 'dismiss_clarification', dismissal_message_id='105'))
        selection = dict(binding=BINDING, clarification_id=second['id'],
            task_id=drafts[1]['task']['id'], pages=self.pages(history, now), now=now)
        before = runtime.status(), runtime.coach.status(), self.cli('list')
        for identifier in ('105', '104'):
            with self.subTest(consumed=identifier), self.assertRaisesRegex(ValueError, 'already belongs'):
                runtime.resolve_clarification(**selection, selection_message_id=identifier, history_plan=history_request(runtime, 'resolve_clarification', **selection, selection_message_id=identifier))
            self.assertEqual((runtime.status(), runtime.coach.status(), self.cli('list')), before)
        history.insert(0, self.message('106', now, 'The second task'))
        selection.update(pages=self.pages(history, now), selection_message_id='106')
        result = runtime.resolve_clarification(**selection, history_plan=history_request(runtime, 'resolve_clarification', **selection))
        self.assertEqual(Driver(self.data).resolve_clarification(**dict(selection, pages=self.pages(history, now)), history_plan=history_request(Driver(self.data), 'resolve_clarification', **dict(selection, pages=self.pages(history, now)))), result)

    def test_resolution_rejects_another_resolution_selection(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('104', now), self.message('103', now)]
        first, second = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['clarifications']
        history.insert(0, self.message('105', now, 'The second task'))
        selection = dict(binding=BINDING, clarification_id=first['id'],
            task_id=drafts[1]['task']['id'], selection_message_id='105',
            pages=self.pages(history, now), now=now)
        runtime.resolve_clarification(**selection, history_plan=history_request(runtime, 'resolve_clarification', **selection))
        before = runtime.status(), runtime.coach.status(), self.cli('list')
        with self.assertRaisesRegex(ValueError, 'already belongs'):
            runtime.resolve_clarification(**dict(selection, clarification_id=second['id']), history_plan=history_request(runtime, 'resolve_clarification', **dict(selection, clarification_id=second['id'])))
        self.assertEqual((runtime.status(), runtime.coach.status(), self.cli('list')), before)

    def test_future_followup_observe_dispatch_confirm_does_not_reask_or_engage(self):
        runtime, history, drafts, now, hold, args = self.pending()
        runtime.dismiss_clarification(**args, history_plan=history_request(runtime, 'dismiss_clarification', **args))
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        self.assertTrue(runtime.preflight(now=now)['wakeAgent'])
        draft = runtime.draft(event['token'], 'A future check-in', now=now)
        # Original and cancellation have no reply reference, as in actual tools.
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now, history_plan=history_request(runtime, 'observe', draft['token'], draft['fence']))
        self.assertTrue(evidence['complete'])
        self.assertFalse(evidence['engaged'])
        sender = self.data.parent / 'sender'
        sender.write_text('#!' + sys.executable + '\nprint(\'{"success": true, "message_id": "106"}\')\n')
        sent = runtime.dispatch(draft['token'], draft['fence'], hermes=str(sender), now=now)
        self.assertEqual(sent['candidate_id'], '106')
        history.insert(0, self.message('106', now, draft['body'], bot=True))
        receipt = runtime.confirm(draft['token'], draft['fence'], self.pages(history, now), now=now, history_plan=history_request(runtime, 'confirm', draft['token'], draft['fence']))
        self.assertEqual(receipt['message_id'], '106')
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertEqual(len(runtime.status()['clarifications']), 1)
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            runtime.dispatch(draft['token'], draft['fence'], hermes=str(sender), now=now)

    def test_concurrent_dismiss_and_resolve_have_one_durable_outcome(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        runtime, history, drafts, now, hold, args = self.pending()
        barrier = threading.Barrier(2)
        def action(kind):
            barrier.wait(timeout=5)
            try:
                driver = Driver(self.data)
                if kind == 'dismiss':
                    return driver.dismiss_clarification(**args, history_plan=history_request(driver, 'dismiss_clarification', **args))
                return driver.resolve_clarification(binding=BINDING, clarification_id=hold['id'],
                    task_id=drafts[1]['task']['id'], selection_message_id='105', pages=args['pages'], now=now, history_plan=history_request(driver, 'resolve_clarification', selection_message_id='105'))
            except ValueError as error:
                return str(error)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(action, ['dismiss', 'resolve']))
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1, results)
        self.assertIn('conflicting', next(r for r in results if isinstance(r, str)))
        stored = Driver(self.data).status()['clarifications'][hold['id']]
        self.assertEqual(stored['result'], next(r for r in results if isinstance(r, dict)))
        stopped = runtime.coach.status()['episode']['next_tasks'][0]['stopped']
        self.assertEqual(stopped, None if stored['state'] == 'dismissed' else 'owner-engaged')
        self.assertEqual(runtime.pending_clarifications(BINDING), [])

    def test_concurrent_identical_and_conflicting_dismissals_survive_restart(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        runtime, history, drafts, now, hold, args = self.pending()
        history.insert(0, self.message('106', now, 'Dismiss that question'))
        args['pages'] = self.pages(history, now)
        winner = None
        for identifiers in (['105', '106'], None):
            identifiers = identifiers or [winner, winner]
            barrier = threading.Barrier(2)
            def dismiss(identifier):
                barrier.wait(timeout=5)
                try:
                    return Driver(self.data).dismiss_clarification(**dict(args, dismissal_message_id=identifier), history_plan=history_request(Driver(self.data), 'dismiss_clarification', **dict(args, dismissal_message_id=identifier)))
                except ValueError as error:
                    return str(error)
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(dismiss, identifiers))
            successes = [r for r in results if isinstance(r, dict)]
            self.assertEqual(len(successes), 2 if identifiers[0] == identifiers[1] else 1)
            winner = successes[0]['dismissal_message_id']
            self.assertEqual(successes[0], Driver(self.data).dismiss_clarification(
                **dict(args, dismissal_message_id=winner, pages=self.pages(history, now)), history_plan=history_request(Driver(self.data), 'dismiss_clarification', **dict(args, dismissal_message_id=winner, pages=self.pages(history, now)))))
        self.assertEqual(runtime.pending_clarifications(BINDING), [])

    def test_durable_resolving_choice_cannot_be_undone_even_after_engine_commit(self):
        from contextlib import contextmanager
        runtime, history, drafts, now, hold, args = self.pending()
        transaction = runtime.coach._transaction
        @contextmanager
        def crash_after_engine_commit():
            with transaction() as state:
                yield state
                stopped = state['episode']['next_tasks'][0]['stopped']
            if stopped == 'owner-engaged':
                raise RuntimeError('process died after engagement')
        runtime.coach._transaction = crash_after_engine_commit
        selection = dict(binding=BINDING, clarification_id=hold['id'], task_id=drafts[1]['task']['id'],
            selection_message_id='105', pages=args['pages'], now=now)
        with self.assertRaisesRegex(RuntimeError, 'process died'):
            runtime.resolve_clarification(**selection, history_plan=history_request(runtime, 'resolve_clarification', **selection))
        before = Driver(self.data).status(), Driver(self.data).coach.status()
        self.assertEqual(before[0]['clarifications'][hold['id']]['state'], 'resolving')
        with self.assertRaisesRegex(ValueError, 'resolution already durable'):
            Driver(self.data).dismiss_clarification(**args, history_plan=history_request(Driver(self.data), 'dismiss_clarification', **args))
        self.assertEqual((Driver(self.data).status(), Driver(self.data).coach.status()), before)
        self.assertEqual(Driver(self.data).preflight(now=now)['reason'], 'pending-clarification')
        Driver(self.data).resolve_clarification(**selection, history_plan=history_request(Driver(self.data), 'resolve_clarification', **selection))
        with self.assertRaisesRegex(ValueError, 'resolution already durable'):
            Driver(self.data).dismiss_clarification(**args, history_plan=history_request(Driver(self.data), 'dismiss_clarification', **args))

    def test_dismissal_preserves_pause_failure_legacy_stops_and_uncertain_journal(self):
        from task_coach.coaching import window_stop
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Uncertain followup', now=now)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now, history_plan=history_request(runtime, 'observe', draft['token'], draft['fence']))
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=now)
        history.insert(0, self.message('104', now))
        hold = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))['clarifications'][0]
        history.insert(0, self.message('105', now, 'Never mind'))
        with runtime.coach.transaction() as state:
            state['paused'] = True
            window_stop(state['episode'], 'failed-delivery')
            state['episode']['next_tasks'][0]['stopped'] = 'ambiguous-engagement'
        before = runtime.coach.status(), runtime.status()['outbox'], self.cli('list')
        runtime.dismiss_clarification(binding=BINDING, clarification_id=hold['id'],
            dismissal_message_id='105', pages=self.pages(history, now), now=now, history_plan=history_request(runtime, 'dismiss_clarification', dismissal_message_id='105'))
        self.assertEqual((runtime.coach.status(), runtime.status()['outbox'], self.cli('list')), before)
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        self.assertEqual(runtime.preflight(now=now)['reason'], 'unconfirmed-delivery')
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=now)

    def test_dismissal_after_due_slot_blocks_catchup_at_final_send_boundary(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        now = event['slot']
        draft = runtime.draft(event['token'], 'Must never be sent', now=now)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, now), now=now, history_plan=history_request(runtime, 'observe', draft['token'], draft['fence']))
        test = self
        class RacingDriver(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                stamp = now.isoformat()
                history.insert(0, test.message('104', stamp))
                driver = Driver(test.data)
                hold = driver.engagement(BINDING, test.pages(history, stamp), now=now, history_plan=history_request(driver, 'engagement'))['clarifications'][0]
                history.insert(0, test.message('105', stamp, 'Never mind'))
                driver.dismiss_clarification(binding=BINDING, clarification_id=hold['id'],
                    dismissal_message_id='105', pages=test.pages(history, stamp), now=now, history_plan=history_request(driver, 'dismiss_clarification', dismissal_message_id='105'))
                return True
        sent = RacingDriver(self.data).dispatch(draft['token'], draft['fence'],
            hermes=str(self.data.parent / 'sender'), now=now)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('clarification-missed-opportunity', sent['uncertain'])
        self.assertEqual(runtime.preflight(now=now)['reason'], 'unconfirmed-delivery')

    def test_duplicate_consumed_audit_identities_fail_closed(self):
        runtime, history, drafts, now, hold, args = self.pending()
        runtime.dismiss_clarification(**args, history_plan=history_request(runtime, 'dismiss_clarification', **args))
        template = runtime.status()
        modes = ('pending', 'resolving', 'resolved', 'dismissed')
        for first_mode in modes:
            for second_mode in modes:
                with self.subTest(first=first_mode, second=second_mode):
                    state = copy.deepcopy(template)
                    state['clarifications'] = {}
                    for key, mode, original_id, consumed_id in (
                            ('first', first_mode, '103', '105'),
                            ('second', second_mode, '104', '106')):
                        record = copy.deepcopy(hold)
                        record.update(id=key, state=mode, message=self.message(original_id, now))
                        if mode != 'pending':
                            record['resolved_at'] = now
                            if mode == 'dismissed':
                                record['dismissal'] = self.message(consumed_id, now)
                                record['result'] = dict(dismissed=True, engaged=False, clarification_id=key,
                                    original_message_id=original_id, dismissal_message_id=consumed_id,
                                    provenance='explicit-owner-dismissal')
                            else:
                                candidate = record['candidates'][0]
                                record['selected_token'] = candidate['token']
                                record['selection'] = self.message(consumed_id, now)
                                record['result'] = dict(engaged=True, context=dict(task=candidate['task'],
                                    task_id=candidate['task']['id'], event_token=candidate['token'],
                                    receipt=candidate['receipt'], binding=BINDING),
                                    provenance='explicit-owner-selection', clarification_id=key,
                                    original_message_id=original_id, selection_message_id=consumed_id)
                        state['clarifications'][key] = record
                    Driver.validate_state(state)  # Outcomes and timestamps are otherwise valid.
                    first, second = state['clarifications'].values()
                    if first_mode == 'pending':
                        duplicate = second['message']['id'] if second_mode == 'pending' else '106'
                        first['message']['id'] = duplicate
                    elif second_mode == 'pending':
                        second['message']['id'] = '105'
                    else:
                        field = 'dismissal' if second_mode == 'dismissed' else 'selection'
                        second[field]['id'] = '105'
                        second['result'][field + '_message_id'] = '105'
                    with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                        Driver.validate_state(state)

    def test_malformed_dismissed_audit_is_rejected_not_treated_as_release(self):
        runtime, history, drafts, now, hold, args = self.pending()
        runtime.dismiss_clarification(**args, history_plan=history_request(runtime, 'dismiss_clarification', **args))
        state = runtime.status()
        for identifier in (105, 'not-an-id'):
            invalid = copy.deepcopy(state)
            record = invalid['clarifications'][hold['id']]
            record['dismissal']['id'] = identifier
            record['result']['dismissal_message_id'] = identifier
            with self.subTest(identifier=identifier), self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                Driver.validate_state(invalid)

    def test_published_dismissal_contract_and_native_instruction(self):
        root = fixtures.fixtures.SCRIPTS.parents[2]
        skill = (root / 'skills/task-coach/SKILL.md').read_text()
        guide = (root / 'skills/task-coach/references/native-runtime.md').read_text()
        readme = (root / 'README.md').read_text()
        runtime, history, drafts, now = self.fixture()
        instruction = runtime.native_plan('/fictional/profile', python='/usr/bin/python3',
            helper='/fictional/helper', hermes='/fictional/hermes')['inbound_instruction']
        for text in (guide,):
            for token in ('dismiss-clarification', '--dismissal-message-id', 'never mind',
                          'dismiss that question', 'cancel', 'resolving'):
                self.assertIn(token, text)
        self.assertIn('resolution/dismissal', skill)
        self.assertIn('bounded history plan', skill)
        self.assertIn('immutable clarification outcomes', instruction)
        self.assertIn('--history-plan-file', instruction)
        self.assertIn('dismiss-clarification', readme)
        self.assertNotIn('hold-discard command is provided', guide)

    def test_cli_dismissal_is_immutable_idempotent_and_never_engages_or_reasks(self):
        runtime, history, drafts, now, hold, args = self.pending()
        before = runtime.coach.status(), self.cli('list'), runtime.status()['outbox']
        path = self.data.parent / 'dismissal-pages.json'
        path.write_text(json.dumps(args['pages']))
        with patch('task_coach.driver.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat(now)
            result = self.cli('runtime', *history_cli(runtime, 'dismiss-clarification', '--binding', json.dumps(BINDING),
                '--clarification-id', hold['id'], '--dismissal-message-id', '105', '--pages-file', str(path)))
        self.assertEqual(result, dict(dismissed=True, engaged=False, clarification_id=hold['id'],
            original_message_id='104', dismissal_message_id='105', provenance='explicit-owner-dismissal'))
        stored = runtime.status()['clarifications'][hold['id']]
        self.assertEqual(stored['state'], 'dismissed')
        self.assertEqual(stored['message'], hold['message'])
        self.assertEqual(stored['candidates'], hold['candidates'])
        self.assertEqual(stored['dismissal'], history[0])
        self.assertEqual(Driver(self.data).dismiss_clarification(**dict(args, pages=self.pages(history, now)), history_plan=history_request(Driver(self.data), 'dismiss_clarification', **dict(args, pages=self.pages(history, now)))), result)
        import subprocess
        # A restarted real parser must reauthorize and recapture the unchanged
        # owner dismissal; completed audits remain immutable.
        retried = subprocess.run(fictional_clock_command([sys.executable, '-I', '-B',
            str(fixtures.fixtures.SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data),
            'runtime', *history_cli(runtime, 'dismiss-clarification', '--binding', json.dumps(BINDING),
            '--clarification-id', hold['id'], '--dismissal-message-id', '105',
            '--pages-file', str(path))], now), capture_output=True, text=True, timeout=15)
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(json.loads(retried.stdout), result)
        self.assertEqual(runtime.pending_clarifications(BINDING), [])
        # Replays, including changed originals, must not ask again or engage tasks.
        history[1]['content'] = 'Edited original after dismissal'
        again = runtime.engagement(BINDING, self.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))
        self.assertFalse(again['engaged'])
        self.assertIsNone(again['error'])
        self.assertEqual((runtime.coach.status(), self.cli('list'), runtime.status()['outbox']), before)
        self.assertEqual(runtime.status()['clarifications'][hold['id']], stored)
        history.insert(0, self.message('106', now, 'A different dismissal'))
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            runtime.dismiss_clarification(**dict(args, dismissal_message_id='106', pages=self.pages(history, now)), history_plan=history_request(runtime, 'dismiss_clarification', dismissal_message_id='106'))
        with self.assertRaisesRegex(ValueError, 'dismissed|conflicting'):
            runtime.resolve_clarification(binding=BINDING, clarification_id=hold['id'],
                task_id=drafts[0]['task']['id'], selection_message_id='105', pages=args['pages'], now=now, history_plan=history_request(runtime, 'resolve_clarification', selection_message_id='105'))
