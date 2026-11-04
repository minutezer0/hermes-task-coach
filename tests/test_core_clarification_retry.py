"""Vertical native-protocol tests; all stores and senders are synthetic."""
import copy
from datetime import datetime, timedelta
import json
import sys
from unittest.mock import patch

from test_core_clarification import ClarificationTest
from test_core_driver import BINDING
from task_coach.coaching import instant
from task_coach.driver import Driver


class RetryTest(ClarificationTest):
    # Reuse fixtures, not the parent's tests (see load_tests below).
    def held(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now, 'That one'))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        return runtime, history, drafts, now, pending

    def at_cli(self, now, *args):
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return instant(now).astimezone(tz)
        with patch('task_coach.driver.datetime', Clock):
            return self.cli('runtime', *args)

    def test_zero_budget_legacy_hold_is_retained_after_automatic_adoption(self):
        self.cli('setup', '--update', '--max-unanswered-followups', '0', '--weekdays', 'mon,tue,wed,thu,fri')
        runtime, history, drafts, now, pending = self.held()
        tasks = self.cli('list')
        before = runtime.coach.status()
        for when in (now, '2030-01-08T00:00:00Z', '2030-01-08T08:59:00Z'):
            self.assertFalse(runtime.preflight(now=when)['wakeAgent'])
            self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
            if when == now:
                self.assertEqual(runtime.coach.status(), before)
        runtime.preflight(now='2030-01-08T09:00:00Z')
        retired = runtime.status()['clarifications'][pending['id']]
        self.assertEqual(retired, pending)  # Adoption preserves the old hold verbatim.
        self.assertEqual(retired['message'], pending['message'])
        self.assertEqual(retired['candidates'], pending['candidates'])
        self.assertEqual(self.cli('list'), tasks)
        self.assertEqual(runtime.pending_clarifications(BINDING), [pending])
        again = runtime.engagement(BINDING, self.pages(history, '2030-01-08T09:00:00Z'), now='2030-01-08T09:00:00Z')
        self.assertFalse(again['engaged'])
        self.assertEqual(len(runtime.status()['clarifications']), 1)
        with self.assertRaises(ValueError):
            runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'], selection_message_id='105', pages=[], now='2030-01-08T09:00:00Z')

    def test_fresh_owner_reply_to_retry_routes_question_and_blocks_further_retry(self):
        self.test_retry_traverses_real_cli_draft_history_sender_and_receipt()
        runtime = Driver(self.data)
        retry = next(r for r in runtime.status()['outbox'].values() if r['intent'].get('kind') == 'clarification')
        now = retry['receipt']['delivered_at']
        context = runtime.context(BINDING, reply_to_message_id='110')
        self.assertIsNone(context.get('task'))
        self.assertEqual(context['clarification_ids'], retry['intent']['clarification_ids'])
        history = [self.message('111', now, 'I mean that one', message_reference=dict(message_id='110', channel_id='123')),
                   self.message('110', now, retry['body'], bot=True)]
        before = runtime.coach.status(), self.cli('list')
        result = runtime.engagement(BINDING, self.pages(history, now), now=now,
                                    reply_to_message_id='110', inbound_message_id='111')
        self.assertFalse(result['engaged'])
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertEqual(len(result['clarifications']), 1)
        record = result['clarifications'][0]
        self.assertEqual([m['id'] for m in record['responses']], ['111'])
        self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        later = (instant(now) + timedelta(minutes=30)).isoformat()
        self.assertFalse(Driver(self.data).preflight(now=later)['wakeAgent'])
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][record['id']], record)
        again = runtime.engagement(BINDING, self.pages(history, '2030-01-08T09:00:00Z'), now='2030-01-08T09:00:00Z')
        self.assertFalse(again['engaged'])
        self.assertEqual(len(runtime.status()['clarifications']), 1)

    def test_retained_receipts_do_not_recreate_ambiguity_after_retirement(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.preflight(now='2030-01-08T09:00:00Z')
        history.insert(0, self.message('120', '2030-01-08T09:01:00Z', 'Hello again'))
        result = runtime.engagement(BINDING, self.pages(history, '2030-01-08T09:01:00Z'), now='2030-01-08T09:01:00Z')
        self.assertEqual(len(runtime.status()['clarifications']), 1)
        self.assertFalse(result['engaged'])
        self.assertIsNone(runtime.context(BINDING))

    def test_clock_regression_is_durable_and_cannot_be_cleared_by_rollover(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.preflight(now=now)
        backwards = (instant(now) - timedelta(minutes=1)).isoformat()
        self.assertFalse(runtime.preflight(now=backwards)['wakeAgent'])
        self.assertFalse(runtime.preflight(now='2030-01-08T09:00:00Z')['wakeAgent'])
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        self.assertEqual(runtime.status()['clarification_retry']['safety_block'], 'clock-regressed')

    def test_retry_spacing_uses_actual_receipt_and_never_catches_up(self):
        self.test_retry_traverses_real_cli_draft_history_sender_and_receipt()
        runtime = Driver(self.data)
        cycle = runtime.status()['clarification_retry']
        first = cycle['events'][0]
        # Model a valid late positive receipt: the first send took thirty seconds.
        with runtime.transaction() as state:
            row = state['outbox'][first['token']]
            row['receipt']['delivered_at'] = (instant(first['slot']) + timedelta(seconds=30)).isoformat()
        second = cycle['events'][1]
        self.assertFalse(runtime.preflight(now=second['slot'])['wakeAgent'], 'must not violate actual min spacing')
        expired = (instant(second['expires']) + timedelta(minutes=1)).isoformat()
        self.assertFalse(runtime.preflight(now=expired)['wakeAgent'])
        self.assertEqual(runtime.status()['clarification_retry']['events'][1]['state'], 'missed')

    def test_multiple_legacy_holds_share_budget_and_preserve_remaining_after_rollover(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        self.assertEqual(len(held), 2)
        due = (instant(now) + timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        self.assertEqual(set(offered['intent']['clarification_ids']), {c['id'] for c in held})
        history.insert(0, self.message('106', due, 'Dismiss the first question'))
        runtime.dismiss_clarification(binding=BINDING, clarification_id=held[0]['id'], dismissal_message_id='106', pages=self.pages(history, due), now=due)
        runtime.preflight(now='2030-01-08T09:00:00Z')
        states = {c['state'] for c in runtime.status()['clarifications'].values()}
        self.assertEqual(states, {'dismissed', 'pending'})  # New-day adoption preserves legacy audit.
        self.assertEqual(len(runtime.status()['clarification_retry']['events']), 2)

    def test_legacy_upgrade_is_deterministic_and_does_not_invent_receipts(self):
        import shutil
        runtime, history, drafts, now, pending = self.held()
        self.assertNotIn('clarification_retry', runtime.status())
        self.cli('setup', '--update', '--min-followup-interval', '10', '--max-followup-interval', '40')
        # Upgrade uses only an unchanged saved configuration; give this legacy
        # fixture its matching historical snapshot rather than bypassing guards.
        with runtime.coach.transaction() as engine:
            for sequence in [engine['episode']] + engine['episode']['next_tasks']:
                sequence['config'] = runtime.coach.config()
        clone = self.data.parent / 'legacy-clone'
        shutil.copytree(self.data, clone)
        runtime.preflight(now=now)
        Driver(clone).preflight(now=now)
        self.assertEqual(runtime.status()['clarification_retry'], Driver(clone).status()['clarification_retry'])
        self.assertEqual(len(runtime.status()['outbox']), len(drafts))
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['message'], pending['message'])

    def retry_draft(self):
        runtime, history, drafts, now, pending = self.held()
        due = (instant(now) + timedelta(minutes=30)).isoformat()
        prepared = runtime.preflight(now=due)
        draft = runtime.draft(prepared['intent']['event_token'], 'Which task: Synthetic task or Second fictional task?', now=due)
        return runtime, history, drafts, due, pending, draft

    def test_every_candidate_receipt_needs_raw_bot_readback(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        history[1]['author']['id'] = 'wrong-bot'
        with self.assertRaisesRegex(ValueError, 'candidate'):
            runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        self.assertIsNone(runtime.row(draft['token'], draft['fence'])['evidence'])

    def test_invalid_history_and_stale_evidence_never_send(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        captures = [[], self.pages(history[:-1], due)]
        for mutation in ('route', 'owner', 'bot', 'stale'):
            pages = self.pages(history, due)
            if mutation == 'route':
                pages[0]['channel_id'] = '999'
            elif mutation == 'owner':
                pages[0]['result']['messages'][0]['author']['id'] = 'stranger'
            elif mutation == 'bot':
                pages[0]['result']['messages'][-1]['author']['bot'] = False
            else:
                pages[0]['observed_at'] = (instant(due)-timedelta(seconds=61)).isoformat()
            captures.append(pages)
        for pages in captures:
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                runtime.observe(draft['token'], draft['fence'], pages, now=due)
            self.assertIsNone(runtime.row(draft['token'], draft['fence'])['evidence'])
        sent = runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('uncertain', sent)
        self.assertNotEqual(runtime.preflight(now='2030-01-08T09:00:00Z').get('reason'), 'unconfirmed-delivery')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')

    def test_new_owner_history_blocks_retry_without_engaging_tasks(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        before = runtime.coach.status(), self.cli('list')
        history.insert(0, self.message('105', due, 'The first task'))
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        self.assertFalse(evidence['complete'])
        with self.assertRaises(ValueError):
            runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'draft')
        self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        args = dict(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'],
                    selection_message_id='105', pages=self.pages(history, due), now=due)
        chosen = runtime.resolve_clarification(**args)
        self.assertEqual(Driver(self.data).resolve_clarification(**args), chosen)
        self.assertEqual(chosen['context']['task_id'], drafts[0]['task']['id'])

    def test_final_boundary_dismissal_blocks_stale_retry(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        test = self
        class Racing(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                history.insert(0, test.message('105', due, 'Never mind'))
                Driver(test.data).dismiss_clarification(binding=BINDING, clarification_id=pending['id'],
                    dismissal_message_id='105', pages=test.pages(history, due), now=due)
        sent = Racing(self.data).dispatch(draft['token'], draft['fence'], hermes=str(self.data.parent / 'sender'), now=due)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('uncertain', sent)
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'dismissed')

    def test_uncertain_retry_recovers_late_receipt_without_resending_or_engaging(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        sent = runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        self.assertEqual(sent['state'], 'sending')
        later = '2030-01-08T09:00:00Z'
        self.assertNotEqual(runtime.preflight(now=later).get('reason'), 'unconfirmed-delivery')
        history.insert(0, self.message('110', due, draft['body'], bot=True))
        before = runtime.coach.status(), self.cli('list')
        receipt = Driver(self.data).confirm(draft['token'], draft['fence'], self.pages(history, later), now=later, message_id='110')
        self.assertEqual(receipt['message_id'], '110')
        self.assertEqual(Driver(self.data).confirm(draft['token'], draft['fence'], [], now=later), receipt)
        self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        with self.assertRaises(ValueError):
            runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=later)
        runtime.preflight(now=later)
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')  # Immutable legacy audit after rollover.

    def test_legacy_audit_survives_later_weekend_and_dst_windows(self):
        self.cli('setup', '--update', '--timezone', 'America/New_York', '--weekdays', 'mon,tue,wed,thu,fri')
        runtime, history, drafts, now = self.fixture()
        friday = '2030-03-08T21:00:00Z'
        history.insert(0, self.message('104', friday, 'That one'))
        pending = runtime.engagement(BINDING, self.pages(history, friday), now=friday)['clarifications'][0]
        for when in (friday, '2030-03-09T14:00:00Z', '2030-03-10T13:00:00Z', '2030-03-11T12:59:00Z'):
            runtime.preflight(now=when)
            self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        runtime.preflight(now='2030-03-11T13:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')  # Immutable legacy audit after rollover.

    def test_safety_blocks_and_pause_survive_next_window(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.preflight(now=now)
        runtime.coach.pause(True)
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        self.assertTrue(runtime.coach.status()['paused'])
        self.assertEqual(runtime.coach.status()['episode']['window_stopped'], 'paused')
        runtime.coach.pause(False)
        runtime.preflight(now='2030-01-09T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')

    def test_non_minute_original_keeps_real_interval_without_rounding_early(self):
        runtime, history, drafts, now = self.fixture()
        original_time = (instant(now) + timedelta(seconds=20)).isoformat()
        history.insert(0, self.message('104', original_time, 'That one'))
        runtime.engagement(BINDING, self.pages(history, original_time), now=original_time)
        due = (instant(original_time) + timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        self.assertTrue(offered['wakeAgent'])
        cycle = runtime.status()['clarification_retry']
        self.assertEqual(instant(cycle['events'][0]['slot']), instant(due))

    def test_retry_budget_exhaustion_keeps_legacy_audit_after_rollover(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        before = runtime.coach.status(), self.cli('list')
        for index in range(2):
            if index:
                due = runtime.status()['clarification_retry']['events'][index]['slot']
                offered = runtime.preflight(now=due)
                draft = runtime.draft(offered['intent']['event_token'], 'Which of the two tasks?', now=due)
            runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
            sender = self.data.parent / 'budget-sender'
            identifier = str(110 + index)
            sender.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(dict(success=True, message_id=identifier))) + ')\n')
            sender.chmod(0o700)
            sent = runtime.dispatch(draft['token'], draft['fence'], hermes=str(sender), now=due)
            self.assertEqual(sent['candidate_id'], identifier)
            history.insert(0, self.message(identifier, due, draft['body'], bot=True))
            runtime.confirm(draft['token'], draft['fence'], self.pages(history, due), now=due)
        later = (instant(due)+timedelta(minutes=30)).isoformat()
        self.assertFalse(Driver(self.data).preflight(now=later)['wakeAgent'])
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        self.assertEqual(sum(r['intent'].get('kind') == 'clarification' for r in runtime.status()['outbox'].values()), 2)
        self.assertEqual((runtime.coach.status(), self.cli('list')), before)
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')  # Immutable legacy audit after rollover.

    def test_resolved_and_resolving_are_immune_to_retirement(self):
        runtime, history, drafts, now, pending = self.held()
        history.insert(0, self.message('105', now, 'First task'))
        chosen = runtime.resolve_clarification(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'], selection_message_id='105', pages=self.pages(history, now), now=now)
        record = runtime.status()['clarifications'][pending['id']]
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']], record)
        # A valid write-ahead record is an old interrupted selection, not pending.
        with runtime.transaction() as state:
            state['clarifications'][pending['id']]['state'] = 'resolving'
        runtime.preflight(now='2030-01-09T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'resolving')

    def test_configuration_change_is_not_bypassed_by_rollover(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.preflight(now=now)
        self.cli('setup', '--update', '--timezone', 'America/New_York')
        runtime.preflight(now=now)
        self.assertEqual(runtime.status()['clarification_retry']['safety_block'], 'configuration-changed')
        self.cli('setup', '--update', '--timezone', 'UTC')
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        with self.assertRaises(ValueError):
            runtime.configure(dict(runtime.status()['route'], bot_id='999'), confirm=True)

    def test_retry_response_identity_cannot_be_reused_for_a_different_hold(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which task?', now=due)
        history.insert(0, self.message('106', due, 'The first question'))
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        records = runtime.status()['clarifications']
        self.assertFalse(any(c.get('responses') for c in records.values()))
        newer = next(c for c in records.values() if c['message']['id'] == '105')
        older = next(c for c in records.values() if c['message']['id'] == '104')
        args = dict(binding=BINDING, clarification_id=newer['id'], dismissal_message_id='106', pages=self.pages(history, due), now=due)
        result = Driver(self.data).dismiss_clarification(**args)
        self.assertEqual(Driver(self.data).dismiss_clarification(**args), result)
        with self.assertRaisesRegex(ValueError, 'already belongs'):
            runtime.dismiss_clarification(**dict(args, clarification_id=older['id']))
        Driver.validate_state(runtime.status())

    def trusted_shared_reply(self, *, resolve):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        due = (instant(now) + timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which question and task?', now=due)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        history.insert(0, self.message('110', due, draft['body'], bot=True))
        runtime.confirm(draft['token'], draft['fence'], self.pages(history, due), now=due, message_id='110')
        history.insert(0, self.message('111', due, 'For the newer question: first task'))
        capture = self.data.parent / 'trusted-shared-pages.json'
        pages = self.pages(history, due)
        capture.write_text(json.dumps(pages))
        result = self.at_cli(due, 'engagement', '--binding', json.dumps(BINDING),
                             '--reply-to-message-id', '110', '--inbound-message-id', '111',
                             '--pages-file', str(capture))
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertNotIn('message_reference', history[0])
        self.assertEqual(json.loads(capture.read_text()), pages)
        before = Driver(self.data).status()
        newer = next(c for c in held if c['message']['id'] == '105')
        older = next(c for c in held if c['message']['id'] == '104')
        args = dict(binding=BINDING, clarification_id=newer['id'], pages=pages, now=due)
        if resolve:
            args.update(task_id=drafts[0]['task']['id'], selection_message_id='111')
            method, command, flag = 'resolve_clarification', 'resolve-clarification', '--selection-message-id'
        else:
            args.update(dismissal_message_id='111')
            method, command, flag = 'dismiss_clarification', 'dismiss-clarification', '--dismissal-message-id'
        for mutation in ('id', 'content', 'author', 'bot', 'attachments', 'timestamp', 'reference'):
            changed = copy.deepcopy(pages)
            message = changed[0]['result']['messages'][0]
            if mutation == 'id':
                message['id'] = '112'
            elif mutation == 'content':
                message['content'] += ' edited'
            elif mutation == 'author':
                message['author']['id'] = 'stranger'
            elif mutation == 'bot':
                message['author']['bot'] = True
            elif mutation == 'attachments':
                message['attachments'] = [dict(id='901', filename='changed.txt')]
            elif mutation == 'timestamp':
                message['timestamp'] = (instant(due) - timedelta(seconds=1)).isoformat()
            else:
                message['message_reference'] = dict(message_id='100', channel_id='123')
            with self.subTest(resolve=resolve, mutation=mutation), self.assertRaises(ValueError):
                getattr(Driver(self.data), method)(**dict(args, pages=changed))
            self.assertEqual(Driver(self.data).status(), before)
        conflicting = copy.deepcopy(pages)
        conflicting[0]['result']['messages'][0]['message_reference'] = dict(message_id='100', channel_id='123')
        with self.assertRaisesRegex(ValueError, 'conflicting reply target'):
            Driver(self.data).engagement(BINDING, conflicting, now=due,
                                         reply_to_message_id='110', inbound_message_id='111')
        cli_args = [command, '--binding', json.dumps(BINDING), '--clarification-id', newer['id'],
                    flag, '111', '--pages-file', str(capture)]
        if resolve:
            cli_args += ['--task-id', str(drafts[0]['task']['id'])]
        chosen = self.at_cli(due, *cli_args)
        self.assertTrue(chosen['engaged' if resolve else 'dismissed'])
        self.assertEqual(getattr(Driver(self.data), method)(**dict(args, pages=[])), chosen)
        self.assertEqual(self.at_cli(due, *cli_args), chosen)
        for other_method, extra in (('resolve_clarification', dict(task_id=drafts[0]['task']['id'], selection_message_id='111')),
                                    ('dismiss_clarification', dict(dismissal_message_id='111'))):
            with self.assertRaisesRegex(ValueError, 'already belongs'):
                getattr(Driver(self.data), other_method)(binding=BINDING, clarification_id=older['id'],
                                                         pages=pages, now=due, **extra)
        state = Driver(self.data).status()
        self.assertEqual(state['clarifications'][newer['id']]['selection' if resolve else 'dismissal'], history[0])
        self.assertEqual(state['clarifications'][older['id']]['state'], 'pending')
        self.assertEqual(state['clarification_responses'], [])
        self.assertEqual(state['outbox'], before['outbox'])
        self.assertEqual(state['clarification_retry'], before['clarification_retry'])
        Driver.validate_state(state)

    def test_trusted_cli_shared_reply_selects_newer_hold_with_unchanged_raw_history(self):
        self.trusted_shared_reply(resolve=True)

    def test_trusted_cli_shared_reply_dismisses_newer_hold_with_unchanged_raw_history(self):
        self.trusted_shared_reply(resolve=False)

    def single_hold_response(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.preflight(now=now)
        due = (instant(now) + timedelta(minutes=30)).isoformat()
        history.insert(0, self.message('105', due, 'First task'))
        runtime.engagement(BINDING, self.pages(history, due), now=due)
        record = runtime.status()['clarifications'][pending['id']]
        self.assertEqual(record['responses'], [history[0]])
        self.assertNotIn('message_reference', record['responses'][0])
        return runtime, history, drafts, due, pending

    def response_cli_args(self, pending, drafts, capture, *, resolve):
        args = ['resolve-clarification' if resolve else 'dismiss-clarification',
                '--binding', json.dumps(BINDING), '--clarification-id', pending['id'],
                '--selection-message-id' if resolve else '--dismissal-message-id', '105',
                '--pages-file', str(capture)]
        if resolve:
            args += ['--task-id', str(drafts[0]['task']['id'])]
        return args

    def single_hold_mutations(self, *, resolve):
        import contextlib
        import io
        import shutil
        from task_coach.cli import main
        runtime, history, drafts, due, pending = self.single_hold_response()
        original = self.data
        for mutation in ('content', 'attachments', 'timestamp', 'reference'):
            with self.subTest(resolve=resolve, mutation=mutation):
                self.data = original.parent / ('single-' + mutation)
                shutil.copytree(original, self.data)
                changed = copy.deepcopy(history)
                if mutation == 'content':
                    changed[0]['content'] += ' edited'
                elif mutation == 'attachments':
                    changed[0]['attachments'] = [dict(id='901', filename='changed.txt')]
                elif mutation == 'timestamp':
                    changed[0]['timestamp'] = (instant(due) - timedelta(seconds=1)).isoformat()
                else:
                    changed[0]['message_reference'] = dict(message_id='100', channel_id='123')
                capture = original.parent / ('single-' + mutation + '.json')
                capture.write_text(json.dumps(self.pages(changed, due)))
                args = self.response_cli_args(pending, drafts, capture, resolve=resolve)
                state = Driver(self.data).status()
                engine = Driver(self.data).coach.status()
                tasks = self.cli('list')
                before = (self.data / 'outbox.sqlite3').read_bytes()
                def raw_cli(*argv):
                    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                        return main(['--data-dir', str(self.data), *argv])
                with patch.object(self, 'cli', raw_cli):
                    result = self.at_cli(due, *args)
                self.assertEqual(result, 2, 'contradictory captured response must be rejected')
                self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
                self.assertEqual(Driver(self.data).status(), state)
                self.assertEqual(Driver(self.data).coach.status(), engine)
                self.assertEqual(self.cli('list'), tasks)
        self.data = original

    def test_single_hold_cli_selection_rejects_mutated_captured_response(self):
        self.single_hold_mutations(resolve=True)

    def test_single_hold_cli_dismissal_rejects_mutated_captured_response(self):
        self.single_hold_mutations(resolve=False)

    def single_hold_outcome(self, *, resolve):
        runtime, history, drafts, due, pending = self.single_hold_response()
        capture = self.data.parent / 'single-valid.json'
        capture.write_text(json.dumps(self.pages(history, due)))
        args = self.response_cli_args(pending, drafts, capture, resolve=resolve)
        result = self.at_cli(due, *args)
        self.assertTrue(result['engaged' if resolve else 'dismissed'])
        self.assertEqual(self.at_cli(due, *args), result)
        method = 'resolve_clarification' if resolve else 'dismiss_clarification'
        extra = dict(task_id=drafts[0]['task']['id'], selection_message_id='105') if resolve else dict(dismissal_message_id='105')
        self.assertEqual(getattr(Driver(self.data), method)(binding=BINDING, clarification_id=pending['id'],
                         pages=[], now=due, **extra), result)
        valid = Driver(self.data).status()
        field = 'selection' if resolve else 'dismissal'
        record = valid['clarifications'][pending['id']]
        self.assertEqual(record['responses'], [record[field]])
        Driver.validate_state(valid)
        for mutation in ('content', 'attachments', 'timestamp', 'reference'):
            with self.subTest(resolve=resolve, mutation=mutation):
                state = copy.deepcopy(valid)
                response = state['clarifications'][pending['id']]['responses'][0]
                if mutation == 'content':
                    response['content'] += ' edited'
                elif mutation == 'attachments':
                    response['attachments'] = [dict(id='901', filename='changed.txt')]
                elif mutation == 'timestamp':
                    response['timestamp'] = (instant(due) - timedelta(seconds=1)).isoformat()
                else:
                    response['message_reference'] = dict(message_id='100', channel_id='123')
                with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                    Driver.validate_state(state)
                from contextlib import closing
                import sqlite3
                with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
                    db.execute('UPDATE runtime SET value=? WHERE id=1', (json.dumps(state),))
                    db.commit()
                persisted = (self.data / 'outbox.sqlite3').read_bytes()
                with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                    Driver(self.data).status()
                self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), persisted)
                if resolve:
                    state['clarifications'][pending['id']]['state'] = 'resolving'
                    with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                        Driver.validate_state(state)

    def test_single_hold_selection_duplicate_identity_is_exact_and_restart_idempotent(self):
        self.single_hold_outcome(resolve=True)

    def test_single_hold_dismissal_duplicate_identity_is_exact_and_restart_idempotent(self):
        self.single_hold_outcome(resolve=False)

    def test_engine_claim_crash_gap_blocks_retry_and_retirement(self):
        runtime, history, drafts, now = self.fixture()
        event = runtime.coach.status()['episode']['next_tasks'][0]['events'][1]
        when = event['slot']
        draft = runtime.draft(event['token'], 'Unconfirmed ordinary followup', now=when)
        evidence = runtime.observe(draft['token'], draft['fence'], self.pages(history, when), now=when)
        claimed = runtime.coach.tick(now=when, binding=BINDING, evidence=evidence, expected_token=event['token'])
        self.assertTrue(claimed['wakeAgent'])
        history.insert(0, self.message('104', when, 'That one'))
        pending = runtime.engagement(BINDING, self.pages(history, when), now=when)['clarifications'][0]
        engine = runtime.coach.status()
        for due in ((instant(when)+timedelta(minutes=30)).isoformat(),):
            self.assertFalse(runtime.preflight(now=due)['wakeAgent'])
            self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
        self.assertEqual(runtime.coach.status(), engine)
        self.assertEqual(runtime.status()['outbox'][draft['token']]['state'], 'draft')

    def test_engine_claim_at_final_boundary_blocks_retry_sender(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        class Racing(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                with self.coach.transaction() as engine:
                    event = engine['episode']['next_tasks'][0]['events'][1]
                    event.update(state='claimed', claimed_at=event['slot'])
                    engine['evidence_ids'].append('synthetic-racing-claim')
        with patch('task_coach.driver.subprocess.run') as sender:
            sender.return_value.stdout = json.dumps(dict(success=True, message_id='110'))
            sender.return_value.returncode = 0
            sent = Racing(self.data).dispatch(draft['token'], draft['fence'], hermes='/synthetic', now=due)
        self.assertFalse(sender.called)
        self.assertIn('clarification retry authorization changed', sent.get('uncertain', ''))
        self.assertNotEqual(runtime.preflight(now='2030-01-08T09:00:00Z').get('reason'), 'unconfirmed-delivery')

    def test_first_local_first_rollover_offers_new_slot_without_modifying_legacy_hold(self):
        runtime, history, drafts, now, pending = self.held()
        runtime.coach.rng.choice = lambda values: values[0]
        first = runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertTrue(first['wakeAgent'])
        self.assertEqual(runtime.status()['clarifications'][pending['id']], pending)
        self.assertEqual(runtime.preflight(now='2030-01-08T09:00:00Z'), first)

    def test_present_null_cycle_is_invalid_but_absent_is_legacy(self):
        runtime, history, drafts, now, pending = self.held()
        state = runtime.status()
        Driver.validate_state(state)
        state['clarification_retry'] = None
        with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
            Driver.validate_state(state)

    def test_boolean_cycle_event_index_is_invalid(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        state = runtime.status()
        state['clarification_retry']['events'][0]['index'] = False
        with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
            Driver.validate_state(state)

    def test_cycle_claim_and_outbox_attempt_must_agree(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        valid = runtime.status()
        mutations = ('orphan-claim', 'attempt-without-claim', 'index', 'expires', 'task-anchor')
        for mutation in mutations:
            state = copy.deepcopy(valid)
            row = state['outbox'][draft['token']]
            if mutation == 'orphan-claim':
                state['clarification_retry']['events'][0]['state'] = 'claimed'
                del state['outbox'][draft['token']]
            elif mutation == 'attempt-without-claim':
                row.update(state='sending', attempted_at=due)
            elif mutation == 'index':
                row['intent']['index'] = 1
            elif mutation == 'expires':
                row['intent']['expires'] = (instant(due)+timedelta(minutes=2)).isoformat()
            else:
                row['previous'] = dict(row['previous'], token=drafts[1]['token'])
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                Driver.validate_state(state)

    def test_shared_quarantine_is_strictly_validated(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which task?', now=due)
        history.insert(0, self.message('106', due, 'Newer question'))
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        valid = runtime.status()
        for mutation in ('duplicate', 'unknown', 'consumed', 'author', 'timestamp', 'null'):
            state = copy.deepcopy(valid)
            entry = state['clarification_responses'][0]
            if mutation == 'duplicate':
                state['clarification_responses'].append(copy.deepcopy(entry))
            elif mutation == 'unknown':
                entry['ids'] = ['unknown']
            elif mutation == 'consumed':
                state['clarifications'][held[0]['id']]['responses'] = [entry['message']]
            elif mutation == 'author':
                entry['message']['author']['bot'] = True
            elif mutation == 'timestamp':
                entry['message']['timestamp'] = '2029-01-01T00:00:00Z'
            else:
                state['clarification_responses'] = None
            with self.subTest(mutation=mutation), self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                Driver.validate_state(state)

    def test_shared_reply_before_cycle_creation_survives_retirement(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        history.insert(0, self.message('106', now, 'Newer question'))
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        self.assertEqual([r['message']['id'] for r in runtime.status().get('clarification_responses', [])], ['106'])
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        self.assertFalse(runtime.preflight(now=due)['wakeAgent'])
        later = '2030-01-08T09:00:00Z'
        runtime.preflight(now=later)
        self.assertFalse(runtime.engagement(BINDING, self.pages(history, later), now=later)['engaged'])
        self.assertEqual(len(runtime.status()['clarifications']), 2)

    def test_shared_confirm_and_engagement_do_not_preassign_later_selection(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which task?', now=due)
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        history[:0] = [self.message('111', due, 'Newer question, first task'), self.message('110', due, draft['body'], bot=True)]
        runtime.engagement(BINDING, self.pages(history, due), now=due)
        Driver(self.data).confirm(draft['token'], draft['fence'], self.pages(history, due), now=due, message_id='110')
        newer = next(c for c in held if c['message']['id'] == '105')
        args = dict(binding=BINDING, clarification_id=newer['id'], task_id=drafts[0]['task']['id'],
                    selection_message_id='111', pages=self.pages(history, due), now=due)
        chosen = runtime.resolve_clarification(**args)
        self.assertEqual(Driver(self.data).resolve_clarification(**args), chosen)
        older = next(c for c in held if c['message']['id'] == '104')
        with self.assertRaisesRegex(ValueError, 'already belongs'):
            runtime.resolve_clarification(**dict(args, clarification_id=older['id']))
        self.assertNotIn('111', [r['message']['id'] for r in runtime.status()['clarification_responses']])

    def test_legacy_engine_uncertainty_without_outbox_attempt_never_retires(self):
        from task_coach.coaching import sequences
        runtime, history, drafts, now, pending = self.held()
        for sequence_index in (0, 1):
            for event_state in ('claimed', 'failed'):
                with self.subTest(sequence=sequence_index, state=event_state):
                    with runtime.coach.transaction() as engine:
                        for sequence in sequences(engine['episode']):
                            for event in sequence['events'][1:]:
                                event.update(state='planned', receipt=None)
                                event.pop('claimed_at', None)
                        sequence = sequences(engine['episode'])[sequence_index]
                        event = sequence['events'][1]
                        event.update(state=event_state, claimed_at=event['slot'])
                        sequence['stopped'] = 'owner-engaged'  # a safe stop must not hide uncertainty
                        engine['evidence_ids'] = ['synthetic-legacy-claim']
                    before = runtime.coach.status()
                    self.assertEqual(Driver(self.data).preflight(now=(instant(now)+timedelta(minutes=30)).isoformat())['reason'], 'unconfirmed-delivery')
                    self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')
                    self.assertEqual(runtime.coach.status(), before)

    def test_shared_draft_hold_identity_cannot_be_silently_narrowed(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        due = (instant(now)+timedelta(minutes=30)).isoformat()
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which task?', now=due)
        state = runtime.status()
        state['outbox'][draft['token']]['intent']['clarification_ids'] = offered['intent']['clarification_ids'][:1]
        with self.assertRaisesRegex(ValueError, 'invalid runtime state'):
            Driver.validate_state(state)

    def subprocess_workers(self, sources):
        import subprocess
        from test_core_coaching import SCRIPTS
        workers = []
        try:
            for source in sources:
                code = 'import sys,json\nsys.path.insert(0, ' + repr(str(SCRIPTS)) + ')\nfrom task_coach.driver import Driver\nprint("ready",flush=True)\nsys.stdin.readline()\n' + source
                worker = subprocess.Popen([sys.executable, '-B', '-c', code], stdin=subprocess.PIPE,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                workers.append(worker)
            for worker in workers:
                self.assertEqual(worker.stdout.readline().strip(), 'ready')
            for worker in workers:
                worker.stdin.write('go\n')
                worker.stdin.flush()
            results = []
            for worker in workers:
                stdout, stderr = worker.communicate(timeout=30)
                self.assertEqual(worker.returncode, 0, stderr)
                results.append(json.loads(stdout))
            return results
        finally:
            for worker in workers:
                if worker.poll() is None:
                    worker.kill()
                worker.communicate()

    def test_subprocess_dispatch_contention_sends_only_once(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        sender = self.data.parent / 'contention-sender'
        marker = self.data.parent / 'synthetic-sends'
        sender.write_text('#!' + sys.executable + '\nwith open(' + repr(str(marker)) + ', "a") as f: f.write("send\\n")\nprint(\'{"success":true,"message_id":"110"}\')\n')
        sender.chmod(0o700)
        source = ('try:\n r=Driver(' + repr(str(self.data)) + ').dispatch(' + repr(draft['token']) + ', ' + repr(draft['fence']) + ', hermes=' + repr(str(sender)) + ', now=' + repr(due) + ')\n print(json.dumps(r))\nexcept ValueError as e:\n print(json.dumps({"refused":str(e)}))\n')
        results = self.subprocess_workers([source, source])
        self.assertEqual(marker.read_text(), 'send\n')
        self.assertEqual(sum('candidate_id' in r for r in results), 1)
        self.assertEqual(sum('refused' in r for r in results), 1)
        self.assertEqual(runtime.status()['outbox'][draft['token']]['state'], 'sending')

    def test_subprocess_shared_reply_binding_is_single_use(self):
        runtime, history, drafts, now = self.fixture()
        history[:0] = [self.message('105', now, 'Other one'), self.message('104', now, 'That one')]
        held = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications']
        history.insert(0, self.message('106', now, 'Dismiss that question'))
        runtime.engagement(BINDING, self.pages(history, now), now=now)
        sources = []
        for record in held:
            args = dict(binding=BINDING, clarification_id=record['id'], dismissal_message_id='106', pages=self.pages(history, now), now=now)
            sources.append('try:\n r=Driver(' + repr(str(self.data)) + ').dismiss_clarification(**' + repr(args) + ')\n print(json.dumps(r))\nexcept ValueError as e:\n print(json.dumps({"refused":str(e)}))\n')
        results = self.subprocess_workers(sources)
        self.assertEqual(sum(r.get('dismissed', False) for r in results), 1)
        self.assertEqual(sum('refused' in r for r in results), 1)
        self.assertEqual(sorted(c['state'] for c in runtime.status()['clarifications'].values()), ['dismissed', 'pending'])
        Driver.validate_state(runtime.status())

    def test_retry_slots_cross_real_dst_gap_and_fold_without_wall_clock_math(self):
        from types import SimpleNamespace
        from zoneinfo import ZoneInfo
        from task_coach import clarification
        from task_coach.coaching import window_minutes
        runtime, history, drafts, now, pending = self.held()
        config = dict(runtime.coach.config(), timezone='America/New_York', weekdays=['sun'],
                      notification_start='01:00', notification_end='04:00')
        driver = SimpleNamespace(coach=SimpleNamespace(config=lambda: config, tasks=runtime.coach.tasks))
        for start, due, wall in (('2030-03-10T06:45:00Z', '2030-03-10T07:15:00Z', '03:15'),
                                 ('2030-11-03T05:45:00Z', '2030-11-03T06:15:00Z', '01:15')):
            with self.subTest(start=start):
                state = copy.deepcopy(runtime.status())
                state['clarifications'][pending['id']]['message']['timestamp'] = start
                engine = dict(paused=False, last_tick=None, episode=dict(config=config, binding=BINDING, stopped=None, events=[]))
                offered = clarification.prepare(driver, state, engine, instant(due))
                self.assertTrue(offered['wakeAgent'])
                event = state['clarification_retry']['events'][0]
                self.assertEqual(instant(event['slot']), instant(due))
                self.assertEqual(instant(event['slot']).astimezone(ZoneInfo(config['timezone'])).strftime('%H:%M'), wall)
                slots = window_minutes(state['clarification_retry']['day'], config)
                self.assertIn(instant(due), slots)
                self.assertEqual(len(slots), 120 if '03-10' in start else 240)
                clarification.validate_cycle(state)

    def test_old_completed_cycle_without_intent_snapshot_remains_valid(self):
        self.test_retry_traverses_real_cli_draft_history_sender_and_receipt()
        runtime = Driver(self.data)
        from task_coach import clarification
        with runtime.transaction() as state:
            with runtime.coach._transaction() as engine:
                clarification.prepare(runtime, state, engine, instant('2030-01-08T09:00:00Z'))
        state = runtime.status()
        for event in state['clarification_retry']['events']:
            event.pop('intent', None)
        Driver.validate_state(state)
        del state['clarification_retry']
        Driver.validate_state(state)

    def test_sending_racing_preflight_snapshot_cannot_be_retired(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        data = self.data
        class Racing(Driver):
            def status(self):
                snapshot = super().status()
                with Driver(data).transaction() as state:
                    state['outbox'][draft['token']].update(state='sending', attempted_at=due)
                    state['clarification_retry']['events'][0]['state'] = 'claimed'
                return snapshot
        Racing(data).preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][pending['id']]['state'], 'pending')

    def test_before_window_legacy_question_survives_first_local_first_window(self):
        runtime, history, drafts, now = self.fixture()
        # Retained receipts can produce a normal-inbound hold before a later day's window.
        early = '2030-01-08T08:40:00Z'
        history.insert(0, self.message('104', early, 'That one'))
        record = runtime.engagement(BINDING, self.pages(history, early), now=early)['clarifications'][0]
        runtime.preflight(now=early)
        self.assertEqual(runtime.status()['clarifications'][record['id']]['state'], 'pending')
        runtime.preflight(now='2030-01-08T09:00:00Z')
        self.assertEqual(runtime.status()['clarifications'][record['id']], record)
        self.assertNotIn('clarification_retry', runtime.status())

    def test_confirmed_retry_quarantines_owner_reply_in_its_fresh_readback(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent', now=due)
        history[:0] = [self.message('111', due, 'The first task'), self.message('110', due, draft['body'], bot=True)]
        runtime.confirm(draft['token'], draft['fence'], self.pages(history, due), now=due, message_id='110')
        record = runtime.status()['clarifications'][pending['id']]
        self.assertEqual([m['id'] for m in record.get('responses', [])], ['111'])
        self.assertFalse(runtime.preflight(now=(instant(due)+timedelta(minutes=30)).isoformat())['wakeAgent'])

    def test_retry_intent_cannot_name_unknown_or_duplicate_holds(self):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        valid = runtime.status()
        Driver.validate_state(valid)
        for ids in (['unknown'], [pending['id'], pending['id']], [], [123]):
            invalid = copy.deepcopy(valid)
            invalid['outbox'][draft['token']]['intent']['clarification_ids'] = ids
            with self.subTest(ids=ids), self.assertRaisesRegex(ValueError, 'invalid runtime state'):
                Driver.validate_state(invalid)

    def test_previous_retry_receipt_must_still_exist_in_fresh_history(self):
        self.test_retry_traverses_real_cli_draft_history_sender_and_receipt()
        runtime = Driver(self.data)
        cycle = runtime.status()['clarification_retry']
        due = cycle['events'][1]['slot']
        offered = runtime.preflight(now=due)
        draft = runtime.draft(offered['intent']['event_token'], 'Which task?', now=due)
        history = [c['message'] for c in runtime.status()['clarifications'].values()]
        for row in runtime.status()['outbox'].values():
            if row['state'] == 'confirmed' and row['intent'].get('kind') != 'clarification':
                history.append(self.message(row['receipt']['message_id'], row['receipt']['delivered_at'], row['body'], bot=True))
        history.sort(key=lambda m: int(m['id']), reverse=True)
        with self.assertRaisesRegex(ValueError, 'retry receipt'):
            runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)

    def final_reply_race(self, *, resolve):
        runtime, history, drafts, due, pending, draft = self.retry_draft()
        runtime.observe(draft['token'], draft['fence'], self.pages(history, due), now=due)
        test = self
        class Racing(Driver):
            def authorize(self, row, *, now=None):
                super().authorize(row, now=now)
                history.insert(0, test.message('105', due, 'The first task'))
                other = Driver(test.data)
                if resolve:
                    other.resolve_clarification(binding=BINDING, clarification_id=pending['id'], task_id=drafts[0]['task']['id'],
                        selection_message_id='105', pages=test.pages(history, due), now=due)
                else:
                    other.engagement(BINDING, test.pages(history, due), now=due)
        sent = Racing(self.data).dispatch(draft['token'], draft['fence'], hermes=str(self.data.parent / 'sender'), now=due)
        self.assertNotIn('candidate_id', sent)
        self.assertIn('uncertain', sent)
        record = runtime.status()['clarifications'][pending['id']]
        self.assertEqual(record['state'], 'resolved' if resolve else 'pending')
        if not resolve:
            self.assertEqual([m['id'] for m in record['responses']], ['105'])
            self.assertNotEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')

    def test_selection_at_final_send_boundary_blocks_retry(self):
        self.final_reply_race(resolve=True)

    def test_ambiguous_owner_at_final_send_boundary_blocks_retry(self):
        self.final_reply_race(resolve=False)

    def test_retry_traverses_real_cli_draft_history_sender_and_receipt(self):
        runtime, history, drafts, now, pending = self.held()
        unchanged = runtime.coach.status(), self.cli('list')
        due = (instant(now) + timedelta(minutes=30)).isoformat()
        prepared = self.at_cli(due, 'preflight')
        self.assertTrue(prepared['wakeAgent'], prepared)
        self.assertEqual(prepared['intent']['kind'], 'clarification')
        self.assertEqual(prepared['intent']['clarification_ids'], [pending['id']])
        self.assertEqual(prepared['clarifications'][0]['candidates'], pending['candidates'])
        self.assertEqual(Driver(self.data).preflight(now=due), prepared)
        body = self.data.parent / 'body.txt'
        body.write_text('Which task: Synthetic task or Second fictional task?')
        draft = self.at_cli(due, 'draft', '--event-token', prepared['intent']['event_token'], '--body-file', str(body))
        capture = self.data.parent / 'pages.json'
        capture.write_text(json.dumps(self.pages(history, due)))
        observed = self.at_cli(due, 'observe', '--event-token', draft['token'], '--fence', draft['fence'], '--pages-file', str(capture))
        self.assertTrue(observed['complete'])
        sender = self.data.parent / 'retry-sender'
        sender.write_text('#!' + sys.executable + '\nimport argparse,json,sqlite3\np=argparse.ArgumentParser(); s=p.add_subparsers(dest="command",required=True).add_parser("send"); s.add_argument("--json",action="store_true"); s.add_argument("--to"); s.add_argument("body"); a=p.parse_args(); assert a.to=="discord:123"\nc=sqlite3.connect(' + repr(str(self.data / 'outbox.sqlite3')) + '); state=json.loads(c.execute("SELECT value FROM runtime").fetchone()[0]); c.close(); assert state["outbox"][' + repr(draft['token']) + ']["state"]=="sending"\nprint(json.dumps(dict(success=True,message_id="110")))\n')
        sender.chmod(0o700)
        sent = self.at_cli(due, 'dispatch', '--event-token', draft['token'], '--fence', draft['fence'], '--hermes', str(sender))
        self.assertEqual(sent.get('candidate_id'), '110', sent)
        history.insert(0, self.message('110', due, body.read_text(), bot=True))
        capture.write_text(json.dumps(self.pages(history, due)))
        receipt = self.at_cli(due, 'confirm', '--event-token', draft['token'], '--fence', draft['fence'], '--pages-file', str(capture))
        self.assertEqual(receipt['message_id'], '110')
        self.assertEqual((runtime.coach.status(), self.cli('list')), unchanged)


def load_tests(loader, tests, pattern):
    suite = __import__('unittest').TestSuite()
    suite.addTests(RetryTest(name) for name in RetryTest.__dict__ if name.startswith('test_'))
    return suite
