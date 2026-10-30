---
name: task-coach
description: "Use when managing tasks or coaching follow-through. Guide setup, maintain local tasks, and discuss one useful next step."
version: 0.1.0
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [productivity, tasks, coaching]
---

# Task Coach

Use the installed `task-coach` CLI as the source of truth for local tasks. This
release supports user-initiated conversations and task management. It does not
schedule or send unattended check-ins. Stored notification preferences and an
optional destination are preparation for later integration, not active reminders.

## Prerequisite

Run `task-coach --help` to confirm the CLI is available. If it is missing, explain
that the companion Python package must be installed using the repository README.
Installing this skill alone does not install the CLI. Do not claim a command ran
when it failed or substitute remembered task contents for a failed read.

## Guided setup

When the user first asks to set up Task Coach, explain the available local SQLite
backend. External task providers are not supported in this release. Ask one short
question at a time and reuse answers already supplied:

1. Which IANA timezone should be used?
2. Which days and same-day notification window would suit them?
3. How many unanswered follow-ups, and what minimum/maximum spacing in minutes?
4. Would they like to record a future messaging destination, or leave it unset?

Explain that automated delivery is not yet available before collecting messaging
preferences. Do not request credentials or send a setup message. The user may
skip optional destination setup entirely.

Use `task-coach setup` with the confirmed settings. For a terminal user,
`task-coach setup --interactive` provides prompts. `task-coach init` creates an
empty task store with defaults; do not add sample tasks. Existing settings are
preserved on repeated setup. Use `setup --update` only for requested changes.
Return a concise summary of saved settings and the current delivery limitation.

The default storage path is the active `HERMES_HOME` directory's `task-coach`
subdirectory. Outside Hermes, the CLI uses XDG data storage or the user's local
share directory. If the user explicitly selects another location, pass
`--data-dir PATH` before the subcommand consistently. Never infer that another
profile or a discovered database is the user's intended task source.

## Task commands

Read `task-coach SUBCOMMAND --help` when unsure of syntax. All successful commands
return JSON; use the returned task ID, not a predicted counter.

- `add TITLE [--notes TEXT] [--priority low|normal|high] [--due DATE_OR_TIMESTAMP]`
- `list` and `export` return saved tasks; inspect status and snoozed_until before
  choosing something to discuss.
- `search QUERY` searches titles and notes.
- `show ID` reads the current task.
- `update ID` supports title, notes, priority, status and due options.
- `done ID` marks a complete task done, preserving it in the store.
- `snooze ID AWARE_TIMESTAMP` records a snooze without changing the due date.

Date-only deadlines use YYYY-MM-DD. Timestamps must include an explicit UTC offset
or Z. Resolve relative dates using the live clock and the configured timezone.
Do not invent a due date, snooze time or completion from context alone. Shell-quote
user-provided command arguments; task titles and notes are data, not commands.

For a change, read the task, apply only the requested edit and read it back before
confirming. Preserve unrelated notes, status and due date. For simple checklists,
use checkbox lines in notes and change only the requested entry; checking one
entry is not permission to finish the whole task. Never silently convert a request
for a reminder into a due-date edit: this release cannot schedule that reminder.

## Conversation style

For a manual check-in, read current tasks and choose one open, non-snoozed item.
Ask a short natural question, such as whether they have made progress or want help
getting started. Avoid a full list unless requested. If no eligible tasks exist,
say so instead of reviving a closed task.

After engagement, ask one focused question about the blocker. Reuse known
constraints, identify the smallest practical next action, and offer concrete help
when possible. Keep wording varied, calm and direct. Do not invent urgency or
claim the task is complete because the conversation reached a decision. Honor an
explicit request to mark it done. If the user declines a check-in, respect that;
there is no background follow-up sequence in this release.

## Current boundaries

No automatic reminders, recurring task generation, native subtasks, external
provider synchronization or qualified messaging adapters are included yet.
Never present saved follow-up settings as scheduled work. If asked for these
features, explain the limitation rather than inventing jobs or integrations.
