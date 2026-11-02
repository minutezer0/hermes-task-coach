"""Bounded clarification work in the native outbox, never a second transport."""
from datetime import timedelta
from zoneinfo import ZoneInfo
import uuid
import json
import random

from .coaching import instant, window_minutes, sequences

TERMINAL = ('resolved', 'dismissed', 'retired')
SAFE_STOPS = (None, 'owner-engaged', 'task-unavailable', 'missed-slot')


def pending(runtime):
    return [c for c in runtime.get('clarifications', {}).values() if c['state'] not in TERMINAL]


def consumed(record):
    ids = {record['message']['id']} | {m['id'] for m in record.get('responses', [])}
    for field in ('selection', 'dismissal'):
        if field in record:
            ids.add(record[field]['id'])
    return ids


def activity(runtime, messages, *, ids=None):
    """Quarantine new owner activity as question responses, never task attribution."""
    held = pending(runtime)
    if ids is not None:
        held = [c for c in held if c['id'] in ids]
    if not held:
        return False
    record = min(held, key=lambda c: (int(c['message']['id']), c['id']))
    known = set().union(*(consumed(c) for c in runtime['clarifications'].values()))
    known.update(r['message']['id'] for r in runtime.get('clarification_responses', []))
    added = False
    for message in messages:
        if (message['author']['id'] != record['binding']['owner'] or message['author']['bot'] is not False
                or message['id'] in known or int(message['id']) <= int(record['message']['id'])):
            continue
        eligible = [c['id'] for c in held if int(message['id']) > int(c['message']['id'])
                    and instant(message['timestamp']) >= instant(c['message']['timestamp'])]
        if not eligible:
            continue
        if len(eligible) == 1 and runtime.get('clarification_retry'):
            runtime['clarifications'][eligible[0]].setdefault('responses', []).append(message)
        else:
            runtime.setdefault('clarification_responses', []).append(dict(message=message, ids=sorted(eligible)))
        known.add(message['id'])
        added = True
    if added and runtime.get('clarification_retry'):
        runtime['clarification_retry']['blocked'] = True
    return added


def bind_response(runtime, record, message):
    """Check immutable captures and bind shared answers on a locked choice."""
    captured = next((m for m in record.get('responses', []) if m['id'] == message['id']), None)
    if captured is not None and captured != message:
        raise ValueError('captured response changed')
    entries = runtime.get('clarification_responses', [])
    captured = next((r for r in entries if r['message']['id'] == message['id']), None)
    if captured is not None:
        if record['id'] not in captured['ids'] or captured['message'] != message:
            raise ValueError('response does not belong to the selected question')
        entries.remove(captured)


def current_receipt(runtime, row):
    return not any(c['state'] == 'retired' and instant(row['receipt']['delivered_at']) <= instant(c['resolved_at'])
                   for c in runtime.get('clarifications', {}).values())


def retry_row(row):
    return row['intent'].get('kind') == 'clarification'


def spacing_ok(runtime, cycle, now):
    receipts = [instant(row['receipt']['delivered_at']) for row in runtime['outbox'].values()
                if retry_row(row) and row['state'] == 'confirmed'
                and set(row['intent']['clarification_ids']) & set(cycle['ids'])]
    previous = max(receipts) if receipts else instant(cycle['started_at'])
    elapsed = (now-previous).total_seconds()
    config = cycle['config']
    return config['min_followup_interval'] * 60 <= elapsed <= config['max_followup_interval'] * 60


def unresolved_engine(engine):
    """Engine claims survive the ordinary tick-to-outbox crash gap."""
    return bool(engine['episode'] and any(e['state'] in ('claimed', 'failed')
                for sequence in sequences(engine['episode']) for e in sequence['events']))


