"""Relocated-skill and installed-wheel checks with synthetic stores only."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1]


class CoachingArtifactTest(unittest.TestCase):
    def test_full_engine_suite_runs_from_copied_skill_without_checkout(self):
        with tempfile.TemporaryDirectory(prefix='coach-copied-synthetic-') as temp:
            root = Path(temp)
            shutil.copytree(SOURCE / 'skills/task-coach', root / 'skills/task-coach', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            (root / 'tests').mkdir()
            shutil.copyfile(SOURCE / 'tests/test_core_coaching.py', root / 'tests/test_core_coaching.py')
            shutil.copyfile(SOURCE / 'tests/test_core_driver.py', root / 'tests/test_core_driver.py')
            env = dict(HOME=str(root / 'synthetic-home'), HERMES_HOME=str(root / 'synthetic-profile'), TMPDIR=str(root), PYTHONDONTWRITEBYTECODE='1')
            result = subprocess.run([sys.executable, '-I', '-B', '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-p', 'test_core_coaching.py', '-q'], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('OK', result.stderr)
            driver_result = subprocess.run([sys.executable, '-I', '-B', '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-p', 'test_core_driver.py', '-v'], cwd=root, env=env, text=True, capture_output=True)
            self.assertEqual(driver_result.returncode, 0, driver_result.stdout + driver_result.stderr)
            self.assertIn('test_synthetic_full_flow_opener_followup_reply_stop', driver_result.stderr)
            self.assertIn('NOT real platform qualification', driver_result.stderr)

    @unittest.skipUnless(importlib.util.find_spec('setuptools'), 'wheel artifact requires setuptools>=68')
    def test_installed_wheel_console_and_engine_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix='coach-wheel-synthetic-') as temp:
            root = Path(temp)
            source = root / 'build-source'
            source.mkdir()
            for filename in ('pyproject.toml', 'README.md', 'LICENSE'):
                shutil.copyfile(SOURCE / filename, source / filename)
            shutil.copytree(SOURCE / 'skills', source / 'skills', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
            dist = root / 'dist'
            dist.mkdir()
            def run(command, **kwargs):
                result = subprocess.run(command, cwd=root, text=True, capture_output=True, **kwargs)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result
            run([sys.executable, '-B', '-c', 'import os, setuptools.build_meta as b; os.chdir(%r); b.build_wheel(%r)' % (str(source), str(dist))])
            wheel, = dist.glob('*.whl')
            venv = root / 'installed'
            run([sys.executable, '-m', 'venv', str(venv)])
            python = venv / 'bin/python'
            run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)])
            shutil.rmtree(source)
            env = dict(HOME=str(root / 'synthetic-home'), HERMES_HOME=str(root / 'synthetic-profile'), TMPDIR=str(root), PYTHONDONTWRITEBYTECODE='1')
            console = str(venv / 'bin/task-coach')
            run([console, 'setup', '--min-followup-interval', '1', '--max-followup-interval', '1'], env=env)
            run([console, 'add', 'Synthetic installed task'], env=env)
            self.assertEqual(json.loads(run([console, 'coach', 'status'], env=env).stdout)['transport'], 'external-bridge-required')
            self.assertIs(json.loads(run([console, 'coach', 'tick'], env=env).stdout)['wakeAgent'], False)
            # Isolated interpreter imports the wheel package, not copied skill code.
            code = '''
from datetime import datetime, timezone
import os, random
from pathlib import Path
from task_coach.coaching import Coach
binding = dict(owner='synthetic-owner', profile='synthetic-profile', account='synthetic-account', chat='synthetic-chat', thread='synthetic-thread')
engine = Coach(Path(os.environ.get('HERMES_HOME')) / 'task-coach', rng=random.Random(1))
engine.tick(now=datetime(2030,1,7,8,tzinfo=timezone.utc), binding=binding)
events = engine.status()['episode']['events']
assert len(events) == 3
for index, event in enumerate(events):
    now = datetime.fromisoformat(event['slot'])
    previous = events[index-1]
    evidence = dict(binding=binding, event_token=previous['token'], message_id='message-'+previous['token'], cursor='cursor-'+previous['token'], snapshot_id='snapshot-'+previous['token'], observed_at=now.isoformat(), complete=True, engaged=False, error=None) if index else None
    assert engine.tick(now=now,binding=binding,evidence=evidence)['wakeAgent'] is True
    assert engine.status()['deliveries'] == index
    assert engine.tick(now=now,binding=binding)['wakeAgent'] is False
    receipt = dict(event_token=event['token'], binding=binding, message_id='message-'+event['token'], cursor='cursor-'+event['token'], delivered_at=now.isoformat())
    engine.acknowledge(receipt, now=now)
assert engine.status()['deliveries'] == 3
assert engine.tick(now=now,binding=binding)['wakeAgent'] is False
print('wheel lifecycle: 3 confirmed deliveries; duplicate claims suppressed')
'''
            result = run([str(python), '-I', '-B', '-c', code], env=env)
            self.assertIn('3 confirmed deliveries', result.stdout)
            copied = root / 'skills/task-coach'
            shutil.copytree(venv / 'share/task-coach/skill', copied)
            (root / 'tests').mkdir()
            for name in ('test_core_coaching.py', 'test_core_driver.py'):
                shutil.copyfile(SOURCE / 'tests' / name, root / 'tests' / name)
            launcher = copied / 'scripts/task-coach.py'
            result = run([sys.executable, '-I', '-B', str(launcher), 'coach', 'inspect'], env=env)
            self.assertEqual(json.loads(result.stdout)['deliveries'], 3)
            self.assertTrue((copied / 'references/coaching.md').is_file())
            result = run([str(python), '-I', '-B', '-m', 'unittest', 'discover', '-s', str(root / 'tests'), '-p', 'test_core_driver.py', '-v'], env=env)
            self.assertIn('test_synthetic_full_flow_opener_followup_reply_stop', result.stderr)
