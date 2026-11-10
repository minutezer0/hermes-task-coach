# Hermes Task Coach

A local task manager for Hermes Agent, with optional proactive check-ins.
Capture a task, pick a small next step, and work through blockers in ordinary
conversation. Tasks live in a local SQLite store and need no messaging account.
Automatic check-ins are optional and off until you configure them.

## Requirements and install

Python 3.11 or newer with SQLite and timezone data. Linux is the qualified
platform, and there are no third-party runtime dependencies. Proactive check-ins
additionally need an existing Discord connection in Hermes; Task Coach never
creates an account or asks for credentials.

```sh
hermes skills install minutezer0/hermes-task-coach/skills/task-coach
```

For direct command-line use, the same package installs with `pip install .` from
the repository.

Installing the skill does not itself launch a chat and does not enable check-ins.
When you are ready, ask Hermes to set up Task Coach:

> Set up Task Coach

Hermes asks about your preferences, uses one real task, installs a paused schedule
and a narrowly scoped reply instruction, offers an optional test that defaults to
No, and asks for a separate approval before regular check-ins start. Nothing is
scheduled or sent before that approval.

## Talking to your coach

Once set up, talk to it like a person. It reads and writes the same local store, so
you never have to remember command syntax:

> Add take out the garbage to todo

> What's on my task list?

> Let's work on the new laptop task

> Mark the garbage as done

> Skip the invoices today

> Remind me about the gutters next weekend

Two habits keep it predictable. It asks **which task** when your message could
mean more than one, and it never completes, snoozes, cancels or reprioritises a
task without your explicit say-so. If you ask for something it cannot do, it says
what is missing rather than guessing.

## Features

### Proactive Mode (the coach)

Task Coach can send check-ins through an already-configured Hermes connection. This
is optional, though it is the point of the skill. Local task management works with
it off, and nothing is sent until you approve activation.

Coaching is **local-first**: it uses your tasks, recorded replies, allowed days and
hours, and a global pause. The native Hermes send is the only transport, and a
successful send is recorded as accepted delivery — the transport accepted the
message, not that a person read it.

Only Discord is supported today. **Discord history is off by default** and is read
only for an explicitly requested reply recovery or delivery verification, one
bounded page, never during routine check-ins. Replying to a check-in stops that
task's follow-ups; later tasks stay scheduled.

### Smart Snooze

Off by default. With it on, replying that you are starting work *right now*
suppresses every Task Coach notification for the rest of your current window, so
other tasks do not interrupt you. It changes no task and never survives the
window: the next allowed day starts clean.

### Check-in days per task

If your global schedule covers all seven days, each task can be limited to
weekdays, weekends, or all days. This controls both the first check-in and its
follow-ups, so a work-only task never nudges you on Saturday. Task days can only
narrow your global window, never widen it, and a task whose days never meet your
global days is still saved — Task Coach warns you on stderr and schedules nothing
until the two overlap.

### Due dates and recurring tasks

Priority and due dates both raise a task's chance of being picked: low, normal and
high weigh 1, 2 and 4, a due date inside the next week raises the weight up to
4.5x as it approaches, and an overdue task gets five times its base weight. A due
date is a preference for when you want to see the task, not a deadline the coach
enforces, and it never overrides your allowed days or hours.

A recurring task takes an explicit first due date plus an interval in days, weeks
or months — changing the furnace filter every three months, for example. It is
withheld from check-ins until its due date arrives, unlike an ordinary dated task
that can appear early, which is deliberate: no three months of nudges about a
filter that only matters on the day.

Only an explicit completion advances it. Replies, snoozes and cancellations do not,
the task stays overdue until you complete it, and no missed occurrences or backlog
are generated. The next due date comes from the actual completion date using
calendar months, not fixed 90-day blocks, with month ends clamped sensibly:
January 31 plus three months is April 30, and completing on October 31 moves the
next due date to January 31, 2027.

## Direct commands (how the agent runs it)

What Hermes executes on your behalf, plus what a human debugging an installation
needs. The helper ships inside the installed skill:
`<skill_dir>/scripts/task-coach.py`. Use the real directory Hermes reports and
quote the path if it contains spaces. Task data lives outside the skill directory,
so reinstalling never deletes tasks.

### Daily commands

```sh
python3 "<skill_dir>/scripts/task-coach.py" init          # empty store, defaults
python3 "<skill_dir>/scripts/task-coach.py" setup         # validate and save preferences

python3 "<skill_dir>/scripts/task-coach.py" add "Draft the invoice" \
  --notes "Use last month's numbers" --due 2031-04-05 --priority high
python3 "<skill_dir>/scripts/task-coach.py" list
python3 "<skill_dir>/scripts/task-coach.py" show 3        # IDs shown by list
python3 "<skill_dir>/scripts/task-coach.py" search invoice
python3 "<skill_dir>/scripts/task-coach.py" update 3 --priority normal --due 2031-04-09
python3 "<skill_dir>/scripts/task-coach.py" update 3 --status cancelled
python3 "<skill_dir>/scripts/task-coach.py" done 3
python3 "<skill_dir>/scripts/task-coach.py" snooze 3 2031-04-12T09:00:00+02:00
python3 "<skill_dir>/scripts/task-coach.py" export        # JSON backup
```

