# Native Hermes runtime: optional Discord adapter

No new bot account, SDK, dependency or importing Hermes into arbitrary Python.
The model uses Hermes's supported `discord` tool for history. The helper launches
native `hermes send` as an argument array, not a shell command. The core task and
coaching engine remain transport-neutral. Only Discord history is implemented;
unsupported platforms are rejected, never silently allowed to follow up.

## Multiple tasks in one daily window

`max_tasks_per_window` defaults to 3 for new stores and accepts integers 1..10.
Existing configurations without the key retain 1 until an explicit setup update.
Ask the maximum-tasks question only for proactive check-ins, showing the default
or current saved value before offering to keep it or customize.

Each distinct selected task has its own opener and bounded follow-ups. A reply
stops only the matching task's follow-ups; later task check-ins remain scheduled.
Global pause, changed configuration/binding and uncertain delivery still suppress
unattended sends. Sequences are planned without overlap and with an inter-task
gap of at least 30 minutes (or the saved minimum follow-up interval if larger).
Fewer eligible tasks or insufficient window space produces fewer sequences.
Context returns an explicitly targeted confirmed task, or the latest confirmed
receipt when only one distinct task is represented. Untargeted multi-task context
returns null rather than guessing; future planned tasks are never returned.
Keep the exact event token and receipt anchor: never apply an older task's
engagement to a later task. An explicit one-check-in test stays one opener with
no follow-ups or additional tasks, regardless of the maximum.

## Confirmed onboarding, paused native job

Initialize task preferences with `setup`; this does not enable automation. Ask the
user to select an already configured Hermes destination. Use native
`hermes send --list` and trusted inbound gateway context, not account secrets or
a guessed nickname. Resolve the exact numeric channel/thread, nonbot owner, bot
ID, active profile and account identity. Binding is exactly:

```json
{"owner":"OWNER_ID","profile":"ACTIVE_PROFILE_ID","account":"ACCOUNT_ID","chat":"CHANNEL_ID","thread":"none"}
```

For a Discord thread, chat is the parent channel, thread is its actual ID, and
channel_id/destination identify the thread itself (`discord:THREAD_ID`). For no
thread, use the literal `none`, not an omitted field or wildcard. These examples
are placeholders, not real account identifiers.

