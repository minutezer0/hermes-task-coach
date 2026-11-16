# Native Hermes runtime: optional Discord adapter

Discord is the only implemented history platform; unsupported platforms are rejected, never allowed to follow up. No new
bot account, SDK, dependency or importing Hermes into arbitrary Python: the model uses Hermes's supported `discord` tool
and the helper launches native `hermes send` as an argument array, not a shell command. The task and coaching engine
stay transport-neutral.

## Notification holds (Smart Snooze)

Smart Snooze is a **hold-only notification preference**, default OFF on fresh and all known older runtimes missing the
field. With it ON, a genuine explicit “start working now” reply to an accepted/delivered check-in or follow-up records
`start-work` and holds **all** Task Coach automated notifications for the remaining current configured local
notification window, including other tasks and legacy clarification retries. It changes no task status, completion,
snooze, priority/selection weights, global pause, reminders or cron activation; generic `engaged`, `skip-for-now`,
completion and ordinary replies never create a hold, and historical engagement is never reinterpreted as start-work. Use
the actual installed helper and approved active-profile data scope:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --enable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --disable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
```

During **check-in** setup, separately ask: “Smart Snooze is off by default. If you explicitly start working after a
check-in, should I hold all Task Coach check-ins until your current notification window ends?” Reuse the saved `runtime
smart-snooze` value on resumed setup instead of re-interviewing; persist only the explicit choice after the confirmed
route is configured, and read back. Never ask this for local-only task setup, and this choice alone never activates
cron. Record clear engagement **BEFORE
substantive assistance, memory recall or delegation**, when an applicable accepted check-in exists, using `runtime
record-engagement --binding JSON --owner OWNER --message-id INBOUND_ID --event-token EVENT --task-id TASK [--cycle-id
CYCLE] --intent start-work` only for genuine explicit agreement to begin working now; `engaged` is general engagement
and `skip-for-now` a skip. Bind the genuine trusted owner/profile/account/chat/thread, inbound message identity and
current task/event/cycle; clarify ambiguous intent or task selection, never fabricate IDs, reply references or history,
and read back before claiming suppression. Normal inbound needs no Discord history; completion and task edits need
separate explicit intent. There is one hold slot, not a hold history. Its route, triggering task/event/message, local
day, timezone/config snapshot and absolute expiry are retained for requested diagnostics: `runtime status` exposes
`notification_policy.active`, reason and hold when a slot exists, and `runtime preflight` returns `wakeAgent:false`,
reason `smart-snooze`, while active. Do not surface audit IDs or diagnostic blocks in everyday coaching unless asked or
needed to explain a problem.

Completion, snooze, cancellation or deletion of the focused task does not release the hold; disable clears it
immediately, and re-enable applies only to future, unconsumed start-work replies. Retrying an old message never
recreates, extends or renews a hold, including messages recorded while OFF, and nothing suppressed or expired is
replayed while stopped sequences never revive; already planned, future unexpired events may still become eligible after
disabling. Expiry is the saved absolute instant at the originating allowed local window end, not a task deadline or
scheduler reset. Later timezone/window changes neither shorten nor extend that saved expiry. The next allowed day
is eligible even if cleanup never ran and the task remains open—ordinary preflight clears/reuses an expired slot.
Weekdays and DST follow the existing real-instant window policy; overnight windows remain unsupported. The shared
directory lock fences planning/claims and the final refreshed-clock transport check against newly recorded holds, but a
send already in flight cannot be recalled. Failed/uncertain attempts remain nonretryable, and malformed or unknown
runtime state refuses without silent repair. Task settings are unchanged, and the optional runtime fields stay separate
from episode configuration so toggling never causes a configuration-changed stop.

After an approved code/instruction update, regenerate/review native-plan artifacts and scoped inbound instructions
(previews side-effect-free, cron initially paused); continuing conversations may cache old instructions, and `hermes
sessions refresh-prompts --session ID --json` preserves history while queuing refresh for the **next turn**, not the
running turn. Report queued versus verified adoption separately and never clear sessions or restart a shared gateway to
refresh prompts; updating this guide is not installation, refresh, live testing or activation approval.

## Discord history: consent and bounded on-demand read

History is OFF by default for fresh stores and all older stores without a saved preference; a configured Discord route
or an available tool is not consent. Local task management, accepted delivery and trusted local-first engagement work
without history, and routine cron never fetches it even after opt-in: only explicitly requested **reply-recovery** or
**delivery-verification** may read history, after checking exact-route saved consent and caller tool availability. Read
`runtime history-preference` to reuse the saved choice when setup resumes. After confirmed Discord check-in setup,
persist an explicit Yes with `runtime history-preference --enable --route FULL_CONFIRMED_ROUTE_JSON --confirm-history`;
an explicit No or change uses `runtime history-preference --disable`, and either change is read back. A No is already
effective because history is OFF, but do not describe it as saved until that write reads back. Configure the confirmed
route first: a preference write before configure is refused and creates no new runtime store, though it does not remove
existing artifacts. A runtime file with a sidecar, or one that is not a valid store, is refused rather than repaired or
deleted; recover it only after an explicit diagnostic review. Missing preferences mean No, not approval.
Consent includes the exact owner/profile/account/chat/thread, channel and bot route; a changed route needs new consent,
and disable/re-enable rotates the grant generation.

For each explicitly requested operation, run `runtime history-plan --purpose reply-recovery|delivery-verification
--target DECIMAL_ID --confirm-history` and save its returned JSON dict in a private plan file. The grant binds the exact
route, generation, purpose and target: fetch only the latest **25 messages, ONE page**, `before=null`, at most **131072
bytes** total and **8192 bytes** per message, never chasing old anchors or fetching additional pages. Preserve genuine
raw tool results with trusted metadata and request-start timestamps. Pass `--history-plan-file PLAN_FILE` with
`--pages-file CAPTURE_FILE` to every applicable history ingress (`observe`, `confirm`, `engagement`,
`resolve-clarification`, `dismiss-clarification`): `delivery-verification` for `confirm`, targeting the exact sent
candidate message ID; `reply-recovery` for `observe` and `engagement`, targeting the exact previous/selected receipt ID;
`OWNER_SELECTION_ID` for `resolve-clarification` and `OWNER_DISMISSAL_ID` for `dismiss-clarification`, not the older
receipt needed in that same captured page. Each command needs its own matching purpose/target plan—never reuse another
operation's plan or fabricate captures or reply references. An absent anchor or insufficient evidence is an optional
warning, not permission to expand the read or block accepted/local-first work; never claim unverified delivery.

The plan represents **caller-asserted explicit user intent**, not cryptographic proof that the user asked, and helper
gates do not sandbox arbitrary external tools. Review installed instructions and tool allowlists after enabling or
disabling—persisted core denial takes effect immediately—and never auto-provision an MCP/hosted connector. Capabilities
separates saved current-route consent, caller-reported tool availability and independent delivery evidence; availability
and consent never establish verified delivery. A preserved legacy episode day retains its existing honest history gates.
If work needs unavailable/unapproved evidence, stop that work and explain the limit; never automatically read, bypass
the gate, revive stopped slots or resend an uncertain attempt.

## Local-first delivery policy

After a code update, known existing runtime stores adopt local-first policy on first ordinary runtime use (including
`runtime status`) after validating saved config, runtime, route and engine state; fresh stores start local-first. No
policy opt-in or second approval is needed, and help or `runtime native-plan` does not adopt it. This changes only
runtime policy, not saved tasks/settings/engine, installation, cron state or send authorization. Quiesce old writers
before updating code and do not run older helpers afterward. Delivery route/setup, artifact installation, live testing
and ongoing activation remain separately explicit: default policy NEVER means automatic sending, and never send to a
real route during update verification. Local eligibility, recorded engagement, windows, spacing, budgets and global
pause authorize **both openers and followups**; native Hermes send remains the only transport. A positive `success:true`
plus nonempty message ID persists `accepted` delivery with `native-send-response` provenance and advances ordinary work
without history—transport acceptance, not verified arrival. Optional `confirm` enriches the outbox as `confirmed`; its
failure is a verification warning, not a failed send or scheduling lock. Failed/uncertain attempts are never retried:
that sequence stops while unrelated tasks and future days keep their own bounded opportunities, and real failures are
reported as `[CRON_FAILURE]`, never silent success.

The caller checks its native tool inventory/actual attempt and runs `runtime capabilities --history-availability
unknown|unavailable|available` (with `--history-error TEXT` for failure). Core does not discover external tools: unknown
means unchecked, unavailable includes absent/error, and available means caller-reported availability, not delivery
verification. Unknown/unavailable is visibly degraded and **nonblocking**: do not wait for history or substitute a
hosted connector when the native tool is absent. No source imports, raw credentials, alternate APIs or workarounds;
Discord history is an optional boundary adapter, never a scheduler dependency. For normal inbound, use exact trusted
binding/owner/message ID and explicit task selection with `runtime record-engagement --binding JSON --owner OWNER
--message-id INBOUND_ID --event-token EVENT --task-id TASK [--cycle-id CYCLE] --intent engaged|skip-for-now`. It needs
no history: provenance is honest `agent-mediated-explicit-intent`, not an invented reply reference. Retry the exact
identity/selection only, and a recorded skip stops only that **current** sequence without completion/snooze edits.
Ambiguity requires a natural clarification before attribution or task edits, not a global check-in freeze; existing
immutable clarification audit/outcomes remain and resolving/resolved choices are never undone, while new local-first
ambiguity is handled conversationally without automated holds or retries. Unknown/unrecorded replies may receive bounded
followups—an accepted tradeoff, not an impossible cross-session reply-suppression guarantee.

Compatibility is explicit: existing episodes, IDs, outbox and clarification audits are retained, not reset/replayed. An
existing episode keeps legacy policy for its whole local day, with local-first beginning on a later day at the saved
episode's local date rather than the command clock; with no episode, adoption applies immediately without creating one,
and already-local-first policy is untouched. Malformed or unknown data refuses before writing, preserving bytes, mtimes
and sidecars rather than repairing it, and old attempts are never resent. Missed slots stop that sequence—no catchup,
backlog or budget expansion—while completion, cancellation, snooze, global pause, authorized route, current cycle and
atomic write/send fences remain hard controls.

## Scheduled and inbound lifecycle

1. Read `runtime status` and `runtime capabilities`; report the optional native history capability from the
   caller inventory/attempt. A missing tool stays absent for a separately authorized test.
2. `runtime preflight`: quiet local guards mean stop. For due ordinary work, compose one short question for
   the returned current task, store plain text in a private body file, and run `runtime draft --event-token
   TOKEN --body-file FILE`.
3. Do not fetch history in routine cron; observe/enrichment belongs only to a separately requested,
   consented on-demand operation.
4. `runtime dispatch --event-token TOKEN --fence FENCE --hermes ABSOLUTE_EXECUTABLE` performs final local
   authorization and the only send; read back `runtime status`. `accepted` is a durable positive native
   response and permits later ordinary work, while `sending`/`uncertain` is not success and must never be
   resent. Report real send failures/uncertainty as `[CRON_FAILURE]`; independent readback warnings do not
   mean the accepted send failed.
5. Only for an explicitly requested, consented on-demand delivery verification, `runtime confirm
   --event-token TOKEN --fence FENCE --pages-file FILE --history-plan-file PLAN_FILE` independently verifies
   bot/body/time/route and records confirmed provenance while retaining the original acceptance. Do not wait
   for it before later valid work, and never echo the check-in in commentary/final output: the helper owns
   delivery.
6. In a normal inbound turn, use `runtime context --binding JSON` or exact trusted `--reply-to-message-id
   TARGET` when present, and inspect status if context is null. Ask naturally which task when selection is
   ambiguous; once explicit meaning and current sequence/cycle are clear, record engagement as above with the
   genuine trusted owner and inbound ID. A skip is engagement only, and history is never required to record
   real trusted inbound. Ask before task completion, snooze, cancellation or pause mutations.

## Recurring task cycle fences

Completion-based tasks reuse IDs, so IDs alone are not snapshot identities. Engine plans and outbox task snapshots
retain the cycle; context, owner engagement, observe/confirm attribution, clarification candidate resolution/retries,
and the final directory-locked send boundary must match the current cycle. An old receipt may still be confirmed
truthfully after completion, but cannot engage, complete or supply the new cycle as context, even after its due date.
Confirming delivery never completes a task; an old draft cannot send for a newer cycle. Use the task CLI's guarded `done
ID --completed-at ACTUAL_DATE_OR_AWARE_TIMESTAMP --expected-cycle CAPTURED_CYCLE --completion-id UNIQUE_REQUEST_ID` only
on explicit completion. Capture the cycle and retain the same unique request ID/date for retries; never interpret a new
cycle as authorization to replay an old completion, and if the actual date is unclear, ask and confirm it. Ordinary
replies, dismissals and snooze are not completion. Recurring due dates restore eligibility within existing random
windows/budgets, not fixed-clock cron/date alerts or bonus notifications. All new task/settings writers share the
exclusive directory lock. Stale pending clarification candidates suppress retries; explicit dismissal or the existing
next-window retirement can release them without task changes. A resolving choice whose candidate changed remains
fail-closed, not automatically rebound.

## Multiple tasks in one daily window

`max_tasks_per_window` defaults to 2 for new stores and accepts integers 1..10; existing configurations without the key
retain 1 until an explicit setup update. Ask the maximum-tasks question only for proactive check-ins, showing the
default or current saved value before offering to keep it or customize. Each distinct selected task has its own opener
and bounded follow-ups; a reply stops only the matching task's follow-ups while later task check-ins remain scheduled.
Global pause and changed configuration/binding still suppress unattended sends, and uncertain delivery suppresses only
its local-first sequence, or globally under retained legacy policy. Sequences are planned without overlap and with an
inter-task gap of at least 30 minutes (or the saved minimum follow-up interval if larger); fewer eligible tasks or
insufficient window space produces fewer sequences. Context returns an explicitly targeted confirmed task, or the latest
confirmed receipt when only one distinct task is represented; untargeted multi-task context returns null rather than
guessing, and future planned tasks are never returned. Keep the exact event token and receipt anchor—never apply an
older task's engagement to a later task—and an explicit one-check-in test stays one opener with no follow-ups or
additional tasks.

## Per-task check-in days

New setups allow all seven global days; saved configurations keep their days. Tasks use
`check_in_days=weekdays|weekends|all` (default `all`) to narrow that window for both initial check-ins and follow-ups in
the configured timezone. Selection, preparation and final dispatch enforce the current task preference and overdue dates
never bypass it; automated clarification retries respect the current day preferences of every candidate, and manual task
commands remain available on any day. Ask the task-add day question only when the saved global window includes all seven
distinct days; otherwise skip it and default new tasks to `all`. Explicit choices and existing task preferences survive
global-window changes—use their intersection, never silently widen either setting. `add`, `update --check-in-days` (when
the saved value changes), reopening through `update --status open`, and any `setup --update --weekdays` change print a
non-blocking stderr warning when saved task days never meet the configured days. The write succeeds and the task stays
saved, with no check-in until the two settings overlap; explain that instead of widening the global days or rewriting
the task's choice without permission. Use `add TITLE --check-in-days weekends` or `update ID --check-in-days weekdays`
and read back. Older tasks read as `all` without writes, stale drafts refuse changed preferences, and missing historical
days mean `all` for snapshot comparison. No migration resets, catch-up sends or extra task budgets.

Replies use conversation and saved task context independently of the notification schedule, including after daily
rollover: clear task references can be used directly and ambiguous ones need a natural clarification, and recording
engagement can use a retained accepted receipt for the current task/cycle. A start-work reply outside a window is
accepted without a hold; inside an allowed window, Smart Snooze ON can hold the remainder of that window, and replays
never create future holds. An unavailable engagement record does not prevent ordinary task help or authorize guessing an
event, completing a task or changing a newer cycle.

## Onboarding and the paused native job

Follow the skill's “Carry proactive setup through to activation” checkpoints; saving preferences never finishes
proactive setup. The optional test question defaults to No and needs an explicit Yes, and a skipped or unavailable test
is not a prerequisite for activation—disclose unverified delivery and follow-up suppression. Keep a failed or uncertain
attempted send paused pending resolution and reuse saved state and matching installed artifacts when resuming.
Onboarding asks for only one task, reusing an existing open task or the one already supplied; the daily maximum is not a
task-entry quota, and a future-due recurring or snoozed task does not require adding another. After Discord check-ins
are chosen and the destination confirmed, ask the separate default-No history question in the skill's Guided onboarding
section, explaining unrelated conversation exposure and repeated model input-token costs; core coaching works without
it. Read the saved preference on resumed setup, persist only the explicit choice with the real history-preference CLI,
and offer later disable. Local-only setup never asks this Discord question. Initialize task preferences with `setup`;
this does not enable automation. Ask the user to select an already configured Hermes destination, using native `hermes
send --list` and trusted inbound gateway context, not account secrets or a guessed nickname, and resolve the exact
numeric channel/thread, nonbot owner, bot ID, active profile and account identity. Binding is exactly:

```json
{"owner":"OWNER_ID","profile":"ACTIVE_PROFILE_ID","account":"ACCOUNT_ID","chat":"CHANNEL_ID","thread":"none"}
```

For a Discord thread, chat is the parent channel, thread is its actual ID, and channel_id/destination identify the
thread itself (`discord:THREAD_ID`). For no thread, use the literal `none`, not an omitted field or wildcard. These
examples are placeholders, not real account identifiers. With explicit user confirmation of binding and preferences:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime configure --confirm-setup --route '{"binding":{"owner":"OWNER_ID","profile":"ACTIVE_PROFILE_ID","account":"ACCOUNT_ID","chat":"CHANNEL_ID","thread":"none"},"platform":"discord","destination":"discord:CHANNEL_ID","channel_id":"CHANNEL_ID","bot_id":"BOT_ID"}'
python3 "<skill_dir>/scripts/task-coach.py" runtime status
python3 "<skill_dir>/scripts/task-coach.py" runtime native-plan --profile-home ABSOLUTE_ACTIVE_PROFILE_HOME --python ABSOLUTE_PYTHON --helper "<skill_dir>/scripts/task-coach.py" --hermes ABSOLUTE_HERMES_EXECUTABLE
```