Neither `init` nor `setup` schedules or sends anything. `add` prints the new task
ID; commands print JSON so tools can read them. For prompts use
`setup --interactive` on a fresh directory, or `setup --update --interactive` to
edit saved settings; blank answers keep current values.

- **Priority** is `low`, `normal`, or `high`.
- **Status** is `open`, `done`, or `cancelled`.
- **Due** accepts a date (`2031-04-05`) or a timestamp with an offset.
- **Snooze** requires a timestamp with an offset and does not change the due date.
- **Notes** are plain text; checkbox lines are yours to maintain by hand.
- `done` is idempotent and keeps history.

### Check-in days

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Garden" --check-in-days weekends
python3 "<skill_dir>/scripts/task-coach.py" update 4 --check-in-days weekdays
```

`all` means every day your global window already allows. `add`, a changed
`update --check-in-days`, reopening with `update --status open`, and a
`setup --update --weekdays` change print a non-blocking warning on stderr when a
task can never meet the global days. `list` and `show` always report what was
saved.

### Recurring commands

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Replace filter" \
  --repeat "3 months" --due 2026-01-31
python3 "<skill_dir>/scripts/task-coach.py" show 5        # read cycle_id
python3 "<skill_dir>/scripts/task-coach.py" done 5 \
  --completed-at 2026-10-31 \
  --expected-cycle CYCLE_ID_FROM_SHOW \
  --completion-id UNIQUE_REQUEST_ID
python3 "<skill_dir>/scripts/task-coach.py" update 5 --repeat "2 weeks"
python3 "<skill_dir>/scripts/task-coach.py" update 5 --remove-repeat
```

Intervals are 1 to 9999 days, weeks, or months. A recurring task refuses a plain
`done ID`: it needs `--completed-at`, the current `--expected-cycle` and a unique
`--completion-id`, which together prevent an accidental or duplicated completion.
Reuse the same values when retrying. Removing recurrence neither completes nor
cancels the task.

### Smart Snooze commands

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --enable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --disable
```

### Setup flags and defaults

`setup --update` is required to change saved settings. Without it, a different
value is refused rather than silently overwritten.

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
same-day window. Overnight windows are not supported, and preferences alone never
trigger a message.

### Data directory and schema

With `HERMES_HOME` set, data lives in `$HERMES_HOME/task-coach`; otherwise
`$XDG_DATA_HOME/task-coach` or `~/.local/share/task-coach`. Pass `--data-dir PATH`
before the subcommand and use the same path every time.

```
task-coach/
├── config.json        saved preferences
├── tasks.sqlite3      tasks, schema version 2
├── coach.sqlite3      coaching episodes and engine state
└── outbox.sqlite3     send journal and delivery receipts
```

Only `init` and `setup` create the store; other commands refuse a missing or
uninitialized directory. Both apply directory mode `0700` and file mode `0600`, and
other commands refuse unsafe modes or symlinked and hardlinked storage.

Tasks use **schema version 2**. Version 1.0 is a base install: no migration from
earlier releases and no upgrade command. A fresh `init` creates version 2 directly.

### Native cron wiring and pause

When enabled, a Hermes cron job runs a preflight wrapper every minute. That is a
check, not a message cadence: a quiet `wakeAgent: false` wakes nobody, and a due
result wakes an agent to compose and validate one check-in through `hermes send`.
The daily plan picks up to your maximum number of tasks with bounded follow-ups,
sequences never overlap, and missed opportunities are not caught up.

The job is installed paused; activation is a separate approval. Pausing cron is
separate from the engine's global pause:

```sh
python3 "<skill_dir>/scripts/task-coach.py" coach pause
python3 "<skill_dir>/scripts/task-coach.py" coach resume
python3 "<skill_dir>/scripts/task-coach.py" coach status
```

`coach resume` clears the global pause but does not revive a stopped day or unpause
cron.

### Troubleshooting

- **"store is not initialized"** — run `init` or `setup`, and check that
  `--data-dir` is the same path every time.
- **"configuration exists; use setup --update"** — add `--update` deliberately.
- **"unsafe storage permissions"** — re-run `init` or `setup` to repair modes.
- **A task never gets check-ins** — its days may not overlap the global window;
  widen it with `setup --update --weekdays` or set `update ID --check-in-days all`.
- **No messages arrive** — check the cron job exists and is unpaused, a route was
  configured, and global pause is off.
- **Fewer check-ins than the maximum** — the budget is a ceiling, not a quota.
- **Check-ins in the TUI** — the TUI is a working surface, not a notification
  target; reply in the configured chat.

Every refusal is deliberate. Do not edit or delete databases to work around a
safety check; fix the input or storage state instead.

### Reset

Only for a genuinely fresh start, never to bypass a refusal.

1. Stop every writer: conversations, manual commands and background workers.
2. Pause the Task Coach cron job and read it back. Leave unrelated jobs alone.
3. Inventory the data directory without following symlinks, and decide on a backup.
4. Remove only `config.json`, `tasks.sqlite3`, `coach.sqlite3` and
   `outbox.sqlite3`. Never run an unrestricted recursive delete over a directory
   you have not inspected.
5. Confirm the directory is empty or gone and the installed skill is intact.
6. Run `init` and `setup` again. Check-ins stay paused until you approve activation.

## License

MIT. See [LICENSE](LICENSE).
