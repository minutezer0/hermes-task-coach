# Hermes Task Coach

A local task manager and conversational coach for Hermes Agent. Capture a task,
choose a small next step, and work through blockers in an ordinary conversation.
No messaging account is needed. Optional automatic check-ins currently support
**already-configured Discord connections only**.

## Completion-based recurring tasks (0.1.0rc4)

Say “replace the filter every three months.” Hermes asks when it was last actually
completed or when it should first become due, confirms relative answers such as
“last Saturday” as a concrete local date, and asks if the date is uncertain.
Only explicit completion advances this task: ordinary replies, dismissals and
snoozes do not. The same row stays overdue indefinitely until completed; no missed
occurrences or backlog are generated. Completion clears snooze, leaves the task
open and computes the next due from actual completion (three calendar months,
not 90 days). Due restores randomized check-in eligibility, not an exact-date send.
The existing shared distinct-task/follow-up notification budget is unchanged.

The bundled JSON CLI supports:

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Replace filter" --repeat "3 months" --due 2024-01-31
python3 "<skill_dir>/scripts/task-coach.py" show ID
python3 "<skill_dir>/scripts/task-coach.py" done ID --completed-at 2024-01-31 --expected-cycle CAPTURED_CYCLE --completion-id UNIQUE_REQUEST_ID
python3 "<skill_dir>/scripts/task-coach.py" update ID --repeat "2 weeks"
python3 "<skill_dir>/scripts/task-coach.py" update ID --remove-repeat
```

Replace placeholders with the returned ID and `cycle_id`. Capture a cycle and one
unique completion request ID **before** completion and reuse the same values and
actual date on retry; never fetch a new cycle to replay an old request. Concurrent
requests cannot advance the same cycle twice. The latest identical request is a
no-op after restart; older/conflicting cycles refuse. Plain `done ID` is unchanged
for ordinary tasks, but refuses for recurring tasks. Status edits cannot bypass
the recurring completion guard. Recurrence edits/removal preserve unrelated fields,
current due/status and snooze; removal does not complete or cancel the task.

Intervals are positive day/week/month counts (1..9999), with an explicit initial
due date/timestamp. A supplied last-completion date is used to derive and confirm
that first due before adding, not recorded as a fake new completion. Date-only due
values gate eligibility by date in the configured IANA timezone; timestamps gate
by instant. Arithmetic uses local calendar days/weeks/months, clamping month ends
(January 31 + three months = April 30; leap years respected). Timestamp completions
preserve local wall time with the target date's offset; DST gaps roll forward by
the gap and folds choose the first occurrence. Date-only completion stays date-only.
Naive timestamps, malformed and future completion values refuse.

Existing unversioned task stores are readable without migration. Before enabling
recurrence, obtain approval, stop old-version writers, and explicitly run
`python3 "<skill_dir>/scripts/task-coach.py" migrate` in the approved data scope.
The exact repository legacy nine-column task schema (`user_version=0`) upgrades
transactionally to version 1 by appending nullable interval/cycle/last-request
fields. IDs, contents, configuration and separate engine/runtime/receipt/audit
stores are preserved. Reads never migrate; malformed data, incompatible DDL or
unknown versions refuse without resetting state. Fresh stores use version 1.
Use only the new helper after migration. See the
[skill's recurrence protocol](skills/task-coach/SKILL.md#completion-based-recurring-tasks)
for full retry, snapshot and stale clarification behavior.

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
check-in preferences, using everyday language. The default is up to **3 distinct
tasks per configured window**. Hermes shows that default (or your saved maximum)
and asks whether to keep it or customize it, separately from follow-up settings.
It presents one understandable
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
message; the runtime does not promise atomic cancellation. Current Discord history
captures omit reply references. Delayed replies can be attributed to an earlier
task with trusted inbound target metadata (see the runtime guide's optional
CLI flags and `reply_targets` envelope), or a later explicit owner clarification.
Without a clear target, eligible multi-task replies temporarily hold automated
sends and ask which task **by title in normal conversation**, before changing task
data or engaging any candidate. Bounded clarification retries reuse the configured
unanswered-follow-up budget and randomized min/max spacing in the current window.
They ask using candidate titles through the same native draft/history/dispatch/
positive-receipt protocol, never a detached reminder. Slots and counts survive
restart; missed retries and missed task sends never catch up. When unanswered, the
hold lasts until the next allowed notification window, then pending questions are
retired with audit retained and tasks, engagement, completion and snoozes unchanged.
Timezone, allowed weekdays and DST determine that window—not midnight. A zero
follow-up budget means no automatic retries. Resolving/resolved selections and
pause, failure, uncertain-delivery and other safety blocks are never cleared by
retirement; clock/configuration/route changes fail closed. A reply to a retry
receipt returns to its question, never automatic task engagement. Shared answers
remain unassigned until an explicit selection/dismissal binds the intended question
atomically; the same reply cannot then be reused for another hold. Unresolved engine
claims/failures block retry sends and retirement even without an outbox sending row. The guarded `runtime resolve-clarification` command
binds the original reply and explicit owner selection to immutable candidate snapshots;
it releases only that ambiguity hold, never other delivery protections or missed
sends. Selection is not manufactured Discord reply metadata. “Never mind” or
“dismiss that question” instead uses guarded `runtime dismiss-clarification`:
the skill binds explicit dismissal to the exact pending question and a fresh
captured later owner message. Neither task is selected, edited or engaged. The
original may be edited/deleted and candidates changed/unavailable; their audit
snapshots and delivery receipts stay immutable. Only that hold is released, future
slots remain eligible and missed sends never catch up. “Cancel” alone prompts a
question: dismiss the clarification, cancel a named task, or pause all check-ins?
Wrong bindings, stale/missing captures and missing receipt anchors refuse safely.
A durable resolving/resolved selection cannot be undone by dismissal because its
suppression may already have committed; retry only the same guarded resolution.
Existing windows permanently blocked by older code are not revived. Explicit replies to unrelated
messages do not engage coaching. See [the end-to-end clarification flow](skills/task-coach/references/native-runtime.md#clarification-before-mutation).

## Minute tick is not message cadence

When enabled, the native job checks the local preflight wrapper every minute.
A quiet `wakeAgent:false` result suppresses the agent turn; it is not an AI call
or a message every minute. A due result wakes an agent to compose and validate a
check-in. The randomized daily plan selects up to the configured maximum of
distinct tasks, with one opener and bounded unanswered follow-ups per task.
Replying stops follow-ups for that task; later task check-ins remain scheduled.
Task sequences do not overlap, with at least 30 minutes between their opportunities
(or the saved minimum follow-up interval if larger). Too few eligible tasks or
too little window space produces fewer check-ins, not repeats to fill a quota.
Uncertain delivery or unverifiable history conservatively blocks later sends. Sends
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

Default preferences are UTC, Monday–Friday, 09:00–17:00, up to 3 distinct tasks,
up to two unanswered follow-ups per task, and 30–120 minute follow-up intervals.
Set `--max-tasks-per-window` to an integer from 1 through 10. Saved configurations
from before this setting retain a maximum of 1 until you explicitly change it
with `setup --update --max-tasks-per-window 3`. Local-only setup leaves unused notification defaults
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