All commands also accept `--data-dir PATH` **before** the subcommand. `configure` requires `--confirm-setup`, stores a
separate confirmed route in outbox.sqlite3, and rejects changing that route once drafts exist (use a separately approved
data directory). It is also the gate for preferences: save history and Smart Snooze only after it succeeds, and read
both back before installing or testing. Local config automation_enabled remains false; the runtime route is the
separate explicit opt-in, `live_verified:false` is truthful status rather than an activation boolean, and there is no
`qualified:true` escape hatch. `native-plan` only returns JSON artifacts: `script_path`, `script_text`, `cron_argv`, `inbound_instruction`,
`initially_paused:true`, `live_verified:false`. No profile writes, jobs, messages or account changes occur, so show
these artifacts and obtain approval before installing. The wrapper path must resolve under the active profile's scripts
directory; save script_text verbatim to script_path as a private executable (0700), never overwriting an existing script
without review. Its shebang and subprocess use explicit interpreter/helper/data paths, not cwd or PATH—read it back
before executing the returned cron_argv as an argument array. Do not run the wrapper against user data before preparing
an intended fresh-setup test, since it calls preflight and can persist a daily episode that makes `prepare-test` refuse.

```
hermes cron create 'every 1m' PROMPT --name task-coach --skill task-coach --script task-coach-preflight.py --deliver local --failure-deliver local --paused
```

