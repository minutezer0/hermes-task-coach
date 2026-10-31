# Native Hermes runtime: optional Discord adapter

No new bot account, SDK, dependency or importing Hermes into arbitrary Python.
The model uses Hermes's supported `discord` tool for history. The helper launches
native `hermes send` as an argument array, not a shell command. The core task and
coaching engine remain transport-neutral. Only Discord history is implemented;
unsupported platforms are rejected, never silently allowed to follow up.

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
PATH. Run and read it back before executing the returned cron_argv as an argument
array. This creates a native, initially paused cron with:

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
and paused job. Keep the job paused until the user authorizes a live pilot and
it demonstrates actual send/readback, owner reply-stop and contextual continuation.
Neither native installer success nor synthetic fixtures qualify real messaging.

## Complete CLI lifecycle

Prefix each command with the explicit installed helper and consistent data path:

| Command | Effect |
|---|---|
| `runtime preflight` | Nonclaiming due inspection; quiet without confirmed setup |
| `runtime status` | Confirmed route and durable outbox rows |
| `runtime configure --route JSON --confirm-setup` | Explicit route opt-in, not account setup |
| `runtime native-plan --profile-home PATH --python PATH --helper PATH --hermes PATH` | Emit wrapper/paused cron/scoped inbound artifacts only |
| `runtime draft --event-token TOKEN --body-file PATH` | Immutable plain text draft and unique fence; no claim/send |
| `runtime observe --event-token TOKEN --fence FENCE --pages-file PATH` | Validate fresh full history and derive evidence/reply-stop |
| `runtime dispatch --event-token TOKEN --fence FENCE --hermes PATH` | Exact-token claim, final authorization, durable sending, one native send attempt |
| `runtime confirm --event-token TOKEN --fence FENCE --pages-file PATH [--message-id ID]` | Exact sent-message readback and receipt reconciliation |
| `runtime context --binding JSON` | Latest confirmed task ID/receipt plus freshly reread current task (null if deleted) |
| `runtime engagement --binding JSON --pages-file PATH` | Derive persistent owner engagement, stop current matching episode, return context |
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

Only persistent posts by the exact nonbot owner after the anchor engage; textless
attachment posts count. Other users and bots do not. Evidence fields are derived
by the helper; callers cannot enable followups with complete/engaged/qualified
booleans. Failure to refresh evidence invalidates the old evidence for that draft.
Confirm also checks owner posts newer than the sent message and immediately stops
if present. No typing indicators, read receipts, transient/deleted posts, voice
presence, or cross-session memory claims are made.

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
