"""Multiple-window-task acceptance with fictional private stores only."""
import json
import unittest
import test_core_coaching as fixtures
BINDING = fixtures.BINDING


class MultipleTasksTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli
    engine = fixtures.EngineTest.engine
    receipt = fixtures.EngineTest.receipt
    evidence = fixtures.EngineTest.evidence

    def test_new_install_default_is_three(self):
        self.assertEqual(self.cli('setup')['config'].get('max_tasks_per_window'), 3)

    def test_legacy_config_stays_single_until_explicit_update(self):
        path = self.data / 'config.json'
        legacy = self.cli('setup')['config']
        legacy.pop('max_tasks_per_window')
        path.write_text(json.dumps(legacy))
        before = path.read_bytes(), path.stat().st_mtime_ns
        self.assertEqual(self.cli('setup')['config']['max_tasks_per_window'], 1)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        config = self.cli('setup', '--update', '--timezone', 'Europe/Paris')['config']
        self.assertEqual(config['max_tasks_per_window'], 1)
        self.assertEqual(self.cli('setup', '--update', '--max-tasks-per-window', '4')['config']['max_tasks_per_window'], 4)

    def test_terminal_checkins_show_maximum_before_keep_or_customize(self):
        flags = ('--timezone', 'UTC', '--weekdays', 'mon', '--notification-start', '09:00', '--notification-end', '17:00', '--max-unanswered-followups', '2', '--min-followup-interval', '30', '--max-followup-interval', '120')
        import subprocess
        import sys
        from test_cli_core import CLITest
        # Use the real isolated launcher, not mocked input/prompt functions.
        command = [sys.executable, '-I', '-B', str(fixtures.SCRIPTS / 'task-coach.py'), '--data-dir', str(self.data), 'setup', '--update', '--interactive', *flags]
        kept = subprocess.run(command, input='discord\nkeep\n', capture_output=True, text=True)
        self.assertEqual(kept.returncode, 0, kept.stderr)
        self.assertIn('Current maximum distinct tasks per window: 3', kept.stderr)
        self.assertIn('Keep or customize?', kept.stderr)
        changed = subprocess.run(command, input='discord\ncustomize\n5\n', capture_output=True, text=True)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        self.assertEqual(json.loads(changed.stdout)['config']['max_tasks_per_window'], 5)
        local = subprocess.run(command, input='local\n', capture_output=True, text=True)
        self.assertEqual(local.returncode, 0, local.stderr)
        self.assertNotIn('tasks per window', local.stderr)

    def test_invalid_maximum_never_changes_saved_config(self):
        from task_coach.cli import validate_config
        path = self.data / 'config.json'
        before = path.read_bytes()
        for value in (0, -1, 11, True, 1.5, '3', None):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'tasks per window'):
                validate_config(dict(json.loads(before), max_tasks_per_window=value))
        self.assertEqual(path.read_bytes(), before)

    def test_three_distinct_sequences_survive_restart_and_owner_reply(self):
        from task_coach.coaching import instant
        self.cli('add', 'Second fictional task')
        self.cli('add', 'Third fictional task')
        engine = self.engine()
        engine.prepare(binding=BINDING, now='2030-01-07T08:00:00Z')
        root = engine.status()['episode']
        sequences = [root] + root.get('next_tasks', [])
        self.assertEqual(len(sequences), 3)
        self.assertEqual(len({s['task_id'] for s in sequences}), 3)
        for a, b in zip(sequences, sequences[1:]):
            self.assertGreaterEqual((instant(b['events'][0]['slot']) - instant(a['events'][-1]['expires'])).total_seconds(), 30*60)
        first = sequences[0]['events'][0]
        self.assertTrue(engine.tick(binding=BINDING, now=first['slot'])['wakeAgent'])
        engine.acknowledge(self.receipt(first), now=first['slot'])
        engine.stop(first['token'], BINDING)
        for sequence in sequences[1:]:
            event = sequence['events'][0]
            engine = self.engine(999)
            due = engine.prepare(binding=BINDING, now=event['slot'])
            self.assertTrue(due['wakeAgent'], due)
            self.assertEqual(due['intent']['task_id'], sequence['task_id'])
            self.assertIsNone(due['previous'])
            self.assertTrue(engine.tick(binding=BINDING, now=event['slot'])['wakeAgent'])
            engine.acknowledge(self.receipt(event), now=event['slot'])
            engine.stop(first['token'], BINDING)  # late A reply never stops B
            engine.stop(event['token'], BINDING)
        self.assertEqual(engine.status()['deliveries'], 3)

    def test_runtime_two_tasks_keep_receipts_and_context_scoped(self):
        from task_coach.driver import Driver
        from task_coach.coaching import instant
        from test_core_driver import BINDING as binding
        import sys
        self.cli('setup', '--update', '--max-tasks-per-window', '2', '--min-followup-interval', '30', '--max-followup-interval', '30')
        self.cli('add', 'Second fictional task')
        runtime = Driver(self.data)
        runtime.coach.rng = __import__('random').Random(1)
        runtime.configure(dict(binding=binding, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        root = runtime.coach.status()['episode']
        tasks = [root] + root['next_tasks']
        sender = self.data.parent / 'fictional-sender'
        history = []
        drafts = []
        def page(now):
            return [dict(binding=binding, channel_id='123', before=None, observed_at=now, result=dict(messages=history))]
        for n, sequence in enumerate(tasks):
            for index, event in enumerate(sequence['events'][:2]):
                now = event['slot']
                token = event['token']
                draft = runtime.draft(token, f'Fictional task {n} check-in {index}', now=now)
                if n and not index:
                    self.assertEqual(runtime.context(binding)['task_id'], tasks[0]['task_id'])
                if index:
                    runtime.observe(token, draft['fence'], page(now), now=now)
                sender.write_text('#!' + sys.executable + '\nprint(' + repr(json.dumps(dict(success=True, message_id=str(100+len(history))))) + ')\n')
                sender.chmod(0o700)
                sent = runtime.dispatch(token, draft['fence'], hermes=str(sender), now=now)
                self.assertIn('candidate_id', sent, sent)
                history.insert(0, dict(id=sent['candidate_id'], content=draft['body'], timestamp=now, author=dict(id='456', bot=True), attachments=[]))
                runtime = Driver(self.data)
                receipt = runtime.confirm(token, draft['fence'], page(now), now=now)
                drafts.append((draft, receipt))
                self.assertEqual(runtime.context(binding, reply_to_message_id=receipt['message_id'])['task_id'], sequence['task_id'])
                if n:
                    self.assertIsNone(runtime.context(binding), 'multiple historical tasks require a trusted target')
                if n:
                    old, old_receipt = drafts[0]
                    self.assertEqual(runtime.confirm(old['token'], old['fence'], [], now=now), old_receipt)
                    runtime.coach.stop(old['token'], binding)
            now = sequence['events'][1]['slot']
            history.insert(0, dict(id=str(100+len(history)), content='Fictional owner reply', timestamp=now, author=dict(id=binding['owner'], bot=False), attachments=[]))
            pages = page(now)
            pages[0]['reply_targets'] = {history[0]['id']: drafts[-1][1]['message_id']}
            self.assertTrue(runtime.engagement(binding, pages, now=now)['engaged'])
        self.assertEqual(runtime.coach.status()['deliveries'], 4)
        self.assertEqual(self.cli('list')[0]['status'], 'open')

    def test_narrow_window_sends_fewer_without_filling_quota(self):
        self.cli('setup', '--update', '--notification-end', '10:10', '--max-unanswered-followups', '0')
        self.cli('add', 'Second fictional task')
        self.cli('add', 'Third fictional task')
        episode = self.engine().preview(binding=BINDING, now='2030-01-07T08:00:00Z', seed=1)['episode']
        self.assertEqual(len([episode] + episode.get('next_tasks', [])), 1)

    def test_legacy_uncertain_send_is_retained_but_next_day_local_work_can_progress(self):
        from task_coach.driver import Driver
        from test_core_driver import BINDING as binding
        self.cli('add', 'Second fictional task')
        runtime = Driver(self.data)
        from test_core_driver import persist_legacy_runtime
        persist_legacy_runtime(runtime, binding=binding)
        runtime.configure(dict(binding=binding, platform='discord', destination='discord:123', channel_id='123', bot_id='456'), confirm=True)
        runtime.preflight(now='2030-01-07T08:00:00Z')
        episode = runtime.coach.status()['episode']
        first = episode['events'][0]
        row = runtime.draft(first['token'], 'Fictional uncertain send', now=first['slot'])
        runtime.dispatch(first['token'], row['fence'], hermes='/nonexistent-fictional-sender', now=first['slot'])
        next_slot = episode['next_tasks'][0]['events'][0]['slot']
        runtime.coach.stop(first['token'], binding)
        self.assertFalse(runtime.preflight(now=next_slot)['wakeAgent'])
        self.assertFalse(runtime.preflight(now='2030-01-08T08:00:00Z')['wakeAgent'])
        # The legacy day's uncertainty never retries; later local-first work is independent.
        journal = runtime.status()['outbox']
        runtime.coach.prepare(binding=binding, now='2030-01-08T08:00:00Z')
        tomorrow = runtime.coach.status()['episode']['events'][0]
        self.assertTrue(Driver(self.data).preflight(now=tomorrow['slot'])['wakeAgent'])
        self.assertEqual(runtime.status()['outbox'], journal)

    def test_late_receipt_and_unverified_history_stop_entire_window(self):
        from task_coach.coaching import instant
        from datetime import timedelta
        self.cli('add', 'Second fictional task')
        self.cli('setup', '--update', '--min-followup-interval', '30', '--max-followup-interval', '30')
        for mode in ('late-receipt', 'missing-history'):
            with self.subTest(mode=mode):
                (self.data / 'coach.sqlite3').unlink(missing_ok=True)
                engine = self.engine()
                engine.prepare(binding=BINDING, now='2030-01-07T08:00:00Z')
                episode = engine.status()['episode']
                first = episode['events'][0]
                engine.tick(binding=BINDING, now=first['slot'])
                if mode == 'late-receipt':
                    engine.reconcile(self.receipt(first), now=instant(first['expires'])+timedelta(seconds=1))
                else:
                    engine.acknowledge(self.receipt(first), now=first['slot'])
                    engine.tick(binding=BINDING, now=episode['events'][1]['slot'])
                later = episode['next_tasks'][0]['events'][0]['slot']
                self.assertFalse(engine.prepare(binding=BINDING, now=later)['wakeAgent'])

    def test_legacy_version_one_receipts_and_config_snapshot_remain_usable(self):
        self.cli('setup', '--update', '--max-tasks-per-window', '1', '--min-followup-interval', '1', '--max-followup-interval', '1')
        engine = self.engine()
        engine.prepare(binding=BINDING, now='2030-01-07T08:00:00Z')
        events = engine.status()['episode']['events']
        engine.tick(binding=BINDING, now=events[0]['slot'])
        receipt = self.receipt(events[0])
        engine.acknowledge(receipt, now=events[0]['slot'])
        # Exact historical disk representation, including an in-flight episode.
        with engine.transaction() as state:
            state['episode']['config'].pop('max_tasks_per_window')
        path = self.data / 'config.json'
        config = json.loads(path.read_text())
        config.pop('max_tasks_per_window')
        path.write_text(json.dumps(config))
        state = engine.status()
        self.assertEqual(state['version'], 1)
        self.assertEqual(state['episode']['events'][0]['receipt'], receipt)
        from task_coach.coaching import instant
        result = self.engine(99).tick(binding=BINDING, now=events[1]['slot'], evidence=self.evidence(events[0], instant(events[1]['slot'])))
        self.assertTrue(result['wakeAgent'], result)
        self.assertNotIn('max_tasks_per_window', engine.status()['episode']['config'])
