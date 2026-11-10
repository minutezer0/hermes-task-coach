# Hermes Task Coach

A local task manager and conversational coach for Hermes Agent. Capture a task,
choose a small next step, and work through blockers in an ordinary conversation.
No messaging account is needed. Optional automatic check-ins currently support
**already-configured Discord connections only**.

## Task check-in days (0.1.0rc9)

New setups default to every day, 09:00–17:00; existing saved days stay unchanged.
Each task supports **weekdays / weekends / all** for both initial check-ins and
follow-ups. Task days always stay within your global allowed days and hours,
using your configured timezone. `all` means all days your global window permits.

When your global window includes all seven days, Task Coach asks for the task’s
check-in days when adding it (default: `all`). With any narrower window, it skips
that question and defaults new tasks to `all`, including granular windows such
as Mon/Wed/Sat. Explicit task preferences remain saved when you change the global
window. Overdue dates do not override day preferences. You can reply and continue
working on a task on any day, even outside its check-in days or hours.

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Garden" --check-in-days weekends
python3 "<skill_dir>/scripts/task-coach.py" update ID --check-in-days weekdays
```

Older tasks read as `all` without changing storage. To use non-`all` preferences
on an existing store, stop older writers and explicitly run `migrate` with user
approval. Exact task schemas 0 and 1 upgrade transactionally to version 2,
preserving task IDs, recurrence cycles, saved settings and notification audits.
Fresh stores use version 2. Do not run older helpers after migration. No live
installation, schedule refresh or activation happens just by updating the source.

## Guided setup (0.1.0rc8)

The setup wizard now guides Proactive Mode through preferences, one task, schedule
installation, an optional test (default No), and a final settings review before
activation. New stores default to up to 2 distinct tasks per window; existing
saved limits are preserved.

## Smart Snooze (0.1.0rc7)

Smart Snooze is a **hold-only notification preference**, default OFF on fresh and
all known older runtimes missing the field. With it ON, a genuine explicit
“start working now” reply to a current accepted/delivered check-in or follow-up
records `start-work` and holds **all** Task Coach automated notifications for the
remaining current configured local notification window, including other tasks and
legacy clarification retries. It does not change task status, completion, snooze,
priority/selection weights, global pause, reminders or cron activation.
Generic `engaged`, `skip-for-now`, completion and ordinary replies never create a
hold; historical engagement is never reinterpreted as start-work.

Use the actual installed helper and approved active-profile data scope:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --enable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --disable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
```

During conversational **check-in** setup, separately ask: “Smart Snooze is off by
default. If you explicitly start working after a check-in, should I hold all Task
Coach check-ins until your current notification window ends?” Reuse and present
the actual saved `runtime smart-snooze` value on resumed setup, rather than
re-interviewing. Persist only the explicit choice and read back. Never ask this
question for local-only task setup. This choice alone never activates cron.

Record clear engagement **BEFORE substantive assistance, memory recall or
delegation**, using `runtime record-engagement --binding JSON --owner OWNER
--message-id INBOUND_ID --event-token EVENT --task-id TASK [--cycle-id CYCLE]
--intent start-work` only for genuine explicit agreement to begin working now.
Use `engaged` for general engagement and `skip-for-now` for a skip. Bind the genuine
trusted owner/profile/account/chat/thread, inbound message identity and current
task/event/cycle; clarify ambiguous intent or task selection, never fabricate IDs,
reply references or history. Read back before claiming suppression. Normal inbound
needs no Discord history. Completion and task edits need separate explicit intent.

There is one current runtime hold slot, not a hold-history table. Its route,
triggering task/event/message, local day, timezone/config snapshot and absolute
expiry are retained for requested diagnostics. `runtime status` exposes
`notification_policy.active`, reason and hold when a slot exists; `runtime preflight`
returns `wakeAgent:false`, reason `smart-snooze` while active. Do not expose audit
IDs or diagnostic blocks in everyday coaching unless requested or needed to explain
a problem. The existing engagement audit can explain past actions.

