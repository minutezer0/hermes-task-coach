"""Command-line interface for the local task store."""
import argparse
from datetime import date, datetime, timezone
import hashlib
import re
from contextlib import closing, contextmanager
import json
from pathlib import Path
import os
import sqlite3
import sys
import uuid
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CONFIG = {
    "timezone": "UTC", "weekdays": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
    "notification_start": "09:00", "notification_end": "17:00",
    "max_tasks_per_window": 2, "max_unanswered_followups": 2, "min_followup_interval": 30,
    "max_followup_interval": 120, "automation_enabled": False,
}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_CONFIG):
        if isinstance(config, dict):
            unexpected = sorted(set(config) - set(DEFAULT_CONFIG))
            missing = sorted(set(DEFAULT_CONFIG) - set(config))
            if unexpected or missing:
                detail = '; '.join(filter(None, (
                    'unexpected ' + ', '.join(unexpected) if unexpected else '',
                    'missing ' + ', '.join(missing) if missing else '')))
                raise ValueError('invalid configuration fields: ' + detail)
        raise ValueError("invalid configuration fields")
    try:
        if not isinstance(config["timezone"], str):
            raise ValueError
        ZoneInfo(config["timezone"])
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError("timezone must be a valid IANA ZoneInfo name") from None
    days = config["weekdays"]
    if not isinstance(days, list) or not days or any(not isinstance(day, str) or day not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun") for day in days) or len(set(days)) != len(days):
        raise ValueError("weekdays must be distinct comma-separated mon..sun values")
    minutes = []
    for field in ("notification_start", "notification_end"):
        value = config[field]
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError("notification times must use HH:MM")
        hour, minute = map(int, value.split(":"))
        minutes.append(hour * 60 + minute)
    if minutes[1] <= minutes[0]:
        raise ValueError("notification window must end after start; overnight windows are not supported")
    if type(config["max_tasks_per_window"]) is not int or not 1 <= config["max_tasks_per_window"] <= 10:
        raise ValueError("maximum tasks per window must be an integer 1..10")
    count = config["max_unanswered_followups"]
    low, high = config["min_followup_interval"], config["max_followup_interval"]
    if any(type(value) is not int for value in (count, low, high)) or not 0 <= count <= 20 or not 1 <= low <= high <= 1440:
        raise ValueError("followups must be 0..20 and intervals 1..1440 minutes with min <= max")
    if count * low > minutes[1] - minutes[0]:
        raise ValueError("notification window cannot fit followups at the minimum interval")
    if config["automation_enabled"] is not False:
        raise ValueError("automation is not available; automation_enabled must be false")
    return config


@contextmanager
def task_store_lock(directory, *, repair=False):
    """Fence task snapshots and writes with the engine/runtime directory lock."""
    import fcntl
    from .coaching import safe_path
    if not repair:
        safe_path(directory, True)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)


def default_data_dir():
    profile_home = os.environ.get("HERMES_HOME")
    if profile_home:
        return Path(profile_home) / "task-coach"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "task-coach"


def due_value(value, *, aware_only=False):
    try:
        if not aware_only and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            date.fromisoformat(value)
        else:
            parsed = datetime.fromisoformat(value)
            if "T" not in value or parsed.utcoffset() is None:
                raise ValueError
            parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise argparse.ArgumentTypeError("expected a valid date or timezone-aware ISO timestamp" if not aware_only else "expected a timezone-aware ISO timestamp") from None
    return value


def title_value(value):
    if not value.strip():
        raise argparse.ArgumentTypeError("title must not be empty")
    return value


TASK_COLUMNS = ("id", "title", "notes", "priority", "status", "due", "snoozed_until", "created_at", "updated_at", "repeat_interval", "cycle_id", "last_completion", "check_in_days")
CHECK_IN_DAYS = ("weekdays", "weekends", "all")
CHECK_IN_DAY_VALUES = {"weekdays": ("mon", "tue", "wed", "thu", "fri"), "weekends": ("sat", "sun")}
TASK_DDL = "CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL, due TEXT, snoozed_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, repeat_interval TEXT, cycle_id TEXT, last_completion TEXT, check_in_days TEXT NOT NULL DEFAULT 'all')"


def task_record(row):
    return dict(row)


