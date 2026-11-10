"""Legal sqliteX names must not evade closed-world schema validation."""
from contextlib import closing
import sqlite3
import sys
import unittest

import test_cli_core as fixtures


class SchemaPrefixCLI(unittest.TestCase):
    setUp = fixtures.CLITest.setUp
    run_cli = fixtures.CLITest.run_cli

    def snapshot(self):
        # Includes SQLite sidecars, config, and every other file, with mtimes.
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.data.iterdir() if p.is_file()}

    def test_task_stores_reject_sqliteX_objects_without_mutation(self):
        for kind in ('table', 'trigger'):
            for command in ('list', 'init'):
                with self.subTest(kind=kind, command=command):
                    self.data = self.root / f'data-{kind}-{command}'
                    self.run_cli('init')
                    store = self.data / 'tasks.sqlite3'
                    with closing(sqlite3.connect(store)) as db:
                        for key, title in ((1, 'First fictional task'), (2, 'Unrelated fictional task')):
                            db.execute("INSERT INTO tasks (id,title,notes,priority,status,created_at,updated_at) VALUES (?,?,?,'normal','open',?,?)",
                                       (key, title, 'Preserve notes', '2024-01-01T00:00:00Z', '2024-01-01T00:00:00Z'))
                        if kind == 'table':
                            db.execute('CREATE TABLE sqliteXextra (value TEXT)')
                        else:
                            db.execute("CREATE TRIGGER sqliteXtrigger AFTER UPDATE ON tasks WHEN NEW.id=1 BEGIN UPDATE tasks SET notes='Unexpected trigger mutation' WHERE id=2; END")
                        db.commit()
                    store.chmod(0o600)
                    before = self.snapshot()
                    error = self.run_cli(command, ok=False)
                    self.assertIn('incompatible task store schema', error.stderr)
                    self.assertEqual(self.snapshot(), before)

    def test_related_state_validators_reject_sqliteX_objects_without_mutation(self):
        sys.path.insert(0, self.env['PYTHONPATH'])
        from task_coach.coaching import Coach
        from task_coach.driver import Driver
        for name, factory, filename, table in (
                ('coach', Coach, 'coach.sqlite3', 'state'),
                ('runtime', Driver, 'outbox.sqlite3', 'runtime')):
            for kind in ('table', 'trigger'):
                with self.subTest(store=name, kind=kind):
                    self.data = self.root / f'data-{name}-{kind}'
                    self.run_cli('init')
                    instance = factory(self.data)
                    with instance.transaction():
                        pass
                    with closing(sqlite3.connect(self.data / filename)) as db:
                        if kind == 'table':
                            db.execute('CREATE TABLE sqliteXextra (value TEXT)')
                        else:
                            db.execute(f'CREATE TRIGGER sqliteXtrigger AFTER INSERT ON {table} BEGIN SELECT 1; END')
                        db.commit()
                    before = self.snapshot()
                    with self.assertRaisesRegex(ValueError, 'incompatible .*schema'):
                        with instance.transaction():
                            self.fail('incompatible store was yielded to a writer')
                    self.assertEqual(self.snapshot(), before)