With explicit user confirmation of binding and preferences:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime configure --confirm-setup --route '{"binding":{"owner":"OWNER_ID","profile":"ACTIVE_PROFILE_ID","account":"ACCOUNT_ID","chat":"CHANNEL_ID","thread":"none"},"platform":"discord","destination":"discord:CHANNEL_ID","channel_id":"CHANNEL_ID","bot_id":"BOT_ID"}'
python3 "<skill_dir>/scripts/task-coach.py" runtime status
python3 "<skill_dir>/scripts/task-coach.py" runtime native-plan --profile-home ABSOLUTE_ACTIVE_PROFILE_HOME --python ABSOLUTE_PYTHON --helper "<skill_dir>/scripts/task-coach.py" --hermes ABSOLUTE_HERMES_EXECUTABLE
```

All commands also accept `--data-dir PATH` **before** the subcommand. `configure`
requires `--confirm-setup`, stores a separate confirmed route in outbox.sqlite3,
and rejects changing that route once drafts exist (use a separately approved data
directory). Local config automation_enabled remains false. The runtime route is
the separate explicit opt-in; `live_verified:false` is truthful status, not an
activation boolean. There is no `qualified:true` escape hatch.

`native-plan` only returns JSON artifacts: `script_path`, `script_text`,
`cron_argv`, `inbound_instruction`, `initially_paused:true`, `live_verified:false`.
No profile writes, jobs, messages or account changes occur. Show these artifacts
and obtain approval before installing them. The wrapper path must resolve under
the active profile's scripts directory. Save script_text verbatim to script_path
as a private executable (0700), never overwrite an existing script without review.
The shebang and subprocess use explicit interpreter/helper/data paths, not cwd or
PATH. Read it back before executing the returned cron_argv as an argument
array. Do not run the wrapper against user data before preparing an intended
fresh-setup test: it calls preflight and can persist a daily episode that makes
`prepare-test` refuse. This creates a native, initially paused cron with:

```
hermes cron create 'every 1m' PROMPT --name task-coach --skill task-coach --script task-coach-preflight.py --deliver local --failure-deliver local --paused
```

The `--script` argument is relative to the active profile's `scripts` directory;
the separate `script_path` artifact is absolute for writing and verification.
No `--no-agent`: the agent must read history and compose human text. The cron
wrapper takes no arguments. Its last nonempty stdout line is always a JSON object
with literal wakeAgent:false on subprocess failure, malformed/missing output or
30-second timeout; otherwise it relays the validated preflight boolean. Native
cron can wake an agent on process failure without that wrapper. Keep final and
failure delivery local: explicit sends own destination delivery, avoiding duplicate
messages or native duplicate-target skips.

Add **only** the returned scoped inbound instruction through the user's approved
normal-inbound instruction workflow (for example, an explicitly approved appended
section in existing instructions). Never replace SOUL, patch installed Hermes
sources, or inspect its internal databases. The snippet applies only to the exact
confirmed owner/profile/account/chat/thread. Read back the installed instruction
and paused job. Installation approval can cover wrapper, paused job and exact
scoped snippet together in plain language; it is not send permission. Keep the job
paused for a separately authorized test. Verify actual send/readback and contextual
continuation/owner engagement; a single-event test cannot demonstrate cancellation
of a live follow-up. Disclose that remaining limit and obtain separate authorization
for any broader bounded pilot or ongoing activation. Neither native installer
success nor synthetic fixtures qualify real messaging.

## Explicit ONE-check-in fresh-setup test

With the exact route already confirmed, an eligible task saved and the current
local day/time inside the saved allowed window, ask explicitly to send **one**
check-in to that route. No permission to change days/windows or clear a global
pause is implied. Keep the native recurring job paused throughout; do not resume
it to test. Use the same approved data directory and installed helper:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime prepare-test --confirm-test
python3 "<skill_dir>/scripts/task-coach.py" runtime preflight
```

Preparation never sends, claims, writes an outbox row or changes cron. It persists
one newly generated planned opener with durable episode
`purpose:one-check-in-test`, the current minute slot and a normal ten-minute
opportunity capped at window end. The config is unchanged; there are **zero
follow-ups**, regardless of saved follow-up limits. The result has
`test_prepared:true`, `wakeAgent:false` and the persisted `episode`. Run normal
preflight, draft, dispatch and confirm for this exact event; real history matching
the exact bot/body/time/route is still required. No receipt/fence/history rule is
relaxed, and uncertain attempts remain permanently nonretryable. Then use normal
context/engagement with real owner reply history and continue the task in chat.

The conservative supported scope is **no existing episode at all and an entirely
empty outbox**. Coach status with `episode:null` is okay. Any active plan, stopped
empty episode, old-day episode, draft, sending/uncertain or confirmed journal
refuses unchanged. This intentionally means existing installations may not qualify;
no automatic reset, archival, token reuse, database deletion or test retry is
supported. The command also refuses missing/invalid route, global pause, clock
regression, unavailable task, disallowed day or outside-window time. There is no
production clock flag or day/window bypass. A repeat preparation refuses even if
the first event was never drafted. After a one-event test, today's episode remains
complete/stopped rather than becoming a new randomized plan; a separately enabled
ongoing job can plan on a later allowed day through the ordinary engine.

