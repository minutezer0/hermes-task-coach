# Hermes Task Coach

A local task manager for Hermes Agent, with optional proactive check-ins.
Capture a task, pick a small next step, and work through blockers in ordinary
conversation. Tasks live in a local SQLite store and need no messaging account.
Automatic check-ins are optional and off until you configure them.

## Requirements and install

You need Python 3.11 or newer with SQLite and timezone data. Linux is the
qualified platform. There are no third-party runtime dependencies.

Install the skill into your Hermes profile:

```sh
hermes skills install minutezer0/hermes-task-coach/skills/task-coach
```

The helper ships inside the installed skill:
`<skill_dir>/scripts/task-coach.py`. Use the real directory Hermes reports for
the skill; quote the path if it contains spaces. Task data is stored outside the
skill directory, so replacing or reinstalling the skill does not delete tasks.
Installing the skill does not itself launch a chat.
When you are ready, ask Hermes to set up Task Coach.

Initialize the store and save your settings once:

```sh
python3 "<skill_dir>/scripts/task-coach.py" init
python3 "<skill_dir>/scripts/task-coach.py" setup
```

`init` creates an empty store with defaults; `setup` validates and saves
preferences. Neither schedules nor sends anything. For prompts, run
`setup --interactive` on a fresh directory, or `setup --update --interactive` to
edit saved settings; blank answers keep the current values.

## First task in five minutes

```sh
python3 "<skill_dir>/scripts/task-coach.py" init
python3 "<skill_dir>/scripts/task-coach.py" setup
python3 "<skill_dir>/scripts/task-coach.py" add "Clear the kitchen table" \
  --notes "Start with the papers"
python3 "<skill_dir>/scripts/task-coach.py" list
python3 "<skill_dir>/scripts/task-coach.py" show 1
```

`add` prints the new task ID. Use that ID for `show`; the example assumes a
fresh, empty store. Commands print JSON so tools can read them, and Hermes
translates results into conversation. You can also just tell Hermes what you
want to do and let it run these commands for you.

## Daily use

```sh
# Add with detail (IDs in this section are examples; use the IDs list shows)
python3 "<skill_dir>/scripts/task-coach.py" add "Draft the invoice" \
  --notes "Use last month's numbers" --due 2031-04-05 --priority high

# Review
python3 "<skill_dir>/scripts/task-coach.py" list
python3 "<skill_dir>/scripts/task-coach.py" show 3
python3 "<skill_dir>/scripts/task-coach.py" search invoice

# Change something
python3 "<skill_dir>/scripts/task-coach.py" update 3 --priority normal \
  --due 2031-04-09
python3 "<skill_dir>/scripts/task-coach.py" update 3 --status cancelled

# Finish or postpone
python3 "<skill_dir>/scripts/task-coach.py" done 3
python3 "<skill_dir>/scripts/task-coach.py" snooze 3 2031-04-12T09:00:00+02:00

# Back up everything as JSON
python3 "<skill_dir>/scripts/task-coach.py" export
```

- **Priority** is `low`, `normal`, or `high`.
- **Status** is `open`, `done`, or `cancelled`.
- **Due** accepts a date (`2031-04-05`) or a timestamp with an offset
  (`2031-04-05T12:00:00+02:00`).
- **Snooze** requires a timestamp with an offset and does not change the due date.
- **Notes** are plain text; you can maintain checkbox lines by hand.
- `done` is idempotent and keeps history.

## Check-in days