The `--script` argument is relative to the active profile's `scripts` directory; the separate `script_path` artifact is
absolute for writing and verification. No `--no-agent`: the agent composes human text and history is optional in
local-first. The cron wrapper takes no arguments; its last nonempty stdout line is always a JSON object with literal
wakeAgent:false on subprocess failure, malformed/missing output or 30-second timeout, and otherwise relays the validated
preflight boolean. Native cron can wake an agent on process failure without that wrapper. Keep final and failure
delivery local: explicit sends own destination delivery, avoiding duplicate messages or native duplicate-target skips.
Add **only** the returned scoped inbound instruction through the user's approved normal-inbound instruction workflow
(for example, an explicitly approved appended section in existing instructions). Never replace SOUL, patch installed
Hermes sources, or inspect its internal databases. The snippet applies only to the exact confirmed
owner/profile/account/chat/thread; read back the installed instruction and paused job. Installation approval can cover
wrapper, paused job and exact scoped snippet together in plain language, but it is not send permission.

## One-check-in fresh-setup test

With the exact route already confirmed, an eligible task saved and the current local day/time inside the saved allowed
window, ask explicitly to send **one** check-in to that route; no permission to change days/windows or clear a global
pause is implied. Keep the native recurring job paused throughout and do not resume it to test. Use the same approved
data directory and installed helper:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime prepare-test --confirm-test
python3 "<skill_dir>/scripts/task-coach.py" runtime preflight
```

Preparation never sends, claims, writes an outbox row or changes cron. It persists one newly generated planned opener
with durable episode `purpose:one-check-in-test`, the current minute slot and a normal ten-minute opportunity capped at
window end. The config is unchanged; there are **zero follow-ups**, regardless of saved follow-up limits. The result has
`test_prepared:true`, `wakeAgent:false` and the persisted `episode`. Run normal preflight, draft and dispatch for this
exact event. Under default local-first policy, confirm/history is optional independent verification, never required for
accepted delivery; the legacy policy still requires exact bot/body/time/route readback. Uncertain attempts remain
permanently nonretryable in either policy. Then use normal context and trusted record-engagement (or optional real
history attribution) and continue the task in chat. The conservative supported scope is **no existing episode at all and
an entirely empty outbox**; coach status with `episode:null` is okay. Any active plan, stopped empty episode, old-day
episode, draft, sending/uncertain or confirmed journal refuses unchanged. This intentionally means existing
installations may not qualify; no automatic reset, archival, token reuse, database deletion or test retry is supported.
The command also refuses missing/invalid route, global pause, clock regression, unavailable task, disallowed day or
outside-window time—there is no production clock flag or day/window bypass. A repeat preparation refuses even if the
first event was never drafted. After a one-event test, today's episode remains complete/stopped rather than becoming a
new randomized plan; a separately enabled ongoing job can plan on a later allowed day through the ordinary engine.

Preparation holds the same directory flock as runtime writes and engine operations, reads the outbox in a read-only
SQLite transaction and commits the engine episode under that lock; only the engine is written. A concurrent ordinary
planner either wins first (test refuses) or sees the new single-event episode, and neither can replace an existing
token, while any stale token/fence still fails normal authorization. Supported operations preserve audit/replay records;
manual database edits or processes ignoring the lock are outside the guarantee. Config/task edits may invalidate
preparation and are rechecked at dispatch, and the platform check/send race remains unchanged. Older helpers that do not
recognize the purpose field fail closed: upgrade the bundled runtime together before using this command. At the
checkpoint, distinguish verified delivery, recognized owner engagement and task continuation from **unverified live
follow-up suppression**, and do not label no-follow-up behavior as a suppression experiment. Keep cron paused if
verification fails. This feature does not monitor cron pause state itself: keeping the job paused and reading back that
exact job are operator obligations, not an invented helper-enforced schedule fence.

Do not add a five-minute test follow-up or require a follow-up pilot during setup; the optional one-check-in delivery
test is the onboarding test. Disclose that cancellation of a pending live follow-up remains unverified, then obtain
distinct ongoing-send approval by reviewing the saved destination, window/timezone, task maximum, follow-up policy,
Smart Snooze and history choices, first task and test outcome/remaining limits. Explain that Yes turns on regular
check-ins and ask “Are you ready to start using your Task Coach?”—allow settings corrections before that question and
add no further approval after it. If settings change, keep cron paused and revisit the affected route/preferences and
installation checkpoints: regenerate/reconcile affected wrapper, cron and scoped reply instructions with approval for
any changed scope, then read back before reviewing the revised settings for activation. A destination change also
requires confirming the new route and its exact-route history consent, since old-route consent does not transfer. After
approval, read back the active schedule and the task's eligibility. If the single task is not yet eligible, confirm
setup is complete with check-ins waiting for eligibility during an allowed window; do not require another task or
promise an exact send. Only with an eligible task and a supported upcoming allowed opportunity, finish naturally: “Task
Coach setup complete—you’ll be hearing from me soon!” If today's episode is stopped, explain that regular check-ins
start on the next allowed day. Paused installations must say check-ins are paused, not that proactive setup is complete.

## CLI commands and dispatch mechanics

Prefix each command with the explicit installed helper and consistent data path. Every history-gated command needs its
own separately requested on-demand purpose, exact-route consent and matching `--history-plan-file PLAN_FILE`.

| Command | Effect |
|---|---|
| `runtime preflight` | Nonclaiming due inspection; quiet without confirmed setup |
| `runtime restart --confirm-restart` | Replan only today's untouched stopped episode; empty outbox required; no send or cron change |
| `runtime status` | Confirmed route and durable outbox rows |
| `runtime configure --route JSON --confirm-setup` | Explicit route opt-in, not account setup |
| `runtime native-plan --profile-home PATH --python PATH --helper PATH --hermes PATH` | Emit wrapper/paused cron/scoped inbound artifacts only |
| `runtime draft --event-token TOKEN --body-file PATH` | Immutable plain text draft and unique fence; no claim/send |
| `runtime observe --event-token TOKEN --fence FENCE --pages-file PATH --history-plan-file PLAN_FILE` | Validate fresh bounded history and derive evidence/reply-stop |
| `runtime dispatch --event-token TOKEN --fence FENCE --hermes PATH` | Exact-token claim, final authorization, durable sending, one native send attempt |
| `runtime confirm --event-token TOKEN --fence FENCE --pages-file PATH --history-plan-file PLAN_FILE [--message-id ID]` | Exact sent-message readback and receipt reconciliation |
| `runtime context --binding JSON [--reply-to-message-id ID]` | Exact target receipt/current task, or latest receipt only when one distinct task is known; null for unrelated targets or multiple tasks without a target |
| `runtime engagement --binding JSON --pages-file PATH --history-plan-file PLAN_FILE [--reply-to-message-id TARGET --inbound-message-id ID]` | Attribute captured owner posts, stop only their matching task sequences, return the newest owner's context or null; paired flags select one trusted inbound reply |
| `coach pause` / `coach resume` / `coach status` | Persistent controls and readback; resume never revives stopped episodes |

Production CLI has no synthetic clock or RNG flags; API tests may inject clocks. Draft returns
token/fence/intent/task/previous/route; repeating an identical draft is idempotent while conflicting text is rejected.
Plain text must be nonempty, at most 1800 characters, with no MEDIA directives. Do not compose shell commands from task
text. Use private files for bodies/history, and keep outputs inside the same approved profile/data scope. Dispatch
receives an absolute native executable and invokes exactly:

```python
[hermes_path, 'send', '--json', '--to', destination, '--', body]
```

The `--` ends native option parsing: even a body beginning with `--file=` or `--to=` stays literal message text and
cannot read a file or override the route. A claimed intent is not counted as a delivery. Sending is committed before the
subprocess; there is no retry transition out of sending. Timeout (45 seconds), crash, invalid JSON, negative exit,
missing message ID, skipped or error payload remain uncertain/nonretryable. A success response must be a JSON object
with literal success:true, nonempty string message_id, no skipped/error. Under the retained legacy policy, state stays
sending until exact bot/content/time/route readback. Confirm sets cursor to the sent ID itself so replies between send
and readback are not lost.

If a crash lost the send response, `--message-id ID` can identify a candidate from real history for a previously
journaled sending attempt; it cannot fabricate an attempt or retry, and exact bot/body/send-time matching is mandatory.
Without a journaled candidate ID, the one consented latest page must cover **strictly before attempted_at**, or prove
end of history with a nonempty page shorter than its effective fetch limit (the minimum of the planned 25-message cap
and supplied page/result limits); a full smaller-limit page is not end-of-history proof. An empty page cannot recover
delivery, since public ingress requires the exact target in a nonempty capture. If the page cannot cover the whole
interval, recovery is unavailable: do not fetch more. All captured raw messages are validated, including those older
than the selected candidate on its page, and exactly one message may match the bot, body and timestamp in that interval;
multiple matches reject recovery whichever ID is selected, and an operator's choice is not delivery proof. Missing
coverage leaves the attempt uncertain; never resend. A journaled positive candidate ID instead requires exact readback
through that ID; a conflicting operator ID is rejected. Confirmed receipts are immutable even after day rollover and
restart, and repeating the same ID (or omitting it) returns the stored receipt without changing accounting while still
validating the authorized fresh capture; another ID is rejected.

Late confirmation records the truth without clearing pause/engagement or reviving an expired episode. A platform outcome
that arrives after the opportunity still records truth for the already journaled on-time attempt but never authorizes a
new late send. If the engine has rolled to a newer day, the old receipt lives in the outbox and the new episode is
untouched.

## Explicit, narrowly scoped same-day restart

Finish preferences and add/verify an eligible task **before** first preflight. Preflight can persist a stopped
`task-unavailable` episode when tasks are empty, and changing tasks/settings alone does not revive it; `coach resume`
never restarts a stopped episode. An explicitly authorized recovery for this untouched case is:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime restart --confirm-restart
python3 "<skill_dir>/scripts/task-coach.py" coach status
python3 "<skill_dir>/scripts/task-coach.py" runtime status
```

