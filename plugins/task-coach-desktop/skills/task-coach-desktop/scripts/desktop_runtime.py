"""ChatGPT output boundary. No scheduler API, network transport or fake receipts.

The unchanged core plans/claims events. Only caller-supplied genuine native output
metadata acknowledges an event. Without it, follow-ups stay blocked rather than
interpreting a prepared response as delivery. All runtime calls are local.
"""
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import threading
from zoneinfo import ZoneInfo

from task_coach import coaching
from task_coach.cli import task_store_lock
from task_coach.recurrence import same_cycle

SCHEMA = 'CREATE TABLE desktop (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)'


def default_directory():
    base = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share')
    return base / 'task-coach-chatgpt-desktop'


def check_scope(directory, *, initializing=False):
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError('data directory must be absolute')
    for part in (directory, *directory.parents):
        if part.is_symlink():
            raise ValueError('symlink desktop storage is not supported')
    hermes_defaults = [Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local' / 'share') / 'task-coach']
    if os.environ.get('HERMES_HOME'):
        hermes_defaults.append(Path(os.environ['HERMES_HOME']) / 'task-coach')
    if directory.resolve() in {path.resolve() for path in hermes_defaults} or (directory / 'outbox.sqlite3').exists():
        raise ValueError('Hermes storage cannot be used by the desktop integration')
    if (directory / 'tasks.sqlite3').exists() and not (directory / 'desktop.sqlite3').exists():
        raise ValueError('existing unmarked task storage cannot be adopted by desktop setup')
    if not initializing and not (directory / 'desktop.sqlite3').is_file():
        raise ValueError('desktop store is not initialized; run setup')


def nonempty(value, label):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError(label + ' must be a nonempty opaque string (at most 4096 characters)')
    return value


class DesktopCoach(coaching.Coach):
    def __init__(self, runtime, rng=None):
        self.runtime = runtime
        super().__init__(runtime.directory, rng=rng, opportunity_minutes=10)
        self.local_first = True

    @contextmanager
    def transaction(self):
        with self.runtime.lock():
            with self._transaction() as state:
                yield state

    def plan(self, day, config, binding, now, recent, *, future_only=False):
        # A desktop can first wake halfway through a window. Never plan past slots.
        return super().plan(day, config, binding, now, recent, future_only=True)


class DesktopRuntime:
    def __init__(self, directory, *, rng=None):
        self.directory = Path(directory)
        self._mutex = threading.RLock()
        self._depth = threading.local()
        self.coach = DesktopCoach(self, rng=rng)

    @contextmanager
    def lock(self):
        with self._mutex:
            depth = getattr(self._depth, 'value', 0)
            if depth:
                self._depth.value += 1
                try:
                    yield
                finally:
                    self._depth.value -= 1
            else:
                with task_store_lock(self.directory):
                    self._depth.value = 1
                    try:
                        yield
                    finally:
                        self._depth.value = 0

    @staticmethod
    def fresh():
        return dict(version=1, conversation=None, enabled=False, schedule_id=None,
                    smart_snooze=False, hold=None, outputs={}, engagements={}, test_token=None,
                    last_clock=None)

    @staticmethod
    def validate(state):
        try:
            if (set(state) != set(DesktopRuntime.fresh()) or type(state['version']) is not int
                    or state['version'] != 1 or type(state['enabled']) is not bool
                    or type(state['smart_snooze']) is not bool):
                raise ValueError('invalid desktop state')
            for field in ('conversation', 'schedule_id', 'test_token'):
                if state[field] is not None:
                    nonempty(state[field], field)
            if state['enabled'] and (not state['conversation'] or not state['schedule_id']):
                raise ValueError('enabled desktop state requires conversation and schedule')
            if state['last_clock'] is not None:
                coaching.instant(state['last_clock'])
            if not isinstance(state['outputs'], dict) or not isinstance(state['engagements'], dict):
                raise ValueError('invalid desktop journal')
            for token, row in state['outputs'].items():
                if (set(row) != {'token', 'conversation', 'body', 'task', 'claimed_at', 'expires', 'receipt'}
                        or token != row['token'] or not isinstance(row['task'], dict)):
                    raise ValueError('invalid output journal')
                nonempty(token, 'token')
                nonempty(row['conversation'], 'conversation')
                nonempty(row['body'], 'body')
                if not coaching.instant(row['claimed_at']) < coaching.instant(row['expires']):
                    raise ValueError('invalid output interval')
                if row['receipt'] is not None:
                    receipt = row['receipt']
                    if (set(receipt) != {'message_id', 'emitted_at'}
                            or not coaching.instant(row['claimed_at']) <= coaching.instant(receipt['emitted_at']) < coaching.instant(row['expires'])):
                        raise ValueError('invalid native output metadata')
                    nonempty(receipt['message_id'], 'message ID')
            for key, row in state['engagements'].items():
                if (not isinstance(key, str) or set(row) != {'conversation', 'message_id', 'token', 'intent', 'at'}
                        or row['token'] not in state['outputs']
                        or row['conversation'] != state['outputs'][row['token']]['conversation']
                        or row['intent'] not in ('engaged', 'skip-for-now', 'start-work')):
                    raise ValueError('invalid engagement journal')
                nonempty(row['message_id'], 'inbound message ID')
                coaching.instant(row['at'])
                expected = hashlib.sha256(json.dumps([row['conversation'], row['message_id']]).encode()).hexdigest()
                if key != expected:
                    raise ValueError('invalid engagement identity')
            hold = state['hold']
            if hold is not None:
                if (set(hold) != {'engagement', 'conversation', 'expires', 'config', 'day'}
                        or hold['engagement'] not in state['engagements']
                        or state['engagements'][hold['engagement']]['intent'] != 'start-work'
                        or hold['conversation'] != state['conversation'] or not state['smart_snooze']):
                    raise ValueError('invalid Smart Snooze hold')
                from task_coach.cli import validate_config
                config = validate_config(hold['config'])
                minutes = coaching.window_minutes(hold['day'], config)
                at = coaching.instant(state['engagements'][hold['engagement']]['at'])
                if (not minutes or not minutes[0] <= at < minutes[-1] + timedelta(minutes=1)
                        or coaching.instant(hold['expires']) != minutes[-1] + timedelta(minutes=1)):
                    raise ValueError('invalid Smart Snooze expiry')
        except (KeyError, TypeError, OverflowError) as error:
            raise ValueError('invalid desktop state') from error

    @contextmanager
    def transaction(self, *, initialize=False, readonly=False):
        with self.lock():
            path = self.directory / 'desktop.sqlite3'
            for suffix in ('', '-journal', '-wal', '-shm'):
                coaching.safe_path(Path(str(path) + suffix))
            fresh = not path.exists()
            if fresh:
                if not initialize:
                    raise ValueError('desktop store is not initialized; run setup')
                fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            uri = path.resolve().as_uri() + '?mode=ro' if readonly else str(path)
            with closing(sqlite3.connect(uri, uri=readonly, timeout=10)) as db:
                db.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
                if fresh:
                    db.execute(SCHEMA)
                    db.execute('PRAGMA user_version=1')
                    state = self.fresh()
                else:
                    schema = db.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchall()
                    if (db.execute('PRAGMA user_version').fetchone()[0] != 1
                            or len(schema) != 1 or schema[0][:2] != ('table', 'desktop')
                            or ''.join(schema[0][2].split()).lower() != ''.join(SCHEMA.split()).lower()):
                        raise ValueError('incompatible desktop state schema')
                    rows = db.execute('SELECT id,value FROM desktop').fetchall()
                    if len(rows) != 1 or rows[0][0] != 1:
                        raise ValueError('invalid desktop state rows')
                    state = json.loads(rows[0][1])
                    self.validate(state)
                yield state
                self.validate(state)
                if not readonly:
                    db.execute('INSERT OR REPLACE INTO desktop VALUES (1,?)', (json.dumps(state),))
                db.commit()

    def initialize(self):
        self.coach.config()
        with self.transaction(initialize=True):
            pass

    def binding(self, conversation):
        return dict(owner=str(os.getuid()), profile=str(self.directory), account='chatgpt-desktop',
                    chat=conversation, thread='none')

    def route(self, state, conversation):
        if not conversation or state['conversation'] != conversation:
            raise ValueError('current conversation does not match the confirmed desktop conversation')
        return self.binding(conversation)

    @staticmethod
    def clock(state, now):
        now = coaching.instant(now or datetime.now(coaching.UTC))
        if state['last_clock'] is not None and now < coaching.instant(state['last_clock']):
            raise ValueError('desktop clock regressed')
        state['last_clock'] = now.isoformat()
        return now

    def configure(self, conversation, *, confirm=False):
        if not confirm:
            raise ValueError('confirm the current conversation before configuring')
        nonempty(conversation, 'conversation')
        with self.transaction() as state:
            if state['enabled']:
                raise ValueError('pause check-ins before changing the conversation')
            if state['conversation'] != conversation:
                state.update(conversation=conversation, schedule_id=None, test_token=None, hold=None)
        return self.status()

    def status(self):
        self.coach.config()
        with self.transaction(readonly=True) as state:
            # Runtime state is deliberately distinct from scheduler readback.
            return dict(state, platform='chatgpt-desktop', scheduler_verified=False,
                        delivery_provenance='caller-supplied-native-metadata',
                        outputs_without_metadata=sum(r['receipt'] is None for r in state['outputs'].values()))

    def activate(self, conversation, schedule_id, *, confirm=False):
        if not confirm:
            raise ValueError('explicit ongoing activation approval is required')
        nonempty(schedule_id, 'native schedule ID')
        with self.transaction() as state:
            self.route(state, conversation)
            self.coach.pause(False)
            state.update(enabled=True, schedule_id=schedule_id)
        # This never creates/resumes a native schedule. The caller does that and
        # reads it back before invoking activate. Persisted fields are assertions.
        return self.status()

    def pause(self):
        with self.transaction() as state:
            state.update(enabled=False, test_token=None)
        self.coach.pause(True)
        return self.status()

    def smart_snooze(self, enabled=None):
        with self.transaction(readonly=enabled is None) as state:
            if enabled is not None:
                state['smart_snooze'] = enabled
                if not enabled:
                    state['hold'] = None
            return dict(enabled=state['smart_snooze'], hold=state['hold'])

    def recover(self, state, now):
        with self.coach.transaction() as engine:
            episode = engine['episode']
        if not episode:
            return
        for row in state['outputs'].values():
            sequence = coaching.event_episode(episode, row['token'])
            if not sequence:
                continue
            if row['receipt']:
                receipt = dict(event_token=row['token'], binding=self.binding(row['conversation']),
                               message_id=row['receipt']['message_id'], cursor=row['receipt']['message_id'],
                               delivered_at=row['receipt']['emitted_at'])
                self.coach.reconcile(receipt, now=now)
        for engagement in state['engagements'].values():
            row = state['outputs'][engagement['token']]
            task = next((t for t in self.coach.tasks() if t['id'] == row['task']['id']), None)
            if coaching.event_episode(episode, engagement['token']) and same_cycle(row['task'], task):
                self.coach.stop(engagement['token'], self.binding(engagement['conversation']))

    def _preflight(self, state, conversation, now):
        binding = self.route(state, conversation)
        if not state['enabled'] and state['test_token'] is None:
            return dict(wakeAgent=False, reason='desktop-paused')
        if state['hold'] and now < coaching.instant(state['hold']['expires']):
            return dict(wakeAgent=False, reason='smart-snooze')
        config = self.coach.config()
        local = now.astimezone(ZoneInfo(config['timezone']))
        if coaching.DAYS[local.weekday()] not in config['weekdays'] or not config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']:
            return dict(wakeAgent=False, reason='outside-window')
        self.recover(state, now)
        if not any(coaching.eligible(t, now, config['timezone']) for t in self.coach.tasks()):
            return dict(wakeAgent=False, reason='no-eligible-task')
        result = self.coach.prepare(binding=binding, now=now)
        if result['wakeAgent']:
            token = result['intent']['event_token']
            if not state['enabled'] and token != state['test_token']:
                return dict(wakeAgent=False, reason='desktop-paused')
            if token in state['outputs']:
                return dict(wakeAgent=False, reason='already-attempted')
            if result['previous'] and not result['previous']['receipt']:
                return dict(wakeAgent=False, reason='native-output-metadata-required')
            result['task_hash'] = hashlib.sha256(json.dumps(result['task'], sort_keys=True).encode()).hexdigest()
        return result

    def preflight(self, conversation, *, now=None):
        with self.transaction() as state:
            now = self.clock(state, now)
            return self._preflight(state, conversation, now)

    def claim(self, conversation, token, body, task_hash, *, now=None):
        nonempty(body, 'check-in body')
        with self.transaction() as state:
            now = self.clock(state, now)
            prepared = self._preflight(state, conversation, now)
            if not prepared['wakeAgent'] or prepared['intent']['event_token'] != token:
                raise ValueError('check-in is not authorized now')
            if prepared['task_hash'] != task_hash:
                raise ValueError('task changed after drafting; inspect it again')
            claimed = self.coach.tick(binding=self.binding(conversation), now=now, expected_token=token)
            if not claimed['wakeAgent']:
                raise ValueError('claim suppressed: ' + claimed['reason'])
            row = dict(token=token, conversation=conversation, body=body, task=prepared['task'],
                       claimed_at=now.isoformat(), expires=prepared['intent']['expires'], receipt=None)
            state['outputs'][token] = row
            # Journal before returning text. A crash/lost final reply is never a
            # reason to retry; no native message identifier is invented here.
            return dict(output=body, token=token, delivery='unverified-output-attempt',
                        instruction='Emit output once as the final reply in the bound conversation only.')

    def record_output(self, conversation, token, message_id, emitted_at, *, now=None):
        nonempty(message_id, 'native assistant message ID')
        with self.transaction() as state:
            now = self.clock(state, now)
            self.route(state, conversation)
            row = state['outputs'].get(token)
            if not row or row['conversation'] != conversation:
                raise ValueError('unknown output attempt for this conversation')
            timestamp = coaching.instant(emitted_at)
            if not coaching.instant(row['claimed_at']) <= timestamp < min(now + timedelta(microseconds=1), coaching.instant(row['expires'])):
                raise ValueError('native output timestamp is outside the attempt interval')
            receipt = dict(message_id=message_id, emitted_at=timestamp.isoformat())
            if row['receipt'] is not None and row['receipt'] != receipt:
                raise ValueError('conflicting native output metadata')
            if any(r['token'] != token and r['conversation'] == conversation and r['receipt']
                   and r['receipt']['message_id'] == message_id for r in state['outputs'].values()):
                raise ValueError('native message identifier was already used')
            row['receipt'] = receipt
        # If interrupted here, preflight replays the persisted receipt idempotently.
        with self.transaction() as state:
            self.recover(state, now)
        return dict(recorded=True, provenance='caller-supplied-native-metadata', independently_verified=False)

    def engage(self, conversation, token, message_id, intent, *, now=None):
        nonempty(message_id, 'genuine inbound message ID')
        if intent not in ('engaged', 'skip-for-now', 'start-work'):
            raise ValueError('unknown engagement intent')
        key = hashlib.sha256(json.dumps([conversation, message_id]).encode()).hexdigest()
        with self.transaction() as state:
            now = self.clock(state, now)
            binding = self.route(state, conversation)
            old = state['engagements'].get(key)
            if old:
                if (old['token'], old['intent']) != (token, intent):
                    raise ValueError('inbound message was already attributed differently')
                return dict(recorded=True, duplicate=True, intent=intent, hold=state['hold'])
            row = state['outputs'].get(token)
            if not row or row['conversation'] != conversation or now < coaching.instant(row['claimed_at']):
                raise ValueError('engagement requires a current output attempt')
            engine = self.coach.status()
            sequence = coaching.event_episode(engine['episode'], token)
            task = next((t for t in self.coach.tasks() if t['id'] == row['task']['id']), None)
            if (not sequence or sequence['binding'] != binding or not same_cycle(row['task'], task)
                    or not coaching.eligible(task, now, self.coach.config()['timezone'])):
                raise ValueError('stale engagement task, cycle or conversation')
            state['engagements'][key] = dict(conversation=conversation, message_id=message_id,
                                            token=token, intent=intent, at=now.isoformat())
            config = self.coach.config()
            local = now.astimezone(ZoneInfo(config['timezone']))
            if (intent == 'start-work' and state['smart_snooze'] and sequence['day'] == local.date().isoformat()
                    and sequence['config'] == config and coaching.DAYS[local.weekday()] in config['weekdays']
                    and config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']):
                end = coaching.window_minutes(sequence['day'], config)[-1] + timedelta(minutes=1)
                if state['hold'] is None or coaching.instant(state['hold']['expires']) <= now:
                    state['hold'] = dict(engagement=key, conversation=conversation, expires=end.isoformat(),
                                         config=config, day=sequence['day'])
        with self.transaction() as state:
            self.recover(state, now)
        return dict(recorded=True, duplicate=False, intent=intent, hold=self.status()['hold'])

    def prepare_test(self, conversation, *, confirm=False, now=None):
        if not confirm:
            raise ValueError('explicit one-check-in test approval is required')
        with self.transaction() as state:
            now = self.clock(state, now)
            binding = self.route(state, conversation)
            if state['enabled'] or state['outputs'] or state['test_token']:
                raise ValueError('test requires a fresh, paused desktop installation')
            config = self.coach.config()
            local = now.astimezone(ZoneInfo(config['timezone']))
            minutes = coaching.window_minutes(local.date().isoformat(), config)
            minute = now.replace(second=0, microsecond=0)
            if minute not in minutes:
                raise ValueError('test requires an allowed day and window')
            task = coaching.choose_task(self.coach.tasks(), now, config['timezone'], self.coach.rng)
            if task is None:
                raise ValueError('test requires an eligible task; keep the saved task and skip the test')
            with self.coach.transaction() as engine:
                if engine['paused'] or engine['episode'] is not None:
                    raise ValueError('test refuses a global pause or any existing episode')
                episode = self.coach.plan(local.date().isoformat(), config, binding, now, engine['recent'])
                # The test is exactly one opener, never follow-ups or a second task.
                event = episode['events'][0] if episode['events'] else None
                if event is None:
                    raise ValueError('test requires remaining window space')
                event.update(slot=minute.isoformat(), expires=min(minute + timedelta(minutes=10), minutes[-1] + timedelta(minutes=1)).isoformat())
                episode.update(task_id=task['id'], cycle_id=task.get('cycle_id'), events=[event])
                episode.pop('next_tasks', None)
                episode.pop('window_stopped', None)
                engine['episode'] = episode
                state['test_token'] = event['token']
        return dict(prepared=True, token=state['test_token'], sends=False, followups=0)

    def native_plan(self, conversation, helper):
        helper = Path(helper)
        if not helper.is_absolute() or not helper.is_file():
            raise ValueError('native plan requires the absolute installed helper path')
        with self.transaction(readonly=True) as state:
            self.route(state, conversation)
        command = [sys.executable, '-I', '-B', str(helper), '--data-dir', str(self.directory),
                   'desktop', 'preflight', '--conversation', conversation]
        prompt = ('Use $task-coach-desktop in this existing conversation only. Current conversation must match '
                  + json.dumps(conversation) + '. Run this argument array with the local executor: '
                  + json.dumps(command) + '. Follow the packaged desktop runtime protocol. '
                  'First reconcile any genuine native output metadata and explicit owner engagement visible in '
                  'this conversation; do not scan unrelated chats or invent IDs. If wakeAgent is false, '
                  'post no check-in. Otherwise draft one coaching message, claim its exact event, and emit '
                  'the returned output once. Prepared output is unverified until genuine native metadata is '
                  'recorded. Never retry an attempted output, bypass a pause, or use Hermes or Discord.')
        config = self.coach.config()
        first_hour = int(config['notification_start'][:2])
        last_hour = int(config['notification_end'][:2]) - (config['notification_end'][3:] == '00')
        days = ','.join(day[:2].upper() for day in config['weekdays'])
        hours = ','.join(str(h) for h in range(first_hour, last_hour + 1))
        cadence = 'RRULE:FREQ=DAILY;BYDAY=' + days + ';BYHOUR=' + hours + ';BYMINUTE=0,5,10,15,20,25,30,35,40,45,50,55'
        return dict(platform='chatgpt-desktop', installed=False, initially_paused=True,
                    conversation=conversation, data_directory=str(self.directory),
                    cadence=cadence, timezone=config['timezone'],
                    prompt=prompt, preflight_argv=command, live_verified=False,
                    requires=['native scheduling controls with readback', 'same conversation delivery',
                              'local executor with access to this data directory', 'trusted conversation identity'],
                    limitations=['Each scheduled run may consume model usage even without a check-in.',
                                 'No native scheduling tool is called by this helper.',
                                 'Follow-ups require genuine native assistant output metadata.',
                                 'No platform guarantee of atomic cancellation of an in-flight response.'])


def run_desktop(directory, argv):
    parser = argparse.ArgumentParser(prog='task-coach-desktop desktop')
    operations = parser.add_subparsers(dest='operation', required=True)
    operations.add_parser('status')
    operations.add_parser('pause')
    snooze = operations.add_parser('smart-snooze')
    choice = snooze.add_mutually_exclusive_group()
    choice.add_argument('--enable', action='store_true')
    choice.add_argument('--disable', action='store_true')
    for name in ('configure', 'activate', 'preflight', 'claim', 'record-output', 'engage', 'prepare-test', 'native-plan'):
        command = operations.add_parser(name)
        command.add_argument('--conversation', required=True)
        if name == 'configure':
            command.add_argument('--confirm-setup', action='store_true')
        if name == 'activate':
            command.add_argument('--schedule-id', required=True)
            command.add_argument('--confirm-activation', action='store_true')
        if name in ('claim', 'record-output', 'engage'):
            command.add_argument('--token', required=True)
        if name == 'claim':
            command.add_argument('--body', required=True)
            command.add_argument('--task-hash', required=True)
        if name in ('record-output', 'engage'):
            command.add_argument('--message-id', required=True)
        if name == 'record-output':
            command.add_argument('--emitted-at', required=True)
        if name == 'engage':
            command.add_argument('--intent', required=True, choices=['engaged', 'skip-for-now', 'start-work'])
        if name == 'prepare-test':
            command.add_argument('--confirm-test', action='store_true')
        if name == 'native-plan':
            command.add_argument('--helper', required=True)
    args = parser.parse_args(argv)
    runtime = DesktopRuntime(directory)
    operation = args.operation
    if operation == 'status':
        result = runtime.status()
    elif operation == 'pause':
        result = runtime.pause()
    elif operation == 'smart-snooze':
        result = runtime.smart_snooze(True if args.enable else False if args.disable else None)
    elif operation == 'configure':
        result = runtime.configure(args.conversation, confirm=args.confirm_setup)
    elif operation == 'activate':
        result = runtime.activate(args.conversation, args.schedule_id, confirm=args.confirm_activation)
    elif operation == 'preflight':
        result = runtime.preflight(args.conversation)
    elif operation == 'claim':
        result = runtime.claim(args.conversation, args.token, args.body, args.task_hash)
    elif operation == 'record-output':
        result = runtime.record_output(args.conversation, args.token, args.message_id, args.emitted_at)
    elif operation == 'engage':
        result = runtime.engage(args.conversation, args.token, args.message_id, args.intent)
    elif operation == 'prepare-test':
        result = runtime.prepare_test(args.conversation, confirm=args.confirm_test)
    else:
        result = runtime.native_plan(args.conversation, args.helper)
    print(json.dumps(result))
    return 0
