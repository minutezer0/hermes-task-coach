"""Desktop integration tests use fictional stores/metadata and no native scheduler."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, redirect_stdout
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import random
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'plugins/task-coach-desktop/skills/task-coach-desktop/scripts'
sys.path.insert(0, str(ROOT / 'skills/task-coach/scripts'))
sys.path.insert(0, str(SCRIPTS))
from desktop_runtime import DesktopRuntime, check_scope
from task_coach.cli import main as core_main
from task_coach.coaching import instant

CHAT = 'fictional-desktop-conversation'
NOW = '2030-01-07T09:00:00Z'


class DesktopRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-coach-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'desktop-store'
        self.task('setup', '--timezone', 'UTC')
        self.runtime = DesktopRuntime(self.data, rng=random.Random(1))
        self.runtime.initialize()
        self.runtime.configure(CHAT, confirm=True)
        self.first = self.task('add', 'Fictional gutters')

    def task(self, *args):
        capture = io.StringIO()
        with redirect_stdout(capture):
            self.assertEqual(core_main(['--data-dir', str(self.data), *args]), 0)
        return json.loads(capture.getvalue())

    def activate(self):
        self.runtime.activate(CHAT, 'fictional-native-job', confirm=True)

    def opener(self):
        self.activate()
        self.runtime.preflight(CHAT, now=NOW)
        event = self.runtime.coach.status()['episode']['events'][0]
        prepared = self.runtime.preflight(CHAT, now=event['slot'])
        self.assertTrue(prepared['wakeAgent'])
        claim = self.runtime.claim(CHAT, event['token'], 'What is one small step?', prepared['task_hash'], now=event['slot'])
        return event, claim

    def test_task_days_suppress_outbound_without_blocking_task_edits(self):
        self.task('update', str(self.first['id']), '--check-in-days', 'weekends')
        self.activate()
        self.assertEqual(self.runtime.preflight(CHAT, now=NOW)['reason'], 'no-eligible-task')
        self.assertFalse(self.runtime.status()['outputs'])
        self.assertEqual(self.task('update', str(self.first['id']), '--title', 'Updated on Monday')['title'], 'Updated on Monday')

    def test_engagement_remains_available_after_task_day_preference_changes(self):
        event, _ = self.opener()
        self.task('update', str(self.first['id']), '--check-in-days', 'weekends')
        result = self.runtime.engage(CHAT, event['token'], 'fictional-off-day-reply', 'engaged', now=event['slot'])
        self.assertTrue(result['recorded'])
        self.assertEqual(self.task('show', str(self.first['id']))['status'], 'open')

    def test_configure_and_activation_require_separate_approvals(self):
        with self.assertRaises(ValueError):
            self.runtime.configure(CHAT)
        with self.assertRaises(ValueError):
            self.runtime.activate(CHAT, 'fictional-native-job')
        result = self.runtime.preflight(CHAT, now=NOW)
        self.assertEqual(result, dict(wakeAgent=False, reason='desktop-paused'))
        self.assertFalse((self.data / 'coach.sqlite3').exists())
        self.activate()
        self.assertFalse(self.runtime.status()['scheduler_verified'])

    def test_status_and_plan_are_readonly_and_never_claim_activation(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.data.iterdir()}
        plan = self.runtime.native_plan(CHAT, SCRIPTS / 'task-coach-desktop.py')
        self.assertTrue(plan['initially_paused'])
        self.assertFalse(plan['installed'])
        self.assertFalse(plan['live_verified'])
        self.assertIn('BYDAY=MO,TU,WE,TH,FR', plan['cadence'])
        self.assertIn('BYHOUR=9,10,11,12,13,14,15,16;', plan['cadence'])
        self.assertIn(str(self.data), plan['preflight_argv'])
        self.runtime.status()
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.data.iterdir()})

    def test_no_hermes_outbox_or_transport_is_created(self):
        event, result = self.opener()
        self.assertEqual(result['delivery'], 'unverified-output-attempt')
        self.assertIsNone(self.runtime.status()['outputs'][event['token']]['receipt'])
        self.assertFalse((self.data / 'outbox.sqlite3').exists())

    def test_wrong_conversation_cannot_claim_or_record_engagement(self):
        self.activate()
        with self.assertRaisesRegex(ValueError, 'conversation'):
            self.runtime.preflight('other-fictional-chat', now=NOW)
        event, result = self.opener()
        with self.assertRaisesRegex(ValueError, 'conversation'):
            self.runtime.engage('other-fictional-chat', event['token'], 'fictional-inbound', 'engaged', now=event['slot'])

    def test_duplicate_claim_after_restart_cannot_emit_again(self):
        event, result = self.opener()
        restarted = DesktopRuntime(self.data)
        with self.assertRaises(ValueError):
            restarted.claim(CHAT, event['token'], result['output'], 'old-hash', now=event['slot'])
        self.assertEqual(len(restarted.status()['outputs']), 1)

    def test_missing_output_metadata_does_not_authorize_followups(self):
        event, result = self.opener()
        followup = self.runtime.coach.status()['episode']['events'][1]
        self.assertFalse(self.runtime.preflight(CHAT, now=followup['slot'])['wakeAgent'])
        self.assertEqual(self.runtime.status()['outputs_without_metadata'], 1)

    def test_genuine_output_metadata_allows_bounded_followup(self):
        event, result = self.opener()
        self.runtime.record_output(CHAT, event['token'], 'fictional-native-assistant-message', event['slot'], now=event['slot'])
        # An identical metadata retry is idempotent, not a second delivery.
        self.runtime.record_output(CHAT, event['token'], 'fictional-native-assistant-message', event['slot'], now=event['slot'])
        followup = self.runtime.coach.status()['episode']['events'][1]
        offered = self.runtime.preflight(CHAT, now=followup['slot'])
        self.assertTrue(offered['wakeAgent'])
        self.assertEqual(offered['intent']['index'], 1)
        with self.assertRaises(ValueError):
            self.runtime.record_output(CHAT, event['token'], 'different-fictional-message', event['slot'], now=followup['slot'])

    def test_output_metadata_rejects_future_and_unknown_attempt(self):
        event, result = self.opener()
        with self.assertRaises(ValueError):
            self.runtime.record_output(CHAT, event['token'], 'fictional-message', '2030-01-08T09:00:00Z', now=event['slot'])
        with self.assertRaises(ValueError):
            self.runtime.record_output(CHAT, 'unknown', 'fictional-message', event['slot'], now=event['slot'])

    def test_task_edit_between_draft_and_claim_refuses_stale_body(self):
        self.activate()
        self.runtime.preflight(CHAT, now=NOW)
        event = self.runtime.coach.status()['episode']['events'][0]
        prepared = self.runtime.preflight(CHAT, now=event['slot'])
        self.task('update', str(self.first['id']), '--title', 'Revised fictional task')
        with self.assertRaisesRegex(ValueError, 'task changed'):
            self.runtime.claim(CHAT, event['token'], 'Stale title', prepared['task_hash'], now=event['slot'])
        self.assertFalse(self.runtime.status()['outputs'])

    def test_completion_between_draft_and_claim_refuses_output(self):
        self.activate()
        self.runtime.preflight(CHAT, now=NOW)
        event = self.runtime.coach.status()['episode']['events'][0]
        prepared = self.runtime.preflight(CHAT, now=event['slot'])
        self.task('done', str(self.first['id']))
        with self.assertRaises(ValueError):
            self.runtime.claim(CHAT, event['token'], 'Stale completed task', prepared['task_hash'], now=event['slot'])

    def test_engagement_stops_followups_without_completing_task(self):
        event, result = self.opener()
        self.runtime.record_output(CHAT, event['token'], 'fictional-assistant', event['slot'], now=event['slot'])
        self.runtime.engage(CHAT, event['token'], 'fictional-owner-reply', 'engaged', now=event['slot'])
        followup = self.runtime.coach.status()['episode']['events'][1]
        self.assertFalse(self.runtime.preflight(CHAT, now=followup['slot'])['wakeAgent'])
        self.assertEqual(self.task('show', str(self.first['id']))['status'], 'open')

    def test_smart_snooze_holds_other_tasks_and_expires(self):
        self.task('add', 'Second fictional task')
        self.runtime.smart_snooze(True)
        event, result = self.opener()
        later = self.runtime.coach.status()['episode']['next_tasks'][0]['events'][0]
        engaged = self.runtime.engage(CHAT, event['token'], 'fictional-start-work', 'start-work', now=event['slot'])
        self.assertEqual(engaged['hold']['expires'], '2030-01-07T17:00:00+00:00')
        self.assertEqual(self.runtime.preflight(CHAT, now=later['slot'])['reason'], 'smart-snooze')
        self.assertNotEqual(self.runtime.preflight(CHAT, now='2030-01-08T09:00:00Z').get('reason'), 'smart-snooze')

    def test_general_engagement_does_not_hold_other_tasks(self):
        self.task('add', 'Second fictional task')
        self.runtime.smart_snooze(True)
        event, result = self.opener()
        later = self.runtime.coach.status()['episode']['next_tasks'][0]['events'][0]
        self.runtime.engage(CHAT, event['token'], 'fictional-general-reply', 'engaged', now=event['slot'])
        self.assertIsNone(self.runtime.status()['hold'])
        self.assertTrue(self.runtime.preflight(CHAT, now=later['slot'])['wakeAgent'])

    def test_disable_and_replay_never_recreate_hold(self):
        self.runtime.smart_snooze(True)
        event, result = self.opener()
        self.runtime.engage(CHAT, event['token'], 'fictional-start', 'start-work', now=event['slot'])
        self.runtime.smart_snooze(False)
        self.runtime.smart_snooze(True)
        duplicate = self.runtime.engage(CHAT, event['token'], 'fictional-start', 'start-work', now=event['slot'])
        self.assertTrue(duplicate['duplicate'])
        self.assertIsNone(duplicate['hold'])
        with self.assertRaises(ValueError):
            self.runtime.engage(CHAT, event['token'], 'fictional-start', 'engaged', now=event['slot'])

    def test_start_recorded_while_off_is_not_reinterpreted(self):
        event, result = self.opener()
        self.runtime.engage(CHAT, event['token'], 'fictional-start', 'start-work', now=event['slot'])
        self.runtime.smart_snooze(True)
        self.runtime.engage(CHAT, event['token'], 'fictional-start', 'start-work', now=event['slot'])
        self.assertIsNone(self.runtime.status()['hold'])

    def test_completed_task_cannot_start_a_smart_snooze_hold(self):
        self.runtime.smart_snooze(True)
        event, result = self.opener()
        self.task('done', str(self.first['id']))
        with self.assertRaises(ValueError):
            self.runtime.engage(CHAT, event['token'], 'fictional-late-start', 'start-work', now=event['slot'])
        self.assertIsNone(self.runtime.status()['hold'])

    def test_pause_reactivation_does_not_revive_stopped_sequence(self):
        event, result = self.opener()
        self.runtime.pause()
        self.assertFalse(self.runtime.preflight(CHAT, now=event['slot'])['wakeAgent'])
        self.activate()
        self.assertFalse(self.runtime.preflight(CHAT, now=event['slot'])['wakeAgent'])

    def test_future_recurring_task_does_not_persist_empty_daily_stop(self):
        self.task('done', str(self.first['id']))
        self.task('add', 'Fictional filter', '--repeat', '3 months', '--due', '2030-02-01')
        self.activate()
        self.assertEqual(self.runtime.preflight(CHAT, now=NOW)['reason'], 'no-eligible-task')
        self.assertIsNone(self.runtime.coach.status()['episode'])
        self.task('add', 'Later user-requested fictional task')
        self.runtime.preflight(CHAT, now=NOW)
        self.assertIsNotNone(self.runtime.coach.status()['episode']['task_id'])

    def test_first_late_wake_plans_future_slots_only(self):
        self.activate()
        self.runtime.preflight(CHAT, now='2030-01-07T15:00:00Z')
        events = self.runtime.coach.status()['episode']['events']
        self.assertTrue(all(instant(e['slot']) > instant('2030-01-07T15:00:00Z') for e in events))

    def test_clock_regression_refuses_before_state_changes(self):
        self.runtime.preflight(CHAT, now=NOW)
        before = (self.data / 'desktop.sqlite3').read_bytes()
        with self.assertRaisesRegex(ValueError, 'regressed'):
            self.runtime.preflight(CHAT, now='2030-01-07T08:00:00Z')
        self.assertEqual((self.data / 'desktop.sqlite3').read_bytes(), before)

    def test_bad_runtime_state_is_not_repaired(self):
        path = self.data / 'desktop.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            state = json.loads(db.execute('SELECT value FROM desktop').fetchone()[0])
            state['unexpected'] = True
            db.execute('UPDATE desktop SET value=?', (json.dumps(state),))
        before = path.read_bytes(), path.stat().st_mtime_ns
        with self.assertRaises(ValueError):
            self.runtime.status()
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_test_preparation_is_one_event_and_never_enables_schedule(self):
        with self.assertRaises(ValueError):
            self.runtime.prepare_test(CHAT, now=NOW)
        result = self.runtime.prepare_test(CHAT, confirm=True, now=NOW)
        episode = self.runtime.coach.status()['episode']
        self.assertEqual(len(episode['events']), 1)
        self.assertNotIn('next_tasks', episode)
        self.assertFalse(self.runtime.status()['enabled'])
        offered = self.runtime.preflight(CHAT, now=NOW)
        self.assertTrue(offered['wakeAgent'])
        self.runtime.claim(CHAT, result['token'], 'Fictional test opener', offered['task_hash'], now=NOW)
        self.assertFalse(self.runtime.preflight(CHAT, now=NOW)['wakeAgent'])
        with self.assertRaises(ValueError):
            self.runtime.prepare_test(CHAT, confirm=True, now=NOW)

    def test_test_refuses_outside_window_existing_episode_and_global_pause(self):
        with self.assertRaises(ValueError):
            self.runtime.prepare_test(CHAT, confirm=True, now='2030-01-07T08:00:00Z')
        self.runtime.coach.pause(True)
        with self.assertRaises(ValueError):
            self.runtime.prepare_test(CHAT, confirm=True, now=NOW)

    def test_tampered_hold_expiry_refuses_without_repair(self):
        self.runtime.smart_snooze(True)
        event, result = self.opener()
        self.runtime.engage(CHAT, event['token'], 'fictional-start', 'start-work', now=event['slot'])
        path = self.data / 'desktop.sqlite3'
        with closing(sqlite3.connect(path)) as db, db:
            state = json.loads(db.execute('SELECT value FROM desktop').fetchone()[0])
            state['hold']['expires'] = '2030-01-08T17:00:00Z'
            db.execute('UPDATE desktop SET value=?', (json.dumps(state),))
        before = path.read_bytes(), path.stat().st_mtime_ns
        with self.assertRaises(ValueError):
            self.runtime.preflight(CHAT, now=event['slot'])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)

    def test_concurrent_claims_emit_at_most_once(self):
        self.activate()
        self.runtime.preflight(CHAT, now=NOW)
        event = self.runtime.coach.status()['episode']['events'][0]
        offered = self.runtime.preflight(CHAT, now=event['slot'])
        def claim(_):
            try:
                DesktopRuntime(self.data).claim(CHAT, event['token'], 'Fictional concurrent output', offered['task_hash'], now=event['slot'])
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(claim, range(2))), 1)


class DesktopArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop-plugin-artifact-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = dict(HOME=str(self.root / 'fictional-home'),
                        HERMES_HOME=str(self.root / 'fictional-hermes'), PYTHONDONTWRITEBYTECODE='1')

    def invoke(self, helper, *args, ok=True):
        result = subprocess.run([sys.executable, '-I', '-B', str(helper), *args], env=self.env,
                                cwd=self.root, text=True, capture_output=True, timeout=20)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('Traceback', result.stderr)
        return result

    def test_launcher_default_ignores_hermes_and_blocks_foreign_store(self):
        helper = SCRIPTS / 'task-coach-desktop.py'
        self.invoke(helper, 'setup', '--timezone', 'UTC')
        self.invoke(helper, 'add', 'Fictional local-only task')
        self.assertFalse(Path(self.env['HERMES_HOME']).exists())
        store = Path(self.env['HOME']) / '.local/share/task-coach-chatgpt-desktop'
        self.assertTrue((store / 'desktop.sqlite3').is_file())
        self.invoke(helper, '--data-dir', str(Path(self.env['HERMES_HOME']) / 'task-coach'), 'setup', ok=False)
        self.invoke(helper, '--data-dir', str(Path(self.env['HERMES_HOME']) / 'unused' / '..' / 'task-coach'), 'setup', ok=False)
        foreign = self.root / 'foreign'
        with redirect_stdout(io.StringIO()):
            self.assertEqual(core_main(['--data-dir', str(foreign), 'setup']), 0)
        before = {p.name: p.read_bytes() for p in foreign.iterdir()}
        self.invoke(helper, '--data-dir', str(foreign), 'setup', ok=False)
        self.assertEqual(before, {p.name: p.read_bytes() for p in foreign.iterdir()})

    def test_help_does_not_initialize_and_hermes_runtime_is_not_exposed(self):
        helper = SCRIPTS / 'task-coach-desktop.py'
        self.invoke(helper, '--help')
        self.assertIn('record-output', self.invoke(helper, 'desktop', '--help').stdout)
        self.invoke(helper, 'runtime', 'configure', ok=False)
        self.invoke(helper, 'setup', '--interactive', ok=False)
        self.assertFalse(Path(self.env['HOME']).exists())

    def test_corrupt_runtime_blocks_task_mutation_before_any_write(self):
        helper = SCRIPTS / 'task-coach-desktop.py'
        self.invoke(helper, 'setup', '--timezone', 'UTC')
        data = Path(self.env['HOME']) / '.local/share/task-coach-chatgpt-desktop'
        with closing(sqlite3.connect(data / 'desktop.sqlite3')) as db, db:
            db.execute('UPDATE desktop SET value=?', ('{"version":999}',))
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in data.iterdir()}
        self.invoke(helper, 'add', 'Must not be added', ok=False)
        self.invoke(helper, 'setup', '--update', '--timezone', 'Europe/Paris', ok=False)
        self.assertEqual(before, {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in data.iterdir()})

    def test_zip_is_self_contained_reproducible_and_preserves_core_bytes(self):
        spec = importlib.util.spec_from_file_location('desktop_builder', ROOT / 'scripts/build-chatgpt-plugin.py')
        builder = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(builder)
        first, second = self.root / 'first.zip', self.root / 'second.zip'
        self.assertEqual(builder.build(first)['sha256'], builder.build(second)['sha256'])
        with zipfile.ZipFile(first) as archive:
            names = archive.namelist()
            self.assertFalse(any(name.endswith(('/driver.py', '/clarification.py')) for name in names))
            self.assertFalse(any('tests/' in name or 'fixtures/' in name for name in names))
            self.assertFalse(any(name.endswith(('.sqlite3', '.pyc')) or 'config.json' in name for name in names))
            manifest = json.loads(archive.read('build-manifest.json'))
            for name, digest in manifest['sha256'].items():
                self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)
            for module in builder.MODULES:
                self.assertEqual(archive.read(builder.SKILL + 'scripts/task_coach/' + module), (builder.CORE / module).read_bytes())
            installed = self.root / 'relocated desktop plugin'
            archive.extractall(installed)
        helper = installed / builder.SKILL / 'scripts/task-coach-desktop.py'
        help_text = self.invoke(helper, 'setup', '--help').stdout
        self.assertNotIn('Discord', help_text)
        self.assertIn('native scheduling', help_text)
        self.invoke(helper, 'setup', '--timezone', 'America/Vancouver')
        task = json.loads(self.invoke(helper, 'add', 'Fictional installed task').stdout)
        self.assertEqual(task['title'], 'Fictional installed task')
        self.assertEqual(json.loads(self.invoke(helper, 'list').stdout)[0]['id'], task['id'])
        self.invoke(helper, 'update', str(task['id']), '--notes', '- [ ] Fictional step')
        checklist = json.loads(self.invoke(helper, 'checklist', 'show', str(task['id'])).stdout)
        self.invoke(helper, 'checklist', 'check', str(task['id']), '1', '--expected-notes-digest', checklist['notes_digest'])
        self.invoke(helper, 'desktop', 'configure', '--conversation', CHAT, '--confirm-setup')
        status = json.loads(self.invoke(helper, 'desktop', 'status').stdout)
        self.assertFalse(status['enabled'])
        self.assertFalse(Path(self.env['HERMES_HOME']).exists())


if __name__ == '__main__':
    unittest.main()