Use the same approved `--data-dir` before each subcommand if applicable. Restart uses the real UTC production clock
after acquiring the storage lock; there is no CLI date/time/token override, and deterministic API clocks are for
synthetic tests. The episode must already exist, be stopped, and belong to **today in both its saved timezone and the
current configured timezone**, and the confirmed runtime route must be valid with its binding matching that episode.
Global pause and a clock older than the last tick are refusals, not flags to clear automatically. **Zero prior events
means zero**, not merely zero deliveries: planned, claimed, failed and delivered events all refuse. **The entire outbox
must be empty**, even if a row appears historical—drafts are durable pending work, sending/uncertain rows may still be
in flight, and confirmed rows are permanent safety/audit. Unknown or corrupt formats fail validation rather than being
treated as empty. This is deliberately stricter than classifying relevant rows by dates, and prevents resurrecting a
reused same-day token or a worker's old authorization: no old token is recycled, no journal is erased, no receipt is
retried.

Restart holds the shared directory flock while reading a read-only outbox transaction and validating/replacing the
coaching episode in one SQLite transaction; only coaching state is written, so no cross-database write commit is needed.
The lock serializes against engine prepare/tick and runtime journal writes. Multi-step draft/dispatch workers cannot
have an authorized old event in the accepted zero-event case: any prior planned event alone refuses restart, and any
journal row also refuses it, while stale tokens/fences still fail existing checks. This guarantee covers supported local
operations, not manual database edits or hostile processes ignoring the lock. Concurrent task/config edits can still
invalidate the fresh plan and are rechecked by preflight/dispatch. On success it rereads current preferences/tasks,
chooses an eligible task, and plans only minute-aligned slots **strictly later than now** within today's configured
days/window; before-window execution may plan later today but never catches up a past/current minute. No eligible task
or no remaining slots is a ValueError with rollback, other refusals leave the existing episode and journals intact, and
an active second restart refuses instead of regenerating tokens.