def prepare(driver, runtime, engine, now):
    """Called under the common directory lock; never claims or sends."""
    if unresolved_engine(engine) or any(row['state'] == 'sending' for row in runtime['outbox'].values()):
        return dict(wakeAgent=False, reason='unconfirmed-delivery')
    held = pending(runtime)
    if not held:
        return None
    quiet = dict(wakeAgent=False, reason='pending-clarification')
    if any(c['state'] != 'pending' for c in held):
        return quiet
    root = engine['episode']
    config = driver.coach.config()
    from .cli import validate_config
    cycle = runtime.get('clarification_retry')
    ids = sorted(c['id'] for c in held)
    if cycle is None or not any(key in ids for key in cycle['ids']):
        start = max(instant(c['message']['timestamp']) for c in held)
        day = start.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
        minutes = window_minutes(day, config)
        events = []
        seed = json.dumps(dict(ids=ids, config=config, start=start.isoformat()), sort_keys=True)
        rng = random.Random(seed)
        slot = start
        count = config['max_unanswered_followups'] if start.replace(second=0, microsecond=0) in minutes else 0
        for index in range(count):
            slot += timedelta(minutes=rng.randint(config['min_followup_interval'], config['max_followup_interval']))
            if slot.replace(second=0, microsecond=0) not in minutes:
                break
            events.append(dict(token=uuid.uuid5(uuid.NAMESPACE_URL, seed + ':' + str(index)).hex, slot=slot.isoformat(),
                               expires=min(slot + timedelta(minutes=1), minutes[-1] + timedelta(minutes=1)).isoformat(), index=index, state='planned'))
        cycle = dict(ids=ids, config=config, route=runtime['route'], day=day,
                     started_at=start.isoformat(), last_seen=start.isoformat(), blocked=any(c.get('responses') for c in held) or any(set(r['ids']) & set(ids) for r in runtime.get('clarification_responses', [])), safety_block=None, events=events)
        runtime['clarification_retry'] = cycle
    if now < instant(cycle['last_seen']) or (engine['last_tick'] and now < instant(engine['last_tick'])):
        cycle['safety_block'] = cycle['safety_block'] or 'clock-regressed'
    if (cycle['config'] != config or cycle['route'] != runtime['route']
            or not root or validate_config(root['config']) != config or root['binding'] != runtime['route']['binding']):
        cycle['safety_block'] = cycle['safety_block'] or 'configuration-changed'
    if root and (root.get('window_stopped') or any(s['stopped'] not in SAFE_STOPS for s in sequences(root))):
        cycle['safety_block'] = cycle['safety_block'] or 'engine-safety-stop'
    if cycle['safety_block'] or engine['paused'] or not set(ids) <= set(cycle['ids']):
        return quiet
    cycle['last_seen'] = now.isoformat()
    local_day = now.astimezone(ZoneInfo(config['timezone'])).date().isoformat()
    started_in_window = instant(cycle['started_at']).replace(second=0, microsecond=0) in window_minutes(cycle['day'], config)
    next_window = local_day > cycle['day'] or (local_day == cycle['day'] and not started_in_window)
    if next_window and now.replace(second=0, microsecond=0) in window_minutes(local_day, config):
        for record in held:
            record.update(state='retired', resolved_at=now.isoformat())
        return None
    if cycle['blocked']:
        return quiet
    for event in cycle['events']:
        if event['state'] != 'planned':
            continue
        if now >= instant(event['expires']):
            event['state'] = 'missed'
            continue
        if now < instant(event['slot']):
            return quiet
        if not spacing_ok(runtime, cycle, now):
            return quiet
        candidate = min((c for h in held for c in h['candidates']), key=lambda c: int(c['receipt']['message_id']))
        previous = dict(token=candidate['token'], receipt=candidate['receipt'], state='delivered')
        return dict(wakeAgent=True, intent=dict(kind='clarification', event_token=event['token'],
                    clarification_ids=ids, index=event['index'], task_id=candidate['task']['id'],
                    binding=runtime['route']['binding'], expires=event['expires']),
                    previous=previous, task=candidate['task'], clarifications=held)
    return quiet


def authorize(driver, runtime, engine, row, now):
    """Recheck the entire retry authorization under the final send lock."""
    from .cli import validate_config
    # Never perform lifecycle rollover here: a journaled send may be uncertain.
    # Compare current holds and safety state without retiring any records.
    cycle = runtime.get('clarification_retry')
    event = next((e for e in cycle['events'] if e['token'] == row['token']), None) if cycle else None
    if (not cycle or not event or event['state'] != 'claimed' or cycle['blocked'] or cycle['safety_block']
            or cycle['config'] != driver.coach.config() or cycle['route'] != runtime['route']
            or runtime['route'] != row['route']
            or sorted(c['id'] for c in pending(runtime)) != row['intent']['clarification_ids']
            or not all(c['state'] == 'pending' for c in pending(runtime))
            or unresolved_engine(engine)
            or engine['paused'] or not engine['episode'] or engine['episode'].get('window_stopped')
            or any(s['stopped'] not in SAFE_STOPS for s in sequences(engine['episode']))
            or validate_config(engine['episode']['config']) != cycle['config']
            or engine['episode']['binding'] != row['route']['binding']
            or now < instant(cycle['last_seen'])
            or (engine['last_tick'] and now < instant(engine['last_tick']))
            or not instant(event['slot']) <= now < instant(event['expires'])
            or not spacing_ok(runtime, cycle, now)
            or not instant(row['attempted_at']) <= now < instant(row['attempted_at']) + timedelta(seconds=120)):
        raise ValueError('clarification retry authorization changed')
    observe(driver, runtime, row, row['evidence']['pages'] if row['evidence'] else [], now, update=False)
    return True


