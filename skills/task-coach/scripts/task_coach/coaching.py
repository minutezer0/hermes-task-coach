"""Deterministic local coaching. Intents are not messages or delivery receipts."""
from contextlib import closing, contextmanager
from datetime import datetime, time, timedelta, timezone
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import uuid
from zoneinfo import ZoneInfo

UTC = timezone.utc
BINDING_FIELDS = {'owner', 'profile', 'account', 'chat', 'thread'}
DAYS = ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')
STATE_SCHEMA = 'CREATE TABLE state (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)'


def instant(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise ValueError('expected an aware timestamp')
    try:
        return value.astimezone(UTC)
    except OverflowError:
        raise ValueError('timestamp is outside the representable UTC range') from None


def eligible(task, now):
    return task['status'] == 'open' and (not task['snoozed_until'] or instant(task['snoozed_until']) <= now)


def task_weight(task, now, zone):
    weight = {'low': 1, 'normal': 2, 'high': 4}[task['priority']]
    if task['due']:
        due = task['due']
        if len(due) == 10:
            due = datetime.combine(datetime.fromisoformat(due).date(), time(), ZoneInfo(zone))
        days = (instant(due) - instant(now)).total_seconds() / 86400
        weight *= 5 if days < 0 else 1 + max(0, 7 - days) / 2
    return weight


def choose_task(tasks, now, zone, rng, recent=()):
    tasks = [task for task in tasks if eligible(task, now)]
    alternatives = [task for task in tasks if task['id'] not in recent]
    tasks = alternatives or tasks
    if not tasks:
        return None
    return rng.choices(tasks, weights=[task_weight(task, now, zone) for task in tasks], k=1)[0]


# Each operation owns a short SQLite transaction. Task storage is always read-only.


def validate_binding(binding):
    if not isinstance(binding, dict) or set(binding) != BINDING_FIELDS or any(not isinstance(v, str) or not v.strip() for v in binding.values()):
        raise ValueError('binding requires nonempty owner/profile/account/chat/thread strings')
    return binding


def safe_path(path, directory=False):
    for part in (path, *path.parents):
        if part.is_symlink():
            raise ValueError('symlink coaching storage is not supported')
    if path.exists():
        info = path.stat()
        if info.st_uid != os.getuid() or (not directory and info.st_nlink != 1):
            raise ValueError('coaching storage must be owned and not hardlinked')
        if (directory and not path.is_dir()) or (not directory and not path.is_file()):
            raise ValueError('invalid coaching storage type')
        if info.st_mode & 0o7777 != (0o700 if directory else 0o600):
            raise ValueError('unsafe coaching storage permissions')


def window_minutes(day, config):
    """Enumerate real instants, not imaginary wall times; folds occur twice.

    Minute-aligned UTC instants round-trip through ZoneInfo, so gaps never
    become slots and both occurrences of repeated local minutes are eligible.
    """
    zone = ZoneInfo(config['timezone'])
    base = datetime.fromisoformat(day).replace(tzinfo=UTC) - timedelta(days=1)
    result = []
    for n in range(3 * 1440):
        value = base + timedelta(minutes=n)
        local = value.astimezone(zone)
        if local.date().isoformat() == day and DAYS[local.weekday()] in config['weekdays'] and config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']:
            result.append(value)
    return result


def validate_state(state):
    """Reject incompatible or partial state; never recreate a questionable episode."""
    from .cli import validate_config
    try:
        if not (isinstance(state, dict) and set(state) == {'version', 'paused', 'episode', 'recent', 'evidence_ids', 'message_ids', 'last_tick'}):
            raise ValueError('invalid coaching state')
        if not (type(state['version']) is int and state['version'] == 1 and type(state['paused']) is bool):
            raise ValueError('invalid coaching state')
        if not (isinstance(state['recent'], list) and len(state['recent']) <= 7 and all(type(k) is int and k > 0 for k in state['recent'])):
            raise ValueError('invalid coaching state')
        if not (isinstance(state['evidence_ids'], list) and all(isinstance(k, str) and k.strip() for k in state['evidence_ids'])):
            raise ValueError('invalid coaching state')
        if not (len(set(state['evidence_ids'])) == len(state['evidence_ids'])):
            raise ValueError('invalid coaching state')
        if not isinstance(state['message_ids'], list) or any(not isinstance(k, str) or len(k) != 64 or any(c not in '0123456789abcdef' for c in k) for k in state['message_ids']) or len(set(state['message_ids'])) != len(state['message_ids']):
            raise ValueError('invalid coaching state')
        if state['last_tick'] is not None:
            instant(state['last_tick'])
        episode = state['episode']
        if episode is None:
            return
        if not (isinstance(episode, dict) and set(episode) == {'day', 'task_id', 'binding', 'config', 'events', 'stopped'}):
            raise ValueError('invalid coaching state')
        if not (datetime.fromisoformat(episode['day']).date().isoformat() == episode['day']):
            raise ValueError('invalid coaching state')
        if not (episode['task_id'] is None or (type(episode['task_id']) is int and episode['task_id'] > 0)):
            raise ValueError('invalid coaching state')
        if not (episode['stopped'] is None or isinstance(episode['stopped'], str) and episode['stopped'].strip()):
            raise ValueError('invalid coaching state')
        validate_binding(episode['binding'])
        config = validate_config(episode['config'])
        events = episode['events']
        if not (isinstance(events, list) and len(events) <= 1 + config['max_unanswered_followups']):
            raise ValueError('invalid coaching state')
        if not (not events or episode['task_id'] is not None):
            raise ValueError('invalid coaching state')
        # Every claimed followup consumed a distinct snapshot. Older episodes may
        # leave additional IDs, but cannot account for fewer than this episode.
        if sum(e.get('index', 0) > 0 and e.get('state') != 'planned' for e in events if isinstance(e, dict)) > len(state['evidence_ids']):
            raise ValueError('invalid coaching state')
        tokens, messages = set(), set()
        previous = None
        unfinished = False
        for index, event in enumerate(events):
            required = {'token', 'index', 'slot', 'expires', 'state', 'receipt'}
            if not (isinstance(event, dict) and required <= set(event) <= required | {'claimed_at'}):
                raise ValueError('invalid coaching state')
            if not (type(event['index']) is int and event['index'] == index):
                raise ValueError('invalid coaching state')
            if not (isinstance(event['token'], str) and event['token'].strip() and event['token'] not in tokens):
                raise ValueError('invalid coaching state')
            tokens.add(event['token'])
            slot, expires = instant(event['slot']), instant(event['expires'])
            if not (slot < expires <= slot + timedelta(minutes=10) and slot.second == slot.microsecond == 0):
                raise ValueError('invalid coaching state')
            local = slot.astimezone(ZoneInfo(config['timezone']))
            if not (local.date().isoformat() == episode['day'] and DAYS[local.weekday()] in config['weekdays']):
                raise ValueError('invalid coaching state')
            if not (config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']):
                raise ValueError('invalid coaching state')
            if previous is not None:
                if not (config['min_followup_interval'] * 60 <= (slot-previous).total_seconds() <= config['max_followup_interval'] * 60):
                    raise ValueError('invalid coaching state')
            previous = slot
            if not (event['state'] in ('planned', 'claimed', 'delivered', 'failed')):
                raise ValueError('invalid coaching state')
            if not (not unfinished or event['state'] == 'planned'):
                raise ValueError('invalid coaching state')
            unfinished = event['state'] != 'delivered'
            if event['state'] == 'failed' and episode['stopped'] is None:
                raise ValueError('invalid coaching state')
            if event['state'] == 'planned':
                if not ('claimed_at' not in event and event['receipt'] is None):
                    raise ValueError('invalid coaching state')
            else:
                if not (slot <= instant(event['claimed_at']) < expires):
                    raise ValueError('invalid coaching state')
                receipt = event['receipt']
                if event['state'] == 'delivered':
                    if not (isinstance(receipt, dict) and set(receipt) == {'event_token', 'binding', 'message_id', 'cursor', 'delivered_at'}):
                        raise ValueError('invalid coaching state')
                    if not (receipt['binding'] == episode['binding'] and receipt['event_token'] == event['token']):
                        raise ValueError('invalid coaching state')
                    if not (all(isinstance(receipt[k], str) and receipt[k].strip() for k in ('message_id', 'cursor', 'delivered_at'))):
                        raise ValueError('invalid coaching state')
                    if not (instant(event['claimed_at']) <= instant(receipt['delivered_at']) and (instant(receipt['delivered_at']) < expires or episode['stopped'] is not None)):
                        raise ValueError('invalid coaching state')
                    if not (receipt['message_id'] not in messages):
                        raise ValueError('invalid coaching state')
                    messages.add(receipt['message_id'])
                    message_key = hashlib.sha256(json.dumps([receipt['binding'], receipt['message_id']], sort_keys=True).encode('utf-8')).hexdigest()
                    if message_key not in state['message_ids']:
                        raise ValueError('invalid coaching state')
                else:
                    if not (receipt is None):
                        raise ValueError('invalid coaching state')
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError('invalid coaching state') from None


class Coach:
    def __init__(self, data_dir, *, rng=None, opportunity_minutes=1):
        if type(opportunity_minutes) is not int or not 1 <= opportunity_minutes <= 10:
            raise ValueError('opportunity must be 1..10 minutes')
        self.opportunity_minutes = opportunity_minutes
        self.directory = Path(data_dir)
        self.rng = rng if rng is not None else random.SystemRandom()

    def config(self):
        from .cli import validate_config
        safe_path(self.directory, True)
        path = self.directory / 'config.json'
        safe_path(path)
        return validate_config(json.loads(path.read_text(encoding='utf-8')))

    @contextmanager
    def transaction(self):
        # Lock the already-private directory before creating the database. SQLite
        # alone cannot serialize the gap between O_EXCL creation and initialization.
        safe_path(self.directory, True)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            with self._transaction() as state:
                yield state
        finally:
            os.close(fd)

    @contextmanager
    def _transaction(self):
        safe_path(self.directory, True)
        path = self.directory / 'coach.sqlite3'
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(Path(str(path) + suffix))
        fresh = False
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
            fresh = True
        with closing(sqlite3.connect(path, timeout=10)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                if fresh:
                    db.execute(STATE_SCHEMA)
                    db.execute('PRAGMA user_version=1')
                    state: dict = dict(version=1, paused=False, episode=None, recent=[], evidence_ids=[], message_ids=[], last_tick=None)
                else:
                    if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                        raise ValueError('incompatible coaching state version')
                    # SQLite has no CHECK-constraint introspection. Accept only
                    # our versioned DDL (ignoring whitespace/case), not a table
                    # that merely happens to contain a plausible first row.
                    schema = db.execute("SELECT type, name, sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
                    if len(schema) != 1 or schema[0][:2] != ('table', 'state') or ''.join(schema[0][2].split()).lower() != ''.join(STATE_SCHEMA.split()).lower():
                        raise ValueError('incompatible coaching state schema')
                    columns = db.execute('PRAGMA table_xinfo(state)').fetchall()
                    if columns != [(0, 'id', 'INTEGER', 0, None, 1, 0), (1, 'value', 'TEXT', 1, None, 0, 0)] or db.execute('PRAGMA index_list(state)').fetchall():
                        raise ValueError('incompatible coaching state schema')
                    rows = db.execute('SELECT id, value FROM state').fetchall()
                    if len(rows) != 1 or type(rows[0][0]) is not int or rows[0][0] != 1 or not isinstance(rows[0][1], str):
                        raise ValueError('invalid coaching state')
                    state = json.loads(rows[0][1])
                    validate_state(state)
                yield state
                validate_state(state)
                db.execute('INSERT OR REPLACE INTO state VALUES (1, ?)', (json.dumps(state),))
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def tasks(self):
        from .cli import validate_store
        path = self.directory / 'tasks.sqlite3'
        safe_path(path)
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            validate_store(db)
            tasks = [dict(row) for row in db.execute('SELECT * FROM tasks ORDER BY id')]
            from .cli import due_value
            try:
                for task in tasks:
                    if task['id'] <= 0 or task['status'] not in ('open', 'done', 'cancelled') or task['priority'] not in ('low', 'normal', 'high'):
                        raise ValueError('invalid task values')
                    if task['due'] is not None:
                        due_value(task['due'])
                    if task['snoozed_until'] is not None:
                        due_value(task['snoozed_until'], aware_only=True)
            except (TypeError, ValueError, argparse.ArgumentTypeError):
                raise ValueError('uncertain task data; coaching suppressed') from None
            return tasks

    def status(self):
        with self.transaction() as state:
            return dict(state, transport='external-bridge-required', deliveries=sum(e['state'] == 'delivered' for e in (state['episode'] or {}).get('events', [])))

    def preview(self, *, binding, now=None, seed=None):
        validate_binding(binding)
        now = instant(now if now is not None else datetime.now(UTC))
        config = self.config()
        # A separate object carries the development RNG; nothing opens coach DB.
        preview = Coach(self.directory, rng=random.Random(seed))
        day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
        return dict(preview=True, wakeAgent=False, transport='external-bridge-required', episode=preview.plan(day, config, binding, now, []))

    def pause(self, paused):
        if type(paused) is not bool:
            raise ValueError('paused must be boolean')
        with self.transaction() as state:
            state['paused'] = paused
            if paused and state['episode']:
                state['episode']['stopped'] = state['episode']['stopped'] or 'paused'
            return dict(paused=paused, transport='external-bridge-required')

    def failed(self, event_token, binding):
        validate_binding(binding)
        with self.transaction() as state:
            episode = state['episode']
            event = next((e for e in episode['events'] if e['token'] == event_token), None) if episode else None
            if not episode or episode['binding'] != binding or not event or event['state'] not in ('claimed', 'failed'):
                raise ValueError('failure does not match a claimed event and route')
            event['state'] = 'failed'
            episode['stopped'] = episode['stopped'] or 'failed-delivery'
            return dict(stopped=episode['stopped'])

    def stop(self, event_token, binding):
        validate_binding(binding)
        with self.transaction() as state:
            episode = state['episode']
            if not episode or episode['binding'] != binding or not any(e['token'] == event_token for e in episode['events']):
                raise ValueError('engagement does not match current event and owner binding')
            episode['stopped'] = episode['stopped'] or 'owner-engaged'
            return dict(stopped=episode['stopped'])

    def plan(self, day, config, binding, now, recent) -> dict:
        minutes = window_minutes(day, config)
        task = choose_task(self.tasks(), now, config['timezone'], self.rng, recent) if minutes else None
        events = []
        if task and minutes:
            slot = self.rng.choice(minutes)
            for index in range(config['max_unanswered_followups'] + 1):
                events.append(dict(token=uuid.uuid4().hex, index=index, slot=slot.isoformat(), expires=min(slot + timedelta(minutes=self.opportunity_minutes), minutes[-1] + timedelta(minutes=1)).isoformat(), state='planned', receipt=None))
                candidates = [t for t in minutes if config['min_followup_interval'] * 60 <= (t-slot).total_seconds() <= config['max_followup_interval'] * 60]
                if not candidates:
                    break
                slot = self.rng.choice(candidates)
        return dict(day=day, task_id=task['id'] if task else None, binding=binding, config=config, events=events, stopped=None)

    def prepare(self, *, now=None, binding=None):
        """Inspect due work without consuming history or claiming the event."""
        return self.tick(now=now, binding=binding, prepare_only=True)

    def tick(self, *, now=None, binding=None, evidence=None, expected_token=None, prepare_only=False):
        now = instant(now if now is not None else datetime.now(UTC))
        config = self.config()
        if binding is None:
            return dict(wakeAgent=False, reason='external-bridge-required')
        validate_binding(binding)
        day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
        with self.transaction() as state:
            if state['last_tick'] is not None and now < instant(state['last_tick']):
                if state['episode']:
                    state['episode']['stopped'] = state['episode']['stopped'] or 'clock-regressed'
                return dict(wakeAgent=False, reason='clock-regressed')
            state['last_tick'] = now.isoformat()
            if state['paused']:
                return dict(wakeAgent=False, reason='paused')
            episode = state['episode']
            if episode and (episode['config'] != config or episode['binding'] != binding):
                old_day = now.astimezone(ZoneInfo(episode['config']['timezone'])).date().isoformat()
                if old_day <= episode['day']:
                    episode['stopped'] = episode['stopped'] or 'configuration-changed'
                    return dict(wakeAgent=False, reason=episode['stopped'])
            if episode is None or episode['day'] != day:
                episode = self.plan(day, config, binding, now, state['recent'])
                state['episode'] = episode
                if episode['task_id'] is not None:
                    state['recent'] = (state['recent'] + [episode['task_id']])[-7:]
            if episode['config'] != config or episode['binding'] != binding:
                episode['stopped'] = episode['stopped'] or 'configuration-changed'
            task = next((t for t in self.tasks() if t['id'] == episode['task_id']), None)
            if not task or not eligible(task, now):
                episode['stopped'] = episode['stopped'] or 'task-unavailable'
            if episode['stopped']:
                return dict(wakeAgent=False, reason=episode['stopped'])
            local = now.astimezone(ZoneInfo(config['timezone']))
            if DAYS[local.weekday()] not in config['weekdays'] or not config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']:
                return dict(wakeAgent=False, reason='outside-window')
            for event in episode['events']:
                if event['state'] == 'delivered':
                    continue
                if event['state'] == 'claimed':
                    if now >= instant(event['expires']):
                        episode['stopped'] = 'unconfirmed-delivery'
                    return dict(wakeAgent=False, reason=episode['stopped'] or 'pending-delivery')
                if event['state'] != 'planned':
                    return dict(wakeAgent=False, reason='event-not-planned')
                if now >= instant(event['expires']):
                    episode['stopped'] = 'missed-slot'
                    return dict(wakeAgent=False, reason='missed-slot')
                if now < instant(event['slot']):
                    return dict(wakeAgent=False, reason='not-due')
                if expected_token is not None and event['token'] != expected_token:
                    return dict(wakeAgent=False, reason='event-token-mismatch')
                if prepare_only:
                    return dict(wakeAgent=True, intent=dict(event_token=event['token'], index=event['index'], task_id=episode['task_id'], binding=binding, expires=event['expires']), previous=episode['events'][event['index']-1] if event['index'] else None, task=task)
                if event['index']:
                    previous = episode['events'][event['index'] - 1]
                    elapsed = (now - instant(previous['receipt']['delivered_at'])).total_seconds()
                    if elapsed < config['min_followup_interval'] * 60:
                        return dict(wakeAgent=False, reason='minimum-delivery-spacing')
                    if elapsed > config['max_followup_interval'] * 60:
                        episode['stopped'] = 'maximum-delivery-spacing'
                        return dict(wakeAgent=False, reason=episode['stopped'])
                    if not self.check_evidence(evidence, previous, binding, now, state):
                        episode['stopped'] = 'unverified-engagement'
                        return dict(wakeAgent=False, reason=episode['stopped'])
                event['state'] = 'claimed'
                event['claimed_at'] = now.isoformat()
                return dict(wakeAgent=True, intent=dict(event_token=event['token'], index=event['index'], task_id=episode['task_id'], binding=binding, expires=event['expires'], kind='opener' if not event['index'] else 'followup'))
            return dict(wakeAgent=False, reason='complete')

    @staticmethod
    def check_evidence(evidence, previous, binding, now, state):
        fields = {'binding', 'event_token', 'message_id', 'cursor', 'snapshot_id', 'observed_at', 'complete', 'engaged', 'error'}
        if not isinstance(evidence, dict) or set(evidence) != fields:
            return False
        receipt = previous['receipt']
        if previous['state'] != 'delivered' or not receipt:
            return False
        if evidence['binding'] != binding or evidence['event_token'] != previous['token'] or evidence['message_id'] != receipt['message_id'] or evidence['cursor'] != receipt['cursor']:
            return False
        if evidence['complete'] is not True or evidence['engaged'] is not False or evidence['error'] is not None:
            return False
        snapshot = evidence['snapshot_id']
        if not isinstance(snapshot, str) or not snapshot.strip() or snapshot in state['evidence_ids']:
            return False
        try:
            observed = instant(evidence['observed_at'])
        except (ValueError, TypeError):
            return False
        if not instant(receipt['delivered_at']) <= observed <= now or (now-observed).total_seconds() > 60:
            return False
        state['evidence_ids'].append(snapshot)
        return True

    def reconcile(self, receipt, *, now=None):
        """Record a verified old attempt without reopening a stopped episode."""
        return self.acknowledge(receipt, now=now, reconcile=True)

    def acknowledge(self, receipt, *, now=None, reconcile=False):
        now = instant(now if now is not None else datetime.now(UTC))
        fields = {'event_token', 'binding', 'message_id', 'cursor', 'delivered_at'}
        if not isinstance(receipt, dict) or set(receipt) != fields:
            raise ValueError('receipt requires event_token/binding/message_id/cursor/delivered_at')
        validate_binding(receipt['binding'])
        if any(not isinstance(receipt[k], str) or not receipt[k].strip() for k in ('event_token', 'message_id', 'cursor', 'delivered_at')):
            raise ValueError('receipt identifiers must be nonempty opaque strings')
        delivered = instant(receipt['delivered_at'])
        with self.transaction() as state:
            episode = state['episode']
            if not episode or receipt['binding'] != episode['binding']:
                raise ValueError('receipt binding does not match current episode')
            event = next((e for e in episode['events'] if e['token'] == receipt['event_token']), None)
            if not event:
                raise ValueError('unknown event token')
            if event['state'] == 'delivered':
                if event['receipt'] != receipt:
                    raise ValueError('conflicting receipt')
                return dict(state='delivered', event_token=event['token'])
            if event['state'] != 'claimed' or not instant(event['claimed_at']) <= delivered <= now or (not reconcile and (episode['stopped'] or now >= instant(event['expires']))):
                raise ValueError('receipt is out of order, expired, or episode stopped')
            message_key = hashlib.sha256(json.dumps([receipt['binding'], receipt['message_id']], sort_keys=True).encode('utf-8')).hexdigest()
            if message_key in state['message_ids']:
                raise ValueError('replayed message identifier')
            if reconcile and now >= instant(event['expires']):
                episode['stopped'] = episode['stopped'] or 'late-reconciled'
            event['state'] = 'delivered'
            event['receipt'] = receipt
            state['message_ids'].append(message_key)
            return dict(state='delivered', event_token=event['token'])