Each task can restrict the days it is eligible for both initial check-ins and
follow-ups: `weekdays`, `weekends`, or `all` (the default).

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Garden" --check-in-days weekends
python3 "<skill_dir>/scripts/task-coach.py" update 4 --check-in-days weekdays
```

Task days narrow your global check-in days and hours; they never widen them.
`all` means every day your global window already allows. If a task's days never
overlap the global window, the task is still saved but cannot be scheduled.
`add`, a changed `update --check-in-days`, reopening a task with
`update --status open`, and a `setup --update --weekdays` change print a
non-blocking warning on stderr so you can stage a task before widening the
global window. `list` and `show` always report what was actually saved.

Overdue dates do not override day preferences. You can reply to and work on any
task on any day, inside or outside its check-in days and hours.

## Recurring tasks

Give a repeating task an explicit first due date and a positive interval of
days, weeks, or months:

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Replace filter" \
  --repeat "3 months" --due 2026-01-31

# read cycle_id from show, then complete with the real date
python3 "<skill_dir>/scripts/task-coach.py" show 5
python3 "<skill_dir>/scripts/task-coach.py" done 5 \
  --completed-at 2026-10-31 \
  --expected-cycle CYCLE_ID_FROM_SHOW \
  --completion-id UNIQUE_REQUEST_ID

# change or stop repeating
python3 "<skill_dir>/scripts/task-coach.py" update 5 --repeat "2 weeks"
python3 "<skill_dir>/scripts/task-coach.py" update 5 --remove-repeat
```

Only an explicit completion advances the task. Replies, snoozes, and cancellations
do not. The task stays overdue until you complete it, and no missed occurrences or
backlog are generated. The next due date is calculated from the actual completion
date, using calendar months, not fixed 90-day blocks. Month ends clamp sensibly:
January 31 plus three months is April 30; completing on October 31 moves the
next due date to January 31, 2027.

Intervals must be 1 to 9999 days, weeks, or months. A recurring task refuses a
plain `done ID`: it requires `--completed-at`, the current `--expected-cycle`, and
a unique `--completion-id`, which together prevent an accidental or duplicated
completion. Use the same values if you retry. Removing recurrence does not
complete or cancel the task.

## Optional proactive coaching

Hermes can send you check-ins through an already-configured Hermes connection.
This is entirely optional: local task management works with it off, and nothing
is scheduled or sent until you complete setup and separately approve activation.

Proactive coaching is **local-first** by default. It uses your task data,
recorded replies, your allowed windows, and a global pause. The native Hermes
send is the only transport, and a successful send is recorded as accepted
delivery. It means the transport accepted the message, not that a person read it.

Only Discord is supported for automatic check-ins today, and it must already be
configured in Hermes. Task Coach never creates a messaging account or asks for
credentials. **Discord history is off by default.** Local tasks, accepted
delivery, and normal reply handling work without it. History is read only for an
explicitly requested reply recovery or delivery verification, one bounded page,
and never during routine check-ins.

**Smart Snooze** is off by default. With it on, an explicit "starting now" reply to
a check-in holds all Task Coach notifications until the end of your current window,
without changing any task. Read or change it with `runtime smart-snooze`,
`runtime smart-snooze --enable` or `runtime smart-snooze --disable`.

To set it up, tell Hermes in conversation:

> Help me set up Task Coach. Ask one question at a time and reuse my saved settings.

Hermes asks about preferences, uses one real task, installs a paused schedule and
a narrowly scoped reply instruction, offers an optional test that defaults to No,
and asks for a separate approval before regular check-ins start.

## Advanced

### Optional pip install

The skill install above is the supported path for Hermes. The helper is also
packaged for direct command-line use: `pip install .` from the repository installs
a `task-coach` entry point that accepts the same subcommands.

### Setup flags and defaults

`setup` accepts the flags below. `setup --update` is required to change an
existing configuration; `setup --update --interactive` shows saved values and
keeps them when you press Enter. Without `--update`, a different saved value is
refused rather than silently overwritten.

| Flag | Default | Notes |
| --- | --- | --- |
| `--timezone` | `UTC` | IANA name, e.g. `Europe/Paris` |
| `--weekdays` | `mon,tue,wed,thu,fri,sat,sun` | Comma-separated, distinct |
| `--notification-start` | `09:00` | Local time, `HH:MM` |
| `--notification-end` | `17:00` | Local time, same day |
| `--max-tasks-per-window` | `2` | 1–10 distinct tasks |
| `--max-unanswered-followups` | `2` | 0–20 per task |
| `--min-followup-interval` | `30` | Minutes, 1–1440 |
| `--max-followup-interval` | `120` | Minutes, 1–1440 |
| `--interactive` | off | Prompt for settings |
| `--update` | off | Explicitly update saved settings |

