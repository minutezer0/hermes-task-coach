# ChatGPT desktop runtime protocol

Experimental desktop integration, Python 3.11+, macOS/Linux POSIX host. No API
key, HTTP service, MCP server, cloud database or Discord connection is required.
The app must have a local executor and native scheduling access. No scheduling
management tool is assumed to exist in every chat. In that case local task use
and plan generation work, while installation/activation remain blocked.

## Boundaries and storage

The launcher wraps the shared v1.0.1 task core with an explicit separate data
directory. Its `desktop.sqlite3` stores one confirmed conversation, a local enable
gate, an asserted native schedule ID, output/engagement journals and Smart Snooze.
The shared task and engine schema are unchanged. The desktop store cannot adopt
an existing unmarked task store or a Hermes outbox. The default ignores
`HERMES_HOME`; never override it to point at Hermes data.

Runtime writes share the core's private directory lock with task edits. A runtime
transaction and engine transaction are separate SQLite commits: interruption can
lose an output but never licenses retry. Persisted native receipts and engagement
are reconciled idempotently for the current engine episode. A local file journal
is not a platform sandbox or proof that ChatGPT actually emitted/read a message.

All examples use the absolute installed launcher and selected data directory:

```sh
python3 -I -B "<skill_dir>/scripts/task-coach-desktop.py" --data-dir "<data_dir>" setup --timezone America/Vancouver --weekdays mon,tue,wed,thu,fri --notification-start 09:00 --notification-end 17:00 --max-tasks-per-window 2 --max-unanswered-followups 2 --min-followup-interval 30 --max-followup-interval 120
python3 -I -B "<skill_dir>/scripts/task-coach-desktop.py" --data-dir "<data_dir>" add "Clean the gutters"
```

Configure using the genuine trusted current conversation ID. There is no default
or synthesized conversation identifier. `--confirm-setup` records the user's
route approval, not installation, live-test or ongoing-send approval.

```sh
python3 -I -B "<skill_dir>/scripts/task-coach-desktop.py" --data-dir "<data_dir>" desktop configure --conversation CHAT_ID --confirm-setup
python3 -I -B "<skill_dir>/scripts/task-coach-desktop.py" --data-dir "<data_dir>" desktop native-plan --conversation CHAT_ID --helper "<skill_dir>/scripts/task-coach-desktop.py"
```

The plan is read-only: it returns the prompt, argument array, RRULE, timezone,
same-chat requirement and initially-paused intent. It does not install or change
a schedule. The five-minute checks are scoped to the allowed days and encompassing
hours; preflight still enforces exact minute boundaries. Very short windows and
native run delays may miss opportunities. Never bypass an expired opportunity.
Every native run can consume model usage even if preflight suppresses output.
Use the same persistent local store, not a per-run worktree's relative directory.

Inspect native controls and tool schemas; create/reuse a paused same-conversation
schedule only after approval and read back its prompt, cadence, timezone,
conversation, local environment and paused state. Keep the helper path stable
through upgrades, and regenerate the native prompt after relocation.

After final approval, record the genuine native schedule ID with `desktop activate
--conversation CHAT_ID --schedule-id NATIVE_ID --confirm-activation`, then resume
through supported controls and read back. Failed resume requires `desktop pause`.
The helper never verifies native schedule state itself. `scheduler_verified:false`
is intentional even when enabled; record actual tool evidence in the conversation.

## One scheduled run

1. Verify the actual current conversation is the configured one. Read the current
   task store only through the installed helper. Reconcile genuine native output
   metadata and explicit owner engagement visible in this same chat before
   planning more work. Do not fetch unrelated conversation history.
2. Run `desktop preflight --conversation CHAT_ID`. This may persist an engine
   episode and is not read-only. A paused store, closed window, Smart Snooze hold
   or absent eligible task returns `wakeAgent:false`. Do not post a check-in on a
   quiet result. If the platform posts run summaries anyway, disclose that native
   limitation and keep the prototype paused pending the user's decision.
3. With `wakeAgent:true`, draft one short question about the returned task and
   run `desktop claim --conversation CHAT_ID --token EVENT_TOKEN --task-hash HASH
   --body TEXT`. Use the returned `task_hash`; edits since drafting cause refusal.
   The helper rechecks gates under the shared lock and journals a nonretryable
   attempt before returning the body. Emit the returned `output` exactly once
   as the final response in this same chat. Do not echo it in commentary too.
