# Transport-neutral coaching engine

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
