"""Command-line interface for the local task store."""
import argparse
from datetime import date, datetime, timezone
import re
from contextlib import closing
import json
from pathlib import Path
import os
import sqlite3
import sys
import tempfile
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_CONFIG = {
    "timezone": "UTC", "weekdays": ["mon", "tue", "wed", "thu", "fri"],
    "notification_start": "09:00", "notification_end": "17:00",
    "max_unanswered_followups": 2, "min_followup_interval": 30,
    "max_followup_interval": 120, "destination": None, "automation_enabled": False,
}


def validate_config(config):
    if not isinstance(config, dict) or set(config) != set(DEFAULT_CONFIG):
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
    count = config["max_unanswered_followups"]
    low, high = config["min_followup_interval"], config["max_followup_interval"]
    if any(type(value) is not int for value in (count, low, high)) or not 0 <= count <= 20 or not 1 <= low <= high <= 1440:
        raise ValueError("followups must be 0..20 and intervals 1..1440 minutes with min <= max")
    if count * low > minutes[1] - minutes[0]:
        raise ValueError("notification window cannot fit followups at the minimum interval")
    if config["destination"] is not None and (not isinstance(config["destination"], str) or not config["destination"].strip()):
        raise ValueError("destination must be a non-empty opaque string")
    if config["automation_enabled"] is not False:
        raise ValueError("automation is not available; automation_enabled must be false")
    return config


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


TASK_COLUMNS = ("id", "title", "notes", "priority", "status", "due", "snoozed_until", "created_at", "updated_at")


def validate_store(db):
    columns = tuple(tuple(row)[1:] for row in db.execute("PRAGMA table_xinfo(tasks)"))
    expected = tuple(
        (name, "INTEGER" if name == "id" else "TEXT",
         int(name not in ("id", "due", "snoozed_until")), None, int(name == "id"), 0)
        for name in TASK_COLUMNS
    )
    # A separate primary-key index means id is not the INTEGER rowid alias
    # (for example, INTEGER PRIMARY KEY DESC or a WITHOUT ROWID table).
    separate_pk = any(row[3] == "pk" for row in db.execute("PRAGMA index_list(tasks)"))
    if columns != expected or separate_pk:
        raise ValueError("incompatible task store schema")


def get_task(db, key):
    row = db.execute("SELECT * FROM tasks WHERE id = ?", (key,)).fetchone()
    if row is None:
        raise ValueError("task not found")
    return dict(row)


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
        epilog="Defaults: UTC; weekdays mon,tue,wed,thu,fri; window 09:00–17:00; "
        "2 unanswered followups; intervals 30–120 minutes. Intervals must be 1..1440 "
        "minutes and followups 0..20, fitting within a same-day window at the minimum "
        "interval. Destination is optional and opaque; automation remains disabled.",
    )
    setup.add_argument("--interactive", action="store_true", help="prompt for settings; blank keeps the displayed default")
    setup.add_argument("--update", action="store_true", help="explicitly update an existing configuration")
    for field in ("timezone", "weekdays", "notification-start", "notification-end", "destination"):
        setup.add_argument("--" + field)
    for field in ("max-unanswered-followups", "min-followup-interval", "max-followup-interval"):
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
    done = commands.add_parser("done")
    done.add_argument("id", type=int)
    snooze = commands.add_parser("snooze")
    snooze.add_argument("id", type=int)
    snooze.add_argument("until", type=lambda value: due_value(value, aware_only=True))
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
            for field in DEFAULT_CONFIG:
                if field == "automation_enabled" or field in changes:
                    continue
                default = config[field]
                display = ",".join(default) if isinstance(default, list) else default
                print(f"{field} [{display}]: ", end="", file=sys.stderr, flush=True)
                answer = input().strip()
                if answer:
                    changes[field] = answer.split(",") if field == "weekdays" else int(answer) if type(default) is int else answer
        config.update(changes)
        validate_config(config)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not store.exists():
            fd = os.open(store, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        with closing(sqlite3.connect(store)) as db:
            db.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, notes TEXT NOT NULL, priority TEXT NOT NULL, status TEXT NOT NULL, due TEXT, snoozed_until TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            validate_store(db)
            db.commit()
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
        with closing(sqlite3.connect(store.resolve().as_uri() + "?mode=rw", uri=True)) as db:
            db.row_factory = sqlite3.Row
            validate_store(db)
            if args.command == "add":
                now = datetime.now(timezone.utc).isoformat()
                cursor = db.execute("INSERT INTO tasks (title, notes, priority, status, due, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (args.title, args.notes, args.priority, "open", args.due, now, now))
                db.commit()
                result = dict(db.execute("SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)).fetchone())
            elif args.command in ("update", "done", "snooze"):
                task = get_task(db, args.id)
                changes = {}
                if args.command == "update":
                    changes = {field: getattr(args, field) for field in ("title", "notes", "due", "priority", "status") if getattr(args, field) is not None}
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
            elif args.command == "show":
                result = get_task(db, args.id)
            elif args.command == "search":
                result = [dict(row) for row in db.execute("SELECT * FROM tasks WHERE instr(lower(title), lower(?)) > 0 OR instr(lower(notes), lower(?)) > 0 ORDER BY id", (args.query, args.query))]
            else:
                result = [dict(row) for row in db.execute("SELECT * FROM tasks ORDER BY id")]
    print(json.dumps(result))
    return 0
