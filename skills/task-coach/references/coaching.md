# Transport-neutral coaching engine

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
future unexpired events may still become eligible after disabling, subject to all
ordinary guards. A follow-up whose required preceding message was missed is not
eligible merely because its own slot is still in the future: disabling does not
resume a broken follow-up chain or relax actual delivery-spacing limits.
Expiry is the saved absolute instant at the originating allowed local window end,
not a task deadline or a scheduler reset. Changing timezone/window settings does
not move that saved expiry. The next allowed day is not blocked by this hold even
if cleanup never ran and the task remains open; explicit pause, invalid settings,
route changes and clock-regression protections can independently block scheduling.
Ordinary preflight clears/reuses an expired slot. Weekdays and DST follow the
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

## Completion-based recurrence

`add --repeat "3 months" --due DATE_OR_TIMESTAMP`, `update ID --repeat "2 weeks"`
and `update ID --remove-repeat` operate on the same task row. Completion is
`done ID --completed-at ACTUAL_DATE_OR_AWARE_TIMESTAMP --expected-cycle CAPTURED_CYCLE
--completion-id UNIQUE_REQUEST_ID`. Preserve all three request values on retry.
Only explicit completion resets eligibility, clears snooze and rotates cycle.
No ordinary reply, dismissal or snooze completes a task. Ask when actual completion
is uncertain; confirm a relative date before writing. No occurrence history,
backlog or exact-date alert is generated. Calendar months clamp month-end; calendar
days/weeks and timestamp arithmetic use the configured timezone, DST gaps roll
forward and folds choose the first occurrence. Initial due is explicit and gates
recurring selection; overdue tasks persist unchanged until completion.

Recurring tasks use the existing shared budgets, not extra slots. Stored plans
capture `cycle_id`; a completed/edited cycle makes its old plan unavailable even
when the new cycle is overdue. Completion does not replan the current window.
Historical plain plans without a cycle remain compatible. See SKILL.md for the
explicit version-0-to-1 `migrate` path; reads never migrate or reset stores.


For native unattended integration use the [runtime protocol](native-runtime.md),
not hand-written evidence or receipts. This reference describes the low-level
engine API, which remains usable without Discord or any messaging credentials.
An engine intent is not a send or a positive receipt.

## Low-level compatibility CLI

The standalone `coach tick` API retains its legacy history-evidence contract.
Unattended rc6 local-first work must use `runtime`, which sets local-first claim
provenance instead of consuming fabricated evidence IDs. `deliveries` counts engine
receipts for accepted as well as independently verified runtime outcomes; inspect
outbox `acceptance` and `state` to distinguish provenance.

## CLI

Invoke `python3 "<skill_dir>/scripts/task-coach.py" [--data-dir PATH] coach ...`.
The optional installed `task-coach` console has the same arguments. Initialize
storage with `setup` or `init` first. Successful output is JSON; operational
errors exit 2 with concise stderr. Recognized tick/preflight errors also emit a
final literal `wakeAgent:false` JSON object. The native wrapper additionally
catches process failure, malformed output and timeouts.

- `status` / `inspect`: current state, episode, confirmed deliveries, paused flag.
  The legacy `transport:"external-bridge-required"` field describes the engine,
  not whether the separately configured native driver exists.
- `pause` / `resume`: persistent local controls, not cron edits. Pause stops an
  existing daily episode; resume never revives it. The next eligible day may plan.
- `tick [--binding JSON] [--evidence JSON]`: plan or claim a due event atomically.
  Missing binding returns quiet. Ready output includes `wakeAgent:true` and
  `intent:{event_token,index,task_id,binding,expires,kind}`. This is not delivery.
- `ack --receipt JSON`: strict on-time positive receipt. Exact repeats are
  idempotent; unknown/unclaimed/wrong-route/expired/conflicting receipts fail.
- `failed --event-token TOKEN --binding JSON`: stop a claimed event and episode.
- `engaged --event-token TOKEN --binding JSON`: stop follow-ups for the matching
  task sequence, not the task itself or other planned task sequences.
- `preview --binding JSON [--at AWARE_TIMESTAMP] [--seed INTEGER]`: isolated
  development plan, does not open coaching state. Preview tokens cannot be acked.

Bindings contain exactly five nonempty strings: owner, profile, account, chat,
thread. The engine treats identifiers as opaque; adapters must validate their
platform-specific routing. For the native Discord adapter, thread `"none"` means
no thread, chat is the actual channel and channel_id is chat; otherwise thread is
the actual Discord thread ID and channel_id is thread.