4. A returned body is **unverified**, not a native receipt. If genuine native
   assistant message ID and emission timestamp become available through trusted
   context or supported tool readback, record them using `desktop record-output
   --conversation CHAT_ID --token EVENT_TOKEN --message-id NATIVE_MESSAGE_ID
   --emitted-at AWARE_TIMESTAMP`. That can happen on the next scheduled/inbound
   turn. Never use an event token, random ID, local operation ID or guessed time
   as a native message identifier/timestamp.
5. Without genuine output metadata the claimed event remains unresolved and that
   task receives no automatic follow-ups. Other authorized tasks retain their own
   opportunities. Never resend an unresolved output. `record-output` is honestly
   caller-asserted native metadata, not independent platform delivery verification.

The engine's internal receipt calls its state `delivered`; the desktop adapter
reports its actual provenance and does not claim a user read receipt. A send/final
response already in flight cannot be atomically canceled by a later reply. The
same-conversation output operation is outside Python's lock after claim returns.

## Inbound engagement and Smart Snooze

Use `desktop status` to find current output attempts and their task snapshots.
Select only the exact task/event established by trusted reply targets or explicit
owner intent. A visible reply can establish engagement even before outbound
metadata was available; it does not authorize a fabricated outbound receipt.

```sh
python3 -I -B "<skill_dir>/scripts/task-coach-desktop.py" --data-dir "<data_dir>" desktop engage --conversation CHAT_ID --token EVENT_TOKEN --message-id INBOUND_ID --intent engaged
```

Use `skip-for-now` for a skip and `start-work` only for explicit starting-now
intent. Engagement stops that task's current sequence; completion and snooze need
their own explicit task commands. Native IDs and selections are caller assertions
from trusted context, not values discovered by the helper. Missing trusted inbound
IDs mean automatic engagement recording is unavailable. Do not invent them.

`desktop smart-snooze --enable|--disable` controls an opt-in hold through the
remaining allowed local window. General replies never create the hold. Disabling
clears it; replaying an old start-work reply never recreates/extends it, including
messages first recorded while off. The hold uses an absolute DST-aware window end
and expires without changing any task. Schedule/configuration changes do not revive
stopped sequences. There is no catch-up, retry, backlog or cross-chat awareness.

`desktop pause` closes the local gate and stops the current engine window. Then
pause the native schedule and read back. Explicit reactivation clears the global
pause but never revives today's stopped sequence. Preserve journals on reinstall.

## Optional fresh test and live acceptance

With the native recurring schedule still paused, explicit one-test approval allows
`desktop prepare-test --conversation CHAT_ID --confirm-test`. It prepares one due
opener only in an allowed day/window with an eligible task, no prior episode and
no output attempts. It refuses global pause and an active runtime. It never sends
or grants ongoing-send permission. Follow preflight/claim/output above once.
Skip an unavailable test rather than reset state or add an unwanted task.
The one-event test occupies that day's episode. Activating afterwards does not
add more events or follow-ups to it; explain that ordinary randomized planning
starts on a later allowed day rather than promising another check-in today.

Before claiming native parity, test on the user's macOS installation:

- A clean local plugin install can run the helper from an unrelated working
  directory and preserve tasks across app restart/plugin replacement.
- A paused native job never sends; activation readback matches the chosen chat,
  local data directory, prompt, cadence and timezone. Quiet runs stay quiet.
- One authorized check-in appears once in the existing chat, with no extra run
  conversation or summary. Inspect actual native assistant identity/timestamp.
- A real reply records engagement before help; a pending follow-up is suppressed.
  If IDs are missing, disclose degraded follow-ups and leave ongoing scheduling
  paused unless the user explicitly accepts that limitation.
- Smart Snooze suppresses other tasks through window end only for start-work.
- Changing destination/settings during final review updates all affected native
  artifacts before renewed approval. Local pause blocks output even if native
  controls fail; no uncertain output is retried after restart.

No live check-in, schedule or real user store is created by repository tests.
Public directory review, native Windows, mobile remote behavior and cloud hosting
are outside this prototype. Local-only commands work without scheduler access.

## Platform documentation

- [Native scheduling and existing-chat tasks](https://learn.chatgpt.com/docs/automations)
- [Desktop-only skill packaging](https://developers.openai.com/plugins/deploy/desktop-only)
- [Plugin manifests and onboarding](https://developers.openai.com/plugins/build/plugins)
