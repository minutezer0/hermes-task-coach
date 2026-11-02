"""Reference-aware routing using fictional stores and raw synthetic captures only."""
from datetime import timedelta
import json
import random
import sys
import unittest

import test_core_coaching as fixtures
from test_core_driver import BINDING


class ReplyRoutingTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli

    def two_tasks(self, start='2030-01-07T08:00:00Z'):
        from task_coach.driver import Driver
        self.cli('setup', '--update', '--max-tasks-per-window', '2',
                 '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Second fictional task')
        runtime = Driver(self.data)
        runtime.coach.rng = random.Random(1)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123',
                               channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now=start)
        root = runtime.coach.status()['episode']
        self.sequences = [root] + root['next_tasks']
        self.history = []
        self.runtime = runtime
        return runtime

    def page(self, now):
        return [dict(binding=BINDING, channel_id='123', before=None, observed_at=now,
                     result=dict(messages=self.history, count=len(self.history)))]

    def send(self, event, key, reply=None, *, raw_reply=False, trusted_reply=False):
        runtime = self.runtime
        now = event['slot']
        draft = runtime.draft(event['token'], 'Fictional check-in ' + key, now=now)
        if draft['previous']:
            runtime.observe(draft['token'], draft['fence'], self.page(now), now=now)
        sender = self.data.parent / 'fictional-sender'
        sender.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(dict(success=True, message_id=key))) + ')\n')
        sender.chmod(0o700)
        runtime.dispatch(draft['token'], draft['fence'], hermes=str(sender), now=now)
        self.history.insert(0, dict(id=key, content=draft['body'], timestamp=now,
                                   author=dict(id='456', bot=True), attachments=[], message_reference=None))
        if reply is not None:
            self.add_reply('300', reply, now)
        pages = self.page(now)
        if raw_reply:
            for message in self.history:
                message.pop('message_reference', None)
                message.update(edited_timestamp=None, reactions=[], pinned=False)
        if trusted_reply:
            pages[0]['reply_targets'] = {'300': reply}
        runtime.confirm(draft['token'], draft['fence'], pages, now=now)
        return draft

    def add_reply(self, key, target, now):
        self.history.insert(0, dict(id=key, content='Fictional delayed reply', timestamp=now,
                                   author=dict(id=BINDING['owner'], bot=False), attachments=[],
                                   message_reference=dict(message_id=target, channel_id='123') if target else None))

    def open_b(self, start='2030-01-07T08:00:00Z'):
        runtime = self.two_tasks(start)
        first = self.sequences[0]['events'][0]
        self.send(first, '100')
        runtime.coach.stop(first['token'], BINDING)
        second = self.sequences[1]['events'][0]
        self.send(second, '200')
        return runtime, first, second

    def test_real_tool_shaped_reply_does_not_guess_b(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', None, second['slot'])
        for message in self.history:
            message.pop('message_reference', None)
            message.update(edited_timestamp=None, reactions=[], pinned=False)
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertFalse(result['engaged'])
        self.assertIsNone(result['context'])
        self.assertEqual(result['error'], 'ambiguous-engagement')
        self.assertNotEqual(runtime.coach.status()['episode']['next_tasks'][0]['stopped'], 'owner-engaged')
        self.assertFalse(runtime.preflight(now=self.sequences[1]['events'][1]['slot'])['wakeAgent'])

    def test_observe_delayed_a_reply_does_not_stop_b(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        draft = runtime.draft(followup['token'], 'B followup', now=followup['slot'])
        self.add_reply('300', '100', followup['slot'])
        evidence = runtime.observe(draft['token'], draft['fence'], self.page(followup['slot']), now=followup['slot'])
        self.assertFalse(evidence['engaged'])
        self.assertTrue(evidence['complete'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_confirm_delayed_a_reply_does_not_stop_b(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        self.send(followup, '250', reply='100')
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        self.assertEqual(runtime.coach.status()['deliveries'], 3)

    def test_context_without_target_does_not_guess_between_tasks(self):
        runtime, first, second = self.open_b()
        self.assertIsNone(runtime.context(BINDING))
        self.assertEqual(runtime.context(BINDING, reply_to_message_id='100')['event_token'], first['token'])

    def test_unrelated_explicit_reply_is_not_engagement(self):
        runtime, first, second = self.open_b()
        self.assertIsNone(runtime.context(BINDING, reply_to_message_id='999'))
        self.add_reply('300', '999', second['slot'])
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertFalse(result['engaged'])
        self.assertIsNone(result['context'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_trusted_capture_routes_real_shaped_observe_to_a(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        draft = runtime.draft(followup['token'], 'B followup', now=followup['slot'])
        self.add_reply('300', None, followup['slot'])
        for message in self.history:
            message.pop('message_reference', None)
            message.update(edited_timestamp=None, reactions=[], pinned=False)
        pages = self.page(followup['slot'])
        pages[0]['reply_targets'] = {'300': '100'}
        evidence = runtime.observe(draft['token'], draft['fence'], pages, now=followup['slot'])
        self.assertTrue(evidence['complete'])
        self.assertFalse(evidence['engaged'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        self.assertNotIn('message_reference', self.history[0], 'raw capture must stay unchanged')

    def test_cli_trusted_inbound_target_routes_real_shaped_reply(self):
        from datetime import datetime
        from unittest.mock import patch
        runtime, first, second = self.open_b()
        self.add_reply('300', None, second['slot'])
        for message in self.history:
            message.pop('message_reference', None)
        context = self.cli('runtime', 'context', '--binding', json.dumps(BINDING), '--reply-to-message-id', '100')
        self.assertEqual(context['event_token'], first['token'])
        path = self.data.parent / 'pages.json'
        path.write_text(json.dumps(self.page(second['slot'])))
        with patch('task_coach.driver.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat(second['slot'])
            result = self.cli('runtime', 'engagement', '--binding', json.dumps(BINDING),
                              '--pages-file', str(path), '--inbound-message-id', '300', '--reply-to-message-id', '100')
        self.assertTrue(result['engaged'])
        self.assertEqual(result['context']['event_token'], first['token'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_newest_unrelated_reply_does_not_return_older_a_context(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        self.add_reply('301', '150', second['slot'])
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertFalse(result['engaged'])
        self.assertIsNone(result['context'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_real_shaped_observe_blocks_ambiguous_delivery(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        draft = runtime.draft(followup['token'], 'B followup', now=followup['slot'])
        self.add_reply('300', None, followup['slot'])
        self.history[0].pop('message_reference')
        evidence = runtime.observe(draft['token'], draft['fence'], self.page(followup['slot']), now=followup['slot'])
        self.assertFalse(evidence['engaged'])
        self.assertFalse(evidence['complete'])
        self.assertEqual(evidence['error'], 'ambiguous-engagement')
        self.assertFalse(runtime.preflight(now=followup['slot'])['wakeAgent'])

    def test_real_shaped_confirm_records_receipt_but_blocks_ambiguity(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        draft = self.send(followup, '250', reply='100', raw_reply=True)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'confirmed')
        self.assertEqual(runtime.coach.status()['deliveries'], 3)
        self.assertEqual(runtime.coach.status()['episode']['window_stopped'], 'ambiguous-engagement')
        self.assertFalse(runtime.preflight(now=self.sequences[1]['events'][2]['slot'])['wakeAgent'])

    def test_real_shaped_confirm_with_trusted_a_target_keeps_b(self):
        runtime, first, second = self.open_b()
        self.send(self.sequences[1]['events'][1], '250', reply='100', raw_reply=True, trusted_reply=True)
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        self.assertEqual(runtime.coach.status()['deliveries'], 3)

    def test_unrelated_reference_does_not_engage_observe_or_confirm(self):
        runtime, first, second = self.open_b()
        followup = self.sequences[1]['events'][1]
        draft = runtime.draft(followup['token'], 'Fictional check-in 250', now=followup['slot'])
        self.add_reply('240', '150', followup['slot'])
        evidence = runtime.observe(draft['token'], draft['fence'], self.page(followup['slot']), now=followup['slot'])
        self.assertTrue(evidence['complete'])
        self.assertFalse(evidence['engaged'])
        self.send(followup, '250', reply='150')
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_explicit_b_reply_stops_only_b(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '200', second['slot'])
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertEqual(result['context']['event_token'], second['token'])
        self.assertTrue(result['engaged'])
        self.assertEqual(runtime.coach.status()['episode']['next_tasks'][0]['stopped'], 'owner-engaged')

    def test_reference_metadata_is_validated_before_state_changes(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        before = runtime.coach.status()
        for reference in ('100', {}, {'message_id': None}, {'message_id': []}):
            with self.subTest(reference=reference):
                self.history[0]['message_reference'] = reference
                with self.assertRaises(ValueError):
                    runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
                self.assertEqual(runtime.coach.status(), before)

    def test_trusted_capture_rejects_missing_owner_conflicts_and_bad_ids(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        for targets in ({'999': '100'}, {'200': '100'}, {'300': '200'}, {'300': []}, []):
            with self.subTest(targets=targets):
                pages = self.page(second['slot'])
                pages[0]['reply_targets'] = targets
                with self.assertRaises(ValueError):
                    runtime.engagement(BINDING, pages, now=second['slot'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_trusted_inbound_flags_require_exact_captured_owner(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        for kwargs in (dict(reply_to_message_id='100'), dict(inbound_message_id='300'),
                       dict(reply_to_message_id='100', inbound_message_id='200'),
                       dict(reply_to_message_id='200', inbound_message_id='300'),
                       dict(reply_to_message_id='100', inbound_message_id='999')):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'], **kwargs)
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_cross_channel_reference_is_not_engagement(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '200', second['slot'])
        self.history[0]['message_reference']['channel_id'] = '999'
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertFalse(result['engaged'])
        self.assertIsNone(result['context'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_isolated_cli_subprocess_routes_trusted_reply_and_unrelated_target(self):
        from datetime import datetime, timezone
        import subprocess
        runtime, first, second = self.open_b(start='2020-01-06T08:00:00Z')
        self.add_reply('300', None, second['slot'])
        for message in self.history:
            message.pop('message_reference', None)
            message.update(edited_timestamp=None, reactions=[], pinned=False)
        path = self.data.parent / 'pages.json'
        path.write_text(json.dumps(self.page(datetime.now(timezone.utc).isoformat())))
        command = [sys.executable, '-I', '-B', str(fixtures.SCRIPTS / 'task-coach.py'),
                   '--data-dir', str(self.data), 'runtime']
        context = subprocess.run(command + ['context', '--binding', json.dumps(BINDING),
                                           '--reply-to-message-id', '100'], capture_output=True, text=True)
        self.assertEqual(context.returncode, 0, context.stderr)
        self.assertEqual(json.loads(context.stdout)['event_token'], first['token'])
        for target, engaged in (('100', True), ('150', False)):
            result = subprocess.run(command + ['engagement', '--binding', json.dumps(BINDING),
                                    '--pages-file', str(path), '--inbound-message-id', '300',
                                    '--reply-to-message-id', target], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload['engaged'], engaged)
            if engaged:
                self.assertEqual(payload['context']['event_token'], first['token'])
            else:
                self.assertIsNone(payload['context'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_equivalent_raw_and_trusted_references_do_not_conflict(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        self.history[0]['message_reference'] = {'message_id': '100', 'type': 0}
        pages = self.page(second['slot'])
        pages[0]['reply_targets'] = {'300': '100'}
        result = runtime.engagement(BINDING, pages, now=second['slot'],
                                    reply_to_message_id='100', inbound_message_id='300')
        self.assertEqual(result['context']['event_token'], first['token'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])

    def test_generated_inbound_instruction_does_not_guess_targets(self):
        runtime = self.two_tasks()
        plan = runtime.native_plan(self.data.parent / 'fictional-profile', python=sys.executable,
                                   helper=fixtures.SCRIPTS / 'task-coach.py', hermes='/fictional/hermes')
        self.assertIn('--reply-to-message-id', plan['inbound_instruction'])
        self.assertIn('--inbound-message-id', plan['inbound_instruction'])
        self.assertIn('never infer', plan['inbound_instruction'])

    def test_delayed_explicit_reply_engages_a_not_b(self):
        runtime, first, second = self.open_b()
        self.add_reply('300', '100', second['slot'])
        result = runtime.engagement(BINDING, self.page(second['slot']), now=second['slot'])
        self.assertEqual(result['context']['event_token'], first['token'])
        self.assertTrue(result['engaged'])
        self.assertIsNone(runtime.coach.status()['episode']['next_tasks'][0]['stopped'])
        self.assertTrue(runtime.preflight(now=self.sequences[1]['events'][1]['slot'])['wakeAgent'])