Completion, snooze, cancellation or deletion of the focused task does not release
the hold. Disable immediately clears it. Re-enable applies only to future,
unconsumed start-work replies: retrying an old message never recreates, extends or
renews a hold, including messages originally recorded while OFF. No suppressed or
expired events are replayed and stopped sequences never revive; already planned,
future unexpired events may still become eligible after disabling. Expiry is the
current allowed local window end, not a task deadline or a scheduler reset. The
next allowed day is eligible even if cleanup never ran and the task remains open;
ordinary preflight clears/reuses an expired slot. Weekdays and DST follow the
existing real-instant window policy; overnight windows remain unsupported.

The shared directory lock fences planning/claims and the final refreshed-clock
transport check against newly recorded holds. A send already in flight cannot be
recalled. Failed/uncertain attempts remain nonretryable; no claim of stronger
platform delivery, typing/read-receipt or cross-session intent detection is made.
Malformed/unknown runtime state refuses without silently repairing it. The task
SQLite schema and settings are unchanged; the optional runtime fields remain in
schema version 1, separate from episode configuration so toggling never causes a
configuration-changed stop. No network SDK or new history access is introduced.

After an approved code/instruction update, regenerate/review native-plan artifacts
and scoped inbound instructions; previews are side-effect-free and cron stays
initially paused. Continuing conversations may cache old system instructions.
The supported targeted command is
`hermes sessions refresh-prompts --session ID --json`: it preserves conversation
history and queues refresh for the **next turn**, not the already-running turn.
Report queued versus verified adoption separately; do not clear sessions or restart
a shared gateway just to refresh prompts. Updating this guide is not installation,
refresh, live testing or activation approval.

## Discord history consent and bounded on-demand use (rc6)

History is OFF by default for fresh stores and all older stores without a saved
preference. A configured Discord route or an available tool is not consent.
Local task management, accepted delivery and trusted local-first engagement work
without history. Never fetch history in routine cron, even after opt-in.
Only explicitly requested **reply-recovery** or **delivery-verification** may read
history, after checking exact-route saved consent and caller tool availability.
No automatic needs detector or routine scan is implemented.

Read `runtime history-preference` to reuse the actual saved choice when setup
resumes. After confirmed Discord check-in setup, persist an explicit Yes using
`runtime history-preference --enable --route FULL_CONFIRMED_ROUTE_JSON --confirm-history`.
An explicit No/change uses `runtime history-preference --disable`; read back the
preference after either change. Missing preferences already mean No, not approval.
Consent includes the exact owner/profile/account/chat/thread, channel and bot route;
a changed route needs new consent. Disable/re-enable rotates the grant generation.

For each explicitly requested operation, run
`runtime history-plan --purpose reply-recovery|delivery-verification --target DECIMAL_ID --confirm-history`
and save its returned JSON dict in a private plan file. The grant binds the exact
route, generation, purpose and target: fetch only the latest **25 messages, ONE page**,
`before=null`, at most **131072 bytes** total and **8192 bytes** per message.
Never chase old anchors or fetch additional pages. Preserve genuine raw tool
results with trusted metadata and request-start timestamps. Pass
`--history-plan-file PLAN_FILE` with `--pages-file CAPTURE_FILE` to every applicable
history ingress (`observe`, `confirm`, `engagement`, `resolve-clarification`,
`dismiss-clarification`). Do not fabricate captures or reply references. An absent
anchor or insufficient evidence is an optional warning, not permission to expand
the read or block accepted/local-first work; never claim unverified delivery.

The plan represents **caller-asserted explicit user intent**, not cryptographic
proof that the user asked. Helper gates do not sandbox arbitrary external tools.
Review/refresh existing installed instructions and tool allowlists after enabling
or disabling; persisted core denial takes effect immediately. Deny history tools
in routine cron, review normal-inbound access separately, and never auto-provision
an MCP/hosted connector. Capabilities separates saved current-route consent,
caller-reported tool availability and independent delivery evidence; availability
and consent never establish verified delivery.

A preserved legacy episode day retains its existing honest history gates. If
work needs unavailable/unapproved evidence, stop that work and explain the limit;
never automatically read, bypass the gate, revive stopped slots or resend an
uncertain attempt. Local-first begins at the established later-day boundary.
Native-plan is a read-only preview: no adoption, route mutation or installation;
its cron remains initially paused with both delivery targets local.

## Local-first proactive policy (0.1.0rc6)

