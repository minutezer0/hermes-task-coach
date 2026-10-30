# Hermes Task Coach

A local task manager and conversational coaching skill for Hermes Agent.

## Available now

- An installable `task-coach` command and JSON output for agent workflows.
- Empty SQLite task storage, persistent task IDs, notes, priorities and deadlines.
- Add, list, search, show, update, complete, snooze and export commands.
- Guided terminal setup and a Hermes skill for conversational setup and coaching.
- Saved timezone, weekdays, notification window and follow-up preferences.

This is an early local-only release. Automated check-ins are **not enabled or
implemented**. Saving a destination or follow-up settings does not schedule
messages. Recurring tasks, native subtasks and external task-provider integrations
are not included yet. Platform-independent delivery remains a planned feature.

## Requirements

Python 3.11 or newer with SQLite and IANA timezone data. Initial validation is on
Linux; other operating systems have not been qualified. There are no third-party
runtime Python dependencies.

## Install from a checkout

Run these commands from a checkout containing this version:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/task-coach --help
```

Activate that environment or add its `bin` directory to the PATH used by Hermes
so that `task-coach` is available to the agent. The CLI can be used on its own.
For development without installation, use `PYTHONPATH=src python3 -m task_coach`.

To add the Hermes skill, copy `skills/task-coach` into the intended active
profile's `skills` directory. The main file is `skills/task-coach/SKILL.md`.
Installing the skill does not install the companion command; both are needed for
the Hermes workflow. No gateway configuration or scheduled jobs are created.

## Get started

```sh
task-coach setup --interactive
task-coach add 'Example task' --notes 'Choose a small next step'
task-coach list
task-coach show 1
task-coach done 1
```

The ID above assumes a newly initialized empty store. Use the ID returned by
`add` when working with an existing store. Commands return JSON. A task remains
stored after completion; inspect its status in `list` or `export`.

`init` creates an empty store with defaults. `setup` validates and saves settings;
repeat setup preserves tasks and configuration. Use `setup --update` to change
existing settings deliberately. For example:

```sh
task-coach setup --update --timezone UTC --weekdays mon,wed,fri
task-coach setup --help
```

Default preferences are UTC, Monday through Friday, 09:00–17:00, two unanswered
follow-ups and 30–120 minute intervals. Preferences are stored but do not trigger
reminders in this release. Overnight notification windows are not supported.

## Storage and task fields

When `HERMES_HOME` is set, data lives in its `task-coach` subdirectory. Otherwise
the CLI uses `$XDG_DATA_HOME/task-coach` or `~/.local/share/task-coach`.
An explicit override goes before the subcommand:

```sh
task-coach --data-dir ./example-data init
task-coach --data-dir ./example-data add 'Example task'
```

Only `init` and `setup` initialize a store. Other commands report an error if it
has not been initialized. Storage is not automatically imported from other tools.

- Priority: `low`, `normal` or `high`.
- Status: `open`, `done` or `cancelled`.
- Due: a date such as `2031-04-05`, or a timestamp with offset such as
  `2031-04-05T12:00:00+02:00`.
- Snooze: a timestamp with an explicit offset; it does not change the due date.
- Notes: plain text; checkbox lines may be maintained manually.

Use `task-coach COMMAND --help` for each command's options. `export` writes all
tasks as JSON to stdout. `done` is idempotent; repeating it does not create a new
task or change an already completed task's timestamp.

## Use with Hermes

Ask Hermes to set up Task Coach, capture a task, review one task with you or help
work through a blocker. The skill uses the CLI's current task records instead of
conversation history. It starts with one short question and follows your answer,
rather than presenting the entire list by default.

Requests for automatic reminders require a future delivery integration. This
release does not create cron jobs or silently fall back to another messenger.

## Development

```sh
python3 -B -m unittest discover -s tests -v
```

## License

MIT. See [LICENSE](LICENSE).
