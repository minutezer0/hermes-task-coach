"""Small completion-based interval and cycle primitives; no occurrence generation."""
import calendar
from datetime import date, datetime, timedelta, timezone
import json
import re
import uuid
from zoneinfo import ZoneInfo


def interval(value):
    match = re.fullmatch(r'([1-9][0-9]{0,3}) (day|week|month)s?', value)
    if not match:
        raise ValueError('repeat must be a positive interval such as 3 months, 2 weeks or 1 day')
    return f'{int(match[1])} {match[2]}s'


def same_cycle(snapshot, task):
    return task is not None and snapshot.get('cycle_id') == task.get('cycle_id')


def same_snapshot(snapshot, task):
    if task is None:
        return False
    # Migration adds only nullable fields, never changes a historical plain task.
    fields = ('repeat_interval', 'cycle_id', 'last_completion')
    return dict(snapshot, **{k: snapshot.get(k) for k in fields}) == dict(task, **{k: task.get(k) for k in fields})


def next_due(completed, repeat, zone):
    count, unit = interval(repeat).split()
    count = int(count)
    value = date.fromisoformat(completed) if len(completed) == 10 else datetime.fromisoformat(completed).astimezone(ZoneInfo(zone))
    if unit == 'months':
        month = value.year * 12 + value.month - 1 + count
        year, month = divmod(month, 12)
        value = value.replace(year=year, month=month + 1, day=min(value.day, calendar.monthrange(year, month + 1)[1]))
    else:
        value += timedelta(days=count * (7 if unit == 'weeks' else 1))
    if isinstance(value, datetime):
        # Gap wall times roll forward by the gap; folds choose the first instant.
        value = value.replace(fold=0).astimezone(timezone.utc).astimezone(ZoneInfo(zone))
    return value.isoformat()


def completion_changes(task, completed, expected, identity, zone, now):
    if not all(isinstance(v, str) and v.strip() for v in (completed, expected, identity)):
        raise ValueError('recurring completion requires completed-at, expected-cycle and completion-id')
    from .cli import due_value
    due_value(completed)
    local = now.astimezone(ZoneInfo(zone))
    if (date.fromisoformat(completed) > local.date() if len(completed) == 10 else datetime.fromisoformat(completed).astimezone(timezone.utc) > now):
        raise ValueError('completion cannot be in the future')
    request = dict(cycle=expected, identity=identity, completed_at=completed)
    if task.get('last_completion') and json.loads(task['last_completion']) == request:
        return {}
    if task.get('cycle_id') != expected:
        raise ValueError('stale completion cycle')
    if task.get('last_completion') and json.loads(task['last_completion'])['identity'] == identity:
        raise ValueError('completion identity already used')
    if not task.get('repeat_interval') or task['status'] != 'open':
        raise ValueError('completion requires an open recurring task')
    return dict(due=next_due(completed, task['repeat_interval'], zone), status='open', snoozed_until=None,
                cycle_id=uuid.uuid4().hex, last_completion=json.dumps(request, sort_keys=True))