Success is JSON containing `restarted:true`, `wakeAgent:false`, `previous_stop` and the fresh `episode`. API refusals
are descriptive ValueErrors; CLI refusals use the normal nonzero exit and stderr error. All tasks, saved config, route,
message/evidence replay records and outbox bytes are preserved, and the existing bounded recent-selection history is
updated as for an ordinary new plan. The empty stopped episode is replaced, not archived as a delivery. Restart does not
claim, send, clear pause, create/enable cron, or promise an immediate check-in—native cron pause and global coaching
pause are separate controls, so keep a pilot schedule paused until separately approved. Never edit/delete a database,
prune an outbox or bypass dispatch as an operator workaround for a refused restart.

## History capture format and reply attribution

Use native Discord `fetch_messages` for the exact granted channel, limit 25, latest only (`before=null`). Retain a
single raw result in the existing page envelope (`binding`, `channel_id`, `before`, `observed_at`, `result`, optional
trusted `reply_targets`), enforce 131072 payload bytes and 8192 per message, and never truncate evidence into a
plausible capture. Missing anchors or incomplete attempt coverage make independent verification/recovery unavailable;
never page backward or claim success without evidence. Current native Discord `fetch_messages` returns `id`, `content`,
`author`, `timestamp`, `edited_timestamp`, `attachments`, `reactions`, and `pinned`. It does **not** expose `message_reference`, and history order
alone cannot tell whether an owner post replies to task A, task B, or an
unrelated message. Do not add invented references to `result`, infer targets from message text, or claim history-only
delayed-reply attribution has been verified live. When a trusted inbound event/adapter actually exposes a reply target
for the exact bound owner and destination, preserve it separately from the unmodified raw result. An optional
page-envelope field supplies only those known targets, keyed by an owner message ID present on that page:

```json
"reply_targets": {"300": "100"}
```

Here the fictional owner message `300` explicitly replies to confirmed check-in `100`. A value of `null` is allowed
**only** when trusted metadata positively says that post has no reply target; absence of a mapping means unknown, not
null. Each entry must match a captured nonbot owner post on that page, and malformed IDs, nonowner posts, missing
messages, or conflicts with available raw references reject the capture. A raw reference from a metadata-capable adapter
is also supported and validated, including its channel. This is a trusted capture contract, not an implemented gateway hook,
signature, or source of metadata that the current Discord history tool lacks—if trusted inbound metadata is not
exposed to the caller, leave the mapping absent and accept the conservative block. For one trusted inbound explicit
reply, `runtime context --binding JSON --reply-to-message-id TARGET` returns that exact receipt and current task.
`runtime engagement --binding JSON --pages-file PATH --history-plan-file PLAN_FILE --reply-to-message-id TARGET
--inbound-message-id ID` requires **both** IDs and verifies the exact owner message in fresh history through the target
receipt; the flags select only that inbound post. Observe/confirm still require complete interval captures with any
available trusted metadata for each post, and unknown/non-coach targets return no coaching context and do not count as
engagement—do not substitute a guessed target to avoid null.

Without a target, context returns the latest receipt only while the binding's confirmed journal contains one eligible
real task; closed, missing and currently snoozed tasks are not implicit candidates, and with multiple eligible tasks it
returns null, including across days, because audit receipts are retained rather than silently forgotten. Unknown-target
candidate snapshots use current eligible task data and confirmed receipts preceding the original owner post; they never
guess the latest task. For history-only engagement, use `runtime status` to find the latest confirmed receipt anchor and
capture through it. Persistent nonbot owner activity can use legacy single-task temporal engagement when only one prior
task is a candidate: this stops prompts for that sole task but does **not** prove a reply reference or exclude unrelated
activity, and a known unthreaded post similarly uses the latest prior receipt. An explicit reference always takes
precedence: replies to unrelated messages do not engage, and delayed replies to A do not stop B. Every owner post is
attributed independently; the newest owner's attribution determines the engagement return context, while earlier
correctly attributed posts can still stop their own task sequences. Attachments count; other users and bots do not.

With multiple eligible prior tasks and missing target metadata, engagement returns `engaged:false`, `context:null`,
`error:"ambiguous-engagement"` and `clarifications`. Observe saves incomplete, error-bearing evidence; confirm still
records verified delivery truth; all three persist a **temporary runtime hold**, not `window_stop` or guessed
`owner-engaged`. The entire captured owner batch is classified before any engagement: a clear earlier post cannot
partially suppress a candidate when another post is ambiguous, and existing pending holds also prevent candidate
engagement. No owner posts means no new ambiguity, though an existing hold still blocks automation, and failed refresh
invalidates earlier draft evidence. No typing indicators, read receipts, transient/deleted posts, voice presence, or
cross-session memory claims are made.

### Clarification before mutation

1. On normal inbound only, use the approved binding and inspect `runtime status`. If no clarification is pending,
   run context; only on explicit recovery request use the consented bounded raw history through the latest
   confirmed receipt; run engagement. If a pending record already exists, inspect its original message and
   candidate titles first, so the owner's selection is not mistaken for a new task reply.
2. Ask “Do you mean ‘Draft proposal’ or ‘Book appointment’?” using the returned candidate titles, **before
   changing task data or marking engagement**. Never require the user to know IDs. Initial clarification is
   normal conversation; unattended clarification retries require a due native clarification intent and the
   complete guarded protocol below, never direct sends from preflight/observe.
