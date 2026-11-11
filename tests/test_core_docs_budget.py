"""Keep the published docs lean: budgets, no release labels, no duplicated prose."""
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BUDGETS = {
    'skills/task-coach/SKILL.md': 480,
    'skills/task-coach/references/native-runtime.md': 700,
    'skills/task-coach/references/coaching.md': 150,
    'README.md': 320,
    'docs/command-reference.md': 300,
}


def paragraphs(text):
    # Fenced code blocks are commands, not prose: an identical command example in
    # two documents is not duplication. Only prose is compared.
    text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
    blocks = []
    for block in re.split(r'\n\s*\n', text):
        normalized = ' '.join(block.split())
        if len(normalized) >= 200:
            blocks.append((hashlib.sha256(normalized.encode()).hexdigest(), normalized))
    return blocks


class DocumentationBudgetTest(unittest.TestCase):
    def test_each_document_stays_within_its_line_budget(self):
        for name, budget in BUDGETS.items():
            with self.subTest(path=name):
                lines = (ROOT / name).read_text().splitlines()
                self.assertLessEqual(len(lines), budget, f'{name} is {len(lines)} lines')

    def test_no_heading_carries_a_release_or_version_label(self):
        for name in BUDGETS:
            text = (ROOT / name).read_text()
            with self.subTest(path=name):
                for heading in re.findall(r'^#{1,3} .*$', text, re.MULTILINE):
                    self.assertIsNone(
                        re.search(r'\brc\d+\b|0\.1\.0|v1\.0', heading, re.I),
                        f'release label in heading: {heading}')

    def test_no_long_paragraph_appears_in_two_documents(self):
        seen = {}
        for name in BUDGETS:
            for digest, body in paragraphs((ROOT / name).read_text()):
                seen.setdefault(digest, []).append(name)
        shared = [names for names in seen.values() if len(names) > 1]
        self.assertEqual(shared, [], f'duplicated paragraphs across {shared}')

    def test_removed_surfaces_are_not_documented(self):
        for name in BUDGETS:
            text = (ROOT / name).read_text()
            with self.subTest(path=name):
                self.assertNotIn('upgrade-local-first', text)
                self.assertNotIn('--destination', text)
                self.assertIsNone(re.search(r'\bmigrate\b', text))


if __name__ == '__main__':
    unittest.main()