Fresh runtime stores use local-first policy by default. After a code update,
known existing runtime stores automatically adopt it on first ordinary runtime
use (including `runtime status`), after validating saved config, runtime, route
and engine state. No policy opt-in or second approval is needed. The compatibility
alias `runtime upgrade-local-first` remains idempotent; its old `--confirm-upgrade`
flag is accepted but unnecessary. Help and `runtime native-plan` do not adopt policy.

This changes only runtime policy, not task schema, saved tasks/settings/engine,
installation, cron state or send authorization. Quiesce old writers before updating
code; do not run older helpers afterward. Recurrence still requires explicit task
`migrate` on legacy task databases. Delivery route/setup, artifact installation,
live testing and ongoing activation remain separately explicit: default policy
NEVER means automatic sending. Never send to a real route during update verification.

Local task eligibility, recorded engagement, windows, spacing, budgets and global
pause authorize **both openers and followups**. Native Hermes send remains the only
transport. A positive `success:true` plus nonempty message ID persists `accepted`
delivery with `native-send-response` provenance and advances ordinary work without
history. This means transport acceptance, not independently verified arrival.
Optional `confirm` validates real history and enriches the outbox as `confirmed`;
its failure is a verification warning, not a failed send or a global scheduling lock.
Failed/uncertain attempts remain nonretryable; their task sequence stops, while
unrelated tasks and future days retain their own bounded opportunities. Report
actual failed/uncertain sends with `[CRON_FAILURE]`, never silent success.

The caller checks its native tool inventory/actual attempt and runs
`runtime capabilities --history-availability unknown|unavailable|available`
(with `--history-error TEXT` for failure). Core does not discover external tools:
unknown means not checked, unavailable includes absent/error, and available means
caller-reported availability, not delivery verification. Unknown/unavailable is
visibly degraded and **nonblocking**. Do not wait for history or substitute a hosted
connector when the native tool is absent. No source imports, raw credentials,
alternate APIs or workarounds. Discord history remains an optional boundary
adapter, never a scheduler dependency; no new platform is supported.

For normal inbound, use exact trusted binding/owner/message ID and explicit task
selection with `runtime record-engagement --binding JSON --owner OWNER
--message-id INBOUND_ID --event-token EVENT --task-id TASK [--cycle-id CYCLE]
--intent engaged|skip-for-now`. It needs no history: provenance is honest
`agent-mediated-explicit-intent`, not an invented reply reference. Retry the exact
identity/selection only. A recorded skip stops only that **current** sequence,
without completion/snooze edits. Ambiguity requires a natural clarification before
attribution or task edits, not a global check-in freeze. Existing immutable
clarification audit/outcomes remain; resolving/resolved choices are never undone.
New local-first ambiguity is handled conversationally, without creating automated
clarification holds or retries.
Unknown/unrecorded replies may receive bounded followups: this is an accepted
tradeoff, not an impossible cross-session reply-suppression guarantee.

Compatibility is explicit: existing episodes, IDs, outbox and clarification audits
are retained, not reset/replayed. An existing episode keeps legacy policy for its
whole local day; local-first begins on a later day. No current-day stopped episode
or missed slot is revived. The boundary is the saved episode's local date, not the
command clock; with no episode, adoption applies immediately without creating one.
Already-local-first policy is untouched. Malformed or unknown data refuses before
writing, preserving bytes, mtimes and sidecars rather than repairing it. Old
attempts are never resent; existing receipt and clarification audits stay intact.
Missed slots stop that task sequence; there is no catchup, backlog or budget
expansion. Completion, cancellation, snooze, global pause, authorized route, current
recurrence cycle and atomic write/send fences remain hard controls.

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
transactionally to version 2 by appending nullable interval/cycle/last-request
fields and `check_in_days` with default `all`. IDs, contents, configuration and
separate engine/runtime/receipt/audit stores are preserved. Reads never migrate;
malformed data, incompatible DDL or
unknown versions refuse without resetting state. Exact version 1 stores can also
upgrade, appending `check_in_days` with default `all`. Fresh stores use version 2.
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