Preparation holds the same directory flock as runtime writes and engine operations,
reads the outbox in a read-only SQLite transaction and commits the engine episode
under that lock. Only the engine is written. A concurrent ordinary planner either
wins first (test refuses) or sees the new single-event episode; neither can
replace an existing token. Any stale token/fence still fails normal authorization.
Supported operations preserve audit/replay records; manual database edits or
processes ignoring the lock are outside the guarantee. Config/task edits may
invalidate preparation and are rechecked at dispatch. The platform check/send
race remains unchanged. Older helpers that do not recognize the purpose field
fail closed: upgrade the bundled runtime together before using this command.

At the checkpoint, speak naturally: distinguish verified delivery, recognized
owner engagement and task continuation from **unverified live follow-up
suppression**. Do not label no-follow-up behavior as a suppression experiment.
Keep cron paused if verification fails. Installation, test authorization and
ongoing activation are separate permissions. This feature does not monitor cron
pause state itself: keeping the job paused and reading back that exact job are
operator obligations, not an invented helper-enforced schedule fence.

Do not add a five-minute test follow-up or require a follow-up pilot during setup.
The optional one-check-in delivery test is the onboarding test; disclose that
cancellation of a pending live follow-up remains unverified, then obtain distinct
ongoing-send approval. After that approval, read back the active schedule and
verify an eligible task and a supported upcoming allowed opportunity before
finishing naturally: “Task Coach setup complete—you’ll be hearing from me soon!”
If today's episode is stopped, explain that regular check-ins start on the next
allowed day rather than promising a send soon today. Paused installations must
say check-ins are paused, not that proactive setup is complete.

## Complete CLI lifecycle

Prefix each command with the explicit installed helper and consistent data path:

| Command | Effect |
|---|---|
| `runtime preflight` | Nonclaiming due inspection; quiet without confirmed setup |
| `runtime restart --confirm-restart` | Replan only today's untouched stopped episode; empty outbox required; no send or cron change |
| `runtime status` | Confirmed route and durable outbox rows |
| `runtime configure --route JSON --confirm-setup` | Explicit route opt-in, not account setup |
| `runtime native-plan --profile-home PATH --python PATH --helper PATH --hermes PATH` | Emit wrapper/paused cron/scoped inbound artifacts only |
| `runtime draft --event-token TOKEN --body-file PATH` | Immutable plain text draft and unique fence; no claim/send |
| `runtime observe --event-token TOKEN --fence FENCE --pages-file PATH` | Validate fresh full history and derive evidence/reply-stop |
| `runtime dispatch --event-token TOKEN --fence FENCE --hermes PATH` | Exact-token claim, final authorization, durable sending, one native send attempt |
| `runtime confirm --event-token TOKEN --fence FENCE --pages-file PATH [--message-id ID]` | Exact sent-message readback and receipt reconciliation |
| `runtime context --binding JSON [--reply-to-message-id ID]` | Exact target receipt/current task, or latest receipt only when one distinct task is known; null for unrelated targets or multiple tasks without a target |
| `runtime engagement --binding JSON --pages-file PATH [--reply-to-message-id TARGET --inbound-message-id ID]` | Attribute captured owner posts, stop only their matching task sequences, return the newest owner's context or null; paired flags select one trusted inbound reply |
| `coach pause` / `coach resume` / `coach status` | Persistent controls and readback; resume never revives stopped episodes |

Production CLI has no synthetic clock or RNG flags. API tests may inject clocks.
Draft returns token/fence/intent/task/previous/route. Repeat identical draft is
idempotent; conflicting text is rejected. Plain text must be nonempty, at most
1800 characters, with no MEDIA directives. Do not compose shell commands from
task text. Use private files for bodies/history. Keep outputs inside the same
approved profile/data scope.

Dispatch receives an absolute native executable and invokes exactly:

```python
[hermes_path, 'send', '--json', '--to', destination, '--', body]
```

The `--` ends native option parsing: even a body beginning with `--file=` or
`--to=` stays literal message text and cannot read a file or override the route.

