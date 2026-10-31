"""Synthetic runtime fixtures: never live platform qualification."""
import test_core_coaching as fixtures
import unittest
BINDING = dict(fixtures.BINDING, chat='123', thread='none')
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


class RuntimeTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli
    engine = fixtures.EngineTest.engine
    def prepare(self):
        self.cli('setup', '--update', '--min-followup-interval', '1', '--max-followup-interval', '1')
        engine = self.engine()
        engine.tick(now=datetime(2030, 1, 7, 8, tzinfo=timezone.utc), binding=BINDING)
        return engine, engine.status()['episode']['events']

    def receipt(self, event):
        return dict(event_token=event['token'], binding=BINDING, message_id='opaque-'+event['token'], cursor='cursor-'+event['token'], delivered_at=event['slot'])

    def test_confirmed_setup_and_draft_persist_unique_event(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('task_coach.driver'), 'runtime driver missing')
        from task_coach.driver import Driver
        engine, events = self.prepare()
        runtime = Driver(self.data)
        route = dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456')
        with self.assertRaises(ValueError):
            runtime.configure(route, confirm=False)
        for malformed in (None, [], 'not-a-route'):
            with self.subTest(route=malformed), self.assertRaises(ValueError):
                runtime.configure(malformed, confirm=True)
        runtime.configure(route, confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic opener', now=now)
        self.assertEqual(draft['state'], 'draft')
        self.assertEqual(runtime.draft(events[0]['token'], 'Synthetic opener', now=now), draft)
        with self.assertRaises(ValueError):
            runtime.draft(events[0]['token'], 'Conflicting text', now=now)
        self.assertEqual(engine.status()['episode']['events'][0]['state'], 'planned')

    def test_dispatch_commits_sending_before_subprocess_and_requires_readback(self):
        from task_coach.driver import Driver
        import os
        engine, events = self.prepare()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic opener', now=now)
        self.assertTrue(hasattr(runtime, 'dispatch'), 'native dispatch is missing')
        fake = Path(self.temp.name) / 'synthetic-hermes'
        fake.write_text('#!/usr/bin/env python3\nimport json,sqlite3,sys\nc=sqlite3.connect('+repr(str(self.data / 'outbox.sqlite3'))+')\ns=json.loads(c.execute("SELECT value FROM runtime").fetchone()[0]); c.close()\nassert list(s["outbox"].values())[0]["state"] == "sending"\nassert sys.argv[1:5] == ["send","--json","--to","discord:123"]\nprint(json.dumps({"success":True,"message_id":"100"}))\n')
        fake.chmod(0o700)
        result = runtime.dispatch(draft['token'], draft['fence'], hermes=str(fake), now=now)
        self.assertEqual(result['state'], 'sending')
        self.assertEqual(engine.status()['deliveries'], 0)
        with self.assertRaises(ValueError):
            runtime.dispatch(draft['token'], draft['fence'], hermes=str(fake), now=now)
        page = dict(binding=BINDING, channel_id='123', observed_at=now.isoformat(), before=None,
                    result=dict(messages=[dict(id='100', content='Synthetic opener', timestamp=now.isoformat(), author=dict(id='456', bot=True), attachments=[])]))
        receipt = runtime.confirm(draft['token'], draft['fence'], [page], now=now)
        self.assertEqual(receipt['message_id'], '100')
        self.assertEqual(receipt['cursor'], '100')
        self.assertEqual(engine.status()['deliveries'], 1)
        self.assertEqual(runtime.context(BINDING)['task']['title'], 'Synthetic task')
        self.assertTrue(hasattr(runtime, 'engagement'), 'normal inbound engagement protocol missing')
        page['result']['messages'].insert(0, dict(id='101', content='A synthetic reply', timestamp=now.isoformat(), author=dict(id=BINDING['owner'], bot=False), attachments=[]))
        self.assertTrue(runtime.engagement(BINDING, [page], now=now)['engaged'])
        self.assertEqual(engine.status()['episode']['stopped'], 'owner-engaged')
        self.cli('update', '1', '--title', 'Current synthetic title')
        self.assertEqual(runtime.context(BINDING)['task']['title'], 'Current synthetic title', 'normal inbound context must reread current task')

    def test_dispatch_option_like_body_is_literal_native_positional(self):
        """Real subprocess + stdlib argparse contract, without Hermes dependencies."""
        from task_coach.driver import Driver
        import sys
        private = Path(self.temp.name) / 'fictional-private.txt'
        private.write_text('Fictional file contents must not become the body')
        for body in ('--file=' + str(private), '--to=discord:999'):
            with self.subTest(body=body):
                for filename in ('coach.sqlite3', 'outbox.sqlite3'):
                    (self.data / filename).unlink(missing_ok=True)
                engine, events = self.prepare()
                runtime = Driver(self.data)
                runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
                now = datetime.fromisoformat(events[0]['slot'])
                draft = runtime.draft(events[0]['token'], body, now=now)
                capture = Path(self.temp.name) / 'captured-argv.json'
                fake = Path(self.temp.name) / 'synthetic-parser'
                fake.write_text('#!' + sys.executable + '\nimport argparse,json,sys\nfrom pathlib import Path\nPath(' + repr(str(capture)) + ').write_text(json.dumps(sys.argv[1:]))\nroot=argparse.ArgumentParser()\np=root.add_subparsers(dest="command",required=True).add_parser("send")\np.add_argument("--json",action="store_true")\np.add_argument("--to")\np.add_argument("--file")\np.add_argument("message",nargs="?")\na=root.parse_args()\nassert a.to == "discord:123" and a.file is None and a.message == ' + repr(body) + '\nprint(json.dumps({"success":True,"message_id":"100"}))\n')
                fake.chmod(0o700)
                result = runtime.dispatch(draft['token'], draft['fence'], hermes=str(fake), now=now)
                self.assertEqual(capture.read_text(), json.dumps(['send', '--json', '--to', 'discord:123', '--', body]))
                self.assertEqual(result.get('candidate_id'), '100', result)

    def test_followup_history_derives_reply_stop_and_preserves_task(self):
        from task_coach.driver import Driver
        engine, events = self.prepare()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        first = datetime.fromisoformat(events[0]['slot'])
        engine.tick(now=first, binding=BINDING)
        receipt = dict(self.receipt(events[0]), message_id='100', cursor='100')
        engine.acknowledge(receipt, now=first)
        now = datetime.fromisoformat(events[1]['slot'])
        draft = runtime.draft(events[1]['token'], 'Synthetic followup', now=now)
        self.assertTrue(hasattr(runtime, 'observe'), 'history-derived engagement missing')
        anchor = dict(id='100', content='Synthetic opener', timestamp=first.isoformat(), author=dict(id='456', bot=True), attachments=[])
        page = dict(binding=BINDING, channel_id='123', observed_at=now.isoformat(), before=None, result=dict(messages=[anchor]))
        evidence = runtime.observe(draft['token'], draft['fence'], [page], now=now)
        self.assertFalse(evidence['engaged'])
        with self.assertRaises(ValueError):
            runtime.observe(draft['token'], draft['fence'], [], now=now)
        self.assertIsNone(runtime.row(draft['token'], draft['fence'])['evidence'], 'failed refresh must invalidate earlier evidence')
        reply = dict(id='101', content='', timestamp=now.isoformat(), author=dict(id=BINDING['owner'], bot=False), attachments=[dict(filename='synthetic.txt')])
        page['result']['messages'].insert(0, reply)
        evidence = runtime.observe(draft['token'], draft['fence'], [page], now=now)
        self.assertTrue(evidence['engaged'])
        self.assertEqual(engine.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(self.cli('show', '1')['status'], 'open')

    def test_runtime_opportunity_and_late_receipt_does_not_revive(self):
        from task_coach.driver import Driver
        import random
        from task_coach.coaching import Coach
        self.assertIn('opportunity_minutes', __import__('inspect').signature(Coach).parameters, 'bounded runtime opportunity missing')
        engine = Coach(self.data, rng=random.Random(1), opportunity_minutes=10)
        engine.prepare(binding=BINDING, now='2030-01-07T08:00:00Z')
        event = engine.status()['episode']['events'][0]
        slot = datetime.fromisoformat(event['slot'])
        self.assertGreater(datetime.fromisoformat(event['expires'])-slot, timedelta(minutes=1))
        now = slot + timedelta(minutes=2)
        self.assertTrue(engine.tick(binding=BINDING, now=now, expected_token=event['token'])['wakeAgent'])
        engine.pause(True)
        receipt = dict(self.receipt(event), delivered_at=now.isoformat())
        self.assertTrue(hasattr(engine, 'reconcile'), 'late positive reconciliation missing')
        engine.reconcile(receipt, now=now+timedelta(minutes=20))
        self.assertEqual(engine.status()['deliveries'], 1)
        self.assertEqual(engine.status()['episode']['stopped'], 'paused')
        self.assertFalse(engine.prepare(binding=BINDING, now=now+timedelta(minutes=21))['wakeAgent'])

    def test_final_authorization_rechecks_claim_lease_and_task(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        engine, events = self.prepare()
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic opener', now=now)
        engine.tick(binding=BINDING, now=now, expected_token=draft['token'])
        self.assertTrue(hasattr(runtime, 'authorize'), 'final authorization missing')
        runtime.authorize(draft, now=now)
        self.cli('update', '1', '--title', 'Changed synthetic task')
        with self.assertRaises(ValueError):
            runtime.authorize(draft, now=now)
        self.cli('update', '1', '--title', 'Synthetic task')
        with self.assertRaises(ValueError):
            runtime.authorize(draft, now=now+timedelta(seconds=121))

    def test_runtime_cli_preflight_is_fail_closed(self):
        import subprocess, sys
        from test_core_coaching import SCRIPTS
        command = [sys.executable, '-I', '-B', str(SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'runtime', 'preflight']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIs(json.loads(result.stdout)['wakeAgent'], False)
        (self.data / 'config.json').write_text('broken synthetic config')
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIs(json.loads(result.stdout)['wakeAgent'], False)

    def test_native_setup_artifacts_wrapper_fails_closed(self):
        from task_coach.driver import Driver
        import subprocess, sys
        from test_core_coaching import SCRIPTS
        runtime = Driver(self.data)
        self.assertTrue(hasattr(runtime, 'native_plan'), 'guided native artifacts missing')
        profile = Path(self.temp.name) / 'synthetic-profile'
        plan = runtime.native_plan(profile, python=sys.executable, helper=SCRIPTS / 'task-coach.py', hermes='/synthetic/hermes')
        self.assertIn('--paused', plan['cron_argv'])
        script_arg = plan['cron_argv'][plan['cron_argv'].index('--script') + 1]
        self.assertEqual(script_arg, 'task-coach-preflight.py',
                         'native cron accepts a profile-relative script name, not an absolute path')
        self.assertNotIn('--no-agent', plan['cron_argv'])
        self.assertFalse(profile.exists())
        result = self.cli('runtime', 'native-plan', '--profile-home', str(profile), '--python', sys.executable, '--helper', str(SCRIPTS / 'task-coach.py'), '--hermes', '/synthetic/hermes')
        self.assertEqual(result['script_path'], plan['script_path'])
        self.assertFalse(profile.exists())
        script = Path(plan['script_path'])
        script.parent.mkdir(parents=True)
        script.write_text(plan['script_text'])
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIs(json.loads(result.stdout.splitlines()[-1])['wakeAgent'], False)
        (self.data / 'config.json').write_text('broken synthetic config')
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertIs(json.loads(result.stdout.splitlines()[-1])['wakeAgent'], False)

    def test_history_rejects_malformed_page_without_uncaught_keyerror(self):
        from task_coach.driver import validate_pages
        now = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)
        route = dict(binding=BINDING, channel_id='123')
        for pages in ([{}], [dict(binding=BINDING, channel_id='123', before=None)], [None]):
            with self.subTest(pages=pages), self.assertRaises(ValueError):
                validate_pages(pages, route, '100', now)

    def test_uncertain_attempt_can_reconcile_exact_readback_after_rollover(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        engine, events = self.prepare()
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic uncertain opener', now=now)
        sent = runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent/synthetic-hermes', now=now)
        self.assertIn('uncertain', sent)
        tomorrow = datetime(2030, 1, 8, 8, tzinfo=timezone.utc)
        engine.prepare(binding=BINDING, now=tomorrow)
        page = dict(binding=BINDING, channel_id='123', before=None, observed_at=tomorrow.isoformat(), result=dict(messages=[dict(id='100', content=draft['body'], timestamp=now.isoformat(), author=dict(id='456', bot=True), attachments=[])]))
        receipt = runtime.confirm(draft['token'], draft['fence'], [page], now=tomorrow, message_id='100')
        self.assertEqual(receipt['message_id'], '100')
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'confirmed')
        self.assertEqual(engine.status()['episode']['day'], '2030-01-08')
        self.assertEqual(engine.status()['deliveries'], 0)

    def uncertain_fixture(self):
        from task_coach.driver import Driver
        engine, events = self.prepare()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic lost response', now=now)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent/synthetic-hermes', now=now)
        def message(key, **changes):
            return dict(dict(id=str(key), content=draft['body'], timestamp=now.isoformat(), author=dict(id='456', bot=True), attachments=[]), **changes)
        def page(messages, **changes):
            return dict(dict(binding=BINDING, channel_id='123', before=None, observed_at=now.isoformat(), result=dict(messages=messages, count=len(messages))), **changes)
        return runtime, engine, draft, now, message, page

    def test_confirmed_receipt_is_immutable_after_rollover_and_restart(self):
        from task_coach.driver import Driver
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        receipt = runtime.confirm(draft['token'], draft['fence'], [page([message(100)])], now=now, message_id='100')
        tomorrow = now + timedelta(days=1)
        engine.prepare(binding=BINDING, now=tomorrow)
        runtime = Driver(self.data)
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            runtime.confirm(draft['token'], draft['fence'], [page([message(101)], observed_at=tomorrow.isoformat())], now=tomorrow, message_id='101')
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['receipt'], receipt)
        self.assertEqual(runtime.confirm(draft['token'], draft['fence'], [], now=tomorrow, message_id='100'), receipt)
        self.assertEqual(runtime.confirm(draft['token'], draft['fence'], [], now=tomorrow), receipt)
        self.assertEqual(engine.status()['deliveries'], 0)

    def test_known_candidate_rejects_conflicting_operator_id(self):
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        with runtime.transaction() as state:
            state['outbox'][draft['token']]['candidate_id'] = '100'
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            runtime.confirm(draft['token'], draft['fence'], [page([message(100)])], now=now, message_id='101')
        receipt = runtime.confirm(draft['token'], draft['fence'], [page([message(101), message(100)])], now=now, message_id='100')
        self.assertEqual(receipt['message_id'], '100')
        self.assertEqual(engine.status()['deliveries'], 1)

    def test_lost_response_rejects_both_choices_in_ambiguous_raw_page(self):
        from task_coach.driver import Driver
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        pages = [page([message(101), message(100)])]
        for candidate in ('101', '100'):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, 'ambiguous'):
                Driver(self.data).confirm(draft['token'], draft['fence'], pages, now=now, message_id=candidate)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'sending')
        self.assertEqual(engine.status()['deliveries'], 0)

    def test_lost_response_requires_coverage_before_attempt_not_only_candidate(self):
        from task_coach.driver import Driver
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        batch = [message(200)] + [message(k, content='Unrelated fictional post') for k in range(199, 100, -1)]
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runtime.confirm(draft['token'], draft['fence'], [page(batch)], now=now, message_id='200')
        older = message(100, timestamp=(now-timedelta(seconds=1)).isoformat())
        pages = [page(batch), page([older], before='101')]
        receipt = Driver(self.data).confirm(draft['token'], draft['fence'], pages, now=now, message_id='200')
        self.assertEqual(receipt['message_id'], '200')
        self.assertEqual(engine.status()['deliveries'], 1)

    def test_lost_response_complete_empty_terminal_page_and_idempotent_restart(self):
        from task_coach.driver import Driver
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        batch = [message(200)] + [message(k, content='Unrelated fictional post') for k in range(199, 100, -1)]
        pages = [page(batch), page([], before='101')]
        receipt = Driver(self.data).confirm(draft['token'], draft['fence'], pages, now=now, message_id='200')
        self.assertEqual(receipt['message_id'], '200')
        self.assertEqual(Driver(self.data).confirm(draft['token'], draft['fence'], [], now=now, message_id='200'), receipt)
        self.assertEqual(engine.status()['deliveries'], 1)

    def test_lost_response_validates_raw_tail_and_all_paginated_matches(self):
        from task_coach.driver import Driver
        import copy
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        batch = [message(200)] + [message(k, content='Unrelated fictional post') for k in range(199, 100, -1)]
        pages = [page(batch), page([message(100)], before='101')]
        for candidate in ('200', '100'):
            with self.subTest(candidate=candidate), self.assertRaisesRegex(ValueError, 'ambiguous'):
                Driver(self.data).confirm(draft['token'], draft['fence'], pages, now=now, message_id=candidate)
        for mutation in ('count', 'id', 'timestamp', 'route', 'pagination', 'stale'):
            bad = copy.deepcopy(pages)
            tail = bad[-1]
            if mutation == 'count':
                tail['result']['count'] = 2
            elif mutation == 'id':
                tail['result']['messages'][0]['id'] = '101'
            elif mutation == 'timestamp':
                tail['result']['messages'][0]['timestamp'] = (now+timedelta(seconds=1)).isoformat()
            elif mutation == 'route':
                tail['channel_id'] = '999'
            elif mutation == 'pagination':
                tail['before'] = '102'
            else:
                tail['observed_at'] = (now-timedelta(seconds=61)).isoformat()
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                runtime.confirm(draft['token'], draft['fence'], bad, now=now, message_id='200')
        # A full final page is sufficient only when it reaches strictly before
        # the attempt; equal timestamps can still conceal another match.
        batch[-1]['timestamp'] = (now-timedelta(seconds=1)).isoformat()
        receipt = Driver(self.data).confirm(draft['token'], draft['fence'], [page(batch)], now=now, message_id='200')
        self.assertEqual(receipt['message_id'], '200')
        self.assertEqual(engine.status()['deliveries'], 1)

    def test_confirmation_race_cannot_replace_durable_receipt(self):
        from task_coach.driver import Driver
        from unittest.mock import patch
        runtime, engine, draft, now, message, page = self.uncertain_fixture()
        tomorrow = now + timedelta(days=1)
        engine.prepare(binding=BINDING, now=tomorrow)
        original_status = runtime.coach.status
        def competing_confirmation():
            Driver(self.data).confirm(draft['token'], draft['fence'], [page([message(100)], observed_at=tomorrow.isoformat())], now=tomorrow, message_id='100')
            return original_status()
        with patch.object(runtime.coach, 'status', side_effect=competing_confirmation):
            with self.assertRaisesRegex(ValueError, 'conflicting'):
                runtime.confirm(draft['token'], draft['fence'], [page([message(101)], observed_at=tomorrow.isoformat())], now=tomorrow, message_id='101')
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['receipt']['message_id'], '100')

    def test_sender_errors_remain_nonretryable_across_restart(self):
        from task_coach.driver import Driver
        import sys
        for payload in ('[]', '{broken', '{"success":true,"skipped":true}', '{"success":false,"error":"synthetic"}', '{"success":true}'):
            with self.subTest(payload=payload):
                for filename in ('coach.sqlite3', 'outbox.sqlite3'):
                    (self.data / filename).unlink(missing_ok=True)
                engine, events = self.prepare()
                runtime = Driver(self.data)
                runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
                now = datetime.fromisoformat(events[0]['slot'])
                draft = runtime.draft(events[0]['token'], 'Synthetic failure', now=now)
                fake = Path(self.temp.name) / 'synthetic-broken-hermes'
                fake.write_text('#!'+sys.executable+'\nprint('+repr(payload)+')\n')
                fake.chmod(0o700)
                result = runtime.dispatch(draft['token'], draft['fence'], hermes=str(fake), now=now)
                self.assertIn('uncertain', result)
                self.assertEqual(engine.status()['deliveries'], 0)
                with self.assertRaises(ValueError):
                    Driver(self.data).dispatch(draft['token'], draft['fence'], hermes=str(fake), now=now)

    def test_synthetic_full_flow_opener_followup_reply_stop(self):
        """Runnable acceptance: subprocess doubles, NOT real platform qualification."""
        from task_coach.driver import Driver
        import sys
        engine, events = self.prepare()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        history = []
        for index in (0, 1):
            now = datetime.fromisoformat(events[index]['slot'])
            token = events[index]['token']
            draft = runtime.draft(token, 'Synthetic check-in '+str(index), now=now)
            def page(messages):
                return dict(binding=BINDING, channel_id='123', before=None, observed_at=now.isoformat(), result=dict(messages=messages))
            if index:
                runtime.observe(token, draft['fence'], [page(history)], now=now)
            fake = Path(self.temp.name) / 'synthetic-sender'
            fake.write_text('#!'+sys.executable+'\nimport json\nprint(json.dumps({"success":True,"message_id":'+repr(str(100+index))+'}))\n')
            fake.chmod(0o700)
            self.assertEqual(runtime.dispatch(token, draft['fence'], hermes=str(fake), now=now)['state'], 'sending')
            history.insert(0, dict(id=str(100+index), content=draft['body'], timestamp=now.isoformat(), author=dict(id='456', bot=True), attachments=[]))
            if index:
                history.insert(0, dict(id='102', content='Synthetic owner reply', timestamp=now.isoformat(), author=dict(id=BINDING['owner'], bot=False), attachments=[]))
            runtime = Driver(self.data)  # real restart, durable outbox and fences
            runtime.confirm(token, draft['fence'], [page(history)], now=now)
        self.assertEqual(engine.status()['deliveries'], 2)
        self.assertEqual(engine.status()['episode']['stopped'], 'owner-engaged', 'readback owner reply must stop immediately')
        self.assertFalse(runtime.preflight(now=datetime.fromisoformat(events[2]['slot']))['wakeAgent'])
        self.assertEqual(runtime.context(BINDING)['task']['id'], 1)
        self.assertEqual(self.cli('show', '1')['status'], 'open')

    def test_configure_rejects_binding_route_mismatch(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        with self.assertRaisesRegex(ValueError, 'binding.*channel'):
            runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:999', channel_id='999', bot_id='456'), confirm=True)

    def test_history_validates_pagination_route_owner_and_declared_totals(self):
        from task_coach.driver import validate_pages
        import copy
        now = datetime(2030, 1, 7, 12, tzinfo=timezone.utc)
        route = dict(binding=BINDING, channel_id='123')
        def message(key):
            return dict(id=str(key), content='Synthetic history', timestamp=now.isoformat(), author=dict(id='other-owner', bot=False), attachments=[])
        base = dict(binding=BINDING, channel_id='123', before=None, observed_at=now.isoformat(), result=dict(messages=[message(100)], count=1))
        wrong_count = copy.deepcopy(base)
        wrong_count['result']['count'] = 2
        with self.assertRaisesRegex(ValueError, 'count'):
            validate_pages([wrong_count], route, '100', now)
        for changed in (dict(base, channel_id='999'), dict(base, binding=dict(BINDING, owner='wrong')), dict(base, observed_at=(now-timedelta(seconds=61)).isoformat()), dict(base, before='200')):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                validate_pages([changed], route, '100', now)
        latest = dict(base, result=dict(messages=[message(k) for k in range(200, 100, -1)], count=100))
        older = dict(base, before='101')
        self.assertEqual(len(validate_pages([latest, older], route, '100', now)), 101)
        with self.assertRaises(ValueError):
            validate_pages([latest, dict(older, before='102')], route, '100', now)
        with self.assertRaises(ValueError):
            validate_pages([base], route, '99', now)

    def test_corrupt_outbox_row_rejected_without_mutation(self):
        from task_coach.driver import Driver
        import sqlite3, contextlib
        engine, events = self.prepare()
        runtime = Driver(self.data)
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic draft', now=now)
        path = self.data / 'outbox.sqlite3'
        with contextlib.closing(sqlite3.connect(path)) as db:
            state = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
            state['outbox'][draft['token']]['state'] = 'confirmed'
            db.execute('UPDATE runtime SET value=?', (json.dumps(state),))
            db.commit()
        before = path.read_bytes(), path.stat().st_mtime_ns
        with self.assertRaisesRegex(ValueError, 'runtime state'):
            runtime.status()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_positive_readback_after_opportunity_records_truth_without_revival(self):
        from task_coach.driver import Driver
        runtime = Driver(self.data)
        engine, events = self.prepare()
        runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        now = datetime.fromisoformat(events[0]['slot'])
        draft = runtime.draft(events[0]['token'], 'Synthetic delayed delivery', now=now)
        runtime.dispatch(draft['token'], draft['fence'], hermes='/nonexistent/synthetic-hermes', now=now)
        later = datetime.fromisoformat(events[0]['expires']) + timedelta(seconds=1)
        page = dict(binding=BINDING, channel_id='123', before=None, observed_at=later.isoformat(), result=dict(messages=[dict(id='100', content=draft['body'], timestamp=later.isoformat(), author=dict(id='456', bot=True), attachments=[])]))
        runtime.confirm(draft['token'], draft['fence'], [page], now=later, message_id='100')
        self.assertEqual(engine.status()['deliveries'], 1)
        self.assertEqual(engine.status()['episode']['stopped'], 'late-reconciled')
        self.assertFalse(runtime.preflight(now=later)['wakeAgent'])

    def test_prepare_does_not_claim_and_expected_token_fences_claim(self):
        engine, events = self.prepare()
        now = datetime.fromisoformat(events[0]['slot'])
        self.assertTrue(hasattr(engine, 'prepare'), 'nonclaiming prepare API missing')
        prepared = engine.prepare(binding=BINDING, now=now)
        self.assertTrue(prepared['wakeAgent'])
        self.assertEqual(engine.status()['episode']['events'][0]['state'], 'planned')
        self.assertFalse(engine.tick(binding=BINDING, now=now, expected_token='wrong')['wakeAgent'])
        self.assertTrue(engine.tick(binding=BINDING, now=now, expected_token=events[0]['token'])['wakeAgent'])