def observe(driver, runtime, row, pages, now, *, update=True):
    from .driver import validate_pages
    anchor = row['previous']['receipt']
    messages = validate_pages(pages, row['route'], anchor['message_id'], now)
    old = runtime['outbox'][row['previous']['token']]
    bot = messages[-1]
    if (bot['author']['id'] != row['route']['bot_id'] or bot['author']['bot'] is not True
            or bot['content'] != old['body'] or bot['timestamp'] != anchor['delivered_at']):
        raise ValueError('history anchor does not match confirmed receipt')
    for previous in runtime['outbox'].values():
        if (not retry_row(previous) or previous['state'] != 'confirmed'
                or not set(previous['intent']['clarification_ids']) & set(row['intent']['clarification_ids'])):
            continue
        receipt = previous['receipt']
        captured = next((m for m in messages if m['id'] == receipt['message_id']), None)
        if (not captured or captured['author']['id'] != row['route']['bot_id']
                or captured['author']['bot'] is not True or captured['content'] != previous['body']
                or instant(captured['timestamp']) != instant(receipt['delivered_at'])):
            raise ValueError('previous retry receipt missing or changed in raw history')
    held = [runtime['clarifications'][key] for key in row['intent']['clarification_ids']]
    for record in held:
        for candidate in record['candidates']:
            receipt = candidate['receipt']
            captured = next((m for m in messages if m['id'] == receipt['message_id']), None)
            source = runtime['outbox'][candidate['token']]
            if (not captured or captured['author']['id'] != row['route']['bot_id']
                    or captured['author']['bot'] is not True or captured['content'] != source['body']
                    or instant(captured['timestamp']) != instant(receipt['delivered_at'])):
                raise ValueError('candidate receipt missing or changed in raw history')
        original = next((m for m in messages if m['id'] == record['message']['id']), None)
        if original != record['message']:
            raise ValueError('original captured message changed or missing')
    known = {c['message']['id'] for c in runtime.get('clarifications', {}).values()}
    owners = [m for m in messages if m['author']['id'] == row['route']['binding']['owner'] and m['author']['bot'] is False and m['id'] not in known]
    evidence = dict(complete=not owners, engaged=False, pages=pages)
    if owners:
        if update:
            activity(runtime, owners, ids=row['intent']['clarification_ids'])
        else:
            raise ValueError('new owner activity; normal inbound clarification required')
    if update:
        row['evidence'] = evidence
    return evidence


def validate_cycle(runtime):
    if 'clarification_retry' not in runtime:
        return
    cycle = runtime['clarification_retry']
    if not isinstance(cycle, dict):
        raise ValueError('invalid clarification cycle')
    if (set(cycle) != {'ids', 'config', 'route', 'day', 'started_at', 'last_seen', 'blocked', 'safety_block', 'events'}
            or cycle['route'] != runtime['route'] or type(cycle['blocked']) is not bool
            or cycle['safety_block'] not in (None, 'clock-regressed', 'configuration-changed', 'engine-safety-stop')
            or not cycle['ids'] or cycle['ids'] != sorted(set(cycle['ids']))
            or any(key not in runtime.get('clarifications', {}) for key in cycle['ids'])):
        raise ValueError('invalid clarification cycle')
    from .cli import validate_config
    config = validate_config(cycle['config'])
    start = instant(cycle['started_at'])
    if instant(cycle['last_seen']) < start or cycle['day'] != start.astimezone(ZoneInfo(config['timezone'])).date().isoformat():
        raise ValueError('invalid clarification clock')
    if not isinstance(cycle['events'], list) or len(cycle['events']) > config['max_unanswered_followups']:
        raise ValueError('invalid clarification budget')
    slots = window_minutes(cycle['day'], config)
    previous = start
    tokens = set()
    for index, event in enumerate(cycle['events']):
        slot = instant(event['slot'])
        spacing = (slot-previous).total_seconds()/60
        required = {'token', 'slot', 'expires', 'index', 'state'}
        if (not required <= set(event) <= required | {'intent'} or type(event['index']) is not int or event['index'] != index
                or event['state'] not in ('planned', 'claimed', 'missed')
                or not isinstance(event['token'], str) or not event['token'] or event['token'] in tokens
                or slot.replace(second=0, microsecond=0) not in slots
                or instant(event['expires']) != min(slot + timedelta(minutes=1), slots[-1] + timedelta(minutes=1))
                or not config['min_followup_interval'] <= spacing <= config['max_followup_interval']):
            raise ValueError('invalid clarification event')
        row = runtime['outbox'].get(event['token'])
        if 'intent' in event and (not row or event['intent'] != row['intent']):
            raise ValueError('clarification intent identity changed')
        if event['state'] == 'claimed' and (not row or not retry_row(row) or row['state'] == 'draft'):
            raise ValueError('clarification claim without an attempt')
        if row:
            intent = row['intent']
            if (not retry_row(row) or intent['index'] != index or intent['expires'] != event['expires']
                    or not set(intent['clarification_ids']) <= set(cycle['ids'])
                    or (row['state'] != 'draft') != (event['state'] == 'claimed')
                    or (row['state'] != 'draft' and not slot <= instant(row['attempted_at']) < instant(event['expires']))):
                raise ValueError('clarification attempt does not match cycle')
        tokens.add(event['token'])
        previous = slot