CHECKLIST_LINE = re.compile(r"^([ ]{0,3})(?:([-*+])[ \t]+)?\[([ xX])\](?:[ \t]+(.*?))?[ \t]*$")
CHECKLIST_FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})")
CHECKLIST_FENCE_END = re.compile(r"^[ ]{0,3}(`{3,}|~{3,})[ \t]*$")
NOTES_DIGEST = re.compile(r"^[0-9a-f]{64}$")


def notes_digest(notes):
    return hashlib.sha256(notes.encode("utf-8")).hexdigest()


def checklist_matches(notes):
    """Return (line number, match) pairs for clear task-list lines outside code fences."""
    matches, fence = [], None
    for number, line in enumerate(notes.splitlines()):
        opening = CHECKLIST_FENCE.match(line)
        if fence is not None:
            if opening and opening.group(1)[0] == fence[0] and len(opening.group(1)) >= len(fence) and CHECKLIST_FENCE_END.match(line):
                fence = None
            continue
        if opening:
            fence = opening.group(1)
            continue
        match = CHECKLIST_LINE.match(line)
        if match:
            matches.append((number, match))
    return matches


def checklist_items(notes):
    return [{"index": index, "checked": match.group(3) in "xX", "text": match.group(4) or ""}
            for index, (_, match) in enumerate(checklist_matches(notes), start=1)]


def set_checklist_item(notes, index, checked):
    """Return notes with one item's marker changed; every other character is untouched."""
    matches = checklist_matches(notes)
    if not 1 <= index <= len(matches):
        raise ValueError("checklist item index out of range")
    number, match = matches[index - 1]
    if (match.group(3) in "xX") == checked:
        return notes
    lines = notes.splitlines(keepends=True)
    line, start = lines[number], match.start(3)
    lines[number] = line[:start] + ("x" if checked else " ") + line[start + 1:]
    return "".join(lines)


def checklist_payload(task):
    items = checklist_items(task["notes"])
    return {"id": task["id"], "notes_digest": notes_digest(task["notes"]),
            "checked": sum(1 for item in items if item["checked"]),
            "total": len(items), "items": items}


def validate_store(db):
    version = db.execute("PRAGMA user_version").fetchone()[0]
    schema = [tuple(row) for row in db.execute("SELECT type,name,sql FROM sqlite_schema WHERE name NOT GLOB 'sqlite_*'")]
    if version != 2 or len(schema) != 1 or schema[0][:2] != ('table', 'tasks') or ''.join(schema[0][2].split()).lower() != ''.join(TASK_DDL.split()).lower():
        raise ValueError("incompatible task store schema or version")
    columns = tuple(tuple(row)[1:] for row in db.execute("PRAGMA table_xinfo(tasks)"))
    expected = tuple(
        (name, "INTEGER" if name == "id" else "TEXT",
         int(name not in ("id", "due", "snoozed_until", "repeat_interval", "cycle_id", "last_completion")), "'all'" if name == "check_in_days" else None, int(name == "id"), 0)
        for name in TASK_COLUMNS
    )
    # A separate primary-key index means id is not the INTEGER rowid alias
    # (for example, INTEGER PRIMARY KEY DESC or a WITHOUT ROWID table).
    separate_pk = any(row[3] == "pk" for row in db.execute("PRAGMA index_list(tasks)"))
    if columns != expected or separate_pk:
        raise ValueError("incompatible task store schema")
    from .recurrence import interval
    try:
        for row in db.execute("SELECT * FROM tasks"):
            task = dict(zip(TASK_COLUMNS, row))
            if type(task['id']) is not int or task['id'] <= 0 or not isinstance(task['title'], str) or not task['title'].strip() or not isinstance(task['notes'], str) or task['priority'] not in ('low', 'normal', 'high') or task['status'] not in ('open', 'done', 'cancelled'):
                raise ValueError('invalid task data')
            for field in ('due', 'snoozed_until', 'created_at', 'updated_at'):
                value = task[field]
                if value is not None:
                    due_value(value, aware_only=field != 'due')
            if task['check_in_days'] not in CHECK_IN_DAYS:
                raise ValueError('invalid check-in days')
            cycle = task['cycle_id']
            if cycle is not None and (not isinstance(cycle, str) or not re.fullmatch('[0-9a-f]{32}', cycle)):
                raise ValueError('invalid cycle')
            if task['repeat_interval'] is not None:
                if interval(task['repeat_interval']) != task['repeat_interval'] or cycle is None or task['due'] is None or task['status'] == 'done':
                    raise ValueError('invalid recurrence')
            if task['last_completion'] is not None:
                record = json.loads(task['last_completion'])
                if set(record) != {'cycle', 'identity', 'completed_at'} or not re.fullmatch('[0-9a-f]{32}', record['cycle']) or not isinstance(record['identity'], str) or not record['identity'].strip() or cycle is None or record['cycle'] == cycle:
                    raise ValueError('invalid completion')
                due_value(record['completed_at'])
    except (TypeError, KeyError, argparse.ArgumentTypeError, OverflowError):
        raise ValueError('invalid task data') from None


