# Hermes Task Coach

A local task manager and conversational coach for Hermes Agent. Capture a task,
choose a small next step, and work through blockers in an ordinary conversation.
No messaging account is needed. Optional automatic check-ins currently support
**already-configured Discord connections only**.

## Install

Requires Python 3.11+ with SQLite and timezone data. Linux is the qualified platform;
there are no third-party runtime dependencies.

```sh
hermes skills install minutezer0/hermes-task-coach/skills/task-coach
```

## Start here

Open a Hermes conversation after installing and ask Hermes to set up Task Coach.
Installing the skill does not itself launch a chat. Say:

> Help me set up Task Coach. Ask one question at a time and reuse my saved settings.

Hermes first asks whether you want **local conversational tasks** or **optional
Discord check-ins**. Local setup does not ask about notification schedules, install
jobs, or send messages. Tell Hermes a task in your own words, then work on it
together. Tasks are never marked complete just because you replied.

For Discord, Hermes confirms your existing destination and asks only for missing
check-in preferences, using everyday language. It presents one understandable
approval for installing a **paused schedule and a narrowly scoped reply-handling
instruction**. This is not permission to send or activate ongoing check-ins.

A **separately authorized one-check-in test** can be prepared immediately within
your allowed day/window on a fresh setup. It does not require waiting for a random
slot or enabling the recurring job. It refuses any existing daily episode or
nonempty send journal—even an untouched active plan—rather than resetting safety
records. Prepare it before running the first preflight. A stopped empty episode
may instead qualify for the limited restart described below; restart is not an
immediate test. If refused, Hermes explains the limit, not a workaround.

The test uses the ordinary guarded send and exact history readback. Hermes checks
that your reply continues the right task and is recognized as engagement. A
single-message test has no follow-up to cancel: it does **not** prove live
follow-up suppression under a recurring schedule. Neither saving settings nor
passing automated tests proves live delivery. Ongoing activation needs its own
approval after the verification checkpoint.

Setup ends with a short conversational explanation of what's ready and what to
expect next—not a dashboard. If only local tasks are ready, no automatic message
is promised. A test alone leaves the ongoing schedule paused. Everyday coaching
stays focused on the task, without task IDs or test bookkeeping unless requested.

After separately authorized ongoing activation, Hermes verifies the active
schedule, an eligible task and a supported upcoming allowed opportunity before
saying: **“Task Coach setup complete—you’ll be hearing from me soon!”** If today's
episode is stopped, it explains that check-ins start on the next allowed day,
rather than promising another send today. Paused installations say check-ins are
paused. No five-minute test follow-up or follow-up pilot is required to finish
onboarding; the optional one-check-in test and disclosure of remaining live
follow-up suppression limits are sufficient before separate ongoing approval.

<details>
<summary>Advanced setup, terminal commands, storage and troubleshooting</summary>

## Runtime and permissions

The runtime is bundled in the skill; no separate pip install or PATH change is
needed. Use the actual installed skill directory reported by Hermes. Task data
lives outside it and survives skill replacement. Only local tasks are configured
by ordinary setup; no messaging accounts are provisioned.

For exact route confirmation, installing the wrapper and paused cron plus scoped
inbound instruction, the explicit test protocol and ongoing activation, read the
[native runtime guide](skills/task-coach/references/native-runtime.md).
The [engine contract](skills/task-coach/references/coaching.md) describes scheduling
and state behavior. Generated artifacts do not install themselves. Confirm all
installed artifacts by readback; do not replace existing instructions.

Interactive coaching works in the Hermes TUI or a connected chat. The TUI is not
an automatic notification destination. Reply in the configured Discord conversation
to stop Discord follow-ups; replies in a different TUI session are not detected.
A reply arriving during an already-authorized network send can race with that
message; the runtime does not promise atomic cancellation.

## Minute tick is not message cadence

When enabled, the native job checks the local preflight wrapper every minute.
A quiet `wakeAgent:false` result suppresses the agent turn; it is not an AI call
or a message every minute. A due result wakes an agent to compose and validate a
check-in. The randomized daily plan allows one opener plus up to the configured
number of unanswered follow-ups, within allowed days/window and spacing. Sends
still require authorization and, for follow-ups, fresh complete Discord history.
Missed opportunities are not caught up; failures can suppress a message entirely.
The native runtime's opportunity is up to ten minutes, capped at window end.

## Pause, resume and limited same-day restart