A claimed intent is not counted as a delivery. Sending is committed before the
subprocess; there is no retry transition out of sending. Timeout (45 seconds),
crash, invalid JSON, negative exit, missing message ID, skipped or error payload
remain uncertain/nonretryable. A success response must be a JSON object with
literal success:true, nonempty string message_id, no skipped/error. Even then,
state stays sending until exact bot/content/time/route readback. Confirm sets
cursor to the sent ID itself so replies between send and readback are not lost.

If a crash lost the send response, `--message-id ID` can identify a candidate from
real history for a previously journaled sending attempt. It cannot fabricate an
attempt or retry. Exact bot/body/send-time matching is mandatory. Without a
journaled candidate ID, capture fresh history from latest through **strictly
before attempted_at**, or to complete end of history (a short final page, including
an empty terminal page). Cover the whole interval from the attempt to the fresh
readback, not just the selected candidate. All raw messages and pages are validated,
including those older than the selected candidate on its page. Exactly one message
may match the bot, body and timestamp in that interval; multiple matches reject
recovery whichever ID is selected. An operator's choice is not delivery proof.
Missing coverage leaves the attempt uncertain; never resend. A journaled positive
candidate ID instead requires exact readback through that ID; a conflicting
operator ID is rejected. Confirmed receipts are immutable even after day rollover
and restart. Repeating the same ID (or omitting it) returns the stored receipt
without changing accounting or requiring a new capture; another ID is rejected.

Late confirmation records the truth without clearing pause/engagement or
reviving an expired episode. A platform outcome that itself arrives after the
opportunity still records truth for the already journaled on-time attempt; it
never authorizes a new late send. If the engine has rolled to a newer day, the old
receipt lives in the outbox; the new episode is untouched.

## Explicit, narrowly scoped same-day restart