def get_task(db, key):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (key,)).fetchone()
    if row is None:
        raise ValueError("task not found")
    return task_record(row)


def check_in_days_conflict(task, config):
    """True when narrower task days can never meet the configured days."""
    days = task.get("check_in_days", "all")
    return days != "all" and not set(CHECK_IN_DAY_VALUES.get(days, ())) & set(config["weekdays"])


def warn_check_in_days(task, config):
    """Warn without blocking: a task may be staged before the global days widen."""
    if task.get("status") != "open" or not check_in_days_conflict(task, config):
        return
    days = task.get("check_in_days", "all")
    print("task-coach: warning: task " + str(task["id"]) + " has check-in days '"
          + str(days) + "' but the configured days are '" + ",".join(config["weekdays"])
          + "'; it will not be checked in until they overlap", file=sys.stderr)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    positional = arguments
    if positional[:1] == ['--data-dir']:
        positional = positional[2:]
    elif positional and positional[0].startswith('--data-dir='):
        positional = positional[1:]
    is_tick = positional[:2] in (['coach', 'tick'], ['runtime', 'preflight'])
    try:
        return run(arguments)
    except SystemExit as error:
        if is_tick and error.code:
            print(json.dumps(dict(wakeAgent=False, reason='invalid-tick-arguments')))
            return 2
        raise
    except (OSError, sqlite3.Error, ValueError, EOFError, KeyboardInterrupt) as error:
        print("task-coach: error: " + str(error), file=sys.stderr)
        if is_tick:
            print(json.dumps(dict(wakeAgent=False, reason='engine-error')))
        return 2