Ask Hermes to pause coaching explicitly; `coach pause` persists a global pause.
`coach resume` clears that pause but never revives a stopped daily episode. Native
cron pause is separate: neither resume nor restart activates a paused cron job.
Changing tasks or preferences alone also does not restart today's stopped plan.

For the narrow first-setup case where preflight ran with no eligible task and
left today's episode stopped **without any events**, a supported command is:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime restart --confirm-restart
```

Use the actual installed `<skill_dir>` and the same approved data scope. Suggested
recovery request:

> Inspect Task Coach's current episode and outbox. If today's already-stopped
> episode has zero prior events and the entire outbox is empty, I authorize the
> supported runtime restart --confirm-restart command. Keep native cron paused;
> do not send. Preserve my tasks, preferences, route and safety records. If any
> safety check refuses, explain it; do not edit or delete databases to work around it.

Restart uses the real production clock, rereads current tasks/preferences, and
plans strictly future slots in today's configured window. It refuses global
pause, unconfirmed/invalid or changed binding, another day's episode, active
plans, clock regression, **any prior event (even unclaimed)**, and **any outbox
row (even an old draft or confirmed receipt)**. It also refuses if no eligible
task or future slots remain. A second restart of the active plan is refused.
It never sends, enables cron, clears pause or retries an attempt. Broader
restarts are deliberately unsupported; keep safety journals intact.

## Use the helper directly (optional)

Replace `<skill_dir>` with the actual installed directory reported by Hermes.
Quote the path, including when it contains spaces. Run from any working directory:

```sh
python3 "<skill_dir>/scripts/task-coach.py" --help
python3 "<skill_dir>/scripts/task-coach.py" setup --interactive
python3 "<skill_dir>/scripts/task-coach.py" add 'Example task' --notes 'Choose a small next step'
python3 "<skill_dir>/scripts/task-coach.py" list
python3 "<skill_dir>/scripts/task-coach.py" show 1
python3 "<skill_dir>/scripts/task-coach.py" done 1
```

The ID assumes a new empty store; use the ID returned by `add` otherwise.
Commands return JSON for tools; Hermes translates results into conversation.
Interactive terminal setup asks local or Discord preferences first, never asks for
an opaque destination, and never configures a connection. In chat, Hermes collects
answers and uses flags, not terminal stdin.

`init` creates an empty store with defaults. `setup` validates and saves settings;
repeat setup preserves tasks and configuration. Use `setup --update` for deliberate
changes. `setup --update --interactive` displays saved values; blank keeps them.
Legacy `--destination` stores a preference only and does not configure delivery.

Default preferences are UTC, Monday–Friday, 09:00–17:00, two unanswered follow-ups
and 30–120 minute intervals. Local-only setup leaves unused notification defaults
alone. Preferences do not trigger messages. Overnight windows are unsupported.

## Storage and task fields

With `HERMES_HOME`, data lives in its `task-coach` subdirectory. Otherwise it uses
`$XDG_DATA_HOME/task-coach` or `~/.local/share/task-coach`. Put an explicit
`--data-dir PATH` before the subcommand and use it consistently. Only `init` and
`setup` initialize task storage. No imports or migrations happen automatically.

- Priority: `low`, `normal` or `high`; status: `open`, `done` or `cancelled`.
- Due: `2031-04-05` or an aware timestamp such as `2031-04-05T12:00:00+02:00`.
- Snooze: an aware timestamp; it does not change the due date.
- Notes: plain text; checkbox lines can be maintained manually.
- `export` writes all tasks as JSON; `done` is idempotent and preserves history.
- Recurring tasks, native subtasks and external task providers are not implemented.

## Standalone CLI and development

The skill does not need a package installation. For a standalone checkout command:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/task-coach --help
```

The console entry point is `task_coach.cli:main`. The canonical runtime is
`skills/task-coach/scripts/task_coach`; there is no separate source copy. Wheels
include the complete skill under `share/task-coach/skill`.

```sh
python3 skills/task-coach/scripts/task-coach.py --help
python3 -B -m unittest discover -s tests -v
```

Runtime and copied-skill tests need only the standard library. The wheel artifact
test requires `setuptools>=68` and venv/pip support; it is skipped if unavailable.
It builds and installs offline into temporary storage, then runs the console
entry point and a relocated skill helper. Tests use fictional stores/transports;
they are not live Discord verification.

</details>

## License

MIT. See [LICENSE](LICENSE).
