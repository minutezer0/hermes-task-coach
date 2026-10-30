from pathlib import Path
import tomllib
import unittest


class SkillBundleTest(unittest.TestCase):
    def test_packaging_metadata_declares_the_companion_skill(self):
        root = Path(__file__).resolve().parents[1]
        metadata = tomllib.loads((root / "pyproject.toml").read_text())
        files = metadata["tool"]["setuptools"].get("data-files", {})
        self.assertEqual(
            files.get("share/task-coach/skill"),
            ["skills/task-coach/SKILL.md"],
        )
        self.assertTrue((root / files["share/task-coach/skill"][0]).is_file())


if __name__ == "__main__":
    unittest.main()