Hermes first asks: **“Enable Proactive Mode (currently only supported in Discord)?”**
It explains how check-ins help and that you can manage tasks with Proactive Mode off.
For fresh setup inside a conversation identified as Discord by trusted Hermes
context, Yes is the suggested default; Hermes still asks for your answer. Saved
choices take precedence. Local setup does not ask about notification schedules, install
jobs, or send messages. Tell Hermes a task in your own words, then work on it
together. Tasks are never marked complete just because you replied.

For Proactive Mode, Hermes guides you through preferences, a real task, schedule
installation, an optional test, and a separate approval to turn on regular check-ins.
Setup asks for only one task, regardless of the daily maximum, and reuses a task
you already supplied. If it is not eligible yet, Hermes explains that check-ins
will wait rather than asking you to add extra tasks.
When adding your first ordinary task, Hermes offers an optional due date; you can
leave it without one. Recurring tasks require an initial due date.
Saving preferences is an intermediate step; Hermes continues to the next unfinished
checkpoint. The optional test defaults to **No** and sends only after an explicit
Yes. You can skip the test and activate after reviewing the unverified
delivery limits. If a step is blocked, Hermes explains what is needed to continue.

For Discord, Hermes confirms your existing destination and asks only for missing
check-in preferences, using everyday language. It offers every day, 9am–5pm
in your confirmed timezone or suggests a timezone from trusted user context for
confirmation. If none is available, it asks; the server timezone is not assumed
to be yours. Only after choosing Discord
check-ins and confirming the destination, Hermes separately asks whether to allow
bounded history for explicitly requested reply recovery or delivery verification
(**default No**), explaining unrelated messages and extra model input tokens.
Local-only setup never asks that Discord question. Resumed setup reuses the actual
saved choice; the user can disable it later. The default is up to **2 distinct
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

The test uses the ordinary guarded send. In local-first, history readback is optional
and acceptance is reported separately from independently verified arrival. Hermes checks
that your reply continues the right task and is recognized as engagement. A
single-message test has no follow-up to cancel: it does **not** prove live
follow-up suppression under a recurring schedule. Neither saving settings nor
passing automated tests proves live delivery. Ongoing activation needs its own
approval after the verification checkpoint.

Setup ends with a short conversational explanation of what's ready and what to
expect next—not a dashboard. If only local tasks are ready, no automatic message
is promised. A test alone leaves the ongoing schedule paused. Everyday coaching
stays focused on the task, without task IDs or test bookkeeping unless requested.

The final step reviews your chosen settings, first task and any unverified test
limits. Hermes explains that Yes turns on regular check-ins, then asks:
**“Are you ready to start using your Task Coach?”** You can correct settings before
agreeing; Hermes updates and verifies any affected schedule and reply-handling
instructions before asking for activation again. No leaves the schedule paused.

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

The following history-based clarification details apply only to the retained
legacy policy. Local-first uses trusted `record-engagement` and does not globally
hold ordinary scheduling on ambiguity or verification failure.

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
Only the retained legacy policy globally blocks later sends on uncertain delivery
or unverifiable history and requires complete history for follow-ups. Local-first
uses recorded engagement and local controls; uncertainty stops its affected sequence.
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

Default preferences are UTC, every day, 09:00–17:00, up to 2 distinct tasks,
up to two unanswered follow-ups per task, and 30–120 minute follow-up intervals.
Set `--max-tasks-per-window` to an integer from 1 through 10. Saved configurations
from before this setting retain a maximum of 1 until you explicitly change it
with `setup --update --max-tasks-per-window 2`. Local-only setup leaves unused notification defaults
alone. Preferences do not trigger messages. Overnight windows are unsupported.

## Storage and task fields

With `HERMES_HOME`, data lives in its `task-coach` subdirectory. Otherwise it uses
`$XDG_DATA_HOME/task-coach` or `~/.local/share/task-coach`. Put an explicit
`--data-dir PATH` before the subcommand and use it consistently. Only `init` and
`setup` initialize task storage. No imports or migrations happen automatically.

- Priority: `low`, `normal` or `high`; status: `open`, `done` or `cancelled`.
- Due: `2031-04-05` or an aware timestamp such as `2031-04-05T12:00:00+02:00`.
- Snooze: an aware timestamp; it does not change the due date.
- Check-in days: `weekdays`, `weekends` or `all`; applies to initial check-ins and follow-ups within the global window.
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
