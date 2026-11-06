"""Guard the published multi-task onboarding contract and Markdown format."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class MultiTaskDocumentationTest(unittest.TestCase):
    def test_readme_contains_markdown_not_reader_line_numbers(self):
        text = (ROOT / 'README.md').read_text()
        self.assertTrue(text.startswith('# Hermes Task Coach\n'))
        self.assertIsNone(re.search(r'^\d+\|', text, re.MULTILINE))
        self.assertIn('--max-tasks-per-window', text)

    def test_chat_setup_shows_two_before_keep_or_customize(self):
        text = (ROOT / 'skills/task-coach/SKILL.md').read_text()
        self.assertIn('The default is up to 2 distinct tasks', text)
        self.assertIn('Keep the default of 2, or customize?', text)
        self.assertIn('--max-tasks-per-window 2', text)
        self.assertIn('later task check-ins remain scheduled', text)
        self.assertNotIn('then ask. if', text)

    def test_native_runtime_documents_task_scoped_engagement(self):
        text = (ROOT / 'skills/task-coach/references/native-runtime.md').read_text()
        self.assertIn('max_tasks_per_window', text)
        self.assertIn('later task check-ins remain scheduled', text)

    def test_capture_contract_discloses_real_history_limit_and_trusted_inputs(self):
        text = (ROOT / 'skills/task-coach/references/native-runtime.md').read_text()
        for token in ('reply_targets', '--reply-to-message-id', '--inbound-message-id',
                      'ambiguous-engagement', 'does **not** expose `message_reference`',
                      'not an implemented gateway hook', 'does **not** prove a reply reference'):
            self.assertIn(token, text)
