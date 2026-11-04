"""Automatic policy adoption uses synthetic persisted rc.4 stores, never live data."""
from test_core_history_fixtures import enable_history, history_request
import json
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import test_core_driver as fixtures
from task_coach.driver import Driver, SCHEMA


class DefaultPolicyTest(__import__('unittest').TestCase):
    setUp = fixtures.RuntimeTest.setUp
    cli = fixtures.RuntimeTest.cli
    engine = fixtures.RuntimeTest.engine
    prepare = fixtures.RuntimeTest.prepare
    def legacy(self, *, episode=True):
        if episode:
            self.prepare()
        with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
            db.execute(SCHEMA)
            db.execute('PRAGMA user_version=1')
            db.execute('INSERT INTO runtime VALUES(1,?)', (json.dumps(dict(route=dict(
                binding=fixtures.BINDING, platform='discord', destination='discord:123',
                channel_id='123', bot_id='456'), outbox={})),))
            db.commit()
        (self.data / 'outbox.sqlite3').chmod(0o600)
        return Driver(self.data)

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.data.iterdir()}

    def test_first_use_adopts_episode_day_without_engine_rewrite(self):
        runtime = self.legacy()
        before = self.snapshot()
        self.assertEqual(runtime.status()['local_first'], {'after_day': '2030-01-07'})
        after = self.snapshot()
        self.assertEqual({k:v for k,v in before.items() if k != 'outbox.sqlite3'},
                         {k:v for k,v in after.items() if k != 'outbox.sqlite3'})
        self.assertFalse(runtime.local_first(now='2030-01-07T23:00:00Z'))
        self.assertTrue(runtime.local_first(now='2030-01-08T08:00:00Z'))
        adopted = self.snapshot()
        self.assertEqual(Driver(self.data).status(), runtime.status())
        self.assertEqual(adopted, self.snapshot())

    def test_empty_legacy_store_adopts_immediately_without_engine_creation(self):
        runtime = self.legacy(episode=False)
        self.assertEqual(runtime.status()['local_first'], {'after_day': None})
        self.assertFalse((self.data / 'coach.sqlite3').exists())

    def test_concurrent_first_use_has_one_stable_policy(self):
        self.legacy()
        barrier = Barrier(6)
        def read(_):
            barrier.wait()
            return Driver(self.data).status()['local_first']
        with ThreadPoolExecutor(max_workers=6) as pool:
            self.assertEqual(list(pool.map(read, range(6))), [{'after_day': '2030-01-07'}] * 6)

    def test_concurrent_fresh_initialization_defaults_local_first(self):
        barrier = Barrier(6)
        def read(_):
            barrier.wait()
            return Driver(self.data).status()
        with ThreadPoolExecutor(max_workers=6) as pool:
            states = list(pool.map(read, range(6)))
        self.assertTrue(all(s == dict(route=None, outbox={}, local_first=dict(after_day=None)) for s in states))
        self.assertFalse((self.data / 'coach.sqlite3').exists())

    def test_invalid_compatibility_inputs_preserve_all_files(self):
        import tempfile
        import shutil
        runtime = self.legacy()
        baseline = self.data
        for mutation in ('runtime-version', 'runtime-fields', 'engine-fields', 'engine-table',
                         'config', 'engine-null', 'runtime-table'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory(dir=self.temp.name) as folder:
                self.data = __import__('pathlib').Path(folder) / 'store'
                shutil.copytree(baseline, self.data)
                if mutation == 'config':
                    (self.data / 'config.json').write_text('{"timezone":"NoSuch/Zone"}')
                else:
                    kind = 'outbox' if mutation.startswith('runtime') else 'coach'
                    table = 'runtime' if kind == 'outbox' else 'state'
                    with closing(sqlite3.connect(self.data / (kind + '.sqlite3'))) as db:
                        if mutation.endswith('version'):
                            db.execute('PRAGMA user_version=99')
                        elif mutation.endswith('table'):
                            db.execute('CREATE TABLE unexpected(value)')
                        else:
                            state = json.loads(db.execute('SELECT value FROM ' + table).fetchone()[0])
                            if mutation == 'engine-null':
                                state = None
                            else:
                                state['unknown'] = True
                            db.execute('UPDATE ' + table + ' SET value=?', (json.dumps(state),))
                        db.commit()
                before = self.snapshot()
                with self.assertRaises((ValueError, TypeError)):
                    Driver(self.data).status()
                self.assertEqual(before, self.snapshot())
                self.data = baseline

    def test_first_use_preserves_legacy_receipts_holds_and_stopped_slots(self):
        from test_core_clarification import ClarificationTest
        helper = ClarificationTest()
        helper.data, helper.cli = self.data, self.cli
        runtime, history, drafts, now = helper.fixture()
        history.insert(0, helper.message('200', now))
        runtime.engagement(fixtures.BINDING, helper.pages(history, now), now=now, history_plan=history_request(runtime, 'engagement'))
        runtime.coach.stop(drafts[0]['token'], fixtures.BINDING)
        # Reconstruct rc.4's exact persisted runtime shape, not a future fresh store.
        with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
            historical = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
            historical.pop('local_first')
            db.execute('UPDATE runtime SET value=?', (json.dumps(historical),))
            db.commit()
        before = self.snapshot()
        adopted = Driver(self.data).status()
        self.assertEqual(adopted, dict(historical, local_first=dict(after_day='2030-01-07')))
        self.assertEqual(self.snapshot()['coach.sqlite3'], before['coach.sqlite3'])
        Driver(self.data).preflight(now='2030-01-08T08:00:00Z')
        later = Driver(self.data).status()
        self.assertEqual(later['outbox'], historical['outbox'])
        self.assertEqual(later['clarifications'], historical['clarifications'])

    def test_boundary_is_saved_local_date_across_dst_not_upgrade_clock(self):
        self.cli('setup', '--update', '--timezone', 'America/New_York')
        runtime = Driver(self.data)
        fixtures.persist_legacy_runtime(runtime, now='2030-03-10T07:30:00Z')
        self.assertEqual(runtime.status()['local_first'], {'after_day': '2030-03-10'})
        self.assertFalse(runtime.local_first(now='2030-03-11T03:59:59Z'))
        self.assertTrue(Driver(self.data).local_first(now='2030-03-11T04:00:00Z'))

    def test_capabilities_reports_effective_day_before_rollover_preflight(self):
        runtime = self.legacy()
        self.assertTrue(runtime.capabilities(now='2030-01-07T20:00:00Z')['history_required'])
        self.assertFalse(runtime.capabilities(now='2030-01-08T00:00:00Z')['history_required'])
        # Reporting policy does not prepare tomorrow or rewrite the legacy engine.
        self.assertEqual(runtime.coach.status()['episode']['day'], '2030-01-07')

    def test_alias_needs_no_second_optin(self):
        runtime = self.legacy()
        self.assertEqual(runtime.upgrade_local_first(), {'after_day': '2030-01-07'})

    def test_native_plan_does_not_adopt_or_require_history_for_fresh_install(self):
        runtime = self.legacy()
        before = self.snapshot()
        plan = runtime.native_plan('/fictional/profile', python='/usr/bin/python3',
                                   helper='/fictional/helper', hermes='/fictional/hermes')
        self.assertEqual(before, self.snapshot())
        # Before persisted adoption the legacy episode is still effective.
        self.assertIn('preserved legacy episode retains its honest history gates', plan['cron_argv'][4])
        self.assertIn('Never fetch Discord history in routine cron', plan['cron_argv'][4])
        self.assertIn('runtime capabilities', plan['cron_argv'][4])
        self.assertIn('preserve legacy gates', plan['inbound_instruction'])
        self.assertIn('With history OFF make no external history reads', plan['inbound_instruction'])
        (self.data / 'outbox.sqlite3').unlink()
        plan = runtime.native_plan('/fictional/profile', python='/usr/bin/python3',
                                   helper='/fictional/helper', hermes='/fictional/hermes')
        self.assertIn('openers AND followups without history', plan['cron_argv'][4])
        self.assertFalse((self.data / 'outbox.sqlite3').exists())

    def test_malformed_engine_refuses_without_any_writes(self):
        runtime = self.legacy()
        with closing(sqlite3.connect(self.data / 'coach.sqlite3')) as db:
            db.execute('PRAGMA user_version=99')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            runtime.status()
        self.assertEqual(before, self.snapshot())

    def test_malformed_stored_route_refuses_without_any_writes(self):
        runtime = self.legacy()
        with closing(sqlite3.connect(self.data / 'outbox.sqlite3')) as db:
            state = json.loads(db.execute('SELECT value FROM runtime').fetchone()[0])
            state['route']['destination'] = 'discord:999'
            db.execute('UPDATE runtime SET value=?', (json.dumps(state),))
            db.commit()
        before = self.snapshot()
        with self.assertRaises(ValueError):
            runtime.status()
        self.assertEqual(before, self.snapshot())
