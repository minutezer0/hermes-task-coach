"""Generated guidance and public consent contract; fictional data only."""
import tempfile
import unittest
from pathlib import Path
import test_core_coaching
from task_coach.driver import Driver

ROOT = Path(__file__).resolve().parents[1]
ROUTE = dict(binding=dict(owner='owner-test', profile='profile-test', account='account-test', chat='123', thread='none'), platform='discord', destination='discord:123', channel_id='123', bot_id='456')

class HistoryGuidanceTest(unittest.TestCase):
    def test_capabilities_separates_consent_inventory_and_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = Driver(Path(directory) / 'data')
            import contextlib, io
            from task_coach.cli import main
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--data-dir', str(driver.directory), 'init']), 0)
            driver.configure(ROUTE, confirm=True)
            before = (driver.directory / 'outbox.sqlite3').read_bytes()
            caps = driver.capabilities(history_available=True)
            self.assertFalse(caps['history']['consent']['enabled'])
            self.assertFalse(caps['history']['routine_reads_allowed'])
            self.assertFalse(caps['history']['delivery_verified'])
            self.assertEqual((driver.directory / 'outbox.sqlite3').read_bytes(), before)
            driver.history_preference(enabled=True, route=ROUTE, confirm=True)
            caps = driver.capabilities(history_available=False)
            self.assertTrue(caps['history']['consent']['enabled'])
            self.assertEqual(caps['history']['state'], 'unavailable')
            self.assertFalse(caps['history']['routine_reads_allowed'])

    def test_native_preview_prohibits_routine_history_even_with_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            driver = Driver(Path(directory) / 'data')
            import contextlib, io
            from task_coach.cli import main
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--data-dir', str(driver.directory), 'init']), 0)
            driver.configure(ROUTE, confirm=True)
            for enabled in (False, True):
                if enabled:
                    driver.history_preference(enabled=True, route=ROUTE, confirm=True)
                before = (driver.directory / 'outbox.sqlite3').read_bytes()
                plan = driver.native_plan('/fictional/profile', python='/usr/bin/python3', helper='/fictional/helper.py', hermes='/fictional/hermes')
                self.assertEqual((driver.directory / 'outbox.sqlite3').read_bytes(), before)
                self.assertIn('Never fetch Discord history in routine cron', plan['cron_argv'][4])
                self.assertIn('runtime history-plan --purpose', plan['inbound_instruction'])
                self.assertIn('--history-plan-file', plan['inbound_instruction'])
                self.assertIn('caller-asserted', plan['inbound_instruction'])
                self.assertTrue(plan['initially_paused'])
                self.assertFalse(plan['history_policy']['routine_reads_allowed'])
                self.assertIn('--failure-deliver', plan['cron_argv'])

    def test_native_preview_has_no_fresh_store_or_profile_side_effects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / 'missing-data'
            profile = root / 'missing-profile'
            Driver(data).native_plan(profile, python='/usr/bin/python3', helper='/fictional/helper.py', hermes='/fictional/hermes')
            self.assertFalse(data.exists())
            self.assertFalse(profile.exists())

    def test_public_onboarding_and_versions(self):
        skill = (ROOT / 'skills/task-coach/SKILL.md').read_text()
        self.assertIn('Default: No', skill)
        self.assertIn('unrelated messages', skill)
        self.assertIn('input tokens', skill)
        self.assertIn('runtime history-preference --enable --route', skill)
        self.assertIn('runtime history-preference --disable', skill)
        self.assertIn('Local-only setup never asks', skill)
        self.assertLess(skill.index('Confirm the exact route from trusted context'), skill.index('Default: No'))
        for name in ('skills/task-coach/SKILL.md', 'skills/task-coach/references/native-runtime.md'):
            text = (ROOT / name).read_text()
            self.assertIn('131072', text)
            self.assertIn('--history-plan-file', text)
            self.assertNotIn('limit=100', text)
            self.assertNotIn('Page backward', text)
        self.assertIn('1.0.1', skill)

if __name__ == '__main__':
    unittest.main()
