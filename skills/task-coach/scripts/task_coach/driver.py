"""Native Hermes orchestration. History is supplied by the agent, not a bot SDK."""
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import uuid
import threading
from functools import wraps
from inspect import signature

from . import clarification
from .recurrence import same_cycle, same_snapshot
from .coaching import Coach, UTC, instant, safe_path, validate_binding, sequences, event_episode


def history_ingress(method):
    """One directory-lock lease covers consent, capture validation and all commits."""
    parameters = signature(method)

    @wraps(method)
    def guarded(self, *args, **kwargs):
        values = parameters.bind(self, *args, **kwargs)
        values.apply_defaults()
        with self._directory_lock():
            self._authorize_ingress(method.__name__, values.arguments)
            return method(self, *args, **kwargs)
    return guarded


class _DriverCoach(Coach):
    def __init__(self, driver):
        self.driver = driver
        super().__init__(driver.directory, opportunity_minutes=10)

    @contextmanager
    def transaction(self):
        # The Driver and engine share one reentrant, thread-local directory lease.
        with self.driver._directory_lock():
            with self._transaction() as state:
                yield state

SCHEMA = 'CREATE TABLE runtime (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)'


class Driver:
    @staticmethod
    def validate_state(state):
        try:
            if not {'route', 'outbox'} <= set(state) <= {'route', 'outbox', 'clarifications', 'clarification_retry', 'clarification_responses', 'local_first', 'engagements', 'history_consent', 'smart_snooze_enabled', 'smart_snooze_hold'} or not isinstance(state['outbox'], dict):
                raise ValueError
            if type(state.get('smart_snooze_enabled', False)) is not bool:
                raise ValueError
            if 'history_consent' in state:
                consent = state['history_consent']
                if (not isinstance(consent, dict) or set(consent) != {'enabled', 'route', 'generation'}
                        or type(consent['enabled']) is not bool
                        or not isinstance(consent['generation'], str) or not consent['generation']
                        or consent['route'] != state['route']):
                    raise ValueError
                Driver.validate_route(consent['route'])
            if 'local_first' in state:
                policy = state['local_first']
                if not isinstance(policy, dict) or set(policy) != {'after_day'}:
                    raise ValueError
                if policy['after_day'] is not None and date.fromisoformat(policy['after_day']).isoformat() != policy['after_day']:
                    raise ValueError
            if state['route'] is not None:
                validate_binding(state['route']['binding'])
                if 'local_first' in state:
                    Driver.validate_route(state['route'])
            clarification.validate_cycle(state)
            records = state.get('clarifications', {})
            if not isinstance(records, dict):
                raise ValueError
            identities = set()
            for key, record in records.items():
                required = {'id', 'binding', 'message', 'candidates', 'state'}
                resolved = {'selected_token', 'selection', 'result', 'resolved_at'} if record['state'] in ('resolving', 'resolved') else set()
                dismissed = {'dismissal', 'result', 'resolved_at'} if record['state'] == 'dismissed' else set()
                retired = {'resolved_at'} if record['state'] == 'retired' else set()
                optional = {'responses'} if 'responses' in record else set()
                if set(record) != required | resolved | dismissed | retired | optional or record['state'] not in ('pending', 'resolving', 'resolved', 'dismissed', 'retired') or record['id'] != key:
                    raise ValueError
                if not isinstance(key, str) or not key or record['binding'] != state['route']['binding']:
                    raise ValueError
                message = record['message']
                if (not isinstance(message['id'], str) or not message['id'].isdecimal()
                        or message['author']['id'] != record['binding']['owner'] or message['author']['bot'] is not False
                        or not isinstance(message['content'], str) or not isinstance(message['attachments'], list)):
                    raise ValueError
                instant(message['timestamp'])
                if retired and instant(record['resolved_at']) < instant(message['timestamp']):
                    raise ValueError
                responses = record.get('responses', [])
                if not isinstance(responses, list) or len({m['id'] for m in responses}) != len(responses):
                    raise ValueError
                for response in responses:
                    if (not isinstance(response['id'], str) or not response['id'].isdecimal()
                            or response['author']['id'] != record['binding']['owner'] or response['author']['bot'] is not False
                            or int(response['id']) <= int(message['id'])
                            or instant(response['timestamp']) < instant(message['timestamp'])
                            or not isinstance(response['content'], str) or not isinstance(response['attachments'], list)):
                        raise ValueError
                for field in ('selection', 'dismissal'):
                    if field in record and any(response['id'] == record[field]['id'] and response != record[field]
                                               for response in responses):
                        raise ValueError
                consumed = clarification.consumed(record)
                for consumed_id in consumed:
                    identity = (json.dumps(record['binding'], sort_keys=True), consumed_id)
                    if identity in identities:
                        raise ValueError
                    identities.add(identity)
                candidates = record['candidates']
                if not isinstance(candidates, list) or len(candidates) < 2 or len({c['task']['id'] for c in candidates}) != len(candidates):
                    raise ValueError
                for candidate in candidates:
                    row = state['outbox'][candidate['token']]
                    if (set(candidate) != {'token', 'task', 'receipt'} or row['state'] != 'confirmed'
                            or candidate['receipt'] != row['receipt'] or candidate['task']['id'] != row['task']['id']
                            or not same_cycle(candidate['task'], row['task'])
                            or int(candidate['receipt']['message_id']) >= int(message['id'])
                            or instant(candidate['receipt']['delivered_at']) > instant(message['timestamp'])):
                        raise ValueError
                if dismissed:
                    dismissal = record['dismissal']
                    if (not isinstance(dismissal['id'], str) or not dismissal['id'].isdecimal()
                            or dismissal['author']['id'] != record['binding']['owner']
                            or dismissal['author']['bot'] is not False or int(dismissal['id']) <= int(message['id'])
                            or instant(dismissal['timestamp']) < instant(message['timestamp'])
                            or instant(record['resolved_at']) < instant(dismissal['timestamp'])
                            or not isinstance(dismissal['content'], str) or not isinstance(dismissal['attachments'], list)
                            or record['result'] != dict(dismissed=True, engaged=False, clarification_id=key,
                                original_message_id=message['id'], dismissal_message_id=dismissal['id'],
                                provenance='explicit-owner-dismissal')):
                        raise ValueError
                if resolved:
                    selected = next(c for c in candidates if c['token'] == record['selected_token'])
                    selection = record['selection']
                    if instant(record['resolved_at']) < instant(selection['timestamp']):
                        raise ValueError
                    result = record['result']
                    if (selection['author'] != message['author'] or int(selection['id']) <= int(message['id'])
                            or instant(selection['timestamp']) < instant(message['timestamp'])
                            or result != dict(engaged=True, context=dict(task=selected['task'], task_id=selected['task']['id'],
                                 event_token=selected['token'], receipt=selected['receipt'], binding=record['binding']),
                                 provenance='explicit-owner-selection', clarification_id=key,
                                 original_message_id=message['id'], selection_message_id=selection['id'])):
                        raise ValueError
            quarantine = state.get('clarification_responses', [])
            if not isinstance(quarantine, list):
                raise ValueError
            for entry in quarantine:
                if set(entry) != {'message', 'ids'} or not isinstance(entry['ids'], list) or not entry['ids'] or entry['ids'] != sorted(set(entry['ids'])):
                    raise ValueError
                message = entry['message']
                identity = (json.dumps(state['route']['binding'], sort_keys=True), message['id'])
                if (identity in identities or not isinstance(message['id'], str) or not message['id'].isdecimal()
                        or message['author']['id'] != state['route']['binding']['owner'] or message['author']['bot'] is not False
                        or not isinstance(message['content'], str) or not isinstance(message['attachments'], list)):
                    raise ValueError
                identities.add(identity)
                for key in entry['ids']:
                    original = records[key]['message']
                    if int(message['id']) <= int(original['id']) or instant(message['timestamp']) < instant(original['timestamp']):
                        raise ValueError
            engagements = state.get('engagements', {})
            if not isinstance(engagements, dict):
                raise ValueError
            for message_id, entry in engagements.items():
                request, result = entry['request'], entry['result']
                row = state['outbox'][request['event_token']]
                if (set(entry) not in ({'request', 'result', 'recorded_at'}, {'request', 'result', 'recorded_at', 'message'})
                        or set(request) != {'binding', 'owner', 'message_id', 'event_token', 'task_id', 'cycle_id', 'intent'}
                        or not isinstance(message_id, str) or not message_id.strip() or request['message_id'] != message_id
                        or request['binding'] != state['route']['binding'] or request['owner'] != request['binding']['owner']
                        or request['task_id'] != row['task']['id'] or request['cycle_id'] != row['task'].get('cycle_id')
                        or row['state'] not in ('accepted', 'confirmed') or request['intent'] not in ('engaged', 'skip-for-now', 'start-work')
                        or result != dict(engaged=True, task_id=request['task_id'], event_token=request['event_token'], provenance='captured-owner-history' if 'message' in entry else 'agent-mediated-explicit-intent')
                        or ('message' in entry and (entry['message']['id'] != message_id
                            or entry['message']['author'] != dict(id=request['owner'], bot=False)))
                        or (json.dumps(request['binding'], sort_keys=True), message_id) in identities):
                    raise ValueError
                instant(entry['recorded_at'])
            if 'smart_snooze_hold' in state:
                hold = state['smart_snooze_hold']
                if (not isinstance(hold, dict) or set(hold) != {'route', 'day', 'config', 'event_token',
                        'task_id', 'message_id', 'started_at', 'expires'}
                        or not state.get('smart_snooze_enabled', False) or hold['route'] != state['route']):
                    raise ValueError
                from .coaching import window_minutes
                from .cli import validate_config
                config = validate_config(hold['config'])
                minutes = window_minutes(hold['day'], config)
                entry = engagements[hold['message_id']]
                request = entry['request']
                if (not minutes or instant(hold['expires']) != minutes[-1] + timedelta(minutes=1)
                        or not minutes[0] <= instant(hold['started_at']) < instant(hold['expires'])
                        or hold['started_at'] != entry['recorded_at'] or request['intent'] != 'start-work'
                        or request['event_token'] != hold['event_token'] or request['task_id'] != hold['task_id']
                        or instant(hold['started_at']) < instant(state['outbox'][hold['event_token']]['receipt']['delivered_at'])):
                    raise ValueError
            for token, row in state['outbox'].items():
                required = {'token', 'fence', 'state', 'body', 'route', 'task', 'intent', 'previous', 'evidence'}
                if not required <= set(row) <= required | {'attempted_at', 'candidate_id', 'uncertain', 'receipt', 'acceptance'}:
                    raise ValueError
                if row['token'] != token or row['route'] != state['route'] or row['state'] not in ('draft', 'sending', 'accepted', 'confirmed'):
                    raise ValueError
                if not all(isinstance(row[k], str) and row[k].strip() for k in ('token', 'fence', 'body')):
                    raise ValueError
                if row['intent']['event_token'] != token or row['intent']['task_id'] != row['task']['id'] or row['intent']['binding'] != row['route']['binding']:
                    raise ValueError
                if clarification.retry_row(row):
                    intent = row['intent']
                    ids = intent['clarification_ids']
                    if (set(intent) != {'kind', 'event_token', 'clarification_ids', 'index', 'task_id', 'binding', 'expires'}
                            or not isinstance(ids, list) or not ids or any(not isinstance(key, str) for key in ids)
                            or ids != sorted(set(ids)) or any(key not in records for key in ids)
                            or type(intent['index']) is not int or intent['index'] < 0
                            or not row['previous'] or row['previous']['state'] != 'delivered'):
                        raise ValueError
                    instant(intent['expires'])
                    candidate = min((c for key in ids for c in records[key]['candidates']),
                                    key=lambda c: int(c['receipt']['message_id']))
                    if (row['previous'] != dict(token=candidate['token'], receipt=candidate['receipt'], state='delivered')
                            or row['task'] != candidate['task']):
                        raise ValueError
                    cycle = state.get('clarification_retry')
                    if not cycle or token not in {e['token'] for e in cycle['events']}:
                        # Replaced cycles retain completed/stale audit rows, but
                        # cannot hide an active or orphaned attempt.
                        if any(records[key]['state'] not in clarification.TERMINAL for key in ids) or row['state'] == 'sending':
                            raise ValueError
                if row['state'] == 'draft' and any(k in row for k in ('attempted_at', 'candidate_id', 'receipt')):
                    raise ValueError
                if row['state'] != 'draft':
                    instant(row['attempted_at'])
                if row['state'] == 'accepted' and 'acceptance' not in row:
                    raise ValueError
                if 'acceptance' in row:
                    acceptance = row['acceptance']
                    accepted = acceptance['receipt']
                    if (set(acceptance) != {'provenance', 'receipt'} or acceptance['provenance'] != 'native-send-response'
                            or row['state'] not in ('accepted', 'confirmed') or 'local_first' not in state
                            or set(accepted) != {'event_token', 'binding', 'message_id', 'cursor', 'delivered_at'}
                            or accepted['event_token'] != token or accepted['binding'] != row['route']['binding']
                            or accepted['cursor'] != accepted['message_id'] or accepted['message_id'] != row['candidate_id']
                            or instant(accepted['delivered_at']) < instant(row['attempted_at'])
                            or row['receipt']['message_id'] != accepted['message_id']
                            or row['state'] == 'accepted' and row['receipt'] != accepted):
                        raise ValueError
                if row['state'] in ('accepted', 'confirmed'):
                    receipt = row['receipt']
                    if receipt['event_token'] != token or receipt['binding'] != row['route']['binding'] or receipt['cursor'] != receipt['message_id'] or not receipt['message_id']:
                        raise ValueError
                    instant(receipt['delivered_at'])
        except (KeyError, TypeError, ValueError, AttributeError, StopIteration):
            raise ValueError('invalid runtime state') from None

    def __init__(self, data_dir):
        self._locks = threading.local()
        self.directory = Path(data_dir)
        self.coach = _DriverCoach(self)

    @contextmanager
    def _directory_lock(self):
        import fcntl
        if getattr(self._locks, 'fd', None) is not None:
            yield self._locks.fd
            return
        safe_path(self.directory, True)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._locks.fd = fd
            yield fd
        finally:
            self._locks.fd = None
            os.close(fd)

    def _policy_boundary(self, runtime):
        """Read/validate compatibility inputs under the already-held directory lock.

        Never use engine transactions here: they write and may initialize storage.
        The preserved day comes from the persisted episode, not the upgrade clock.
        """
        from .coaching import STATE_SCHEMA, validate_state
        self.coach.config()
        if runtime['route'] is not None:
            self.validate_route(runtime['route'])
        path = self.directory / 'coach.sqlite3'
        for suffix in ('', '-journal', '-wal', '-shm'):
            safe_path(Path(str(path) + suffix))
        if not path.exists():
            return None
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            schema = db.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchall()
            if (db.execute('PRAGMA user_version').fetchone()[0] != 1 or len(schema) != 1
                    or schema[0][:2] != ('table', 'state')
                    or ''.join(schema[0][2].split()).lower() != ''.join(STATE_SCHEMA.split()).lower()
                    or db.execute('PRAGMA table_xinfo(state)').fetchall() != [(0, 'id', 'INTEGER', 0, None, 1, 0), (1, 'value', 'TEXT', 1, None, 0, 0)]
                    or db.execute('PRAGMA index_list(state)').fetchall()):
                raise ValueError('incompatible coaching state schema or version')
            rows = db.execute('SELECT id,value FROM state').fetchall()
            if len(rows) != 1 or rows[0][0] != 1:
                raise ValueError('invalid coaching state')
            engine = json.loads(rows[0][1])
            validate_state(engine)
            return engine['episode']['day'] if engine['episode'] else None

    @contextmanager
    def transaction(self, *, readonly=False, adopt=True):
        # Same directory lock as the engine, but never nest these transactions.
        import fcntl
        safe_path(self.directory, True)
        held = getattr(self._locks, 'fd', None)
        fd = os.dup(held) if held is not None else os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            path = self.directory / 'outbox.sqlite3'
            for suffix in ('', '-journal', '-wal', '-shm'):
                safe_path(Path(str(path) + suffix))
            fresh = not path.exists()
            if fresh and readonly:
                raise ValueError('runtime setup not confirmed')
            if fresh:
                created = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(created)
            read_connection = readonly and not adopt
            target = path.resolve().as_uri() + '?mode=ro' if read_connection else path
            with closing(sqlite3.connect(target, uri=read_connection)) as db:
                db.execute('BEGIN' if read_connection else 'BEGIN IMMEDIATE')
                try:
                    if fresh:
                        db.execute(SCHEMA)
                        db.execute('PRAGMA user_version=1')
                        state = dict(route=None, outbox={}, local_first=dict(after_day=None), smart_snooze_enabled=False)
                    else:
                        schema = db.execute("SELECT sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'").fetchall()
                        if db.execute('PRAGMA user_version').fetchone()[0] != 1 or schema != [(SCHEMA,)]:
                            raise ValueError('incompatible runtime schema')
                        rows = db.execute('SELECT id,value FROM runtime').fetchall()
                        if len(rows) != 1 or rows[0][0] != 1:
                            raise ValueError('invalid runtime state')
                        state = json.loads(rows[0][1])
                    self.validate_state(state)
                    original = None if fresh else json.dumps(state)
                    if adopt and 'local_first' not in state:
                        state['local_first'] = dict(after_day=self._policy_boundary(state))
                        self.validate_state(state)
                    adopted = json.dumps(state)
                    yield state
                    self.validate_state(state)
                    result = adopted if readonly else json.dumps(state)
                    if result != original:
                        db.execute('INSERT OR REPLACE INTO runtime VALUES (1,?)', (result,))
                    db.commit()
                except BaseException:
                    db.rollback()
                    raise
        finally:
            os.close(fd)

    @staticmethod
    def validate_route(route):
        if not isinstance(route, dict) or set(route) != {'binding', 'platform', 'destination', 'channel_id', 'bot_id'}:
            raise ValueError('invalid route fields')
        validate_binding(route['binding'])
        if route['platform'] != 'discord' or not all(isinstance(route[k], str) and route[k].strip() for k in ('destination', 'channel_id', 'bot_id')):
            raise ValueError('only the Discord history adapter is supported')
        if route['destination'] != 'discord:' + route['channel_id']:
            raise ValueError('destination must identify the exact Discord channel or thread')
        binding = route['binding']
        channel = binding['chat'] if binding['thread'] == 'none' else binding['thread']
        if route['channel_id'] != channel:
            raise ValueError('binding must match exact history channel or thread')
        if route['bot_id'] == binding['owner']:
            raise ValueError('owner must not be the bot')

    def configure(self, route, *, confirm=False):
        if not confirm:
            raise ValueError('explicit setup confirmation required')
        self.validate_route(route)
        with self.transaction() as state:
            if state['outbox'] and state['route'] != route:
                raise ValueError('cannot rebind a nonempty outbox; use a separate data directory')
            if state['route'] != route:
                state.pop('history_consent', None)
            state['route'] = route
        return dict(configured=True, route=route, live_verified=False)

    def history_preference(self, *, enabled=None, route=None, confirm=False):
        """Explicit opt-in for this exact confirmed route; absent rc5 field is OFF."""
        with self.transaction(readonly=enabled is None, adopt=False) as state:
            if enabled is not None:
                if type(enabled) is not bool:
                    raise ValueError('history preference must be boolean')
                if enabled and (not confirm or route != state['route']):
                    raise ValueError('history requires explicit confirmation of the exact route')
                if state['route'] is None:
                    raise ValueError('runtime setup not confirmed')
                state['history_consent'] = dict(enabled=enabled, route=state['route'], generation=uuid.uuid4().hex)
                # A new consent generation cannot inherit old history evidence.
                for row in state['outbox'].values():
                    row['evidence'] = None
            return json.loads(json.dumps(state.get('history_consent',
                dict(enabled=False, route=state['route'], generation=None))))

    def history_plan(self, *, purpose, target, confirm=False):
        """Declare caller intent for one bounded on-demand read; no fetch or proof of intent."""
        preference = self.history_preference()
        if not preference['enabled']:
            raise ValueError('Discord history authorization required (default OFF)')
        if (not confirm or purpose not in ('reply-recovery', 'delivery-verification')
                or not isinstance(target, str) or not target.isdecimal()):
            raise ValueError('Discord history authorization requires explicit on-demand purpose and exact target')
        return dict(generation=preference['generation'], route=preference['route'],
            purpose=purpose, target=target, channel_id=preference['route']['channel_id'],
            limit=25, max_pages=1, max_payload_bytes=131072, max_message_bytes=8192,
            before=None, trigger='on-demand')

    def authorize_history(self, request, *, purpose, target):
        expected = self.history_plan(purpose=purpose, target=target, confirm=True)
        if (type(request) is not dict or request != expected
                or any(type(request.get(key)) is not type(value) for key, value in expected.items())):
            raise ValueError('Discord history authorization mismatch or revoked request')
        return expected

    def _authorize_ingress(self, operation, values, *, capture=True):
        self._require_history()
        request = values.get('history_plan')
        if not isinstance(request, dict):
            raise ValueError('Discord history authorization plan required')
        purpose = 'delivery-verification' if operation == 'confirm' else 'reply-recovery'
        # First validate the grant itself before looking at any caller capture.
        self.authorize_history(request, purpose=purpose, target=request.get('target'))
        with self.transaction(readonly=True, adopt=False) as runtime:
            route = runtime['route']
            if 'binding' in values and values['binding'] != route['binding']:
                raise ValueError('Discord history authorization binding mismatch')
            if operation in ('confirm', 'observe'):
                row = runtime['outbox'].get(values['token'])
                if not row or row['fence'] != values['fence'] or row['route'] != route:
                    raise ValueError('Discord history authorization unknown event or stale fence')
                if operation == 'confirm':
                    fixed = row.get('candidate_id') or row.get('receipt', {}).get('message_id')
                    if fixed and values.get('message_id') is not None and values['message_id'] != fixed:
                        raise ValueError('Discord history authorization conflicting receipt target')
                    target = fixed or values.get('message_id')
                else:
                    target = (row.get('previous') or {}).get('receipt', {}).get('message_id')
            elif operation == 'engagement':
                rows = [r for r in runtime['outbox'].values()
                        if r['route'] == route and r['state'] == 'confirmed']
                selected = [r for r in rows if r['receipt']['message_id'] == values.get('reply_to_message_id')] or rows
                row = max(selected, key=lambda r: (instant(r['receipt']['delivered_at']), int(r['receipt']['message_id']))) if selected else None
                target = row['receipt']['message_id'] if row else None
                if values.get('reply_to_message_id') is not None and values['reply_to_message_id'] != target:
                    raise ValueError('Discord history authorization unknown reply target')
            else:
                record = runtime.get('clarifications', {}).get(values['clarification_id'])
                if not record or record['binding'] != values['binding']:
                    raise ValueError('Discord history authorization unknown clarification')
                target = values['selection_message_id' if operation == 'resolve_clarification' else 'dismissal_message_id']
        self.authorize_history(request, purpose=purpose, target=target)
        if capture:
            self._history_capture_budget(values['pages'], request)

    @staticmethod
    def _history_capture_budget(pages, request):
        # Validate the raw envelope and every message, including the tail after
        # the target: the semantic parser may intentionally stop at its anchor.
        if type(pages) is not list or len(pages) != 1 or type(pages[0]) is not dict:
            raise ValueError('history budget requires exactly one raw page')
        page = pages[0]
        if (page.get('binding') != request['route']['binding']
                or page.get('channel_id') != request['channel_id']
                or 'before' not in page or page['before'] is not None
                or type(page.get('result')) is not dict):
            raise ValueError('history authorization raw envelope mismatch')
        result = page['result']
        for envelope in (page, result):
            if (('channel_id' in envelope and envelope['channel_id'] != request['channel_id'])
                    or ('before' in envelope and envelope['before'] is not None)
                    or ('limit' in envelope and (type(envelope['limit']) is not int or not 1 <= envelope['limit'] <= request['limit']))):
                raise ValueError('history authorization raw request mismatch')
        batch = result.get('messages')
        if type(batch) is not list or not 1 <= len(batch) <= request['limit']:
            raise ValueError('history message budget exceeded or unavailable')

        def bounded_json(value, maximum):
            total = 0
            try:
                for chunk in json.JSONEncoder(ensure_ascii=False).iterencode(value):
                    total += len(chunk.encode('utf-8'))
                    if total > maximum:
                        raise ValueError('history payload byte budget exceeded')
            except (TypeError, RecursionError, UnicodeError):
                raise ValueError('malformed history payload') from None
        for message in batch:
            if type(message) is not dict:
                raise ValueError('malformed history message')
            if 'channel_id' in message and message['channel_id'] != request['channel_id']:
                raise ValueError('history authorization raw message channel mismatch')
            bounded_json(message, request['max_message_bytes'])
        bounded_json(pages, request['max_payload_bytes'])
        if not any(message.get('id') == request['target'] for message in batch):
            raise ValueError('history authorization target missing from actual capture')

    def _history_state(self):
        # Authorization/rejection must not implicitly adopt an old runtime.
        with self.transaction(readonly=True, adopt=False) as state:
            return json.loads(json.dumps(state))

    def _history_row(self, token, fence):
        row = self._history_state()['outbox'].get(token)
        if row is None or row['fence'] != fence:
            raise ValueError('unknown event or stale fence')
        return row

    def _require_history(self):
        preference = self.history_preference()
        if not preference['enabled']:
            raise ValueError('Discord history authorization required (default OFF)')

    @staticmethod
    def _active_hold(state, now):
        hold = state.get('smart_snooze_hold')
        return hold if (state.get('smart_snooze_enabled', False) and hold
                        and now < instant(hold['expires'])) else None

    def smart_snooze(self, *, enabled=None, now=None):
        if enabled is not None and type(enabled) is not bool:
            raise ValueError('Smart Snooze preference must be boolean')
        with self.transaction() as state:
            if enabled is not None:
                if not enabled and state.get('smart_snooze_hold'):
                    hold = state['smart_snooze_hold']
                    cutoff = instant(now or datetime.now(UTC))
                    # Disabling cannot replay an opportunity suppressed while held.
                    # Engine first is conservative on a crash: the still-ON hold
                    # remains authoritative until the atomic runtime clear commits.
                    with self.coach._transaction() as engine:
                        for sequence in sequences(engine['episode']):
                            if (sequence['day'] == hold['day'] and sequence['binding'] == hold['route']['binding']
                                    and any(e['state'] == 'planned' and instant(e['slot']) <= cutoff
                                            for e in sequence['events'])):
                                sequence['stopped'] = sequence['stopped'] or 'missed-slot'
                    retry = state.get('clarification_retry')
                    if retry:
                        for event in retry['events']:
                            if event['state'] == 'planned' and instant(event['slot']) <= cutoff:
                                event['state'] = 'missed'
                    state.pop('smart_snooze_hold', None)
                state['smart_snooze_enabled'] = enabled
            return dict(enabled=state.get('smart_snooze_enabled', False))

    def status(self, *, now=None):
        with self.transaction() as state:
            result = json.loads(json.dumps(state))
            if state.get('smart_snooze_hold'):
                active = bool(self._active_hold(state, instant(now or datetime.now(UTC))))
                result['notification_policy'] = dict(active=active, reason='smart-snooze' if active else 'expired',
                    hold=result['smart_snooze_hold'])
            return result

    def restart(self, *, confirm=False, now=None):
        if confirm is not True:
            raise ValueError('explicit restart confirmation required')
        from zoneinfo import ZoneInfo
        # Hold the shared directory lock across both databases. Only coaching
        # state changes: a crash cannot leave an outbox half of a restart.
        with self.transaction(readonly=True) as runtime:
            self.validate_route(runtime['route'])
            # Deliberately stricter than day-based relevance: even an old row
            # may represent an in-flight worker. Never discard its journal.
            if runtime['outbox']:
                raise ValueError('restart requires an empty outbox; prior drafts or attempts are not restartable')
            path = self.directory / 'coach.sqlite3'
            safe_path(path)
            if not path.exists():
                raise ValueError('restart requires an already-stopped episode')
            # Already hold the directory lock: bypass only the engine's outer
            # flock, not its SQLite transaction or state/schema validation.
            with self.coach._transaction() as state:
                now = instant(now if now is not None else datetime.now(UTC))
                config = self.coach.config()
                day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
                previous = state['episode']
                if state['paused']:
                    raise ValueError('globally paused; restart does not clear pause')
                if not previous or not previous['stopped']:
                    raise ValueError('restart requires an already-stopped episode')
                old_day = now.astimezone(ZoneInfo(previous['config']['timezone'])).date().isoformat()
                if previous['day'] != day or previous['day'] != old_day:
                    raise ValueError('restart is limited to today in both saved and current timezones')
                if state['last_tick'] is not None and now < instant(state['last_tick']):
                    raise ValueError('clock regressed; restart refused')
                if previous['binding'] != runtime['route']['binding']:
                    raise ValueError('confirmed route does not match the stopped episode binding')
                if any(s['events'] for s in sequences(previous)):
                    raise ValueError('restart requires zero prior events, including unclaimed plans')
                episode = self.coach.plan(day, config, runtime['route']['binding'], now, state['recent'], future_only=True)
                if episode['task_id'] is None or not episode['events']:
                    raise ValueError('no eligible task or future slots remain today')
                state['episode'] = episode
                state['last_tick'] = now.isoformat()
                state['recent'] = (state['recent'] + [s['task_id'] for s in sequences(episode)])[-7:]
                return dict(restarted=True, wakeAgent=False, previous_stop=previous['stopped'], episode=episode)

    def prepare_test(self, *, confirm=False, now=None):
        """Authorize one fresh onboarding event, never a send or a schedule change."""
        if confirm is not True:
            raise ValueError('explicit one-check-in test confirmation required')
        from zoneinfo import ZoneInfo
        from .coaching import window_minutes, choose_task
        # Lock outbox and engine together. Refusing *any* episode/outbox avoids
        # replacing an active plan or reviving tokens held by another worker.
        with self.transaction(readonly=True) as runtime:
            self.validate_route(runtime['route'])
            if runtime['outbox']:
                raise ValueError('test requires an empty outbox; preserve all safety records')
            # Validate fallible read-only prerequisites before first DB creation;
            # a refused fresh setup must not leave an uninitialized SQLite file.
            now = instant(now if now is not None else datetime.now(UTC))
            config = self.coach.config()
            day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
            slot = now.replace(second=0, microsecond=0)
            minutes = window_minutes(day, config)
            if slot not in minutes:
                raise ValueError('test requires the current allowed day and notification window')
            from .coaching import eligible
            tasks = [task for task in self.coach.tasks() if eligible(task, now, config['timezone'])]
            if not tasks:
                raise ValueError('test requires an eligible task')
            with self.coach._transaction() as state:
                if state['paused']:
                    raise ValueError('globally paused; test does not clear pause')
                if state['episode'] is not None:
                    raise ValueError('test requires no existing episode; active and stopped plans are not replaceable')
                if state['last_tick'] is not None and now < instant(state['last_tick']):
                    raise ValueError('clock regressed; test refused')
                task = choose_task(tasks, now, config['timezone'], self.coach.rng, state['recent'])
                event = dict(token=uuid.uuid4().hex, index=0, slot=slot.isoformat(),
                             expires=min(slot + timedelta(minutes=10), minutes[-1] + timedelta(minutes=1)).isoformat(),
                             state='planned', receipt=None)
                episode = dict(day=day, task_id=task['id'], cycle_id=task.get('cycle_id'), binding=runtime['route']['binding'], config=config,
                               events=[event], stopped=None, purpose='one-check-in-test')
                state.update(episode=episode, last_tick=now.isoformat(), recent=(state['recent'] + [task['id']])[-7:])
                return dict(test_prepared=True, wakeAgent=False, episode=episode)

    def capabilities(self, *, history_available=None, history_error=None, now=None):
        """Caller reports optional native tool inventory/attempt; core discovers none."""
        if history_available is not None and type(history_available) is not bool:
            raise ValueError('history availability must be boolean or unknown')
        if history_error is not None and (not isinstance(history_error, str) or not history_error.strip()):
            raise ValueError('history error must be nonempty text')
        state = 'unavailable' if history_error or history_available is False else 'available' if history_available else 'unknown'
        local_first = self.local_first(now=now if now is not None else datetime.now(UTC))
        preference = self.history_preference()
        return dict(local_first=local_first,
                    history=dict(state=state, source='caller-inventory-or-attempt', error=history_error,
                                 consent=preference, routine_reads_allowed=False,
                                 delivery_verified=False,
                                 verification='availability-and-consent-are-not-delivery-evidence',
                                 purposes=['reply-recovery', 'delivery-verification']),
                    degraded=state != 'available', history_required=not local_first)

    def record_engagement(self, **kwargs):
        # Runtime audit and hold commit together BEFORE any start-work engine
        # mutation. A crash in the second phase is recovered from that audit.
        with self._directory_lock():
            result = self._record_engagement(**kwargs)
            if kwargs.get('intent') == 'start-work':
                with self.transaction(readonly=True) as runtime:
                    self._reconcile_start_work(runtime)
            return result

    def _reconcile_start_work(self, runtime):
        starts = [entry['request'] for entry in runtime.get('engagements', {}).values()
                  if entry['request']['intent'] == 'start-work']
        if not starts:
            return
        with self.coach._transaction() as engine:
            for request in starts:
                sequence = event_episode(engine['episode'], request['event_token'])
                if (sequence and sequence['binding'] == request['binding']
                        and sequence.get('cycle_id') == request['cycle_id']):
                    sequence['stopped'] = sequence['stopped'] or 'owner-engaged'

    def _record_engagement(self, *, binding, owner, message_id, event_token, task_id,
                          cycle_id, intent, now=None):
        """Agent-mediated explicit intent from trusted native inbound metadata.

        This records attribution, not an independently observed reply reference.
        """
        validate_binding(binding)
        if owner != binding['owner'] or not isinstance(message_id, str) or not message_id.strip():
            raise ValueError('exact trusted owner and inbound message ID required')
        if intent not in ('engaged', 'skip-for-now', 'start-work'):
            raise ValueError('explicit engagement intent required')
        now = instant(now or datetime.now(UTC))
        request = dict(binding=binding, owner=owner, message_id=message_id,
                       event_token=event_token, task_id=task_id, cycle_id=cycle_id, intent=intent)
        with self.transaction() as runtime:
            if runtime['route'] is None or runtime['route']['binding'] != binding:
                raise ValueError('inbound binding does not match authorized route')
            records = runtime.setdefault('engagements', {})
            if message_id in records:
                if records[message_id]['request'] != request:
                    raise ValueError('inbound identity already attributed differently')
                return records[message_id]['result']
            if (any(message_id in clarification.consumed(record)
                    for record in runtime.get('clarifications', {}).values())
                    or any(message_id == entry['message']['id']
                           for entry in runtime.get('clarification_responses', []))):
                raise ValueError('inbound identity already consumed by clarification')
            row = runtime['outbox'].get(event_token)
            if not row or row['state'] not in ('accepted', 'confirmed') or row['task']['id'] != task_id:
                raise ValueError('exact accepted task event required')
            with self.coach._transaction() as engine:
                sequence = event_episode(engine['episode'], event_token)
                task = next((t for t in self.coach.tasks() if t['id'] == task_id), None)
                from .coaching import task_available
                # A retained receipt identifies the reply even after daily rollover.
                # Only a still-present source sequence may be stopped by that reply.
                if (row['task'].get('cycle_id') != cycle_id or not same_cycle(row['task'], task)
                        or not task_available(task, now, self.coach.config()['timezone'])
                        or sequence and (sequence['binding'] != binding or sequence['task_id'] != task_id
                                         or not same_cycle(sequence, task))):
                    raise ValueError('stale or unavailable engagement sequence')
                result = dict(engaged=True, task_id=task_id, event_token=event_token,
                              provenance='agent-mediated-explicit-intent')
                records[message_id] = dict(request=request, result=result, recorded_at=now.isoformat())
                if intent == 'start-work':
                    from .coaching import window_minutes
                    from zoneinfo import ZoneInfo
                    config = self.coach.config()
                    day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
                    minutes = window_minutes(day, config)
                    if (now < instant(row['receipt']['delivered_at'])
                            or engine['last_tick'] and now < instant(engine['last_tick'])):
                        raise ValueError('start-work clock regressed')
                    in_window = minutes and minutes[0] <= now < minutes[-1] + timedelta(minutes=1)
                    if (in_window and runtime.get('smart_snooze_enabled', False)
                            and not self._active_hold(runtime, now)):
                        runtime['smart_snooze_hold'] = dict(route=runtime['route'], day=day, config=config,
                            event_token=event_token, task_id=task_id, message_id=message_id,
                            started_at=now.isoformat(), expires=(minutes[-1] + timedelta(minutes=1)).isoformat())
                self.validate_state(runtime)
                if sequence and intent != 'start-work':
                    sequence['stopped'] = sequence['stopped'] or 'owner-engaged'
            return result

    def local_first(self, *, now=None):
        with self.transaction(readonly=True) as runtime:
            policy = runtime.get('local_first')
            if policy is None:
                return False
            day = self._policy_boundary(runtime)
            if now is not None:
                from zoneinfo import ZoneInfo
                day = instant(now).astimezone(ZoneInfo(self.coach.config()['timezone'])).date().isoformat()
            return policy['after_day'] is None or day is not None and day > policy['after_day']

    def preflight(self, *, now=None):
        with self._directory_lock():
            return self._preflight(now=now)

    def _preflight(self, *, now=None):
        self.coach.config()  # Validate current settings before recoverable engine writes.
        with self.transaction() as locked:
            current = instant(now or datetime.now(UTC))
            self._reconcile_start_work(locked)
            if self._active_hold(locked, current):
                return dict(wakeAgent=False, reason='smart-snooze', hold=locked['smart_snooze_hold'])
            if locked.get('smart_snooze_hold') and current >= instant(locked['smart_snooze_hold']['expires']):
                locked.pop('smart_snooze_hold')
            runtime = json.loads(json.dumps(locked))
        self.coach.local_first = self.local_first(now=now or datetime.now(UTC))
        if self.coach.local_first:
            episode = self.coach.status()['episode']
            for row in runtime['outbox'].values():
                sequence = event_episode(episode, row['token']) if episode else None
                if row.get('acceptance') and sequence:
                    self.coach.reconcile(row['acceptance']['receipt'], now=now)
        route = runtime['route']
        if not self.coach.local_first and any(row['state'] == 'sending' for row in runtime['outbox'].values()):
            return dict(wakeAgent=False, reason='unconfirmed-delivery')
        if not self.coach.local_first and clarification.pending(runtime):
            with self.transaction() as locked:
                current = instant(now or datetime.now(UTC))
                with self.coach._transaction() as engine:
                    result = clarification.prepare(self, locked, engine, current)
                    if result is not None:
                        return result
                runtime = json.loads(json.dumps(locked))
                route = runtime['route']
        if route is None:
            return dict(wakeAgent=False, reason='setup-not-confirmed')
        prepared = self.coach.prepare(binding=route['binding'], now=now)
        if prepared['wakeAgent']:
            root = self.coach.status()['episode']
            sequence = event_episode(root, prepared['intent']['event_token'])
            event = next(e for e in sequence['events'] if e['token'] == prepared['intent']['event_token'])
            if not self.coach.local_first and self.missed_during_clarification(runtime, route['binding'], event):
                return dict(wakeAgent=False, reason='clarification-missed-opportunity')
        return prepared

    @staticmethod
    def missed_during_clarification(runtime, binding, event):
        return any(c['binding'] == binding and c['state'] in ('resolved', 'dismissed', 'retired')
                   and instant(event['slot']) <= instant(c['resolved_at'])
                   for c in runtime.get('clarifications', {}).values())

    def draft(self, token, body, *, now=None):
        prepared = self.preflight(now=now)
        if not prepared['wakeAgent'] or prepared['intent']['event_token'] != token:
            raise ValueError('event is not currently available')
        if not isinstance(body, str) or not body.strip() or len(body) > 1800 or 'MEDIA:' in body:
            raise ValueError('draft must be nonempty plain text of at most 1800 characters')
        with self.transaction() as state:
            existing = state['outbox'].get(token)
            if existing:
                if existing['body'] != body:
                    raise ValueError('conflicting draft')
                return existing
            row = dict(token=token, fence=uuid.uuid4().hex, state='draft', body=body,
                       route=state['route'], task=prepared['task'], intent=prepared['intent'], previous=prepared['previous'], evidence=None)
            state['outbox'][token] = row
            if clarification.retry_row(row):
                event = next(e for e in state['clarification_retry']['events'] if e['token'] == token)
                event['intent'] = json.loads(json.dumps(row['intent']))
            return row

    def row(self, token, fence):
        row = self.status()['outbox'].get(token)
        if row is None or row['fence'] != fence:
            raise ValueError('unknown event or stale fence')
        return row

    def authorize(self, row, *, now=None):
        """Last local authorization; a platform check/send race remains unavoidable."""
        now = instant(now or datetime.now(UTC))
        from zoneinfo import ZoneInfo
        from .coaching import DAYS, eligible
        with self.transaction(readonly=True) as runtime:
            if self._active_hold(runtime, now):
                raise ValueError('smart-snooze')
        if not self.local_first() and (row['previous'] or clarification.retry_row(row)):
            self._require_history()
        if clarification.retry_row(row):
            with self.transaction() as runtime:
                with self.coach._transaction() as engine:
                    return clarification.authorize(self, runtime, engine, row, now)
        if not self.local_first() and self.pending_clarifications(row['route']['binding']):
            raise ValueError('pending clarification; delivery held')
        config = self.coach.config()
        state = self.coach.status()
        root = state['episode']
        episode = event_episode(root, row['token'])
        event = next((e for e in episode['events'] if e['token'] == row['token']), None) if episode else None
        task = next((t for t in self.coach.tasks() if t['id'] == row['task']['id']), None)
        local = now.astimezone(ZoneInfo(config['timezone']))
        from .cli import validate_config
        if state['paused'] or not episode or root.get('window_stopped') or episode['stopped'] or validate_config(episode['config']) != config or episode['binding'] != row['route']['binding'] or self.status()['route'] != row['route']:
            raise ValueError('episode, pause, configuration or route changed')
        if not self.local_first() and event and self.missed_during_clarification(self.status(), row['route']['binding'], event):
            raise ValueError('clarification-missed-opportunity')
        if not event or event['state'] != 'claimed' or not instant(event['claimed_at']) <= now < min(instant(event['expires']), instant(event['claimed_at']) + timedelta(seconds=120)):
            raise ValueError('claim lease expired or event changed')
        if not same_snapshot(row['task'], task) or not eligible(task, now, config['timezone']) or local.date().isoformat() != episode['day'] or DAYS[local.weekday()] not in config['weekdays'] or not config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']:
            raise ValueError('task or notification window changed')
        if row['previous']:
            if not self.local_first():
                evidence = row['evidence']
                copy = dict(state, evidence_ids=[k for k in state['evidence_ids'] if not evidence or k != evidence['snapshot_id']])
                if not self.coach.check_evidence(evidence, row['previous'], row['route']['binding'], now, copy):
                    raise ValueError('fresh complete engagement evidence required')
            elapsed = (now-instant(row['previous']['receipt']['delivered_at'])).total_seconds()
            if not config['min_followup_interval']*60 <= elapsed <= config['max_followup_interval']*60:
                raise ValueError('actual delivery spacing exceeded')
        return True

    def dispatch(self, token, fence, *, hermes, now=None):
        now_supplied = now is not None
        now = instant(now or datetime.now(UTC))
        row = self.row(token, fence)
        local_first = self.local_first()
        if not local_first and (row['previous'] or clarification.retry_row(row)):
            self._require_history()
        if row['state'] != 'draft':
            raise ValueError('event already attempted; automatic resend forbidden')
        prepared = self.preflight(now=now)
        if not prepared['wakeAgent'] or prepared['intent'] != row['intent'] or not same_snapshot(row['task'], prepared['task']) or self.status()['route'] != row['route']:
            raise ValueError('draft authorization changed')
        if not clarification.retry_row(row):
            with self._directory_lock():
                with self.transaction(readonly=True) as runtime:
                    if self._active_hold(runtime, now):
                        raise ValueError('smart-snooze before claim')
                    claimed = self.coach.tick(now=now, binding=row['route']['binding'], evidence=row['evidence'], expected_token=token)
                    if not claimed['wakeAgent']:
                        raise ValueError('claim suppressed: ' + claimed['reason'])
        with self.transaction() as state:
            current = state['outbox'][token]
            if current['state'] != 'draft' or current['fence'] != fence:
                raise ValueError('event already attempted')
            if clarification.retry_row(row):
                with self.coach._transaction() as engine:
                    available = clarification.prepare(self, state, engine, now)
                    if not available or not available['wakeAgent'] or available['intent'] != row['intent']:
                        raise ValueError('clarification changed before claim')
                event = next(e for e in state['clarification_retry']['events'] if e['token'] == token)
                event['state'] = 'claimed'
            current.update(state='sending', attempted_at=now.isoformat())
        # The durable sending fence precedes the network boundary. Any exception,
        # timeout, crash, malformed or negative result leaves a nonretryable row.
        try:
            self.authorize(self.row(token, fence), now=now if now_supplied else None)
            # Serialize the final hold check with the send boundary. A hold
            # admitted by another worker cannot be bypassed after authorization.
            with self.transaction() as state:
                if not local_first and (row['previous'] or clarification.retry_row(row)):
                    if (not state.get('history_consent', {}).get('enabled', False)
                            or state['outbox'][token]['evidence'] != row['evidence']):
                        raise ValueError('Discord history authorization revoked at send boundary')
                if not local_first and not clarification.retry_row(row) and clarification.pending(state):
                    raise ValueError('pending clarification; delivery held')
                with self.coach._transaction() as engine:
                    if clarification.retry_row(row):
                        boundary = now if now_supplied else instant(datetime.now(UTC))
                        clarification.authorize(self, state, engine, state['outbox'][token],
                                                boundary)
                    else:
                        sequence = event_episode(engine['episode'], token)
                        event = next((e for e in sequence['events'] if e['token'] == token), None) if sequence else None
                        task = next((t for t in self.coach.tasks() if t['id'] == row['task']['id']), None)
                        from .coaching import eligible, DAYS
                        from .cli import validate_config
                        from zoneinfo import ZoneInfo
                        boundary = now if now_supplied else instant(datetime.now(UTC))
                        config = self.coach.config()
                        local = boundary.astimezone(ZoneInfo(config['timezone']))
                        if (engine['paused'] or engine['episode'].get('window_stopped') or not sequence or sequence['stopped']
                                or validate_config(sequence['config']) != config or sequence['binding'] != row['route']['binding']
                                or state['route'] != row['route'] or not event or event['state'] != 'claimed'
                                or not instant(event['claimed_at']) <= boundary < min(instant(event['expires']), instant(event['claimed_at']) + timedelta(seconds=120))
                                or local.date().isoformat() != sequence['day'] or DAYS[local.weekday()] not in config['weekdays']
                                or not config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']):
                            raise ValueError('local authorization changed at send boundary')
                        if event is None or not same_snapshot(row['task'], task) or not same_cycle(sequence, task) or not eligible(task, boundary, config['timezone']):
                            raise ValueError('task or event changed at send boundary')
                        if row['previous']:
                            elapsed = (boundary - instant(row['previous']['receipt']['delivered_at'])).total_seconds()
                            if not config['min_followup_interval'] * 60 <= elapsed <= config['max_followup_interval'] * 60:
                                raise ValueError('actual delivery spacing exceeded at send boundary')
                        if not local_first and self.missed_during_clarification(state, row['route']['binding'], event):
                            raise ValueError('clarification-missed-opportunity')
                if self._active_hold(state, boundary):
                    raise ValueError('smart-snooze at send boundary')
                result = subprocess.run([hermes, 'send', '--json', '--to', row['route']['destination'], '--', row['body']],
                                        capture_output=True, text=True, timeout=45, check=False)
                payload = json.loads(result.stdout)
                if not isinstance(payload, dict):
                    raise ValueError('send result must be a JSON object')
                message_id = payload.get('message_id')
                if result.returncode or payload.get('success') is not True or payload.get('skipped') or payload.get('error') or not isinstance(message_id, str) or not message_id.strip():
                    raise ValueError('send did not return a positive message identifier')
                if any(other['token'] != token and other['route'] == row['route']
                       and (other.get('candidate_id') == message_id or other.get('receipt', {}).get('message_id') == message_id)
                       for other in state['outbox'].values()):
                    raise ValueError('replayed native message identifier')
                state['outbox'][token]['candidate_id'] = message_id
                if local_first:
                    accepted_at = now if now_supplied else instant(datetime.now(UTC))
                    receipt = dict(event_token=token, binding=row['route']['binding'],
                                   message_id=message_id, cursor=message_id, delivered_at=accepted_at.isoformat())
                    state['outbox'][token].update(state='accepted', receipt=receipt,
                        acceptance=dict(provenance='native-send-response', receipt=receipt))
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            with self.transaction() as state:
                state['outbox'][token]['uncertain'] = str(error)
        result = self.row(token, fence)
        if result['state'] == 'accepted':
            self.coach.reconcile(result['receipt'], now=result['receipt']['delivered_at'])
        return result

    @history_ingress
    def confirm(self, token, fence, pages, *, now=None, message_id=None, history_plan=None):
        return self._confirm_capture(token, fence, pages, now=now, message_id=message_id)

    def _confirm_capture(self, token, fence, pages, *, now=None, message_id=None):
        # Private reuse by observe: its lease already authorizes this exact
        # target/capture for reply recovery, including optional anchor readback.
        self._require_history()
        now = instant(now or datetime.now(UTC))
        row = self._history_row(token, fence)
        if row.get('candidate_id') and message_id is not None and message_id != row['candidate_id']:
            raise ValueError('conflicting candidate ID')
        candidate = row.get('candidate_id') or message_id or row.get('receipt', {}).get('message_id')
        if row['state'] not in ('sending', 'accepted', 'confirmed') or not candidate:
            raise ValueError('confirmation requires a journaled sending attempt and exact message ID')
        if row.get('candidate_id'):
            messages = validate_pages(pages, row['route'], candidate, now)
        else:
            # Anchor validation normally truncates at the selected ID. Recovery
            # must inspect the raw tail too, and cover the entire attempt interval.
            captured = validate_pages(pages, row['route'], candidate, now,
                                      recovery_start=instant(row['attempted_at']))
            matches = [m for m in captured if m['author']['id'] == row['route']['bot_id']
                       and m['author']['bot'] is True and m['content'] == row['body']
                       and instant(row['attempted_at']) <= instant(m['timestamp']) <= now]
            if len(matches) != 1 or matches[0]['id'] != candidate:
                raise ValueError('ambiguous lost-response history')
            messages = captured[:next(i for i, m in enumerate(captured) if m['id'] == candidate) + 1]
        message = next(m for m in messages if m['id'] == candidate)
        delivered = instant(message['timestamp'])
        if message['author']['id'] != row['route']['bot_id'] or message['author']['bot'] is not True or message['content'] != row['body'] or not instant(row['attempted_at']) <= delivered <= now or instant(row['attempted_at']) >= instant(row['intent']['expires']):
            raise ValueError('sent-message readback does not match journaled attempt')
        receipt = dict(event_token=token, binding=row['route']['binding'], message_id=message['id'], cursor=message['id'], delivered_at=message['timestamp'])
        if row['state'] == 'confirmed':
            if receipt != row['receipt']:
                raise ValueError('conflicting confirmed receipt')
            return row['receipt']
        for other in self.status()['outbox'].values():
            if other['token'] != token and other.get('receipt', {}).get('message_id') == message['id'] and other['route'] == row['route']:
                raise ValueError('replayed receipt')
        episode = self.coach.status()['episode']
        if not clarification.retry_row(row) and not row.get('acceptance') and episode and event_episode(episode, token) is not None:
            self.coach.reconcile(receipt, now=now)
        with self.transaction() as state:
            current = state['outbox'][token]
            if current['state'] == 'confirmed':
                if current['receipt'] != receipt:
                    raise ValueError('conflicting confirmed receipt')
                return current['receipt']
            current.update(state='confirmed', receipt=receipt)
            if clarification.retry_row(row):
                clarification.activity(state, messages[:-1], ids=row['intent']['clarification_ids'])
        if not clarification.retry_row(row):
            self._attribute_engagement(messages[:-1], row['route'])
        return receipt

    @history_ingress
    def observe(self, token, fence, pages, *, now=None, history_plan=None):
        self._require_history()
        now = instant(now or datetime.now(UTC))
        row = self._history_row(token, fence)
        if clarification.retry_row(row):
            with self.transaction() as runtime:
                return clarification.observe(self, runtime, runtime['outbox'][token], pages, now)
        previous = row['previous']
        if not previous or not previous['receipt']:
            raise ValueError('observation requires a delivered previous event')
        receipt = previous['receipt']
        messages = validate_pages(pages, row['route'], receipt['message_id'], now)
        # Acceptance timestamps describe the native response, not platform time.
        # Optional observation can independently verify that exact prior attempt;
        # retain its original acceptance and use the verified anchor for history.
        prior = self._history_state()['outbox'].get(previous['token'])
        if not prior or prior['route'] != row['route']:
            raise ValueError('history anchor does not match previous route')
        # All prior receipts, including legacy ones, require exact readback.
        receipt = self._confirm_capture(prior['token'], prior['fence'], pages, now=now)
        anchor = messages[-1]
        if anchor['author']['id'] != row['route']['bot_id'] or anchor['author']['bot'] is not True or instant(anchor['timestamp']) != instant(receipt['delivered_at']):
            raise ValueError('history anchor does not match previous receipt')
        fallback = dict(row, token=previous['token'], receipt=receipt)
        targets, ambiguous = self._attribute_engagement(messages[:-1], row['route'], fallback=fallback)
        ambiguous = ambiguous or bool(self.pending_clarifications(row['route']['binding']))
        engaged = not ambiguous and any(target and target['task']['id'] == row['task']['id'] for target in targets)
        evidence = dict(binding=row['route']['binding'], event_token=previous['token'], message_id=receipt['message_id'], cursor=receipt['cursor'], snapshot_id=uuid.uuid4().hex, observed_at=min(instant(p['observed_at']) for p in pages).isoformat(), complete=not ambiguous, engaged=engaged, error='ambiguous-engagement' if ambiguous else None)
        with self.transaction() as state:
            state['outbox'][token]['evidence'] = evidence
        return evidence

    def _attribute_engagement(self, messages, route, *, fallback=None, trusted_references=None):
        """Classify the entire batch before engagement; persist only ambiguity holds."""
        from .coaching import task_available
        with self.transaction() as runtime:
            with self.coach._transaction() as state:
                episode = state['episode']
                policy = runtime.get('local_first')
                local_first = policy is not None and (policy['after_day'] is None or episode and episode['day'] > policy['after_day'])
                rows = [r for r in runtime['outbox'].values()
                        if r['route'] == route and (r['state'] == 'confirmed' or local_first and r['state'] == 'accepted')]
                if fallback and not any(r['token'] == fallback['token'] for r in rows):
                    rows.append(fallback)
                tasks = {t['id']: t for t in self.coach.tasks()}
                rows = [r for r in rows if clarification.retry_row(r) or same_cycle(r['task'], tasks.get(r['task']['id']))]
                records = runtime.get('clarifications', {})
                already_held = any(c['state'] not in clarification.TERMINAL for c in records.values())
                targets, ambiguous, observations = [], False, []
                for message in messages:
                    if message['author']['id'] != route['binding']['owner'] or message['author']['bot'] is not False:
                        continue
                    prior = runtime.get('engagements', {}).get(message['id'])
                    if prior:
                        target = next((r for r in rows if r['token'] == prior['request']['event_token']), None)
                        reference = (trusted_references or {}).get(message['id'], message.get('message_reference'))
                        if (target and ('message' not in prior or prior['message'] == message)
                                and (reference is None or reference.get('message_id') == target['receipt']['message_id']
                                     and reference.get('channel_id', route['channel_id']) == route['channel_id'])):
                            targets.append(target)
                        continue
                    if any(((c['state'] == 'resolved' and c['selection']['id'] == message['id'])
                            or (c['state'] == 'dismissed' and c['dismissal']['id'] == message['id']))
                           and c['binding'] == route['binding'] for c in records.values()):
                        continue
                    existing = next((c for c in records.values()
                                     if c['binding'] == route['binding'] and c['message']['id'] == message['id']), None)
                    if existing:
                        if existing['state'] in ('dismissed', 'retired'):
                            continue
                        if existing['message'] != message:
                            raise ValueError('conflicting captured original message')
                        if existing['state'] not in clarification.TERMINAL:
                            ambiguous = True
                            targets.append(None)
                        else:
                            targets.append(next((r for r in rows if r['token'] == existing['selected_token']), None))
                        continue
                    if (any(message['id'] in clarification.consumed(c) for c in records.values())
                            or any(message['id'] == r['message']['id'] for r in runtime.get('clarification_responses', []))):
                        continue
                    # Trusted inbound attribution must not alter the raw capture
                    # later compared by explicit selection/dismissal.
                    reference = (trusted_references or {}).get(message['id'], message.get('message_reference'))
                    retry_target = next((r for r in rows if clarification.retry_row(r) and reference
                                         and r['receipt']['message_id'] == reference['message_id']
                                         and reference.get('channel_id', route['channel_id']) == route['channel_id']), None)
                    if retry_target:
                        clarification.activity(runtime, [message], ids=retry_target['intent']['clarification_ids'])
                        ambiguous = bool(clarification.pending(runtime)) or ambiguous
                        targets.append(None)
                        continue
                    if already_held:
                        clarification.activity(runtime, [message])
                        # A later inbound may be the answer to the outstanding
                        # question. Leave it unclassified until explicit resolution;
                        # an in-flight observer must not create a second hold for it.
                        ambiguous = True
                        targets.append(None)
                        continue
                    candidates = [dict(r, task=tasks[r['task']['id']]) for r in rows
                                  if not clarification.retry_row(r) and r['task']['id'] in tasks and same_cycle(r['task'], tasks[r['task']['id']]) and task_available(tasks[r['task']['id']], instant(message['timestamp']), self.coach.config()['timezone'])
                                  and int(r['receipt']['message_id']) < int(message['id'])
                                  and instant(r['receipt']['delivered_at']) <= instant(message['timestamp'])]
                    if reference is None:
                        candidates = [r for r in candidates if clarification.current_receipt(runtime, r)]
                    if reference is not None:
                        candidates = [r for r in candidates if r['receipt']['message_id'] == reference['message_id']
                                      and reference.get('channel_id', route['channel_id']) == route['channel_id']]
                    elif (local_first or 'message_reference' not in message) and len({r['task']['id'] for r in candidates}) > 1:
                        if local_first:
                            # Ask conversationally; do not create new global holds.
                            ambiguous = True
                            targets.append(None)
                            continue
                        # One immutable receipt/task snapshot per candidate task.
                        latest = {}
                        for r in sorted(candidates, key=lambda r: int(r['receipt']['message_id'])):
                            latest[r['task']['id']] = dict(token=r['token'], task=r['task'], receipt=r['receipt'])
                        key = uuid.uuid4().hex
                        records[key] = dict(id=key, binding=route['binding'], message=message,
                                            candidates=list(latest.values()), state='pending')
                        runtime['clarifications'] = records
                        ambiguous = True
                        targets.append(None)
                        continue
                    target = max(candidates, key=lambda r: int(r['receipt']['message_id'])) if candidates else None
                    targets.append(target)
                    if target and target['token'] in runtime['outbox']:
                        observations.append((message, target))
                # A clear message cannot consume a candidate while any batch is held.
                if not ambiguous and not any(c['state'] not in clarification.TERMINAL for c in records.values()):
                    for message, target in observations:
                        request = dict(binding=route['binding'], owner=route['binding']['owner'], message_id=message['id'],
                                       event_token=target['token'], task_id=target['task']['id'],
                                       cycle_id=target['task'].get('cycle_id'), intent='engaged')
                        runtime.setdefault('engagements', {})[message['id']] = dict(request=request, message=message,
                            result=dict(engaged=True, task_id=target['task']['id'], event_token=target['token'],
                                        provenance='captured-owner-history'), recorded_at=instant(message['timestamp']).isoformat())
                    # Validate the shared ledger before any engine mutation.
                    self.validate_state(runtime)
                    for target in targets:
                        if target and episode and event_episode(episode, target['token']) is not None:
                            sequence = event_episode(episode, target['token'])
                            sequence['stopped'] = sequence['stopped'] or 'owner-engaged'
                return targets, ambiguous

    @history_ingress
    def resolve_clarification(self, *, binding, clarification_id, task_id,
                              selection_message_id, pages, now=None, history_plan=None):
        """Normal-inbound explicit selection, not manufactured Discord reply metadata."""
        self._require_history()
        from .coaching import task_available
        now_supplied = now is not None
        validate_binding(binding)
        if not isinstance(selection_message_id, str) or not selection_message_id.isdecimal():
            raise ValueError('selection requires an exact captured owner message ID')
        with self.transaction() as runtime:
            now = instant(now if now_supplied else datetime.now(UTC))
            record = runtime.get('clarifications', {}).get(clarification_id)
            if not record or record['binding'] != binding or runtime['route']['binding'] != binding:
                raise ValueError('unknown clarification or binding mismatch')
            candidate = next((c for c in record['candidates'] if c['task']['id'] == task_id), None)
            if candidate is None or type(task_id) is not int:
                raise ValueError('selection is not a captured candidate')
            if record['state'] in ('dismissed', 'retired'):
                raise ValueError('clarification already dismissed or retired; conflicting resolution')
            if record['state'] in ('resolving', 'resolved'):
                anchor = min(record['candidates'], key=lambda c: int(c['receipt']['message_id']))['receipt']
                messages = validate_pages(pages, runtime['route'], anchor['message_id'], now)
                captured = next((m for m in messages if m['id'] == selection_message_id), None)
                if captured != record['selection']:
                    raise ValueError('conflicting captured selection message')
                if record['selected_token'] != candidate['token'] or record['selection']['id'] != selection_message_id:
                    raise ValueError('conflicting clarification resolution')
                if record['state'] == 'resolved':
                    task = next((t for t in self.coach.tasks() if t['id'] == task_id), None)
                    if not same_cycle(candidate['task'], task):
                        raise ValueError('resolved clarification belongs to an older task cycle')
                    return record['result']
                if now < instant(record['resolved_at']):
                    raise ValueError('clock regressed during clarification resolution')
                with self.coach._transaction() as state:
                    sequence = event_episode(state['episode'], candidate['token'])
                    task = next((t for t in self.coach.tasks() if t['id'] == task_id), None)
                    if not same_snapshot(candidate['task'], task) or not task_available(task, now, self.coach.config()['timezone']):
                        raise ValueError('candidate is no longer valid; preserve the hold')
                    if sequence and sequence['binding'] == binding:
                        sequence['stopped'] = sequence['stopped'] or 'owner-engaged'
                released = now if now_supplied else instant(datetime.now(UTC))
                record.update(state='resolved', resolved_at=max(now, released).isoformat())
                return record['result']
            for other in runtime.get('clarifications', {}).values():
                consumed = clarification.consumed(other)
                if other is record:
                    consumed -= {m['id'] for m in record.get('responses', [])}
                if selection_message_id in consumed:
                    raise ValueError('selection message already belongs to a clarification')
            anchor = min(record['candidates'], key=lambda c: int(c['receipt']['message_id']))['receipt']
            messages = validate_pages(pages, runtime['route'], anchor['message_id'], now)
            original = next((m for m in messages if m['id'] == record['message']['id']), None)
            selection = next((m for m in messages if m['id'] == selection_message_id), None)
            if original != record['message']:
                raise ValueError('original captured message changed or missing')
            if (not selection or selection['author'] != original['author']
                    or int(selection['id']) <= int(original['id'])
                    or instant(selection['timestamp']) < instant(original['timestamp'])):
                raise ValueError('selection must be a later captured bound owner message')
            # Receipt identity remains independent of attribution and immutable.
            row = runtime['outbox'].get(candidate['token'])
            if not row or row['state'] != 'confirmed' or row['receipt'] != candidate['receipt']:
                raise ValueError('candidate receipt changed')
            with self.coach._transaction() as state:
                sequence = event_episode(state['episode'], candidate['token'])
                task = next((t for t in self.coach.tasks() if t['id'] == task_id), None)
                if not same_snapshot(candidate['task'], task) or not task_available(task, now, self.coach.config()['timezone']):
                    raise ValueError('candidate is no longer valid; preserve the hold')
                # Validate before persisting the write-ahead explicit choice.
                # No engagement until that choice has committed in the outbox.
                context = dict(task=candidate['task'], task_id=task_id, event_token=candidate['token'],
                               receipt=candidate['receipt'], binding=binding)
                result = dict(engaged=True, context=context, provenance='explicit-owner-selection',
                              clarification_id=clarification_id, original_message_id=original['id'],
                              selection_message_id=selection['id'])
            clarification.bind_response(runtime, record, selection)
            record.update(state='resolving', selected_token=candidate['token'], selection=selection,
                          result=result, resolved_at=now.isoformat())
        # The committed choice fences competing selections across crashes. The
        # second transaction changes only that task's engine suppression and
        # releases the hold after engine commit; an interrupted retry is safe.
        return self.resolve_clarification(binding=binding, clarification_id=clarification_id,
            task_id=task_id, selection_message_id=selection_message_id, pages=pages,
            now=now if now_supplied else None, history_plan=history_plan)

    @history_ingress
    def dismiss_clarification(self, *, binding, clarification_id, dismissal_message_id, pages, now=None, history_plan=None):
        """Discard one pending question on skill-mediated explicit owner intent.

        No text classifier and no engine write: an existing write-ahead resolution
        is deliberately irreversible here, even if its engine commit is uncertain.
        """
        self._require_history()
        validate_binding(binding)
        if not isinstance(dismissal_message_id, str) or not dismissal_message_id.isdecimal():
            raise ValueError('dismissal requires an exact captured owner message ID')
        with self.transaction() as runtime:
            current = instant(now or datetime.now(UTC))
            record = runtime.get('clarifications', {}).get(clarification_id)
            if not record or record['binding'] != binding or runtime['route']['binding'] != binding:
                raise ValueError('unknown clarification or binding mismatch')
            if record['state'] == 'dismissed':
                anchor = min(record['candidates'], key=lambda c: int(c['receipt']['message_id']))['receipt']
                messages = validate_pages(pages, runtime['route'], anchor['message_id'], current)
                captured = next((m for m in messages if m['id'] == dismissal_message_id), None)
                if captured != record['dismissal']:
                    raise ValueError('conflicting captured dismissal message')
                if record['dismissal']['id'] != dismissal_message_id:
                    raise ValueError('conflicting clarification dismissal')
                return record['result']
            if record['state'] != 'pending':
                raise ValueError('conflicting resolution already durable; cannot dismiss')
            for other in runtime.get('clarifications', {}).values():
                consumed = clarification.consumed(other)
                if other is record:
                    consumed -= {m['id'] for m in record.get('responses', [])}
                if dismissal_message_id in consumed:
                    raise ValueError('dismissal message already belongs to a clarification')
            anchor_candidate = min(record['candidates'], key=lambda c: int(c['receipt']['message_id']))
            receipt = anchor_candidate['receipt']
            messages = validate_pages(pages, runtime['route'], receipt['message_id'], current)
            anchor = messages[-1]
            row = runtime['outbox'][anchor_candidate['token']]
            if (anchor['author']['id'] != runtime['route']['bot_id'] or anchor['author']['bot'] is not True
                    or instant(anchor['timestamp']) != instant(receipt['delivered_at'])
                    or anchor['content'] != row['body']):
                raise ValueError('history anchor does not match confirmed receipt')
            dismissal = next((m for m in messages if m['id'] == dismissal_message_id), None)
            original = record['message']
            if (not dismissal or dismissal['author']['id'] != binding['owner'] or dismissal['author']['bot'] is not False
                    or int(dismissal['id']) <= int(original['id'])
                    or instant(dismissal['timestamp']) < instant(original['timestamp'])):
                raise ValueError('dismissal must be a later captured bound owner message')
            # Use actual release time, not command start, including freshness.
            released = instant(now or datetime.now(UTC))
            if released < current:
                raise ValueError('clock regressed during clarification dismissal')
            validate_pages(pages, runtime['route'], receipt['message_id'], released)
            result = dict(dismissed=True, engaged=False, clarification_id=clarification_id,
                          original_message_id=original['id'], dismissal_message_id=dismissal['id'],
                          provenance='explicit-owner-dismissal')
            clarification.bind_response(runtime, record, dismissal)
            record.update(state='dismissed', dismissal=dismissal, result=result, resolved_at=released.isoformat())
            return result

    def pending_clarifications(self, binding):
        return [c for c in self.status().get('clarifications', {}).values()
                if c['binding'] == binding and c['state'] not in clarification.TERMINAL]

    @history_ingress
    def engagement(self, binding, pages, *, now=None, reply_to_message_id=None, inbound_message_id=None, history_plan=None):
        self._require_history()
        now = instant(now or datetime.now(UTC))
        validate_binding(binding)
        if (reply_to_message_id is None) != (inbound_message_id is None):
            raise ValueError('trusted inbound reply requires both message and target IDs')
        if reply_to_message_id is not None and any(not isinstance(value, str) or not value.isdecimal()
                                                  for value in (reply_to_message_id, inbound_message_id)):
            raise ValueError('trusted inbound IDs must be decimal strings')
        rows = [r for r in self._history_state()['outbox'].values() if r['route']['binding'] == binding and r['state'] == 'confirmed']
        if not rows:
            return dict(engaged=False, context=None, error=None)
        selected = [r for r in rows if r['receipt']['message_id'] == reply_to_message_id] or rows
        row = max(selected, key=lambda r: (instant(r['receipt']['delivered_at']), int(r['receipt']['message_id'])))
        messages = validate_pages(pages, row['route'], row['receipt']['message_id'], now)
        anchor = messages[-1]
        if (anchor['author']['id'] != row['route']['bot_id'] or anchor['author']['bot'] is not True
                or anchor['content'] != row['body']
                or instant(anchor['timestamp']) != instant(row['receipt']['delivered_at'])):
            raise ValueError('history anchor does not match exact confirmed receipt')
        owners = messages[:-1]
        trusted_references = {}
        if inbound_message_id is not None:
            owners = [m for m in owners if m['id'] == inbound_message_id
                      and m['author']['id'] == binding['owner'] and m['author']['bot'] is False]
            if len(owners) != 1:
                raise ValueError('trusted inbound message is not a captured owner message after the anchor')
            reference = dict(message_id=reply_to_message_id, channel_id=row['route']['channel_id'])
            if 'message_reference' in owners[0] and reference_key(owners[0]['message_reference'], row['route']['channel_id']) != reference_key(reference, row['route']['channel_id']):
                raise ValueError('conflicting reply target metadata')
            trusted_references[inbound_message_id] = reference
        targets, ambiguous = self._attribute_engagement(owners, row['route'], trusted_references=trusted_references)
        if ambiguous or self.pending_clarifications(binding):
            return dict(engaged=False, context=None, error='ambiguous-engagement',
                        clarifications=self.pending_clarifications(binding))
        target = targets[0] if targets else None
        context = self.context(binding, reply_to_message_id=target['receipt']['message_id']) if target else None
        return dict(engaged=target is not None, context=context, error=None)

    def native_plan(self, profile_home, *, python, helper, hermes):
        paths = [Path(p) for p in (profile_home, python, helper, hermes)]
        if any(not p.is_absolute() for p in paths):
            raise ValueError('profile, Python, helper and Hermes paths must be absolute')
        profile, python_path, helper_path, hermes_path = paths
        script = profile / 'scripts' / 'task-coach-preflight.py'
        if not script.resolve().is_relative_to(profile.resolve() / 'scripts'):
            raise ValueError('wrapper must resolve inside active profile scripts')
        command = [str(python_path), '-I', '-B', str(helper_path), '--data-dir', str(self.directory.resolve()), 'runtime', 'preflight']
        text = '#!' + str(python_path) + '\nimport json, subprocess\n'
        text += 'result = {"wakeAgent": False, "reason": "preflight-error"}\ntry:\n'
        text += '    process = subprocess.run(' + repr(command) + ', capture_output=True, text=True, timeout=30)\n'
        text += '    candidate = json.loads(process.stdout.splitlines()[-1])\n'
        text += '    if process.returncode == 0 and type(candidate.get("wakeAgent")) is bool:\n        result = candidate\n'
        text += 'except Exception:\n    pass\nprint(json.dumps(result))\n'
        # Final policy applies to every preview, including preserved legacy days.
        prompt = ('Load task-coach. Use helper ' + str(helper_path) + ' with --data-dir ' + str(self.directory.resolve())
            + '. Re-run runtime preflight and runtime capabilities. Never fetch Discord history in routine cron, even with saved opt-in. '
            'Do not call history-plan or any external history tool in scheduled turns. No hosted connector, source imports, raw credentials or alternate APIs. '
            'For local-first work local eligibility, recorded engagement, windows, spacing, budgets and pause authorize openers AND followups without history. '
            'Task check-in days (weekdays/weekends/all) narrow the global allowed days for both openers and followups; never override them for overdue tasks. '
            'A smart-snooze guard suppresses ALL Task Coach notifications until the saved window expiry; stop without drafting or sending. Never reset or replay held opportunities. '
            'Compose only for the returned current task; runtime draft then runtime dispatch --hermes ' + str(hermes_path) + '. '
            'Native Hermes send is the only transport. Accepted is transport acceptance, not independently verified arrival. '
            'Optional history failure or an absent anchor is a verification warning, never a local-first scheduling lock. '
            'Never revive missed slots or resend attempted/uncertain events. Actual failed/uncertain sends require [CRON_FAILURE]; quiet guards and optional verification warnings are separate. '
            'No final chat delivery: delivery is handled by the helper.')
        instruction = ('For normal inbound ONLY matching the confirmed owner/profile/account/chat/thread binding, load task-coach and inspect runtime status/context. '
            'Record explicit owner intent and clear task engagement BEFORE substantive assistance, memory recall or delegation when an applicable accepted check-in exists. Use trusted runtime record-engagement --binding JSON --owner OWNER --message-id INBOUND_ID --event-token EVENT --task-id TASK '
            '[--cycle-id CYCLE] --intent start-work for genuine explicit agreement to begin working now; use engaged for generic engagement or skip-for-now for a skip. Never reinterpret old engaged audit as start-work. Use the genuine inbound message ID and current task/event/cycle; clarify ambiguity, never invent IDs or history. Read back before claiming suppression. No history is required for local-first engagement. '
            'Reply handling is independent of notification days, hours and daily-plan rollover. Use conversation and saved tasks/check-ins to identify the task. Ask naturally which task when ambiguous; never guess the newest. '
            'A retained accepted event for the current task/cycle may record engagement after rollover; do not invent reply references or events. If no applicable accepted event exists, continue ordinary task help without claiming suppression. '
            'Start-work outside an allowed notification window records engagement without a hold; inside an allowed notification window, Smart Snooze ON may hold the remainder of that window even for an older check-in. Never create future holds from retries. '
            'Do not complete/snooze tasks or globally freeze local-first work without explicit intent. '
            'Inspect runtime history-preference and runtime capabilities --history-availability unknown|unavailable|available; tool availability is not consent or delivery verification. '
            'With history OFF make no external history reads. With exact-route consent ON, only an explicitly requested reply-recovery or delivery-verification may use '
            'runtime history-plan --purpose PURPOSE --target DECIMAL_ID --confirm-history. Save the returned dict grant privately, then fetch at most 25 latest messages, '
            'ONE page, before=null, at most 131072 payload bytes and 8192 bytes per message for that exact route/generation/purpose/target. '
            'Pass --history-plan-file FILE alongside --pages-file FILE to the appropriate runtime enrichment command. Never chase old anchors or fabricate captures. '
            'An absent anchor or optional failure is a warning, not a block on accepted/local-first work. '
            'The plan records caller-asserted explicit user intent; it cannot cryptographically prove the user asked. Helper gates do not sandbox arbitrary external tools. '
            'Never fetch routinely, substitute an MCP/hosted connector, or infer consent from tool availability. '
            'Retain exact identities for retries; preserve immutable clarification outcomes, resolving/resolved choices and uncertain attempts. '
            'Smart Snooze defaults OFF; runtime smart-snooze reads or explicitly changes it with --enable/--disable. A new start-work reply while ON holds all Task Coach notifications for the remaining current local window, without task changes. Disable clears the hold; old message retries never recreate it. A send already in flight cannot be recalled. '
            'Pause uses coach pause and readback; completion, snooze and other task edits need separate explicit intent.')
        history_policy = dict(default='off', routine_reads_allowed=False,
            purposes=['reply-recovery', 'delivery-verification'], limit=25, max_pages=1,
            max_payload_bytes=131072, max_message_bytes=8192,
            tool_restrictions='Deny history tools in routine cron; review scoped inbound allowlists separately. Never auto-provision connectors.',
            refresh='Review/refresh installed instructions and tool allowlists after preference changes; persisted core denial is immediate.')
        return dict(script_path=str(script), script_text=text, history_policy=history_policy,
                    cron_argv=[str(hermes_path), 'cron', 'create', 'every 1m', prompt, '--name', 'task-coach', '--skill', 'task-coach', '--script', str(script.relative_to(profile / 'scripts')), '--deliver', 'local', '--failure-deliver', 'local', '--paused'],
                    inbound_instruction=instruction, initially_paused=True, live_verified=False)

    def context(self, binding, *, reply_to_message_id=None):
        validate_binding(binding)
        rows = [row for row in self.status()['outbox'].values() if row['route']['binding'] == binding and row['state'] in ('accepted', 'confirmed')]
        if reply_to_message_id is not None:
            rows = [row for row in rows if row['receipt']['message_id'] == reply_to_message_id]
        else:
            from .coaching import task_available
            tasks = {t['id']: t for t in self.coach.tasks()}
            runtime = self.status()
            rows = [r for r in rows if clarification.current_receipt(runtime, r) and r['task']['id'] in tasks
                    and same_cycle(r['task'], tasks[r['task']['id']]) and task_available(tasks[r['task']['id']], datetime.now(UTC), self.coach.config()['timezone'])]
            if len({row['task']['id'] for row in rows}) > 1:
                return None
        if not rows:
            return None
        row = max(rows, key=lambda r: (instant(r['receipt']['delivered_at']), int(r['receipt']['message_id'])))
        if clarification.retry_row(row):
            records = self.status().get('clarifications', {})
            if not clarification.current_cycles(self, [records[key] for key in row['intent']['clarification_ids']]):
                return None
            return dict(kind='clarification', clarification_ids=row['intent']['clarification_ids'],
                        clarifications=[records[key] for key in row['intent']['clarification_ids']],
                        receipt=row['receipt'], event_token=row['token'], binding=binding)
        task = next((task for task in self.coach.tasks() if task['id'] == row['task']['id']), None)
        if not same_cycle(row['task'], task):
            return None
        return dict(task=task, task_id=row['task']['id'], event_token=row['token'], receipt=row['receipt'], binding=binding)


def reference_key(reference, channel):
    """Validate an optional reference and compare only routing-relevant fields."""
    if reference is None:
        return None
    if (not isinstance(reference, dict) or not isinstance(reference.get('message_id'), str)
            or not reference['message_id'].isdecimal()
            or ('channel_id' in reference and not isinstance(reference['channel_id'], str))):
        raise ValueError('invalid reply reference')
    return reference['message_id'], reference.get('channel_id', channel)


def validate_pages(pages, route, anchor, now, *, recovery_start=None):
    """Fail closed for malformed tool captures as well as incomplete coverage."""
    try:
        return _validate_pages(pages, route, anchor, now, recovery_start=recovery_start)
    except (KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError('malformed history capture') from None


def _validate_pages(pages, route, anchor, now, *, recovery_start=None):
    """Validate agent-captured newest-to-oldest Discord fetch_messages pages."""
    if not isinstance(pages, list) or len(pages) != 1:
        raise ValueError('history budget requires exactly one page')
    messages, seen, before = [], set(), None
    found = False
    for page in pages:
        if (found and recovery_start is None) or page.get('binding') != route['binding'] or page.get('channel_id') != route['channel_id'] or page.get('before') != before:
            raise ValueError('history route, coverage or pagination mismatch')
        observed = instant(page['observed_at'])
        if not 0 <= (now-observed).total_seconds() <= 60:
            raise ValueError('history is stale; refresh from latest')
        result = page['result']
        batch = result.get('messages')
        limits = [25]
        for envelope in (page, result):
            if 'limit' in envelope:
                limit = envelope['limit']
                if type(limit) is not int or not 1 <= limit <= 25:
                    raise ValueError('invalid history fetch limit')
                limits.append(limit)
        effective_limit = min(limits)
        if isinstance(batch, list) and len(batch) > effective_limit:
            raise ValueError('history count exceeds effective fetch limit')
        minimum = 0 if recovery_start is not None else 1
        if result.get('error') or not isinstance(batch, list) or not minimum <= len(batch) <= 25:
            raise ValueError('history unavailable or incomplete')
        if 'count' in result and (type(result['count']) is not int or result['count'] != len(batch)):
            raise ValueError('history count does not match messages')
        reply_targets = page.get('reply_targets', {})
        if not isinstance(reply_targets, dict) or any(
                not isinstance(key, str) or not key.isdecimal()
                or (target is not None and (not isinstance(target, str) or not target.isdecimal()))
                for key, target in reply_targets.items()):
            raise ValueError('invalid trusted reply targets')
        if not set(reply_targets) <= {message['id'] for message in batch}:
            raise ValueError('trusted reply target has no captured message')
        for message in batch:
            key = message['id']
            if key in reply_targets:
                if message['author']['id'] != route['binding']['owner'] or message['author']['bot'] is not False:
                    raise ValueError('trusted reply target requires the bound owner')
                target = reply_targets[key]
                reference = dict(message_id=target, channel_id=route['channel_id']) if target is not None else None
                if 'message_reference' in message and reference_key(message['message_reference'], route['channel_id']) != reference_key(reference, route['channel_id']):
                    raise ValueError('conflicting reply target metadata')
                # Normalize only the validated copy, never invent fields in the raw tool result.
                message = dict(message, message_reference=reference)
            reference_key(message.get('message_reference'), route['channel_id'])
            if not isinstance(key, str) or not key.isdecimal() or key in seen or (before is not None and int(key) >= int(before)):
                raise ValueError('history made no backward progress')
            if not isinstance(message['author']['id'], str) or type(message['author']['bot']) is not bool or not isinstance(message['content'], str) or not isinstance(message['attachments'], list):
                raise ValueError('invalid history message')
            if instant(message['timestamp']) > now:
                raise ValueError('future history timestamp')
            if messages and instant(message['timestamp']) > instant(messages[-1]['timestamp']):
                raise ValueError('history timestamps are not ordered')
            seen.add(key)
            messages.append(message)
            before = key
            if key == anchor:
                found = True
                if recovery_start is None:
                    break
        if recovery_start is not None:
            if len(batch) < effective_limit and page is not pages[-1]:
                raise ValueError('history continues after end of history')
        if recovery_start is None and not found and len(batch) != 25:
            raise ValueError('history ended without exact anchor')
    if not found:
        raise ValueError('history budget exhausted without anchor')
    if recovery_start is not None and len(batch) == effective_limit and instant(messages[-1]['timestamp']) >= recovery_start:
        raise ValueError('lost-response history coverage must reach before attempt start or end of history')
    return messages


def add_parser(commands):
    runtime = commands.add_parser('runtime', help='Native Hermes integration; explicit setup required')
    operations = runtime.add_subparsers(dest='runtime_command', required=True)
    snooze = operations.add_parser('smart-snooze', help='Read or change Smart Snooze (default OFF); never activates cron')
    toggle = snooze.add_mutually_exclusive_group()
    toggle.add_argument('--enable', action='store_true')
    toggle.add_argument('--disable', action='store_true')
    preference = operations.add_parser('history-preference', help='Read or explicitly change exact-route Discord history permission (default OFF)')
    choice = preference.add_mutually_exclusive_group()
    choice.add_argument('--enable', action='store_true')
    choice.add_argument('--disable', action='store_true')
    preference.add_argument('--route', type=json.loads)
    preference.add_argument('--confirm-history', action='store_true')
    plan = operations.add_parser('history-plan', help='Declare one explicit bounded on-demand history request; never fetches')
    plan.add_argument('--purpose', choices=('reply-recovery', 'delivery-verification'), required=True)
    plan.add_argument('--target', required=True)
    plan.add_argument('--confirm-history', action='store_true')
    for name in ('preflight', 'status'):
        operations.add_parser(name)
    inbound = operations.add_parser('record-engagement', help='Agent-mediated explicit intent from exact trusted native inbound metadata; no history required')
    inbound.add_argument('--binding', type=json.loads, required=True)
    for field in ('owner', 'message-id', 'event-token'):
        inbound.add_argument('--' + field, required=True)
    inbound.add_argument('--task-id', type=int, required=True)
    inbound.add_argument('--cycle-id')
    inbound.add_argument('--intent', choices=('engaged', 'skip-for-now', 'start-work'), required=True)
    capability = operations.add_parser('capabilities', help='Report caller optional history inventory/attempt; no external discovery')
    capability.add_argument('--history-availability', choices=('unknown', 'unavailable', 'available'), default='unknown')
    capability.add_argument('--history-error')
    native = operations.add_parser('native-plan', help='Emit wrapper and initially paused cron argv; does not install or execute')
    for option in ('profile-home', 'python', 'helper', 'hermes'):
        native.add_argument('--' + option, required=True)
    test = operations.add_parser('prepare-test', help='Explicitly prepare ONE due onboarding check-in; no send; requires no existing episode and empty outbox')
    test.add_argument('--confirm-test', action='store_true')
    restart = operations.add_parser('restart', help='Explicitly replan an untouched stopped episode for today only; never sends')
    restart.add_argument('--confirm-restart', action='store_true')
    configure = operations.add_parser('configure')
    configure.add_argument('--route', type=json.loads, required=True)
    configure.add_argument('--confirm-setup', action='store_true')
    draft = operations.add_parser('draft')
    draft.add_argument('--event-token', required=True)
    draft.add_argument('--body-file', type=Path, required=True)
    for name in ('observe', 'dispatch', 'confirm'):
        operation = operations.add_parser(name)
        operation.add_argument('--event-token', required=True)
        operation.add_argument('--fence', required=True)
        if name == 'dispatch':
            operation.add_argument('--hermes', required=True, help='Absolute native Hermes executable')
        else:
            operation.add_argument('--pages-file', type=Path, required=True)
            operation.add_argument('--history-plan-file', type=Path, required=True)
            if name == 'confirm':
                operation.add_argument('--message-id')
    resolve = operations.add_parser('resolve-clarification', help='Normal-inbound explicit owner selection; never invent a reply reference')
    resolve.add_argument('--binding', type=json.loads, required=True)
    resolve.add_argument('--clarification-id', required=True)
    resolve.add_argument('--task-id', type=int, required=True)
    resolve.add_argument('--selection-message-id', required=True)
    resolve.add_argument('--pages-file', type=Path, required=True)
    resolve.add_argument('--history-plan-file', type=Path, required=True)
    dismiss = operations.add_parser('dismiss-clarification', help='Discard one pending question on explicit owner intent; never cancel tasks')
    dismiss.add_argument('--binding', type=json.loads, required=True)
    dismiss.add_argument('--clarification-id', required=True)
    dismiss.add_argument('--dismissal-message-id', required=True)
    dismiss.add_argument('--pages-file', type=Path, required=True)
    dismiss.add_argument('--history-plan-file', type=Path, required=True)
    for name in ('context', 'engagement'):
        operation = operations.add_parser(name)
        operation.add_argument('--binding', type=json.loads, required=True)
        operation.add_argument('--reply-to-message-id', help='Explicit target from trusted inbound metadata, never inferred from content')
        if name == 'engagement':
            operation.add_argument('--inbound-message-id', help='Exact captured owner message; required with --reply-to-message-id')
            operation.add_argument('--pages-file', type=Path, required=True)
            operation.add_argument('--history-plan-file', type=Path, required=True)


def run_cli(directory, args):
    driver = Driver(directory)
    operation = args.runtime_command
    if operation == 'smart-snooze':
        return driver.smart_snooze(enabled=True if args.enable else False if args.disable else None)
    if operation == 'history-plan':
        return driver.history_plan(purpose=args.purpose, target=args.target, confirm=args.confirm_history)
    if operation == 'history-preference':
        return driver.history_preference(enabled=True if args.enable else False if args.disable else None,
            route=args.route, confirm=args.confirm_history)
    if operation == 'record-engagement':
        return driver.record_engagement(binding=args.binding, owner=args.owner,
            message_id=args.message_id, event_token=args.event_token, task_id=args.task_id,
            cycle_id=args.cycle_id, intent=args.intent)
    if operation == 'capabilities':
        return driver.capabilities(history_available={'unknown': None, 'available': True, 'unavailable': False}[args.history_availability], history_error=args.history_error)
    if operation == 'native-plan':
        return driver.native_plan(args.profile_home, python=args.python, helper=args.helper, hermes=args.hermes)
    if operation == 'prepare-test':
        return driver.prepare_test(confirm=args.confirm_test)
    if operation == 'restart':
        return driver.restart(confirm=args.confirm_restart)
    if operation == 'configure':
        return driver.configure(args.route, confirm=args.confirm_setup)
    if operation in ('preflight', 'status'):
        return getattr(driver, operation)()
    if operation == 'draft':
        return driver.draft(args.event_token, args.body_file.read_text(encoding='utf-8'))
    if operation == 'dispatch':
        if not Path(args.hermes).is_absolute():
            raise ValueError('Hermes executable must be absolute')
        return driver.dispatch(args.event_token, args.fence, hermes=args.hermes)
    if operation == 'context':
        return driver.context(args.binding, reply_to_message_id=args.reply_to_message_id)
    with driver._directory_lock():
        # OFF is checked before even opening the request file. No authorization
        # snapshot escapes this lease, including bounded capture loading.
        driver._require_history()
        request = _bounded_json_file(args.history_plan_file, 8192)
        values = dict(vars(args), history_plan=request)
        values['token'] = values.get('event_token')
        method = operation.replace('-', '_')
        driver._authorize_ingress(method, values, capture=False)
        pages = _bounded_json_file(args.pages_file, request['max_payload_bytes'])
        if operation == 'resolve-clarification':
            return driver.resolve_clarification(binding=args.binding, clarification_id=args.clarification_id,
                task_id=args.task_id, selection_message_id=args.selection_message_id, pages=pages, history_plan=request)
        if operation == 'dismiss-clarification':
            return driver.dismiss_clarification(binding=args.binding, clarification_id=args.clarification_id,
                dismissal_message_id=args.dismissal_message_id, pages=pages, history_plan=request)
        if operation == 'engagement':
            return driver.engagement(args.binding, pages, reply_to_message_id=args.reply_to_message_id,
                inbound_message_id=args.inbound_message_id, history_plan=request)
        if operation == 'confirm':
            return driver.confirm(args.event_token, args.fence, pages, message_id=args.message_id, history_plan=request)
        return driver.observe(args.event_token, args.fence, pages, history_plan=request)


def _bounded_json_file(path, maximum):
    # stat rejects huge files without opening them; bounded read also fences
    # growth/replacement between stat and read. No raw capture is loaded whole.
    if path.stat().st_size > maximum:
        raise ValueError('history file byte budget exceeded')
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('history file byte budget exceeded')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('malformed history JSON') from None
