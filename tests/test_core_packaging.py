from pathlib import Path
import tomllib
import unittest


class PackagingTest(unittest.TestCase):
    def test_release_versions_agree(self):
        root = Path(__file__).resolve().parents[1]
        package = tomllib.loads((root / 'pyproject.toml').read_text())['project']['version']
        skill = (root / 'skills/task-coach/SKILL.md').read_text().split('version: ', 1)[1].splitlines()[0]
        self.assertEqual(package, '1.0.2')
        self.assertEqual(skill, package)

    def test_packaged_console_entrypoint(self):
        path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        self.assertTrue(path.exists(), "packaging metadata is missing")
        project = tomllib.loads(path.read_text())["project"]
        self.assertEqual(project["name"], "task-coach")
        self.assertEqual(project["requires-python"], ">=3.11")
        self.assertEqual(project["dependencies"], [])
        self.assertEqual(project["scripts"], {"task-coach": "task_coach.cli:main"})