The maximum interval must be at least the minimum, and both must fit inside a
same-day window. Overnight windows are not supported. Preferences alone never
trigger a message.

### Data directory

With `HERMES_HOME` set, data lives in `$HERMES_HOME/task-coach`. Otherwise it uses
`$XDG_DATA_HOME/task-coach`, or `~/.local/share/task-coach` when that is unset.
Pass `--data-dir PATH` before the subcommand and use the same path every time.

```
task-coach/
├── config.json        saved preferences
├── tasks.sqlite3      tasks, schema version 2
├── coach.sqlite3      coaching episodes and engine state
└── outbox.sqlite3     send journal and delivery receipts
```

Only `init` and `setup` create the store; every other command refuses a missing
or uninitialized directory. Files must be owned by you with safe permissions:
`init` and `setup` apply directory mode `0700` and file mode `0600`, and other
commands refuse unsafe modes. Symlinked or hardlinked storage is refused.

Tasks use **schema version 2**. Version 1.0 is a base install: there is no
migration from earlier releases, and no upgrade command exists on this branch.
A fresh `init` creates version 2 directly.

### Native cron and check-in wiring

When enabled, a native Hermes cron job runs a preflight wrapper every minute.
This is a check, not a message cadence. A quiet `wakeAgent: false` result wakes
nobody; a due result wakes an agent to compose and validate one check-in through
`hermes send`.

The daily plan selects up to your maximum number of distinct tasks, with one
opener and bounded unanswered follow-ups per task. Reply to a task and its
follow-ups stop; later tasks stay scheduled. Sequences do not overlap and keep at
least 30 minutes between opportunities, or your larger minimum follow-up
interval. Too few eligible tasks or too little window space produces fewer
check-ins, not repeats to fill a quota. Missed opportunities are not caught up.

The cron job is installed paused. Activation is a separate approval, and pausing
cron is separate from `coach pause`, which persists a global pause in the engine:

```sh
python3 "<skill_dir>/scripts/task-coach.py" coach pause
python3 "<skill_dir>/scripts/task-coach.py" coach resume
python3 "<skill_dir>/scripts/task-coach.py" coach status
```

`coach resume` clears the global pause but does not revive a stopped day or
unpause cron.

### Troubleshooting

- **"store is not initialized"** — run `init` or `setup` first, and check that
  `--data-dir` points at the same directory every time.
- **"configuration exists; use setup --update"** — settings are already saved.
  Add `--update` to change them deliberately.
- **"unsafe storage permissions"** — re-run `init` or `setup` to repair modes,
  and confirm you own the directory and files.
- **A task never gets check-ins** — its check-in days may not overlap the global
  window. Widen the window with `setup --update --weekdays`, or change the task
  with `update ID --check-in-days all`.
- **No messages arrive** — verify the native cron job exists and is not paused,
  that a check-in route was configured, and that global pause is off.
- **Fewer check-ins than the maximum** — the budget is a ceiling, not a quota;
  eligibility and window space usually explain the difference.
- **Check-ins in the TUI** — the TUI is a working surface, not a notification
  target. Reply in the configured chat to stop that chat's follow-ups.

Every refusal is deliberate. Do not edit or delete databases to work around a
safety check; fix the input or storage state instead.

### Reset

Only reset when you want a genuinely fresh start, not to bypass a refusal.

1. Stop every writer: conversations, manual commands, and background workers.
2. Pause the Task Coach cron job with the supported Hermes command and read it
   back to confirm. Leave unrelated jobs alone.
3. Inventory the data directory without following symlinks. Confirm which files
   are Task Coach's and whether you want a backup.
4. Remove only the approved files: `config.json`, `tasks.sqlite3`,
   `coach.sqlite3`, and `outbox.sqlite3`. Never use an unrestricted recursive
   delete over a directory you have not inspected.
5. Confirm the directory is empty or gone and that the installed skill is intact.
6. Run `init` and `setup` again when you are ready. Check-ins stay paused until
   you separately approve activation.

## License

MIT. See [LICENSE](LICENSE).