A receipt contains exactly `event_token`, `binding`, `message_id`, `cursor`,
`delivered_at`. The native driver always sets cursor to the sent message ID, not
a newer fetched tail. A strict acknowledgement requires
`claimed_at <= delivered_at <= now < expires`.

Engine evidence contains exactly `binding`, `event_token` (previous event),
`message_id` (previous sent ID), `cursor`, `snapshot_id`, `observed_at`,
`complete`, `engaged`, `error`. It must match the previous receipt and binding,
be complete, not engaged, error-free, at most 60 seconds old, not future-dated,
and use a unique snapshot ID. The native driver derives these fields by validating
actual agent-captured history; they are not setup switches. The engine cannot
cryptographically authenticate agent/operator-supplied JSON against a platform.

## Python API

All clock/evidence/binding arguments below are keyword-only where shown in source.

```python
Coach(data_dir, rng=None, opportunity_minutes=1)
coach.status()
coach.pause(True)
coach.prepare(now=..., binding=...)
coach.tick(now=..., binding=..., evidence=..., expected_token=...)
coach.acknowledge(receipt, now=...)
coach.reconcile(receipt, now=...)
coach.failed(event_token, binding)
coach.stop(event_token, binding)
coach.preview(binding=..., now=..., seed=...)
```

`prepare` creates/inspects the daily plan and returns due work without claiming
or consuming evidence; followup history is not needed merely to prepare.
`expected_token` fences a claim to the draft's exact event rather than accidentally
claiming another slot/day. `reconcile` accepts an actually claimed, verified
positive outcome of an attempt authorized before the opportunity deadline, even
if the platform accepts it or confirmation arrives late, or the episode has stopped. It never clears a stop. If reconciliation
is late it stops the episode as `late-reconciled` unless already stopped. It must
only be called after the driver's durable journal and exact readback checks, not
as a way to invent sends. Past daily attempts are retained in the separate outbox,
not inserted into a new daily engine episode.

Aware clock/RNG injection is for tests/development; production uses UTC now and
SystemRandom. UTC-overflow timestamps fail with ValueError.

## Planning and durability

Read-only task access uses SQLite mode=ro. The engine writes separate private
`coach.sqlite3`, with directory mode 0700, file modes 0600, current-user ownership,
no hardlinks/symlinks (including ancestors and SQLite sidecars). A Linux directory
lock protects first creation and SQLite BEGIN IMMEDIATE protects state changes.
Versioned DDL, primary key, singleton rows and nested invariants are validated;
incompatible or corrupt stores are never silently reset or repaired.

Tasks must be open and not currently snoozed. Priority weights are low=1,
normal=2, high=4; approaching deadlines add weight and overdue tasks add more.
Date-only deadlines use local midnight. Avoid the seven recent daily selections
when alternatives exist. Plan up to `max_tasks_per_window` distinct eligible tasks
per local day/window. Each task has a randomized opener minute followed by up to
the configured cap of randomized follow-up slots satisfying min/max spacing.
Sequences do not overlap and reserve at least 30 minutes (or the configured
minimum follow-up interval if greater) between their opportunities. Too few tasks
or too little window space yields fewer sequences, never repeats to fill a quota.
Near the end of a sequence's allotted block fewer followups may fit. Slots are
real UTC instants: DST gaps have none and folded local minutes may occur twice.

The default maximum tasks per configured daily window is 3, with integers 1..10
accepted. Configurations missing the key keep the historical maximum of 1 until
an explicit setup update. A reply stops only its task sequence's follow-ups;
later task check-ins remain scheduled. This requires accurate attribution in the
native driver: current Discord history omits reply references, so ambiguous
multi-task owner activity without trusted target metadata stops the window with
`ambiguous-engagement`, not `owner-engaged` on a guessed task. See the native
runtime capture interface; absent metadata cannot prove which check-in received
a reply. Global pause and unsafe delivery/history conditions still suppress
automatic sends across the window.
The default low-level opportunity lasts one minute for backward compatibility;
the native driver uses up to ten minutes, capped at the window end. Independent
final-send authorization limits the claim lease to 120 seconds, and actual
previous-send time enforces min/max spacing. A claim is not a journaled network
attempt. No catch-up after a missed opportunity and no reroll on restart. Pauses,
engagement, changed binding/config, task completion/cancellation/snooze/deletion,
and backward clock movement suppress episodes. Missing or invalid history at
claim stops the episode. Never claim an event whose state is not planned.

The unavoidable platform check/send race is described in the native reference.
An outbox, cron specification, configured destination or synthetic test success
must never be represented as live messaging qualification.
