"""The published instructions must describe the implemented guarded lifecycle."""
from pathlib import Path
import unittest
import test_core_coaching  # expose the installed-style package path
from task_coach.driver import Driver

ROOT = Path(__file__).resolve().parents[1]


class RetryDocumentationTest(unittest.TestCase):
    def test_all_product_guides_describe_bounded_native_retries_and_retirement(self):
        for name in ('README.md', 'skills/task-coach/SKILL.md', 'skills/task-coach/references/native-runtime.md'):
            text = (ROOT / name).read_text()
            with self.subTest(name=name):
                if name.endswith('SKILL.md'):
                    self.assertIn('Legacy episode compatibility', text)
                    self.assertIn('Routine cron must not obtain history', text)
                    self.assertIn('legacy clarification resolution/dismissal', text)
                    self.assertIn('references/native-runtime.md', text)
                else:
                    self.assertIn('clarification retries', text)
                    self.assertIn('next allowed notification window', text)
                    self.assertIn('candidate titles', text)
                self.assertNotIn('Never send an extra unattended clarification', text)
                self.assertNotIn('Do not send clarification\nquestions from cron', text)

    def test_reference_documents_shared_quarantine_and_independent_engine_fence(self):
        text = (ROOT / 'skills/task-coach/references/native-runtime.md').read_text()
        self.assertIn('clarification_responses', text)
        self.assertIn('unassigned', text)
        self.assertIn('tick-to-outbox crash gap', text)
        self.assertIn('first preflight', text)
        self.assertNotIn('explicit choice/dismissal of its own question, never another question.', text)

    def test_generated_fresh_native_instructions_use_default_local_first_policy(self):
        plan = Driver(ROOT).native_plan('/fictional/profile', python='/fictional/python', helper='/fictional/helper', hermes='/fictional/hermes')
        prompt = plan['cron_argv'][4]
        self.assertIn('openers AND followups', prompt)
        self.assertIn('Never fetch Discord history in routine cron', prompt)
        self.assertIn('Optional history failure', prompt)
        self.assertIn('preserved legacy episode retains its honest history gates', prompt)
        self.assertIn('runtime record-engagement', plan['inbound_instruction'])
        self.assertIn('Ask naturally which task', plan['inbound_instruction'])
        self.assertIn('only an explicitly requested reply-recovery', plan['inbound_instruction'])
        self.assertNotIn('fresh complete Discord history', prompt)
        self.assertNotIn('never via unattended sends', plan['inbound_instruction'])