Finish preferences and add/verify an eligible task **before** first preflight.
Preflight can persist a stopped `task-unavailable` episode when tasks are empty;
changing tasks/settings alone does not revive it. `coach resume` never restarts a
stopped episode. An explicitly authorized recovery for this untouched case is:

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime restart --confirm-restart
python3 "<skill_dir>/scripts/task-coach.py" coach status
python3 "<skill_dir>/scripts/task-coach.py" runtime status
```

Use the same approved `--data-dir` before each subcommand if applicable. Restart
uses the real UTC production clock after acquiring the storage lock; there is no
CLI date/time/token override. Deterministic API clocks are for synthetic tests.
The episode must already exist, be stopped, and belong to **today in both its
saved timezone and the current configured timezone**. The confirmed runtime route
must be valid and its binding must match that episode. Global pause and a clock
older than the last tick are refusals, not flags to clear automatically.

**Zero prior events means zero**, not merely zero deliveries: planned, claimed,
failed and delivered events all refuse. **The entire outbox must be empty**, even
if a row appears historical. Drafts are durable pending work; sending/uncertain
rows may still be in flight, and confirmed rows are permanent safety/audit.
Unknown or corrupt formats fail validation rather than being treated as empty.
This is deliberately stricter than trying to classify relevant rows by dates.
It prevents resurrecting a reused same-day token or a worker's old authorization;
no old token is recycled, no journal is erased, and no receipt is retried.

Restart holds the shared directory flock while reading a read-only outbox
transaction and validating/replacing the coaching episode in one SQLite
transaction. Only coaching state is written; no cross-database write commit is
needed. The lock serializes against engine prepare/tick and runtime journal
writes. Multi-step draft/dispatch workers cannot have an authorized old event in
the accepted zero-event case: any prior planned event alone refuses restart; any
journal row also refuses it. Stale tokens/fences still fail existing checks.
This guarantee applies to supported local operations, not manual database edits
or arbitrary hostile processes ignoring the lock. Concurrent task/config edits
can still invalidate the fresh plan and are rechecked by preflight/dispatch;
restart does not relax final-send authorization or the platform send race.

On success it rereads current preferences/tasks, chooses an eligible task, and
plans only minute-aligned slots **strictly later than now** within today's
configured days/window. Before-window execution may plan later today; it never
catches up a past/current minute. No eligible task or no remaining slots is a
ValueError with rollback. Other refusals also leave the existing episode and
journals intact. An active second restart refuses instead of regenerating tokens.

Success is JSON containing `restarted:true`, `wakeAgent:false`, `previous_stop`
and the fresh `episode`. API refusals are descriptive ValueErrors; CLI refusals
use the normal nonzero exit and stderr error. All tasks, saved config, route,
message/evidence replay records and outbox bytes are preserved. The existing
bounded recent-selection history is updated as for an ordinary new plan. The
empty stopped episode is replaced, not archived as a delivery. Restart does not
claim, send, clear pause, create/enable cron, or promise an immediate check-in.
Native cron pause and global coaching pause are separate controls; keep a pilot
schedule paused until separately approved. Never edit/delete a database, prune
an outbox or bypass dispatch as an operator workaround for a refused restart.

## History capture format and coverage

Use native `discord` action `fetch_messages` with exact channel_id, `limit:100`.
Start at latest with neither before nor after; then use `before` equal to the
oldest returned message ID. Do not use an after-only query: forward limits can
hide replies. Continue backward to the **exact** previous sent ID for observe, or
the journaled candidate sent ID for confirm. For lost-response recovery with no
journaled candidate, continue past the selected ID until history reaches strictly
before the attempt start or a short/empty final page proves end of history. Do
not trim a raw page at the selected ID. Capture each unmodified raw tool result:

```json
[
  {
    "binding": {"owner":"OWNER_ID","profile":"ACTIVE_PROFILE_ID","account":"ACCOUNT_ID","chat":"CHANNEL_ID","thread":"none"},
    "channel_id":"CHANNEL_ID",
    "before":null,
    "observed_at":"2030-01-07T12:00:00Z",
    "result":{"messages":[{"id":"100","content":"actual bot body","timestamp":"2030-01-07T11:59:59Z","author":{"id":"BOT_ID","bot":true},"attachments":[]}],"count":1}
  }
]
```

The illustrated values are fictional. Never invent messages or replace the raw
result with a summary. observed_at is the live UTC time recorded at **request
start**, not when the result finishes. Subsequent envelopes use before=oldest ID
from the preceding page and their own request-start timestamp. Every page must be
at most 60 seconds old at authorization; refresh **from latest** if pagination is
slow. Budget is 20 pages (up to 2000 messages). Missing anchor, short page before
anchor, empty/error/malformed output (except an empty terminal page proving end
of history for lost-response recovery), route mismatch, duplicate/nondecreasing IDs,
nonordered/future timestamps or stale capture rejects coverage. Permission/content
limitations that prevent exact send readback mean keep the job paused. History
comes from agent tool captures, not cryptographic provenance: the agent/operator
must use actual native tool output, not manually assert qualification.

### Reply attribution and trusted capture interface

Current native Discord `fetch_messages` returns `id`, `content`, `author`,
`timestamp`, `edited_timestamp`, `attachments`, `reactions`, and `pinned`.
It does **not** expose `message_reference`. History order alone cannot tell
whether an owner post replies to task A, task B, or an unrelated message. Do not
add invented references to `result`, infer targets from message text, or claim
history-only delayed-reply attribution has been verified live.

When a trusted inbound event/adapter actually exposes a reply target for the exact
bound owner and destination, preserve it separately from the unmodified raw result.
An optional page-envelope field supplies only those known targets, keyed by an
owner message ID present on that page:

```json
"reply_targets": {"300": "100"}
```

Here the fictional owner message `300` explicitly replies to confirmed check-in
`100`. A value of `null` is allowed **only** when trusted metadata positively says
that post has no reply target; absence of a mapping means unknown, not null. Each
entry must match a captured nonbot owner post on that page. Malformed IDs,
nonowner posts, missing messages, or conflicts with available raw references
reject the capture. A raw reference from a metadata-capable adapter is also
supported and validated, including its channel. This is a trusted capture contract,
not an implemented gateway hook, signature, or source of metadata that the current
Discord history tool lacks. If trusted inbound metadata is not exposed to the
caller, leave the mapping absent and accept the conservative block.

For one trusted inbound explicit reply, `runtime context --binding JSON
--reply-to-message-id TARGET` returns that exact receipt and current task.
`runtime engagement --binding JSON --pages-file PATH --reply-to-message-id TARGET
--inbound-message-id ID` requires **both** IDs and verifies the exact owner message
in fresh history through the target receipt. Flags select only that inbound post;
observe/confirm still require complete interval captures with any available trusted
metadata for each post. Unknown/non-coach targets return no coaching context and
do not count as engagement. Do not substitute a guessed target to avoid null.

Without a target, context returns the latest receipt only while the binding's
confirmed journal contains one distinct task. With multiple tasks it returns null,
including across days: audit receipts are retained, not silently forgotten. For
history-only engagement, use `runtime status` to find the latest confirmed receipt
anchor and capture through it. Persistent nonbot owner activity can use legacy
single-task temporal engagement when only one prior task is a candidate; this
stops prompts for that sole task, but does **not** prove a reply reference or exclude
unrelated activity. A known unthreaded post similarly uses the latest prior
receipt. An explicit reference always takes precedence: replies to unrelated
messages do not engage, and delayed replies to A do not stop B. Every owner post
is attributed independently; the newest owner's attribution determines the
engagement return context, while earlier correctly attributed posts can still
stop their own task sequences. Attachments count; other users and bots do not.

With multiple prior tasks and missing target metadata, the driver cannot safely
attribute the owner post. Engagement returns `engaged:false`, `context:null`,
`error:"ambiguous-engagement"`; observe saves incomplete, error-bearing evidence;
confirm still records the verified delivery truth. All three block the current
window with `ambiguous-engagement`, not a guessed `owner-engaged` task. Later
captures/clarification do not revive the stopped window. No owner posts means no
attribution ambiguity and complete negative evidence can authorize followups.
Failed refresh still invalidates earlier draft evidence. No typing indicators,
read receipts, transient/deleted posts, voice presence, or cross-session memory
claims are made.

## Final-send authorization and races

The native opportunity is up to ten minutes after a randomized slot, capped at
window end. Claims have a separate 120-second authorization lease. At final
boundary, reread current task (including title/notes), config, route, pause,
episode, exact token and event state; enforce local day/window, opportunity,
actual previous-send min/max spacing and fresh complete history. No catch-up
outside the opportunity, no sending after claim expiry, no automatic resend after
uncertainty. Crashes before/after journaling are fail-closed; receipts are separate.

There is an unavoidable race between the final history/task/pause check and the
platform accepting a send. Discord does not provide an atomic conditional send
against owner history. An owner message or pause arriving inside this interval
may race with one already-authorized message. Do not promise zero messages after
any possible reply instant. Subsequent observation and confirm stop the episode.
Explicit pause plus supported persistent owner posts is the honest scope.

## Synthetic acceptance, not live qualification

From a source checkout (or a copied fixture directory with the installed skill):

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_core_driver.py' -v
python3 -W error::ResourceWarning -m unittest discover -s tests -p 'test_core_driver.py' -k test_synthetic_full_flow -v
```

The full-flow test uses fictional tasks, deterministic API clocks, real SQLite,
real stdlib subprocess sender test doubles, positive candidate/readback receipts,
restart, opener then followup, and owner reply-stop. It does not contact Discord.
Other tests exercise fail-closed errors, uncertainty, pause/task changes, fencing,
late reconciliation and wrapper behavior. Copied-skill and built-wheel tests verify
resources independently from source metadata. Actual user-authorized platform
tests remain separate. Only the Discord history adapter is currently implemented.
