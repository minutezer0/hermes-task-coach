"""Native Hermes orchestration. History is supplied by the agent, not a bot SDK."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import uuid

from .coaching import Coach, UTC, instant, safe_path, validate_binding

SCHEMA = 'CREATE TABLE runtime (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)'


class Driver:
    @staticmethod
    def validate_state(state):
        try:
            if set(state) != {'route', 'outbox'} or not isinstance(state['outbox'], dict):
                raise ValueError
            if state['route'] is not None:
                validate_binding(state['route']['binding'])
            for token, row in state['outbox'].items():
                required = {'token', 'fence', 'state', 'body', 'route', 'task', 'intent', 'previous', 'evidence'}
                if not required <= set(row) <= required | {'attempted_at', 'candidate_id', 'uncertain', 'receipt'}:
                    raise ValueError
                if row['token'] != token or row['route'] != state['route'] or row['state'] not in ('draft', 'sending', 'confirmed'):
                    raise ValueError
                if not all(isinstance(row[k], str) and row[k].strip() for k in ('token', 'fence', 'body')):
                    raise ValueError
                if row['intent']['event_token'] != token or row['intent']['task_id'] != row['task']['id'] or row['intent']['binding'] != row['route']['binding']:
                    raise ValueError
                if row['state'] == 'draft' and any(k in row for k in ('attempted_at', 'candidate_id', 'receipt')):
                    raise ValueError
                if row['state'] != 'draft':
                    instant(row['attempted_at'])
                if row['state'] == 'confirmed':
                    receipt = row['receipt']
                    if receipt['event_token'] != token or receipt['binding'] != row['route']['binding'] or receipt['cursor'] != receipt['message_id'] or not receipt['message_id']:
                        raise ValueError
                    instant(receipt['delivered_at'])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError('invalid runtime state') from None

    def __init__(self, data_dir):
        self.coach = Coach(data_dir, opportunity_minutes=10)
        self.directory = Path(data_dir)

    @contextmanager
    def transaction(self, *, readonly=False):
        # Same directory lock as the engine, but never nest these transactions.
        import fcntl
        safe_path(self.directory, True)
        fd = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
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
            target = path.resolve().as_uri() + '?mode=ro' if readonly else path
            with closing(sqlite3.connect(target, uri=readonly)) as db:
                db.execute('BEGIN' if readonly else 'BEGIN IMMEDIATE')
                try:
                    if fresh:
                        db.execute(SCHEMA)
                        db.execute('PRAGMA user_version=1')
                        state = dict(route=None, outbox={})
                    else:
                        schema = db.execute("SELECT sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%'").fetchall()
                        if db.execute('PRAGMA user_version').fetchone()[0] != 1 or schema != [(SCHEMA,)]:
                            raise ValueError('incompatible runtime schema')
                        rows = db.execute('SELECT id,value FROM runtime').fetchall()
                        if len(rows) != 1 or rows[0][0] != 1:
                            raise ValueError('invalid runtime state')
                        state = json.loads(rows[0][1])
                    self.validate_state(state)
                    yield state
                    self.validate_state(state)
                    if not readonly:
                        db.execute('INSERT OR REPLACE INTO runtime VALUES (1,?)', (json.dumps(state),))
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
            state['route'] = route
        return dict(configured=True, route=route, live_verified=False)

    def status(self):
        with self.transaction() as state:
            return json.loads(json.dumps(state))

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
                if previous['events']:
                    raise ValueError('restart requires zero prior events, including unclaimed plans')
                episode = self.coach.plan(day, config, runtime['route']['binding'], now, state['recent'], future_only=True)
                if episode['task_id'] is None or not episode['events']:
                    raise ValueError('no eligible task or future slots remain today')
                state['episode'] = episode
                state['last_tick'] = now.isoformat()
                state['recent'] = (state['recent'] + [episode['task_id']])[-7:]
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
            tasks = [task for task in self.coach.tasks() if eligible(task, now)]
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
                episode = dict(day=day, task_id=task['id'], binding=runtime['route']['binding'], config=config,
                               events=[event], stopped=None, purpose='one-check-in-test')
                state.update(episode=episode, last_tick=now.isoformat(), recent=(state['recent'] + [task['id']])[-7:])
                return dict(test_prepared=True, wakeAgent=False, episode=episode)

    def preflight(self, *, now=None):
        route = self.status()['route']
        if route is None:
            return dict(wakeAgent=False, reason='setup-not-confirmed')
        return self.coach.prepare(binding=route['binding'], now=now)

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
        config = self.coach.config()
        state = self.coach.status()
        episode = state['episode']
        event = next((e for e in episode['events'] if e['token'] == row['token']), None) if episode else None
        task = next((t for t in self.coach.tasks() if t['id'] == row['task']['id']), None)
        local = now.astimezone(ZoneInfo(config['timezone']))
        if state['paused'] or not episode or episode['stopped'] or episode['config'] != config or episode['binding'] != row['route']['binding'] or self.status()['route'] != row['route']:
            raise ValueError('episode, pause, configuration or route changed')
        if not event or event['state'] != 'claimed' or not instant(event['claimed_at']) <= now < min(instant(event['expires']), instant(event['claimed_at']) + timedelta(seconds=120)):
            raise ValueError('claim lease expired or event changed')
        if task != row['task'] or not eligible(task, now) or local.date().isoformat() != episode['day'] or DAYS[local.weekday()] not in config['weekdays'] or not config['notification_start'] <= local.strftime('%H:%M') < config['notification_end']:
            raise ValueError('task or notification window changed')
        if row['previous']:
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
        if row['state'] != 'draft':
            raise ValueError('event already attempted; automatic resend forbidden')
        prepared = self.preflight(now=now)
        if not prepared['wakeAgent'] or prepared['intent'] != row['intent'] or prepared['task'] != row['task'] or self.status()['route'] != row['route']:
            raise ValueError('draft authorization changed')
        claimed = self.coach.tick(now=now, binding=row['route']['binding'], evidence=row['evidence'], expected_token=token)
        if not claimed['wakeAgent']:
            raise ValueError('claim suppressed: ' + claimed['reason'])
        with self.transaction() as state:
            current = state['outbox'][token]
            if current['state'] != 'draft' or current['fence'] != fence:
                raise ValueError('event already attempted')
            current.update(state='sending', attempted_at=now.isoformat())
        # The durable sending fence precedes the network boundary. Any exception,
        # timeout, crash, malformed or negative result leaves a nonretryable row.
        try:
            self.authorize(self.row(token, fence), now=now if now_supplied else None)
            result = subprocess.run([hermes, 'send', '--json', '--to', row['route']['destination'], '--', row['body']],
                                    capture_output=True, text=True, timeout=45, check=False)
            payload = json.loads(result.stdout)
            if not isinstance(payload, dict):
                raise ValueError('send result must be a JSON object')
            message_id = payload.get('message_id')
            if result.returncode or payload.get('success') is not True or payload.get('skipped') or payload.get('error') or not isinstance(message_id, str) or not message_id.strip():
                raise ValueError('send did not return a positive message identifier')
            with self.transaction() as state:
                state['outbox'][token]['candidate_id'] = message_id
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            with self.transaction() as state:
                state['outbox'][token]['uncertain'] = str(error)
        return self.row(token, fence)

    def confirm(self, token, fence, pages, *, now=None, message_id=None):
        now = instant(now or datetime.now(UTC))
        row = self.row(token, fence)
        if row['state'] == 'confirmed':
            if message_id is not None and message_id != row['receipt']['message_id']:
                raise ValueError('conflicting confirmed receipt')
            return row['receipt']
        if row.get('candidate_id') and message_id is not None and message_id != row['candidate_id']:
            raise ValueError('conflicting candidate ID')
        candidate = row.get('candidate_id') or message_id
        if row['state'] not in ('sending', 'confirmed') or not candidate:
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
        for other in self.status()['outbox'].values():
            if other['token'] != token and other.get('receipt', {}).get('message_id') == message['id'] and other['route'] == row['route']:
                raise ValueError('replayed receipt')
        episode = self.coach.status()['episode']
        if episode and any(e['token'] == token for e in episode['events']):
            self.coach.reconcile(receipt, now=now)
        with self.transaction() as state:
            current = state['outbox'][token]
            if current['state'] == 'confirmed':
                if current['receipt'] != receipt:
                    raise ValueError('conflicting confirmed receipt')
                return current['receipt']
            current.update(state='confirmed', receipt=receipt)
        if episode and any(e['token'] == token for e in episode['events']) and any(m['author']['id'] == row['route']['binding']['owner'] and m['author']['bot'] is False for m in messages[:-1]):
            self.coach.stop(token, row['route']['binding'])
        return receipt

    def observe(self, token, fence, pages, *, now=None):
        now = instant(now or datetime.now(UTC))
        row = self.row(token, fence)
        previous = row['previous']
        if not previous or not previous['receipt']:
            raise ValueError('observation requires a delivered previous event')
        receipt = previous['receipt']
        with self.transaction() as state:
            state['outbox'][token]['evidence'] = None
        messages = validate_pages(pages, row['route'], receipt['message_id'], now)
        anchor = messages[-1]
        if anchor['author']['id'] != row['route']['bot_id'] or anchor['author']['bot'] is not True or instant(anchor['timestamp']) != instant(receipt['delivered_at']):
            raise ValueError('history anchor does not match previous receipt')
        engaged = any(m['author']['id'] == row['route']['binding']['owner'] and m['author']['bot'] is False for m in messages[:-1])
        evidence = dict(binding=row['route']['binding'], event_token=previous['token'], message_id=receipt['message_id'], cursor=receipt['cursor'], snapshot_id=uuid.uuid4().hex, observed_at=min(instant(p['observed_at']) for p in pages).isoformat(), complete=True, engaged=engaged, error=None)
        with self.transaction() as state:
            state['outbox'][token]['evidence'] = evidence
        if engaged:
            self.coach.stop(token, row['route']['binding'])
        return evidence

    def engagement(self, binding, pages, *, now=None):
        now = instant(now or datetime.now(UTC))
        context = self.context(binding)
        if not context:
            raise ValueError('no coaching context for this binding')
        row = self.status()['outbox'][context['event_token']]
        messages = validate_pages(pages, row['route'], context['receipt']['message_id'], now)
        engaged = any(m['author']['id'] == binding['owner'] and m['author']['bot'] is False for m in messages[:-1])
        if engaged:
            episode = self.coach.status()['episode']
            if episode and episode['binding'] == binding and any(e['token'] == row['token'] for e in episode['events']):
                self.coach.stop(row['token'], binding)
        return dict(engaged=engaged, context=context)

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
        prompt = ('Load task-coach and follow its native runtime protocol. Use helper ' + str(helper_path) + ' with --data-dir ' + str(self.directory.resolve()) + '. Re-run runtime preflight. Compose one human check-in only for its current task. For followups fetch and validate fresh complete Discord history before dispatch. Use runtime draft/observe/dispatch/confirm; native Hermes executable ' + str(hermes_path) + '. Never send directly or retry uncertain attempts. No final chat delivery: delivery is handled by the helper.')
        instruction = ('For normal inbound messages ONLY matching the explicitly confirmed Task Coach binding, load task-coach, run runtime context --binding with the trusted inbound owner/profile/account/chat/thread, fetch history to the exact receipt anchor and run runtime engagement. Continue that returned task with one useful next-step question; never mark it done without permission. Honor explicit pause via coach pause. Do not apply this instruction to other users or destinations.')
        return dict(script_path=str(script), script_text=text,
                    cron_argv=[str(hermes_path), 'cron', 'create', 'every 1m', prompt, '--name', 'task-coach', '--skill', 'task-coach', '--script', str(script.relative_to(profile / 'scripts')), '--deliver', 'local', '--failure-deliver', 'local', '--paused'],
                    inbound_instruction=instruction, initially_paused=True, live_verified=False)

    def context(self, binding):
        validate_binding(binding)
        rows = [row for row in self.status()['outbox'].values() if row['route']['binding'] == binding and row['state'] == 'confirmed']
        if not rows:
            return None
        row = max(rows, key=lambda r: instant(r['receipt']['delivered_at']))
        task = next((task for task in self.coach.tasks() if task['id'] == row['task']['id']), None)
        return dict(task=task, task_id=row['task']['id'], event_token=row['token'], receipt=row['receipt'], binding=binding)


def validate_pages(pages, route, anchor, now, *, recovery_start=None):
    """Fail closed for malformed tool captures as well as incomplete coverage."""
    try:
        return _validate_pages(pages, route, anchor, now, recovery_start=recovery_start)
    except (KeyError, TypeError, AttributeError, OverflowError):
        raise ValueError('malformed history capture') from None


def _validate_pages(pages, route, anchor, now, *, recovery_start=None):
    """Validate agent-captured newest-to-oldest Discord fetch_messages pages."""
    if not isinstance(pages, list) or not 1 <= len(pages) <= 20:
        raise ValueError('history requires 1..20 pages')
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
        minimum = 0 if recovery_start is not None else 1
        if result.get('error') or not isinstance(batch, list) or not minimum <= len(batch) <= 100:
            raise ValueError('history unavailable or incomplete')
        if 'count' in result and (type(result['count']) is not int or result['count'] != len(batch)):
            raise ValueError('history count does not match messages')
        for message in batch:
            key = message['id']
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
            if len(batch) < 100 and page is not pages[-1]:
                raise ValueError('history continues after end of history')
        if recovery_start is None and not found and len(batch) != 100:
            raise ValueError('history ended without exact anchor')
    if not found:
        raise ValueError('history budget exhausted without anchor')
    if recovery_start is not None and len(batch) == 100 and instant(messages[-1]['timestamp']) >= recovery_start:
        raise ValueError('lost-response history coverage must reach before attempt start or end of history')
    return messages


def add_parser(commands):
    runtime = commands.add_parser('runtime', help='Native Hermes integration; explicit setup required')
    operations = runtime.add_subparsers(dest='runtime_command', required=True)
    for name in ('preflight', 'status'):
        operations.add_parser(name)
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
            if name == 'confirm':
                operation.add_argument('--message-id')
    for name in ('context', 'engagement'):
        operation = operations.add_parser(name)
        operation.add_argument('--binding', type=json.loads, required=True)
        if name == 'engagement':
            operation.add_argument('--pages-file', type=Path, required=True)


def run_cli(directory, args):
    driver = Driver(directory)
    operation = args.runtime_command
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
        return driver.context(args.binding)
    pages = json.loads(args.pages_file.read_text(encoding='utf-8'))
    if operation == 'engagement':
        return driver.engagement(args.binding, pages)
    if operation == 'confirm':
        return driver.confirm(args.event_token, args.fence, pages, message_id=args.message_id)
    return driver.observe(args.event_token, args.fence, pages)
