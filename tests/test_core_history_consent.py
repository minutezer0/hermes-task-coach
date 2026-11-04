"""Fictional route-scoped Discord history permission; no live tools."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import closing
import test_core_coaching  # establishes source import path
from task_coach.driver import Driver

ROUTE = dict(binding=dict(owner='owner-test', profile='profile-test', account='account-test',
                          chat='123', thread='none'), platform='discord',
             destination='discord:123', channel_id='123', bot_id='456')


class ConsentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.driver = Driver(Path(self.temp.name) / 'data')
        self.driver.directory.mkdir(mode=0o700)
        self.driver.configure(copy.deepcopy(ROUTE), confirm=True)

    def test_explicit_route_scoped_preference_defaults_off_and_revokes(self):
        self.assertTrue(hasattr(self.driver, 'history_preference'), 'persisted history preference API missing')
        self.assertFalse(self.driver.history_preference()['enabled'])
        with self.assertRaises(ValueError):
            self.driver.history_preference(enabled=True, route=ROUTE)
        enabled = self.driver.history_preference(enabled=True, route=ROUTE, confirm=True)
        self.assertTrue(enabled['enabled'])
        self.assertEqual(Driver(self.driver.directory).history_preference(), enabled)
        self.assertFalse(self.driver.history_preference(enabled=False)['enabled'])

    def test_preference_cli_has_enable_disable_and_readback(self):
        import argparse
        from task_coach.driver import add_parser, run_cli
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command'))
        read = parser.parse_args(['runtime', 'history-preference'])
        self.assertFalse(run_cli(self.driver.directory, read)['enabled'])
        enable = parser.parse_args(['runtime', 'history-preference', '--enable', '--confirm-history',
                                    '--route', json.dumps(ROUTE)])
        self.assertTrue(run_cli(self.driver.directory, enable)['enabled'])
        disable = parser.parse_args(['runtime', 'history-preference', '--disable'])
        self.assertFalse(run_cli(self.driver.directory, disable)['enabled'])

    def test_all_history_ingress_refuses_before_capture_or_state_mutation(self):
        before = (self.driver.directory / 'outbox.sqlite3').read_bytes()
        calls = [lambda: self.driver.confirm('unknown', 'unknown', object()),
                 lambda: self.driver.observe('unknown', 'unknown', object()),
                 lambda: self.driver.engagement(ROUTE['binding'], object()),
                 lambda: self.driver.resolve_clarification(binding=ROUTE['binding'], clarification_id='unknown',
                    task_id=1, selection_message_id='900', pages=object()),
                 lambda: self.driver.dismiss_clarification(binding=ROUTE['binding'], clarification_id='unknown',
                    dismissal_message_id='900', pages=object())]
        for call in calls:
            with self.subTest(call=call), self.assertRaisesRegex(ValueError, 'history.*authorization'):
                call()
            self.assertEqual((self.driver.directory / 'outbox.sqlite3').read_bytes(), before)

    def test_request_is_explicit_bounded_route_bound_and_revocable(self):
        self.assertTrue(hasattr(self.driver, 'history_plan'), 'on-demand history plan missing')
        with self.assertRaisesRegex(ValueError, 'authorization'):
            self.driver.history_plan(purpose='reply-recovery', target='100', confirm=True)
        self.driver.history_preference(enabled=True, route=ROUTE, confirm=True)
        with self.assertRaises(ValueError):
            self.driver.history_plan(purpose='scheduled', target='100', confirm=True)
        with self.assertRaises(ValueError):
            self.driver.history_plan(purpose='reply-recovery', target='100')
        request = self.driver.history_plan(purpose='reply-recovery', target='100', confirm=True)
        self.assertEqual(request['channel_id'], '123')
        self.assertEqual((request['limit'], request['max_pages']), (25, 1))
        self.driver.authorize_history(request, purpose='reply-recovery', target='100')
        with self.assertRaises(ValueError):
            self.driver.authorize_history(request, purpose='delivery-verification', target='100')
        self.driver.history_preference(enabled=False)
        self.driver.history_preference(enabled=True, route=ROUTE, confirm=True)
        with self.assertRaises(ValueError):
            self.driver.authorize_history(request, purpose='reply-recovery', target='100')

    def test_plan_rejects_equal_but_wrong_json_types(self):
        self.driver.history_preference(enabled=True, route=ROUTE, confirm=True)
        request = self.driver.history_plan(purpose='reply-recovery', target='100', confirm=True)
        for key, value in [('max_pages', True), ('limit', 25.0), ('max_payload_bytes', 131072.0)]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.driver.authorize_history(dict(request, **{key: value}), purpose='reply-recovery', target='100')

    def test_missing_upgrade_field_is_off_without_adoption_or_audit_write(self):
        path = self.driver.directory / 'outbox.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            state = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
            state.pop('history_consent', None)
            state.pop('local_first', None)
            db.execute('UPDATE runtime SET value=?', (json.dumps(state),))
            db.commit()
        before = path.read_bytes()
        self.assertFalse(Driver(self.driver.directory).history_preference()['enabled'])
        with self.assertRaisesRegex(ValueError, 'authorization'):
            Driver(self.driver.directory).engagement(ROUTE['binding'], object())
        self.assertEqual(path.read_bytes(), before)

    def test_enabled_ingress_still_requires_request_before_capture(self):
        self.driver.history_preference(enabled=True, route=ROUTE, confirm=True)
        before = (self.driver.directory / 'outbox.sqlite3').read_bytes()
        for method, args, kw in [
            ('confirm', ('unknown', 'unknown', object()), {}),
            ('observe', ('unknown', 'unknown', object()), {}),
            ('engagement', (ROUTE['binding'], object()), {}),
            ('resolve_clarification', (), dict(binding=ROUTE['binding'], clarification_id='unknown', task_id=1, selection_message_id='900', pages=object())),
            ('dismiss_clarification', (), dict(binding=ROUTE['binding'], clarification_id='unknown', dismissal_message_id='900', pages=object()))]:
            with self.subTest(method=method), self.assertRaisesRegex(ValueError, 'history.*authorization'):
                getattr(self.driver, method)(*args, **kw)
            self.assertEqual((self.driver.directory / 'outbox.sqlite3').read_bytes(), before)

    def test_disabled_cli_refuses_before_opening_raw_capture(self):
        import argparse
        from task_coach.driver import add_parser, run_cli
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command'))
        args = parser.parse_args(['runtime', 'confirm', '--event-token', 'unknown', '--fence', 'unknown',
                                  '--history-plan-file', str(self.driver.directory / 'missing-plan'),
                                  '--pages-file', str(self.driver.directory / 'does-not-exist')])
        with self.assertRaisesRegex(ValueError, 'history.*authorization'):
            run_cli(self.driver.directory, args)


class HistoryFlowTest(unittest.TestCase):
    setUp = test_core_coaching.EngineTest.setUp
    cli = test_core_coaching.EngineTest.cli
    engine = test_core_coaching.EngineTest.engine

    def capture(self, *, legacy=False):
        from test_core_local_first import LocalFirstTest
        if legacy:
            from test_core_driver import BINDING, persist_legacy_runtime
            runtime = Driver(self.data)
            runtime.coach.rng = __import__('random').Random(1)
            persist_legacy_runtime(runtime)
            runtime.configure(dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        else:
            runtime = LocalFirstTest.runtime(self)
        self.route = runtime.status()['route']
        runtime.history_preference(enabled=True, route=self.route, confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        self.events = runtime.coach.status()['episode']['events']
        self.now = self.events[0]['slot']
        draft = runtime.draft(self.events[0]['token'], 'Fictional opener', now=self.now)
        runtime.dispatch(draft['token'], draft['fence'], hermes=LocalFirstTest.sender(self), now=self.now)
        message = dict(id='100', content=draft['body'], timestamp=self.now,
                       author=dict(id='456', bot=True), attachments=[])
        pages = [dict(binding=self.route['binding'], channel_id='123', before=None,
                      observed_at=self.now, result=dict(messages=[message]))]
        return runtime, draft, pages

    def plan(self, runtime, purpose='delivery-verification', target='100'):
        return runtime.history_plan(purpose=purpose, target=target, confirm=True)

    def test_cli_plan_and_bounded_capture_load(self):
        import argparse
        from task_coach.driver import add_parser, run_cli
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        parser = argparse.ArgumentParser()
        add_parser(parser.add_subparsers(dest='command'))
        request = run_cli(self.data, parser.parse_args(['runtime', 'history-plan', '--purpose',
            'delivery-verification', '--target', '100', '--confirm-history']))
        plan_file = self.data / 'plan.json'
        plan_file.write_text(json.dumps(request))
        capture = self.data / 'large.json'
        with capture.open('wb') as stream:
            stream.truncate(131073)
        args = parser.parse_args(['runtime', 'confirm', '--event-token', draft['token'], '--fence',
            draft['fence'], '--history-plan-file', str(plan_file), '--pages-file', str(capture)])
        original_open = Path.open
        def no_capture_open(path, *args, **kwargs):
            if path == capture:
                raise AssertionError('large capture opened')
            return original_open(path, *args, **kwargs)
        with patch.object(Path, 'open', no_capture_open):
            with self.assertRaisesRegex(ValueError, 'budget'):
                run_cli(self.data, args)
        capture.write_text(json.dumps(pages))
        request['target'] = '999'
        plan_file.write_text(json.dumps(request))
        with patch.object(Path, 'open', no_capture_open):
            with self.assertRaisesRegex(ValueError, 'authorization'):
                run_cli(self.data, args)
        plan_file.write_text(json.dumps(self.plan(runtime)))
        # Current wall clock intentionally differs: verify real CLI using a
        # production clock patch, not fabricated captures from a live service.
        from datetime import datetime
        with patch('task_coach.driver.datetime') as clock:
            clock.now.return_value = datetime.fromisoformat(self.now)
            self.assertEqual(run_cli(self.data, args)['message_id'], '100')

    def test_wrong_request_and_capture_binding_never_reach_parser_or_mutate(self):
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        correct = self.plan(runtime)
        before = {name: (self.data / name).read_bytes() for name in ('outbox.sqlite3', 'coach.sqlite3', 'tasks.sqlite3') if (self.data / name).exists()}
        requests = [None, {}, dict(correct, target='999'), dict(correct, purpose='reply-recovery'),
                    dict(correct, generation='revoked'), dict(correct, limit=26), dict(correct, max_pages=True)]
        for request in requests:
            with self.subTest(request=request), patch('task_coach.driver.validate_pages', side_effect=AssertionError('parser reached')):
                with self.assertRaisesRegex(ValueError, 'authorization'):
                    runtime.confirm(draft['token'], draft['fence'], object(), now=self.now, history_plan=request)
        with patch('task_coach.driver.validate_pages', side_effect=AssertionError('parser reached')):
            with self.assertRaisesRegex(ValueError, 'authorization'):
                runtime.confirm(draft['token'], draft['fence'], object(), now=self.now,
                                message_id='999', history_plan=correct)
        for name, content in before.items():
            self.assertEqual((self.data / name).read_bytes(), content)

    def test_observe_rejected_semantics_preserves_existing_evidence(self):
        runtime, draft, pages = self.capture()
        event = self.events[1]
        followup = runtime.draft(event['token'], 'Fictional followup', now=event['slot'])
        pages[0]['observed_at'] = event['slot']
        request = self.plan(runtime, 'reply-recovery')
        evidence = runtime.observe(followup['token'], followup['fence'], pages,
                                   now=event['slot'], history_plan=request)
        self.assertTrue(evidence['complete'])
        before = (self.data / 'outbox.sqlite3').read_bytes()
        pages[0]['observed_at'] = '2000-01-01T00:00:00Z'
        with self.assertRaisesRegex(ValueError, 'stale'):
            runtime.observe(followup['token'], followup['fence'], pages,
                            now=event['slot'], history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_full_capped_recovery_is_not_end_of_history(self):
        runtime, draft, pages = self.capture()
        # Simulate the journaled crash boundary before a native receipt arrived.
        with runtime.transaction() as state:
            row = state['outbox'][draft['token']]
            row['state'] = 'sending'
            for field in ('candidate_id', 'receipt', 'acceptance'):
                row.pop(field, None)
        pages[0]['result']['messages'].extend([
            dict(pages[0]['result']['messages'][0], id=str(identifier), content='unrelated')
            for identifier in range(99, 75, -1)])
        request = self.plan(runtime)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with self.assertRaisesRegex(ValueError, 'coverage'):
            runtime.confirm(draft['token'], draft['fence'], pages, now=self.now,
                            message_id='100', history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        pages[0]['result']['messages'].pop()
        receipt = runtime.confirm(draft['token'], draft['fence'], pages, now=self.now,
                                  message_id='100', history_plan=request)
        self.assertEqual(receipt['message_id'], '100')

    def test_small_full_fetch_cannot_hide_older_matching_candidate(self):
        runtime, draft, pages = self.capture()
        with runtime.transaction() as state:
            row = state['outbox'][draft['token']]
            row['state'] = 'sending'
            for field in ('candidate_id', 'receipt', 'acceptance'):
                row.pop(field, None)
        request = self.plan(runtime)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        # An older identical bot message can be just beyond this full fetch.
        # Selecting 100 must not manufacture coverage excluding that candidate.
        for envelope in ('page', 'result'):
            capture = copy.deepcopy(pages)
            (capture[0] if envelope == 'page' else capture[0]['result'])['limit'] = 1
            with self.subTest(envelope=envelope), self.assertRaisesRegex(ValueError, 'coverage'):
                runtime.confirm(draft['token'], draft['fence'], capture, now=self.now,
                                message_id='100', history_plan=request)
            self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        # Revealing the hidden older match proves why a full limit=1 was unsafe.
        capture = copy.deepcopy(pages)
        capture[0]['result']['limit'] = 3
        capture[0]['result']['messages'].append(dict(capture[0]['result']['messages'][0], id='99'))
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            runtime.confirm(draft['token'], draft['fence'], capture, now=self.now,
                            message_id='100', history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        # A genuinely short smaller fetch can still prove end-of-history.
        capture[0]['result']['messages'].pop()
        receipt = runtime.confirm(draft['token'], draft['fence'], capture, now=self.now,
                                  message_id='100', history_plan=request)
        self.assertEqual(receipt['message_id'], '100')

    def test_every_raw_budget_and_envelope_rejected_before_parser(self):
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        request = self.plan(runtime)
        variants = [pages * 2]
        for change in ({'channel_id': '999'}, {'binding': dict(self.route['binding'], owner='wrong')},
                       {'before': '50'}, {'result': {'messages': []}}):
            variants.append([dict(pages[0], **change)])
        variants.append([dict(pages[0], result=dict(pages[0]['result'], channel_id='999'))])
        variants.append([dict(pages[0], result=dict(messages=[dict(pages[0]['result']['messages'][0], channel_id='999')]))])
        variants.append([dict(pages[0], limit=100)])
        variants.append([dict(pages[0], result=dict(pages[0]['result'], before='50'))])
        variants.append([dict(pages[0], result=dict(messages=[dict(pages[0]['result']['messages'][0], content='x' * 8193)]))])
        variants.append([dict(pages[0], result=dict(pages[0]['result'], raw_envelope='x' * 131073))])
        variants.append([dict(pages[0], result=dict(messages=[dict(pages[0]['result']['messages'][0], id='999')]))])
        # Oversized tail cannot hide behind the parser's early anchor exit.
        variants.append([dict(pages[0], result=dict(messages=pages[0]['result']['messages'] + [dict(id='99', raw='x' * 8193)]))])
        before = (self.data / 'outbox.sqlite3').read_bytes()
        for capture in variants:
            with self.subTest(capture=str(capture)[:100]), patch('task_coach.driver.validate_pages', side_effect=AssertionError('parser reached')):
                with self.assertRaises(ValueError):
                    runtime.confirm(draft['token'], draft['fence'], capture, now=self.now, history_plan=request)
            self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_revocation_serializes_with_real_processing_and_commit(self):
        import os
        import subprocess
        import sys
        import threading
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        request = self.plan(runtime)
        entered = threading.Event()
        release = threading.Event()
        results, failures = [], []
        original = runtime._history_capture_budget
        def barrier(capture, plan):
            entered.set()
            if not release.wait(10):
                raise AssertionError('history barrier timed out')
            return original(capture, plan)
        def process():
            try:
                results.append(runtime.confirm(draft['token'], draft['fence'], pages,
                                               now=self.now, history_plan=request))
            except BaseException as error:
                failures.append(error)
        with patch.object(runtime, '_history_capture_budget', barrier):
            worker = threading.Thread(target=process)
            worker.start()
            self.assertTrue(entered.wait(5))
            code = ('import sys; from task_coach.driver import Driver; '
                    'd=Driver(sys.argv[1]); print("ready",flush=True); '
                    'd.history_preference(enabled=False); print("revoked",flush=True)')
            env = dict(os.environ, PYTHONPATH=str(test_core_coaching.SCRIPTS))
            child = subprocess.Popen([sys.executable, '-c', code, str(self.data)], env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                with self.assertRaises(subprocess.TimeoutExpired):
                    child.wait(timeout=0.2)
                with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
                    snapshot = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
                self.assertEqual(snapshot['outbox'][draft['token']]['state'], 'accepted')
            finally:
                release.set()
                worker.join(10)
                stdout, stderr = child.communicate(timeout=10)
            self.assertFalse(worker.is_alive())
            self.assertEqual(child.returncode, 0, stderr)
            self.assertIn('revoked', stdout)
        self.assertEqual(failures, [])
        self.assertEqual(results[0]['message_id'], '100')
        self.assertFalse(runtime.history_preference()['enabled'])
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with patch.object(runtime, '_history_capture_budget', side_effect=AssertionError('revoked capture processed')):
            with self.assertRaisesRegex(ValueError, 'authorization'):
                runtime.confirm(draft['token'], draft['fence'], object(), now=self.now, history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_denied_history_and_missing_old_anchor_do_not_block_local_first(self):
        from test_core_local_first import LocalFirstTest
        runtime, draft, pages = self.capture()
        acceptance = runtime.row(draft['token'], draft['fence'])['acceptance']
        capped = copy.deepcopy(pages)
        capped[0]['result']['messages'] = [dict(pages[0]['result']['messages'][0], id=str(n)) for n in range(200, 175, -1)]
        with self.assertRaises(ValueError):
            runtime.confirm(draft['token'], draft['fence'], capped, now=self.now, history_plan=self.plan(runtime))
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['acceptance'], acceptance)
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'accepted')
        runtime.history_preference(enabled=False)
        with self.assertRaisesRegex(ValueError, 'authorization'):
            runtime.engagement(self.route['binding'], object())
        event = self.events[1]
        followup = runtime.draft(event['token'], 'Still local-first', now=event['slot'])
        result = runtime.dispatch(followup['token'], followup['fence'], hermes=LocalFirstTest.sender(self), now=event['slot'])
        self.assertEqual(result['state'], 'accepted')
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['acceptance'], acceptance)

    def test_enabled_engagement_targets_actual_confirmed_receipt(self):
        runtime, draft, pages = self.capture()
        runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=self.plan(runtime))
        pages[0]['result']['messages'].insert(0, dict(id='101', content='I am working on this', timestamp=self.now,
            author=dict(id=self.route['binding']['owner'], bot=False), attachments=[]))
        request = self.plan(runtime, 'reply-recovery')
        with self.assertRaises(ValueError):
            runtime.engagement(self.route['binding'], pages, now=self.now, history_plan=dict(request, target='999'))
        result = runtime.engagement(self.route['binding'], pages, now=self.now, history_plan=request)
        self.assertTrue(result['engaged'])
        self.assertEqual(runtime.coach.status()['episode']['stopped'], 'owner-engaged')
        self.assertEqual(runtime.engagement(self.route['binding'], pages, now=self.now, history_plan=request), result)

    def test_idempotent_confirmation_still_validates_actual_capture(self):
        runtime, draft, pages = self.capture()
        request = self.plan(runtime)
        receipt = runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=request)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        pages[0]['result']['messages'][0]['content'] = 'different actual message'
        with self.assertRaises(ValueError):
            runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        pages[0]['result']['messages'][0]['content'] = draft['body']
        self.assertEqual(runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=request), receipt)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def clarification_capture(self):
        import random
        import sys
        from test_core_driver import BINDING, persist_legacy_runtime
        from test_core_clarification import ClarificationTest
        self.cli('setup', '--update', '--max-tasks-per-window', '2',
                 '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Second fictional task')
        runtime = Driver(self.data)
        runtime.coach.rng = random.Random(1)
        persist_legacy_runtime(runtime)
        self.route = dict(binding=BINDING, platform='discord', destination='discord:123', channel_id='123', bot_id='456')
        runtime.configure(self.route, confirm=True)
        runtime.history_preference(enabled=True, route=self.route, confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        history, drafts = [], []
        sender = self.data.parent / 'fictional-legacy-sender'
        for n, sequence in enumerate([root] + root['next_tasks']):
            event = sequence['events'][0]
            now = event['slot']
            draft = runtime.draft(event['token'], 'Fictional check-in ' + str(n), now=now)
            sender.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(dict(success=True, message_id=str(100+n)))) + ')\n')
            sender.chmod(0o700)
            runtime.dispatch(event['token'], draft['fence'], hermes=str(sender), now=now)
            history.insert(0, ClarificationTest.message(self, str(100+n), now, draft['body'], bot=True))
            runtime.confirm(event['token'], draft['fence'], ClarificationTest.pages(self, history, now),
                            now=now, history_plan=self.plan(runtime, target=str(100+n)))
            drafts.append(draft)
        history.insert(0, ClarificationTest.message(self, '104', now))
        pages = ClarificationTest.pages(self, history, now)
        result = runtime.engagement(self.route['binding'], pages, now=now,
                                    history_plan=self.plan(runtime, 'reply-recovery', '101'))
        record = result['clarifications'][0]
        return runtime, history, drafts, now, record

    def test_resolve_and_dismiss_use_actual_owner_target_not_anchor(self):
        from test_core_clarification import ClarificationTest
        runtime, history, drafts, now, record = self.clarification_capture()
        history.insert(0, ClarificationTest.message(self, '105', now, 'The second task'))
        pages = ClarificationTest.pages(self, history, now)
        kw = dict(binding=self.route['binding'], clarification_id=record['id'], task_id=drafts[1]['task']['id'],
                  selection_message_id='105', pages=pages, now=now)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        for purpose, target in [('delivery-verification', '105'), ('reply-recovery', '100')]:
            with self.assertRaises(ValueError):
                runtime.resolve_clarification(**kw, history_plan=self.plan(runtime, purpose, target))
            self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        plan = self.plan(runtime, 'reply-recovery', '105')
        result = runtime.resolve_clarification(**kw, history_plan=plan)
        self.assertTrue(result['engaged'])
        self.assertEqual(result['selection_message_id'], '105')
        self.assertEqual(runtime.resolve_clarification(**kw, history_plan=plan), result)
        pages[0]['result']['messages'][0]['content'] = 'edited selection'
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with self.assertRaises(ValueError):
            runtime.resolve_clarification(**kw, history_plan=plan)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_dismiss_authorized_actual_capture_and_reject_revoked_request(self):
        from test_core_clarification import ClarificationTest
        runtime, history, drafts, now, record = self.clarification_capture()
        history.insert(0, ClarificationTest.message(self, '105', now, 'Discard the question'))
        pages = ClarificationTest.pages(self, history, now)
        kw = dict(binding=self.route['binding'], clarification_id=record['id'], dismissal_message_id='105', pages=pages, now=now)
        stale = self.plan(runtime, 'reply-recovery', '105')
        runtime.history_preference(enabled=False)
        runtime.history_preference(enabled=True, route=self.route, confirm=True)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with self.assertRaises(ValueError):
            runtime.dismiss_clarification(**kw, history_plan=stale)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        plan = self.plan(runtime, 'reply-recovery', '105')
        result = runtime.dismiss_clarification(**kw, history_plan=plan)
        self.assertTrue(result['dismissed'])
        self.assertEqual(runtime.dismiss_clarification(**kw, history_plan=plan), result)
        pages[0]['result']['messages'][0]['content'] = 'edited dismissal'
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with self.assertRaises(ValueError):
            runtime.dismiss_clarification(**kw, history_plan=plan)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_observe_rejects_edited_confirmed_legacy_anchor_preserving_evidence(self):
        runtime, draft, pages = self.capture(legacy=True)
        runtime.confirm(draft['token'], draft['fence'], pages, now=self.now,
                        history_plan=self.plan(runtime))
        event = self.events[1]
        followup = runtime.draft(event['token'], 'Legacy followup', now=event['slot'])
        pages[0]['observed_at'] = event['slot']
        request = self.plan(runtime, 'reply-recovery')
        self.assertTrue(runtime.observe(followup['token'], followup['fence'], pages,
                                      now=event['slot'], history_plan=request)['complete'])
        before = {name: (self.data / name).read_bytes()
                  for name in ('outbox.sqlite3', 'coach.sqlite3', 'tasks.sqlite3')}
        pages[0]['result']['messages'][0]['content'] = 'Edited captured opener'
        with self.assertRaises(ValueError):
            runtime.observe(followup['token'], followup['fence'], pages,
                            now=event['slot'], history_plan=request)
        for name, content in before.items():
            self.assertEqual((self.data / name).read_bytes(), content)
        pages[0]['result']['messages'][0]['content'] = draft['body']
        self.assertTrue(runtime.observe(followup['token'], followup['fence'], pages,
                                      now=event['slot'], history_plan=request)['complete'])

    def test_legacy_followup_cannot_use_evidence_after_revocation(self):
        from test_core_local_first import LocalFirstTest
        runtime, draft, pages = self.capture(legacy=True)
        runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=self.plan(runtime))
        event = self.events[1]
        followup = runtime.draft(event['token'], 'Legacy followup', now=event['slot'])
        pages[0]['observed_at'] = event['slot']
        runtime.observe(followup['token'], followup['fence'], pages, now=event['slot'],
                        history_plan=self.plan(runtime, 'reply-recovery'))
        runtime.history_preference(enabled=False)
        before = runtime.coach.status()
        with self.assertRaisesRegex(ValueError, 'authorization'):
            runtime.dispatch(followup['token'], followup['fence'], hermes=LocalFirstTest.sender(self), now=event['slot'])
        self.assertEqual(runtime.coach.status(), before, 'reject before claiming an engine event')
        runtime.history_preference(enabled=True, route=self.route, confirm=True)
        self.assertIsNone(runtime.row(followup['token'], followup['fence'])['evidence'])
        with self.assertRaises(ValueError):
            runtime.dispatch(followup['token'], followup['fence'], hermes=LocalFirstTest.sender(self), now=event['slot'])
        self.assertEqual(runtime.row(followup['token'], followup['fence'])['state'], 'draft')

    def test_revocation_wins_before_capture_without_any_mutation(self):
        import threading
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        request = self.plan(runtime)
        ready = threading.Event()
        rejected, failures = [], []
        def process():
            ready.set()
            try:
                runtime.confirm(draft['token'], draft['fence'], object(), now=self.now, history_plan=request)
            except ValueError as error:
                rejected.append(str(error))
            except BaseException as error:
                failures.append(error)
        with runtime._directory_lock():
            runtime.history_preference(enabled=False)
            before = {name: path.read_bytes() for name in ('outbox.sqlite3', 'coach.sqlite3') if (path := self.data / name).exists()}
            with patch.object(runtime, '_history_capture_budget', side_effect=AssertionError('revoked capture parsed')):
                worker = threading.Thread(target=process)
                worker.start()
                self.assertTrue(ready.wait(5))
                self.assertTrue(worker.is_alive())
        worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(len(rejected), 1)
        self.assertIn('authorization', rejected[0])
        for name, content in before.items():
            self.assertEqual((self.data / name).read_bytes(), content)

    def test_unrelated_local_first_task_dispatches_after_denied_history(self):
        from test_core_local_first import LocalFirstTest
        self.cli('setup', '--update', '--max-tasks-per-window', '2')
        self.cli('add', 'Unrelated fictional task')
        runtime, draft, pages = self.capture()
        root = runtime.coach.status()['episode']
        sequence = root['next_tasks'][0]
        self.assertNotEqual(sequence['task_id'], draft['task']['id'])
        runtime.history_preference(enabled=False)
        with self.assertRaises(ValueError):
            runtime.confirm(draft['token'], draft['fence'], object(), now=self.now)
        event = sequence['events'][0]
        unrelated = runtime.draft(event['token'], 'Unrelated local work', now=event['slot'])
        result = runtime.dispatch(unrelated['token'], unrelated['fence'], hermes=LocalFirstTest.sender(self), now=event['slot'])
        self.assertEqual(result['state'], 'accepted')

    def test_cli_capture_read_is_bounded_after_stat_race(self):
        from task_coach.driver import _bounded_json_file
        from unittest.mock import patch
        from types import SimpleNamespace
        import io
        path = self.data / 'growing-capture'
        class GrowingFile(io.BytesIO):
            def read(stream, count=-1):
                self.assertEqual(count, 131073)
                return super(GrowingFile, stream).read(count)
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=1)), \
             patch.object(Path, 'open', return_value=GrowingFile(b'x' * 131074)), \
             patch('task_coach.driver.json.loads', side_effect=AssertionError('large JSON parsed')):
            with self.assertRaisesRegex(ValueError, 'budget'):
                _bounded_json_file(path, 131072)

    def test_engagement_rejects_forged_receipt_capture_without_mutation(self):
        runtime, draft, pages = self.capture()
        runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=self.plan(runtime))
        request = self.plan(runtime, 'reply-recovery')
        pages[0]['result']['messages'][0]['content'] = 'not the receipt message'
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with self.assertRaises(ValueError):
            runtime.engagement(self.route['binding'], pages, now=self.now, history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_invalid_capture_on_enabled_upgrade_does_not_adopt_policy(self):
        runtime, draft, pages = self.capture(legacy=True)
        with runtime.transaction(adopt=False) as state:
            state.pop('local_first', None)
        before = (self.data / 'outbox.sqlite3').read_bytes()
        pages[0]['result']['messages'][0]['content'] = 'wrong actual sent message'
        with self.assertRaises(ValueError):
            runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=self.plan(runtime))
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)

    def test_actual_confirmation_enforces_budget_before_history_parser(self):
        from unittest.mock import patch
        runtime, draft, pages = self.capture()
        request = self.plan(runtime)
        too_many = copy.deepcopy(pages)
        too_many[0]['result']['messages'] *= 26
        before = (self.data / 'outbox.sqlite3').read_bytes()
        with patch('task_coach.driver.validate_pages', side_effect=AssertionError('parser reached')):
            with self.assertRaisesRegex(ValueError, 'budget'):
                runtime.confirm(draft['token'], draft['fence'], too_many, now=self.now, history_plan=request)
        self.assertEqual((self.data / 'outbox.sqlite3').read_bytes(), before)
        receipt = runtime.confirm(draft['token'], draft['fence'], pages, now=self.now, history_plan=request)
        self.assertEqual(receipt['message_id'], '100')
        self.assertEqual(runtime.row(draft['token'], draft['fence'])['state'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
