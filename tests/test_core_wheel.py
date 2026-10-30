"""Artifact tests: build offline, install the wheel, then run its real entry points."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile


@unittest.skipUnless(importlib.util.find_spec("setuptools"), "artifact test requires setuptools>=68 (build dependency)")
class WheelArtifactTest(unittest.TestCase):
    def test_wheel_installs_console_and_self_contained_skill(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix="task coach wheel ") as temp:
            root = Path(temp)
            project = root / "source copy"
            project.mkdir()
            for name in ("pyproject.toml", "README.md", "LICENSE"):
                shutil.copyfile(source / name, project / name)
            shutil.copytree(source / "skills", project / "skills", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            dist = root / "dist"
            dist.mkdir()
            def run(command, **kwargs):
                result = subprocess.run(command, cwd=root, text=True, capture_output=True, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run([sys.executable, "-B", "-c", "import os, setuptools.build_meta as b; os.chdir(%r); b.build_wheel(%r)" % (str(project), str(dist))])
            wheel, = dist.glob("*.whl")
            with zipfile.ZipFile(wheel) as archive:
                names = archive.namelist()
                for path in (source / "skills" / "task-coach").rglob("*"):
                    if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                        suffix = "/data/share/task-coach/skill/" + str(path.relative_to(source / "skills" / "task-coach"))
                        matches = [n for n in names if n.endswith(suffix)]
                        self.assertEqual(len(matches), 1, suffix)
                        self.assertEqual(archive.read(matches[0]), path.read_bytes())
                self.assertIn("task_coach/cli.py", names)
            venv = root / "standalone venv"
            run([sys.executable, "-m", "venv", str(venv)])
            python = venv / "bin" / "python"
            run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
            env = {"HOME": str(root / "fictional home"), "HERMES_HOME": str(root / "fictional profile"),
                   "PYTHONDONTWRITEBYTECODE": "1", "PYTHONNOUSERSITE": "1"}
            command = [str(venv / "bin" / "task-coach")]
            run(command + ["--help"], env=env)
            self.assertFalse((root / "fictional profile").exists())
            config = json.loads(run(command + ["setup", "--timezone", "UTC"], env=env).stdout)["config"]
            self.assertFalse(config["automation_enabled"])
            task = json.loads(run(command + ["add", "Fictional wheel task"], env=env).stdout)
            self.assertEqual(json.loads(run(command + ["show", str(task["id"])], env=env).stdout), task)
            skill = venv / "share" / "task-coach" / "skill"
            # Neither the build tree nor the installed Python package is available to the system interpreter.
            shutil.rmtree(project)
            copied = root / "relocated wheel skill"
            shutil.copytree(skill, copied)
            result = run([sys.executable, "-I", "-B", str(copied / "scripts" / "task-coach.py"), "show", str(task["id"])], env=env)
            self.assertEqual(json.loads(result.stdout), task)