3. After an explicit title choice, privately map it to that record's task ID. Obtain the selection post ID and
   exact owner/profile/account/chat/thread from trusted inbound context. The single bounded page must include the
   **oldest candidate receipt**, preserving each whole unmodified Discord result and request-start timestamp in
   the existing page envelope, and both the immutable original and later nonbot owner selection must be present.
   Do not invent reply references from words or titles.
4. Run the guarded command (substitute actual returned values, not these placeholders):

   ```sh
   python3 /absolute/skill/scripts/task-coach.py --data-dir /approved/store runtime resolve-clarification --binding '{"owner":"OWNER","profile":"PROFILE","account":"ACCOUNT","chat":"CHANNEL","thread":"none"}' --clarification-id CLARIFICATION_ID --task-id TASK_ID --selection-message-id OWNER_SELECTION_ID --pages-file /private/fresh-pages.json --history-plan-file /private/history-plan.json
   ```

   The explicit command asserts the agent has interpreted an **explicit user choice**; the runtime does not
   classify natural language. Its distinct provenance is `explicit-owner-selection`, never Discord
   `message_reference` or `reply_targets`. Trusted metadata can still supply real reply targets through the
   earlier interface, but a title selection must never be placed in that metadata channel.
5. Continue only the returned selected task; completion/snooze/edits still need their normal authorization. The
   original message, candidate task/receipt snapshots and selected receipt remain immutable, while other task
   sequences, global pause, window failures, uncertain send journals and delivery receipts are preserved.

The optional strict `clarifications` mapping records `pending`, write-ahead `resolving`, then `resolved`, or an atomic
`dismissed`/`retired` outcome for a still-pending question. Optional per-hold `responses` retain captures with only one
eligible question. Shared answers stay **unassigned** in optional `clarification_responses`, each with its captured
message and eligible hold IDs; history order never assigns one to the oldest question, and before a retry cycle exists
activity is quarantined there too. Observe, engagement and confirm deduplicate these captures across restarts. An
explicit choice/dismissal atomically binds the capture to the intended eligible question, then its identity is
single-use across holds, and identical completed commands return the stored outcome. Unbound captures remain quarantined
after retirement; neither they nor already-bound response IDs become fresh task replies.

The directory flock serializes admission and resolution. Before engine engagement, the chosen task, selection post and
original binding are durably fenced in a `resolving` record. Engine suppression commits before releasing the hold;
crashes leave it held and an identical command finishes safely, and conflicting choices fail even after an
engine-commit/runtime-commit interruption. Completed retries return the same result without replaying any task operation
and need not refresh history. The exact current task must still match its captured snapshot and remain eligible on first
resolution/recovery. Wrong owner/binding, invalid candidate, edited/missing original, stale/incomplete capture or
unavailable/changed task refuses without task changes: explain the refusal and leave sends held unless the owner
explicitly dismisses the still-pending question using the guarded path below. New unknown messages during a pending hold
are left unclassified (they may be its answer), and selected posts are not later re-engaged.

### Bounded clarification retries and next-window retirement

An ambiguous reply is a question to retry, never a new task. Runtime preflight returns `kind:clarification`, exact
`clarification_ids`, candidate snapshots/titles, a unique event token and a real confirmed candidate receipt anchor.
Compose one short question with the candidate titles for those holds; several questions share one bounded retry
sequence, not one sequence per candidate or an unbounded fanout. Use the existing CLI: `runtime draft`, capture fresh
raw pages from latest through the returned oldest candidate receipt, `runtime observe`, `runtime dispatch`, then fresh
positive `runtime confirm`. No new transport, direct preflight sends, or operator-asserted verified reminders exist. All
candidate receipts (bot/body/time), original owner captures, route and coverage must match; unavailable/stale history
invalidates evidence. Final locked authorization rechecks those raw pages, current holds, config, route, pause, engine
safety and real min/max delivery spacing.

The optional strict `clarification_retry` state saves the hold set, configuration, route, original local window, last
clock, slots/tokens and planned/claimed/missed states. `max_unanswered_followups` is the shared budget; existing min/max
intervals choose randomized gaps, and the first gap starts at the latest captured ambiguous owner timestamp, not an
invented receipt for the conversational question. Each opportunity lasts at most one minute, capped at window end;
expired slots are consumed, never redrawn or caught up. Actual prior retry receipt spacing is also enforced, and zero
budget or no remaining slots means hold without retry. Reopening a process does not reset budget or draw slots again.
Legacy pending records without retry state deterministically derive the same plan from immutable hold identities,
original timestamp and unchanged config, leaving old receipts untouched; absence of retry state supports legacy stores,
while a present null cycle is invalid. Event indexes are integers, never booleans. Claims require matching journaled
attempts; attempts require the matching cycle event, token, index, expiry and hold identities. New drafts fence the
exact intent in their cycle event; older completed cycles without that optional snapshot remain readable, and replaced
cycles may retain terminal audit rows, not orphan active attempts. Unknown state, changed configuration/route or
regressed clocks fail closed.

At the next allowed notification window, preflight retires only still-`pending` questions, retaining originals,
candidate snapshots, responses and release cutoff. This is not midnight rollover: enumerate real instants using saved
timezone, weekdays and notification window, including weekends and DST gaps/folds. No task fields, engagement,
completion or snooze is changed, future ordinary task slots can start clean, and slots missed under the hold are never
revived. The first preflight that retires a hold uses the updated locked release cutoff, including a slot exactly at
window opening, and repeating that timestamp cannot change its eligibility; retired originals and processed retry
responses are not reclassified, and untargeted old receipts before retirement do not immediately recreate stale
ambiguity. Exact old task reply targets remain attribution evidence, not permission to replay sends. New owner activity
in fresh history suppresses stale retries and wakes the normal inbound clarification flow conservatively, not task
engagement. `runtime context` for an explicit retry receipt returns `kind:clarification`, hold identities and snapshots
rather than a task, and trusted reply metadata still uses the same exact owner/route capture contract. Choice/dismissal
use the existing atomic commands; responses remain single-use and identical completed outcomes remain idempotent. A
selection/dismissal admitted while waiting or before final send invalidates the old retry intent. The durable sending
fence is committed before native send, and uncertain attempts remain nonretryable with the same exact-history recovery.

