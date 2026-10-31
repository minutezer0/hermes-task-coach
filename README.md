# Hermes Task Coach

A local task manager and conversational coaching skill for Hermes Agent.

## Available now

- An installable `task-coach` command and JSON output for agent workflows.
- Empty SQLite task storage, persistent task IDs, notes, priorities and deadlines.
- Add, list, search, show, update, complete, snooze and export commands.
- Guided terminal setup and a Hermes skill for conversational setup and coaching.
- Saved timezone, weekdays, notification window and follow-up preferences.
- Randomized daily check-in plans, deadline/priority-weighted task selection and bounded follow-ups.
- An optional native-Hermes runtime with durable send tracking and owner-reply suppression.

Installing the skill or saving preferences does not enable messages. Proactive
coaching requires explicit setup using an already-configured Hermes messaging
destination. The first implemented history adapter is Discord; other messaging
platforms are not supported for automatic check-ins yet. Local task management
does not require a messaging account. Recurring tasks, native subtasks and external
task-provider integrations are not included yet.

## Requirements

Python 3.11 or newer with SQLite and IANA timezone data. Initial validation is on
Linux; other operating systems have not been qualified. There are no third-party
runtime Python dependencies.

## Install the Hermes skill

```sh
hermes skills install minutezer0/hermes-task-coach/skills/task-coach
```

Then open or resume a Hermes conversation and ask Hermes to set up Task Coach.
Installing a skill does not itself launch a chat. Hermes checks the bundled helper,
asks focused questions about your preferences, and saves them using setup flags.
No separate pip install, PATH changes, or manual runtime copying is required for
this skill. Installation alone creates no gateway configuration or scheduled jobs.
If you request proactive coaching, Hermes guides the separate, confirmed setup.

The entire runtime ships inside `skills/task-coach`. Hermes uses the installed
`skill_dir` reported when loading the skill, not a checkout or a global command.
The skill and its runtime can be relocated or reinstalled without moving task
data: settings and tasks are stored outside the skill directory by default.

## Use the helper directly (optional)

Replace `<skill_dir>` below with the actual installed directory reported by
Hermes. Quote the path, including when it contains spaces. You can run the helper
from any working directory:

```sh
python3 "<skill_dir>/scripts/task-coach.py" --help
python3 "<skill_dir>/scripts/task-coach.py" setup --interactive
python3 "<skill_dir>/scripts/task-coach.py" add 'Example task' --notes 'Choose a small next step'
python3 "<skill_dir>/scripts/task-coach.py" list
python3 "<skill_dir>/scripts/task-coach.py" show 1
python3 "<skill_dir>/scripts/task-coach.py" done 1
```

Interactive setup is optional for terminal use. In chat, Hermes collects your
answers and runs non-interactive `setup` with flags instead of waiting for stdin.

The ID above assumes a newly initialized empty store. Use the ID returned by
`add` when working with an existing store. Commands return JSON. A task remains
stored after completion; inspect its status in `list` or `export`.

`init` creates an empty store with defaults. `setup` validates and saves settings;
repeat setup preserves tasks and configuration. Use `setup --update` to change
existing settings deliberately. For example:

```sh
python3 "<skill_dir>/scripts/task-coach.py" setup --update --timezone UTC --weekdays mon,wed,fri
python3 "<skill_dir>/scripts/task-coach.py" setup --help
```

Default preferences are UTC, Monday through Friday, 09:00–17:00, two unanswered
follow-ups and 30–120 minute intervals. Preferences alone do not trigger reminders;
the optional runtime must be configured separately. Overnight notification windows
are not supported.

## Storage and task fields

When `HERMES_HOME` is set, data lives in its `task-coach` subdirectory. Otherwise
the CLI uses `$XDG_DATA_HOME/task-coach` or `~/.local/share/task-coach`.
An explicit override goes before the subcommand:

```sh
python3 "<skill_dir>/scripts/task-coach.py" --data-dir ./example-data init
python3 "<skill_dir>/scripts/task-coach.py" --data-dir ./example-data add 'Example task'
```

Only `init` and `setup` initialize a store. Other commands report an error if it
has not been initialized. Storage is not automatically imported from other tools.

- Priority: `low`, `normal` or `high`.
- Status: `open`, `done` or `cancelled`.
- Due: a date such as `2031-04-05`, or a timestamp with offset such as
  `2031-04-05T12:00:00+02:00`.
- Snooze: a timestamp with an explicit offset; it does not change the due date.
- Notes: plain text; checkbox lines may be maintained manually.

Use `python3 "<skill_dir>/scripts/task-coach.py" COMMAND --help` for options.
`export` writes all
tasks as JSON to stdout. `done` is idempotent; repeating it does not create a new
task or change an already completed task's timestamp.

## Use with Hermes

Ask Hermes to set up Task Coach, capture a task, review one task with you or help
work through a blocker. The skill uses the CLI's current task records instead of
conversation history. It starts with one short question and follows your answer,
rather than presenting the entire list by default.

For automatic check-ins, ask Hermes to configure the optional native runtime.
It uses Hermes cron, composes short questions through the agent, sends through
the existing Hermes connection, and checks owner activity before follow-ups.
Setup produces an initially paused job and a scoped normal-conversation
instruction for your approval; it does not connect messaging accounts or silently
fall back to another messenger. If messaging is not configured, use Hermes's own
messaging setup first, or continue using Task Coach locally.

See the [native runtime guide](skills/task-coach/references/native-runtime.md)
for setup and operation, and the [engine contract](skills/task-coach/references/coaching.md)
for scheduling and state behavior. Automated tests use fictional messaging
fixtures, not live platform qualification. Keep a new job paused until a test in
your chosen conversation verifies delivery, reply suppression and contextual
continuation. A reply arriving during an already-authorized network send can race
with that message; the runtime does not promise atomic cancellation.

## Standalone CLI from a checkout (optional)

The Hermes skill does not need this installation. For a standalone console command,
run from a checkout:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/task-coach --help
.venv/bin/task-coach setup --interactive
```

The optional `task-coach` console entry point is `task_coach.cli:main`, defined
in `pyproject.toml`. It uses the Python interpreter that installed the package
(for example, the virtual environment's interpreter), while the skill invokes
`python3` explicitly. Both use the same canonical runtime in
`skills/task-coach/scripts/task_coach`; there is no separate source copy.
Wheels also include the complete skill under `share/task-coach/skill` in the
installation prefix.

## Development

Run directly from a checkout without installing a package:

```sh
python3 skills/task-coach/scripts/task-coach.py --help
python3 -B -m unittest discover -s tests -v
```

The runtime and copied-skill tests need only the Python standard library.
The separate wheel artifact test requires the build dependency `setuptools>=68`
and Python's `venv`/pip support; it is skipped when setuptools is unavailable.
It builds and installs a wheel offline into temporary storage, then exercises
both its console entry point and its independently copied skill helper.

## License

MIT. See [LICENSE](LICENSE).
