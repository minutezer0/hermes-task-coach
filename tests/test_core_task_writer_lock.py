"""Real CLI task writers must share the runtime's directory lock."""
import fcntl
import os
import subprocess
import sys
import unittest

import test_core_clarification as clarification_fixtures
from test_core_driver import BINDING
import test_core_coaching as fixtures


class TaskWriterLockTest(unittest.TestCase):
    setUp = fixtures.EngineTest.setUp
    cli = fixtures.EngineTest.cli
    fixture = clarification_fixtures.ClarificationTest.fixture
    message = clarification_fixtures.ClarificationTest.message
    pages = clarification_fixtures.ClarificationTest.pages

    def writer(self, *args):
        return subprocess.Popen([sys.executable, str(fixtures.SCRIPTS / 'task-coach.py'),
            '--data-dir', str(self.data), *args], stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True)

    def test_all_task_writers_wait_for_runtime_directory_lock(self):
        for args in [('add', 'Another task'), ('update', '1', '--notes', 'Edited'),
                     ('done', '1'), ('snooze', '1', '2031-01-01T00:00:00Z')]:
            with self.subTest(command=args[0]):
                fd = os.open(self.data, os.O_RDONLY | os.O_DIRECTORY)
                process = None
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                    process = self.writer(*args)
                    with self.assertRaises(subprocess.TimeoutExpired,
                            msg='task writer committed while runtime lock was held'):
                        process.communicate(timeout=0.4)
                finally:
                    os.close(fd)
                    if process is not None:
                        stdout, stderr = process.communicate(timeout=10)
                        self.assertEqual(process.returncode, 0, stderr)

    def test_task_writer_cannot_commit_between_resolution_snapshot_and_release(self):
        runtime, history, drafts, now = self.fixture()
        history.insert(0, self.message('104', now))
        pending = runtime.engagement(BINDING, self.pages(history, now), now=now)['clarifications'][0]
        history.insert(0, self.message('105', now, 'The second task'))
        original_tasks = runtime.coach.tasks
        calls, writers = [], []
        def racing_tasks():
            snapshot = original_tasks()
            calls.append(True)
            if len(calls) == 2:
                process = self.writer('done', str(drafts[1]['task']['id']))
                writers.append(process)
                with self.assertRaises(subprocess.TimeoutExpired,
                        msg='task completion raced past guarded resolution snapshot'):
                    process.communicate(timeout=0.4)
            return snapshot
        runtime.coach.tasks = racing_tasks
        try:
            result = runtime.resolve_clarification(binding=BINDING,
                clarification_id=pending['id'], task_id=drafts[1]['task']['id'],
                selection_message_id='105', pages=self.pages(history, now), now=now)
            self.assertTrue(result['engaged'])
            self.assertEqual(result['context']['task']['status'], 'open')
            self.assertEqual(len(writers), 1)
        finally:
            runtime.coach.tasks = original_tasks
            for process in writers:
                stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0, stderr)
        self.assertEqual(next(t for t in original_tasks()
            if t['id'] == drafts[1]['task']['id'])['status'], 'done')