Never retire `resolving`/`resolved` choices or clear global pause, failed/unconfirmed delivery, legacy engine safety
stops or other protections; a safety-blocked hold can remain held beyond the next window, and state must not be edited
to force retirement. Every engine sequence is independently checked for claimed/failed events, even when a stop string
is otherwise safe and no runtime sending row exists (the ordinary tick-to-outbox crash gap or a legacy claim).
Preparation, next-window retirement and final locked send authorization all preserve that uncertainty without repair. A
positive late retry receipt records delivery truth, never task engagement or a new send. Ordinary silent-task follow-ups
keep their existing behavior.

### Dismissing a clarification without selecting a task

After “Do you mean ‘Draft proposal’ or ‘Book appointment’?”, the owner may say “never mind” or “dismiss that question”.
This is explicit conversational intent, interpreted by the skill, **not a runtime text classifier**. Inspect pending
records before engagement on that turn. Use the exact question and trusted later owner post ID; only an explicitly
requested, consented single page including the **oldest candidate receipt** may be used:

```sh
python3 /absolute/skill/scripts/task-coach.py --data-dir /approved/store runtime dismiss-clarification --binding '{"owner":"OWNER","profile":"PROFILE","account":"ACCOUNT","chat":"CHANNEL","thread":"none"}' --clarification-id CLARIFICATION_ID --dismissal-message-id OWNER_DISMISSAL_ID --pages-file /private/fresh-pages.json --history-plan-file /private/history-plan.json
```

The runtime validates the exact current route/binding, persistent nonbot owner, later post ID/timestamp, fresh complete
capture and the existing confirmed receipt anchor (bot ID, body and delivery time). It does **not** require the original
reply to remain present/unchanged or tasks to match snapshots or stay eligible: an edited or deleted original and
edited, closed, snoozed or deleted candidate are precisely why safe discard is useful. It never selects/restores a stale
task, and the stored original and candidate snapshots and all delivery receipts remain immutable. Read back `runtime
status`; on success say “Okay, I won’t apply that reply; both tasks are unchanged” when still true, otherwise “I won’t
apply that reply or make any task changes.” No task fields or engagement change, and no completion, snooze, task
cancellation or global pause is implied. Only that hold is released; other pending questions, pause, failures, legacy
stops and uncertain sends remain. Both original and dismissal message IDs are processed for this binding, so later
engagement/observe/confirm cannot re-ask the same question or turn the cancellation into task engagement. Later slots
remain eligible and never catch up missed ones. For several questions, ask which one by candidate titles; unknown IDs
never mean discard everything. Bare “cancel” is ambiguous: ask “Dismiss this question, cancel a named task, or pause all
check-ins?” before acting. Task cancellation requires its own explicit task authorization; a global pause uses `coach
pause` with readback. Dismissing a question is neither. The runtime trusts the skill's explicit-intent assertion and
supplied tool captures; it cannot authenticate fabricated operator input.

The atomic `pending` → `dismissed` runtime transaction persists the cancellation capture, `explicit-owner-dismissal`
audit result and actual release cutoff, with no engine write. Identical retries (same binding, clarification and
dismissal ID) return that immutable result across restart without fresh history. A different dismissal, a resolution
after dismissal or a dismissal after durable `resolving`/`resolved` refuses. **Never undo a write-ahead resolution**:
suppression may already have committed even if the response was lost. An interrupted `resolving` choice must finish via
the same guarded resolution; changed candidates may still make that recovery refuse and leave the hold in place.
Dismissal is not a repair bypass. Concurrent dismissal/resolution has one serialized durable winner; the other refuses,
and no suppressed task is revived. Wrong owner/binding, absent later cancellation, missing/mismatched receipt anchor,
stale/incomplete history, clock regression, reused cancellation messages or malformed state leave the hold intact.
Freshness is checked under the lock again at release; there is no age bypass after waiting for a lock, and a completed
identical retry only reads the recorded result.

Preflight, draft/dispatch authorization and the final locked send boundary honor the hold. A runtime release cutoff
prevents sending any event whose slot became due before release, even if its ten-minute opportunity remains open; no
catch-up, replay, rescheduling, or quota filling occurs. Later future slots retain normal eligibility, though normal
missed-slot behavior may end a sequence whose opportunity was skipped. Resolving one record does not clear another
pending record, and no clarification operation clears a global pause or an unconfirmed/failed-delivery block. If an
in-flight worker already journaled `sending`, it stays nonretryable even when a new hold prevents the network call;
verify/reconcile independently and do not silently clear that protection. Old episodes already permanently stopped as
`ambiguous-engagement` remain stopped: upgrade and clarification are not restart authorization. This contract cannot
authenticate fabricated operator captures or infer a missing trusted inbound ID; ask/keep held if that context is
unavailable. Synthetic tests do not establish live Discord qualification.

## Final-send authorization and races

The native opportunity is up to ten minutes after a randomized slot, capped at window end, and claims have a separate
120-second authorization lease. At final boundary, reread current task (including title/notes), config, route, pause,
episode, exact token and event state; enforce local day/window, opportunity, actual previous-send min/max spacing and
fresh complete history. No catch-up outside the opportunity, no sending after claim expiry, no automatic resend after
uncertainty; crashes before/after journaling are fail-closed and receipts are separate. There is an unavoidable race
between the final history/task/pause check and the platform accepting a send. Discord does not provide an atomic
conditional send against owner history, so an owner message or pause arriving inside this interval may race with one
already-authorized message. Do not promise zero messages after any possible reply instant; subsequent observation and
confirm stop the episode. Explicit pause plus supported persistent owner posts is the honest scope.

## Synthetic acceptance, not live qualification

From a source checkout (or a copied fixture directory with the installed skill):

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_core_driver.py' -v
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_core_driver.py' -k test_synthetic_full_flow -v
```

The full-flow test uses fictional tasks, deterministic API clocks, real SQLite, real stdlib subprocess sender test
doubles, positive candidate/readback receipts, restart, opener then followup, and owner reply-stop. It does not contact
Discord. Other tests exercise fail-closed errors, uncertainty, pause/task changes, fencing, late reconciliation and
wrapper behavior, and copied-skill and built-wheel tests verify resources independently from source metadata. Actual
user-authorized platform tests remain separate, and only the Discord history adapter is currently implemented.