def run(argv=None):
    parser = argparse.ArgumentParser(prog="task-coach")
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    setup = commands.add_parser(
        "setup",
        description="Configure local task coaching. No jobs or delivery are enabled.",
        epilog="Defaults: UTC; days mon,tue,wed,thu,fri,sat,sun; window 09:00–17:00; "
        "up to 2 distinct tasks per window (maximum 1..10); "
        "2 unanswered followups per task; intervals 30–120 minutes. Intervals must be 1..1440 "
        "minutes and followups 0..20, fitting within a same-day window at the minimum "
        "interval. Choose local tasks or preferences for already-configured Discord "
        "check-ins; setup never connects messaging or enables delivery, "
        "and automation remains disabled.",
    )
    setup.add_argument("--interactive", action="store_true", help="prompt for settings; blank keeps the displayed default")
    setup.add_argument("--update", action="store_true", help="explicitly update an existing configuration")
    for field in ("timezone", "weekdays", "notification-start", "notification-end"):
        setup.add_argument("--" + field)
    for field in ("max-tasks-per-window", "max-unanswered-followups", "min-followup-interval", "max-followup-interval"):
        setup.add_argument("--" + field, type=int)
    commands.add_parser("list")
    commands.add_parser("export")
    coach = commands.add_parser('coach', description='Local intent engine only; external delivery bridge required.')
    operations = coach.add_subparsers(dest='coach_command', required=True)
    for operation in ('status', 'inspect', 'pause', 'resume'):
        operations.add_parser(operation)
    tick = operations.add_parser('tick', help='Claim a due intent; never sends a message')
    tick.add_argument('--binding', type=json.loads)
    tick.add_argument('--evidence', type=json.loads)
    preview = operations.add_parser('preview', help='Isolated development plan; does not consume engine state')
    preview.add_argument('--binding', type=json.loads, required=True)
    preview.add_argument('--at', type=lambda v: due_value(v, aware_only=True))
    preview.add_argument('--seed', type=int)
    ack = operations.add_parser('ack', help='Record an externally confirmed delivery, not an intent')
    ack.add_argument('--receipt', type=json.loads, required=True)
    for operation in ('engaged', 'failed'):
        outcome = operations.add_parser(operation, help='Stop episode on owner engagement or failed send')
        outcome.add_argument('--event-token', required=True)
        outcome.add_argument('--binding', type=json.loads, required=True)
    from .driver import add_parser
    add_parser(commands)
    add = commands.add_parser("add")
    add.add_argument("title", type=title_value)
    add.add_argument("--notes", default="")
    add.add_argument("--priority", choices=("low", "normal", "high"), default="normal")
    add.add_argument("--due", type=due_value)
    add.add_argument("--repeat")
    add.add_argument("--check-in-days", choices=CHECK_IN_DAYS, default="all",
                     help="days for both check-ins and follow-ups within the global window (default: all)")
    show = commands.add_parser("show")
    show.add_argument("id", type=int)
    search = commands.add_parser("search")
    search.add_argument("query")
    update = commands.add_parser("update")
    update.add_argument("id", type=int)
    for field in ("title", "notes", "due"):
        update.add_argument("--" + field, type=title_value if field == "title" else due_value if field == "due" else str)
    update.add_argument("--priority", choices=("low", "normal", "high"))
    update.add_argument("--status", choices=("open", "done", "cancelled"))
    update.add_argument("--check-in-days", choices=CHECK_IN_DAYS)
    group = update.add_mutually_exclusive_group()
    group.add_argument("--repeat")
    group.add_argument("--remove-repeat", action="store_true")
    done = commands.add_parser("done")
    done.add_argument("id", type=int)
    done.add_argument("--completed-at", type=due_value)
    done.add_argument("--expected-cycle")
    done.add_argument("--completion-id")
    snooze = commands.add_parser("snooze")
    snooze.add_argument("id", type=int)
    snooze.add_argument("until", type=lambda value: due_value(value, aware_only=True))
    checklist = commands.add_parser("checklist", description="Read or tick Markdown checklist items in a task's notes.")
    checklist_operations = checklist.add_subparsers(dest="checklist_command", required=True)
    checklist_show = checklist_operations.add_parser("show", help="Index checklist items and report checked/total")
    checklist_show.add_argument("id", type=int)
    for operation, help_text in (("check", "Tick one indexed checklist item"),
                                 ("uncheck", "Clear one indexed checklist item")):
        mutation = checklist_operations.add_parser(operation, help=help_text)
        mutation.add_argument("id", type=int)
        mutation.add_argument("index", type=int)
        mutation.add_argument("--expected-notes-digest", required=True,
                              help="notes_digest from checklist show; refuses a stale snapshot")
    args = parser.parse_args(argv)
    if hasattr(args, "id") and not 1 <= args.id <= 9223372036854775807:
        parser.error("id must be a positive SQLite integer")
    directory = args.data_dir
    store = directory / "tasks.sqlite3"
    config_path = directory / "config.json"
    for path in (directory, *directory.parents, store, config_path):
        if path.is_symlink():
            raise ValueError("symlink data, store or config paths are not supported")
    for path in (store, config_path):
        if path.exists() and not path.is_file():
            raise ValueError("store and config must be regular files")
    for path in (directory, store, config_path):
        if path.exists():
            info = path.stat()
            if info.st_uid != os.getuid() or (path != directory and info.st_nlink != 1):
                raise ValueError("storage must be owned by the current user and files must not be hardlinked")
    if args.command not in ("init", "setup"):
        for path, mode in ((directory, 0o700), (store, 0o600), (config_path, 0o600)):
            if path.exists() and path.stat().st_mode & 0o7777 != mode:
                raise ValueError("unsafe storage permissions; run init or setup to repair")
    if config_path.is_file():
        config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
    else:
        config = dict(DEFAULT_CONFIG)
    if args.command not in ("init", "setup") and (not store.is_file() or not config_path.is_file()):
        parser.error("store is not initialized; run init or setup")
    if args.command in ("init", "setup"):
        existing = config_path.is_file()
        changes = {field: getattr(args, field, None) for field in DEFAULT_CONFIG if field != "automation_enabled" and getattr(args, field, None) is not None}
        if existing and changes and not getattr(args, "update", False):
            raise ValueError("configuration exists; use setup --update to change it")
        if "weekdays" in changes:
            changes["weekdays"] = changes["weekdays"].split(",")
        if getattr(args, "interactive", False):
            if existing and not args.update:
                raise ValueError("use setup --update --interactive to edit existing settings")
            print('Local tasks or Discord check-ins? [local]: ', end='', file=sys.stderr, flush=True)
            mode = input().strip().lower() or 'local'
            if mode not in ('local', 'discord'):
                raise ValueError('choose local or discord')
            if mode == 'discord':
                print('These are preferences only. Discord must already be configured in Hermes; no messages or schedule are enabled here.', file=sys.stderr)
            labels = {
                'timezone': 'Your timezone (for example Europe/Paris or UTC)',
                'weekdays': 'Check-in days (mon,tue,wed,thu,fri,sat,sun)',
                'notification_start': 'Earliest check-in time (HH:MM)',
                'notification_end': 'Latest check-in time (HH:MM, same day)',
                'max_unanswered_followups': 'Maximum follow-ups without a reply',
                'min_followup_interval': 'Minimum minutes between follow-ups',
                'max_followup_interval': 'Maximum minutes between follow-ups',
            }
            for field, label in labels.items():
                if field in changes or (mode == 'local' and field != 'timezone'):
                    continue
                default = config[field]
                display = ",".join(default) if isinstance(default, list) else default
                print(f"{label} [{display}]: ", end="", file=sys.stderr, flush=True)
                answer = input().strip()
                if answer:
                    changes[field] = answer.split(",") if field == "weekdays" else int(answer) if type(default) is int else answer
            if mode == 'discord' and 'max_tasks_per_window' not in changes:
                label = 'Current' if existing else 'Default'
                print(f"{label} maximum distinct tasks per window: {config['max_tasks_per_window']}. A reply stops only that task's follow-ups; later tasks remain scheduled.", file=sys.stderr)
                print('Keep or customize? [keep]: ', end='', file=sys.stderr, flush=True)
                choice = input().strip().lower() or 'keep'
                if choice not in ('keep', 'customize'):
                    raise ValueError('choose keep or customize')
                if choice == 'customize':
                    print('Maximum distinct tasks per window (1..10): ', end='', file=sys.stderr, flush=True)
                    changes['max_tasks_per_window'] = int(input().strip())
        previous_days = config["weekdays"]
        config.update(changes)
        validate_config(config)
        if getattr(args, "interactive", False) and mode == 'discord' and len(config['weekdays']) == 7:
            print('When adding a task, I’ll ask whether you want check-ins on weekdays, weekends, or all. That includes follow-ups.', file=sys.stderr)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Ownership/type/symlink checks above permit setup's dedicated-mode repair.
        with task_store_lock(directory, repair=True):
            conflicts = []
            fresh = not store.exists()
            if fresh:
                fd = os.open(store, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
            with closing(sqlite3.connect(store)) as db:
                if fresh:
                    db.execute(TASK_DDL)
                    db.execute("PRAGMA user_version=2")
                validate_store(db)
                db.commit()
                if config["weekdays"] != previous_days:
                    db.row_factory = sqlite3.Row
                    for row in db.execute("SELECT * FROM tasks WHERE status = 'open' ORDER BY id"):
                        task = dict(row)
                        if check_in_days_conflict(task, config):
                            conflicts.append(task)
            directory.chmod(0o700)
            store.chmod(0o600)
            if not existing or changes:
                fd, temporary = tempfile.mkstemp(prefix=".config-", dir=directory)
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as file:
                        json.dump(config, file, indent=2)
                        file.write("\n")
                    os.replace(temporary, config_path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            config_path.chmod(0o600)
            for task in conflicts:
                warn_check_in_days(task, config)
        result = {"config": config}
    elif args.command == 'runtime':
        from .driver import run_cli
        result = run_cli(directory, args)
    elif args.command == 'coach':
        from .coaching import Coach
        engine = Coach(directory)
        operation = args.coach_command
        if operation in ('status', 'inspect'):
            result = engine.status()
        elif operation in ('pause', 'resume'):
            result = engine.pause(operation == 'pause')
        elif operation == 'tick':
            result = engine.tick(binding=args.binding, evidence=args.evidence)
        elif operation == 'preview':
            result = engine.preview(binding=args.binding, now=args.at, seed=args.seed)
        elif operation == 'ack':
            result = engine.acknowledge(args.receipt)
        elif operation == 'failed':
            result = engine.failed(args.event_token, args.binding)
        else:
            result = engine.stop(args.event_token, args.binding)
    else:
        with task_store_lock(directory), closing(sqlite3.connect(store.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            config = validate_config(json.loads(config_path.read_text(encoding="utf-8")))
            db.row_factory = sqlite3.Row
            validate_store(db)
            if args.command == "add":
                from .recurrence import interval
                repeat = interval(args.repeat) if args.repeat else None
                if repeat and not args.due:
                    raise ValueError("recurrence requires an explicit initial due date")
                now = datetime.now(timezone.utc).isoformat()
                cursor = db.execute("INSERT INTO tasks (title, notes, priority, status, due, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (args.title, args.notes, args.priority, "open", args.due, now, now))
                if repeat:
                    db.execute("UPDATE tasks SET repeat_interval=?, cycle_id=? WHERE id=?", (repeat, uuid.uuid4().hex, cursor.lastrowid))
                if args.check_in_days != 'all':
                    db.execute("UPDATE tasks SET check_in_days=? WHERE id=?", (args.check_in_days, cursor.lastrowid))
                db.commit()
                result = get_task(db, cursor.lastrowid)
                warn_check_in_days(result, config)
            elif args.command in ("update", "done", "snooze"):
                task = get_task(db, args.id)
                changes = {}
                if args.command == 'done' and not task.get('repeat_interval') and any((args.completed_at, args.expected_cycle, args.completion_id)):
                    raise ValueError('guarded completion does not match a recurring task')
                if args.command == "update":
                    changes = {field: getattr(args, field) for field in ("title", "notes", "due", "priority", "status") if getattr(args, field) is not None}
                    if args.check_in_days is not None:
                        changes['check_in_days'] = args.check_in_days
                    if task.get("repeat_interval") and args.status in ("open", "done") and args.status != task["status"]:
                        raise ValueError("use guarded done for recurring completion; status cannot bypass it")
                    if args.repeat or args.remove_repeat:
                        from .recurrence import interval
                        repeat = interval(args.repeat) if args.repeat else None
                        if repeat and (changes.get("status", task["status"]) != "open" or not changes.get("due", task["due"])):
                            raise ValueError("recurrence requires an open task with an explicit due date")
                        if repeat != task.get("repeat_interval"):
                            changes.update(repeat_interval=repeat, cycle_id=uuid.uuid4().hex)
                elif args.command == "done" and task.get("repeat_interval"):
                    from .recurrence import completion_changes
                    changes = completion_changes(task, args.completed_at, args.expected_cycle, args.completion_id, config["timezone"], datetime.now(timezone.utc))
                elif args.command == "done" and task["status"] != "done":
                    changes = {"status": "done"}
                elif args.command == "snooze":
                    changes = {"snoozed_until": args.until}
                changes = {field: value for field, value in changes.items() if task[field] != value}
                if changes:
                    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
                    # Column names come only from the fixed field sets above.
                    db.execute("UPDATE tasks SET " + ", ".join(field + " = ?" for field in changes) + " WHERE id = ?", (*changes.values(), args.id))
                    db.commit()
                result = get_task(db, args.id)
                if changes.get("check_in_days") or changes.get("status") == "open":
                    warn_check_in_days(result, config)
            elif args.command == "checklist":
                task = get_task(db, args.id)
                if args.checklist_command == "show":
                    result = checklist_payload(task)
                else:
                    if not NOTES_DIGEST.fullmatch(args.expected_notes_digest or ""):
                        raise ValueError("invalid expected notes digest")
                    if args.expected_notes_digest != notes_digest(task["notes"]):
                        raise ValueError("notes changed since checklist read; re-read the checklist")
                    notes = set_checklist_item(task["notes"], args.index,
                                               args.checklist_command == "check")
                    if notes != task["notes"]:
                        db.execute("UPDATE tasks SET notes = ?, updated_at = ? WHERE id = ?",
                                   (notes, datetime.now(timezone.utc).isoformat(), args.id))
                        db.commit()
                    result = checklist_payload(get_task(db, args.id))
            elif args.command == "show":
                result = get_task(db, args.id)
            elif args.command == "search":
                result = [task_record(row) for row in db.execute("SELECT * FROM tasks WHERE instr(lower(title), lower(?)) > 0 OR instr(lower(notes), lower(?)) > 0 ORDER BY id", (args.query, args.query))]
            else:
                result = [task_record(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]
    print(json.dumps(result))
    return 0
