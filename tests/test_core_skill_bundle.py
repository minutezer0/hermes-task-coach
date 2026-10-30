from pathlib import Path
import re
import subprocess
import tomllib
import unittest


class SkillBundleTest(unittest.TestCase):
    def test_skill_documents_every_bundled_runtime_resource(self):
        root = Path(__file__).resolve().parents[1]
        skill = root / "skills" / "task-coach"
        text = (skill / "SKILL.md").read_text()
        links = set(re.findall(r"\]\(([^)]+)\)", text))
        runtime = {str(path.relative_to(skill)) for path in (skill / "scripts").rglob("*.py")}
        self.assertTrue(runtime)
        self.assertTrue(runtime <= links, runtime - links)
        self.assertIn("references/LICENSE", links)
        self.assertEqual((skill / "references" / "LICENSE").read_bytes(), (root / "LICENSE").read_bytes())
        self.assertIn("skill_dir", text)
        self.assertIn('python3 "<skill_dir>/scripts/task-coach.py"', text)
        self.assertIn("non-interactive", text)
        self.assertFalse((root / "src" / "task_coach").exists())

    def test_allowlist_includes_bundle_but_excludes_state_and_binaries(self):
        root = Path(__file__).resolve().parents[1]
        allowed = ["skills/task-coach/SKILL.md", "skills/task-coach/references/LICENSE",
                   "skills/task-coach/scripts/task-coach.py", "skills/task-coach/scripts/task_coach/__init__.py",
                   "skills/task-coach/scripts/task_coach/__main__.py", "skills/task-coach/scripts/task_coach/cli.py",
                   "tests/test_core_installed_skill.py", "tests/test_core_wheel.py"]
        blocked = ["skills/task-coach/scripts/task-coach", "skills/task-coach/scripts/helper.so",
                   "skills/task-coach/scripts/task_coach/cli.pyc", "skills/task-coach/scripts/task_coach/tasks.sqlite3",
                   "skills/task-coach/config.json", "skills/task-coach/references/tasks.json",
                   "skills/task-coach/scripts/task_coach/.env", "skills/task-coach/scripts/task_coach/__pycache__/cli.py",
                   "src/task_coach/cli.py", "dist/task_coach.whl"]
        for expected, paths in ((1, allowed), (0, blocked)):
            for path in paths:
                with self.subTest(path=path):
                    result = subprocess.run(["git", "check-ignore", "--no-index", "-q", path], cwd=root)
                    self.assertEqual(result.returncode, expected, path)

    def test_readme_primary_install_is_the_self_contained_skill(self):
        root = Path(__file__).resolve().parents[1]
        text = (root / "README.md").read_text()
        install = "hermes skills install minutezer0/hermes-task-coach/skills/task-coach"
        self.assertIn(install, text)
        self.assertLess(text.index(install), text.index("pip install"))
        self.assertIn("does not itself launch a chat", text)
        self.assertIn("ask Hermes to set up Task Coach", text)
        self.assertNotIn("PYTHONPATH=src", text)
        self.assertNotIn("both are needed", text)

    def test_packaging_metadata_declares_the_companion_skill(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text())
        files = metadata["tool"]["setuptools"].get("data-files", {})
        expected = {
            "share/task-coach/skill": ["skills/task-coach/SKILL.md"],
            "share/task-coach/skill/references": ["skills/task-coach/references/LICENSE"],
            "share/task-coach/skill/scripts": ["skills/task-coach/scripts/task-coach.py"],
            "share/task-coach/skill/scripts/task_coach": [
                "skills/task-coach/scripts/task_coach/__init__.py",
                "skills/task-coach/scripts/task_coach/__main__.py",
                "skills/task-coach/scripts/task_coach/cli.py",
            ],
        }
        self.assertEqual(files, expected)
        for sources in files.values():
            for source in sources:
                self.assertTrue((root / source).is_file())
        find = metadata["tool"]["setuptools"]["packages"]["find"]
        self.assertEqual(find["where"], ["skills/task-coach/scripts"])


if __name__ == "__main__":
    unittest.main()
