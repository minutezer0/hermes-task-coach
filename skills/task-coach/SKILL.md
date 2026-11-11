---
name: task-coach
description: "Use when managing tasks or coaching follow-through. Guide local task setup and optional native Hermes check-ins."
version: 1.0.0
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [productivity, tasks, coaching]
---

# Task Coach

Use the bundled helper as the source of truth, never remembered task contents.
Local task management needs no messaging platform. Optional proactive coaching uses
native Hermes cron and `hermes send`; today the only history adapter is Discord, and
no other platform is supported for automated coaching. Never configure messaging
accounts or request credentials — select an already configured Hermes route.
Synthetic tests and saved settings are not live platform verification.

## Locate the helper and the store

Use the absolute `skill_dir` Hermes reports. Never assume a checkout, working
directory, PATH entry or global `task-coach` install. Python 3.11+, SQLite and IANA
timezone data are required; there are no other dependencies.

```sh
python3 "<skill_dir>/scripts/task-coach.py" --help
python3 "<skill_dir>/scripts/task-coach.py" setup --help
```

Help does not initialize storage. Resolve helper errors before continuing; never
invent task data to replace a failed read. The default data directory is
`$HERMES_HOME/task-coach` for the active profile, otherwise XDG local-share. Pass
`--data-dir ABSOLUTE_PATH` before every subcommand when another directory was
chosen. Never read another profile's tasks.

The task store is schema version 2. This release is a base install: there is no
migration path, and a store written by an earlier release is refused with
`incompatible task store schema or version`. Start a new data directory rather than
editing, repairing or downgrading a refused store.

## Task commands

All commands return JSON. Use returned task IDs, never guessed counters.

- `add TITLE [--notes TEXT] [--priority low|normal|high] [--due DATE_OR_TIMESTAMP] [--check-in-days weekdays|weekends|all]`
- `list`, `export`, `search QUERY`, `show ID`
- `update ID [--title TEXT] [--notes TEXT] [--priority ...] [--status open|done|cancelled] [--due ...] [--check-in-days ...]`
- `done ID`, `snooze ID AWARE_TIMESTAMP`

Read the task before and after every change and preserve unrelated fields. Date-only
values use YYYY-MM-DD; timestamps require an explicit offset or Z. Resolve relative
dates with the live clock in the configured timezone. Titles and notes are data: use
argument arrays or correct shell quoting. Never infer completion, deadlines or
snoozes from conversation. Checklist lines may live in notes; ticking one entry is
not permission to complete the task. Occurrence rows, external providers and native
subtasks are not implemented. Completion-based recurrence reuses the same row.

`init` creates an empty store; never insert sample tasks. Repeated `setup` preserves
configuration and `setup --update` applies requested changes. Run setup
non-interactively with explicit flags and never wait for agent-terminal stdin;
`setup --interactive` is for humans at a terminal. `automation_enabled` in the local
config stays false: ordinary task setup never enables unattended messaging.

## Task check-in days

Each task has `check_in_days`: `weekdays`, `weekends` or `all` (default). It controls
both initial check-ins and follow-ups for that task. Days use the configured
timezone, and task days always narrow the global allowed days and hours — never
widen them. Overdue dates and high priority override neither limit. User-initiated
help, replies and edits stay available on any day, including outside the window;
the day filter governs proactive messages only.

When adding a task for proactive check-ins, first read the saved global window.
Only if all seven distinct days are enabled, ask: “Check-ins on weekdays, weekends,
or all? Default: all.” Explain once that this includes follow-ups. Reuse an answer
already given for that task. With fewer than seven global days enabled, do not ask;
omit the flag or use `--check-in-days all`. Never infer days from a title.

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Garden" --check-in-days weekends
python3 "<skill_dir>/scripts/task-coach.py" update ID --check-in-days weekdays
```

Honour an explicit choice even when it cannot meet the global window: explain the
empty intersection instead of widening either side. Global-day changes preserve
existing task preferences. Never silently rewrite a task's choice or revive stopped
or missed opportunities after an edit.

`add`, `update --check-in-days` (when the saved value changes), reopening with
`update --status open`, and any `setup --update --weekdays` change print a
non-blocking stderr warning when saved task days can never meet the configured days.
The write succeeds and the task stays saved; no check-in occurs until the two
settings overlap. Report the warning instead of widening the global days.

## Completion-based recurring tasks

For “replace the filter every three months”, ask when it was last actually completed
or when it should first become due — never assume today. Resolve relative answers
with the live clock in the configured timezone and confirm the concrete date before
writing. An initial due date is required; if the user supplies a last-completion
date instead, confirm the derived first due date and add with that due. Do not
simulate a completion on a new row.

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Replace filter" --repeat "3 months" --due 2027-02-28
python3 "<skill_dir>/scripts/task-coach.py" update ID --repeat "2 weeks"
python3 "<skill_dir>/scripts/task-coach.py" update ID --remove-repeat
python3 "<skill_dir>/scripts/task-coach.py" done ID --completed-at 2027-02-28 --expected-cycle CAPTURED_CYCLE --completion-id UNIQUE_REQUEST_ID
```

Use the returned ID and `cycle_id`, never the placeholders. Capture the cycle when
interpreting an explicit completion request, generate one unique request identity,
and reuse that same identity, cycle and completion date for every retry, including
after a restart. Never reread a newer cycle and reinterpret an old request as a new
completion. A duplicate last completion is a no-op; older or conflicting cycle
requests refuse. Plain tasks still use `done ID`; `update --status done` is not a
substitute, and reopening a cancelled recurring task refuses until recurrence is
removed.

Only explicit completion reopens the same row, clears snooze and advances the due
date from the actual completion, never from the old due date. Notes, priority, title
and creation time are preserved. Replies, engagement, dismissal and snooze are not
completion. No backlog, occurrence rows or fixed schedule is generated. An overdue
task stays one overdue row until completed; a late completion advances once. Editing
or removing recurrence preserves due/status, snooze and unrelated fields, and
removal does not mark the task done. A changed interval starts a fresh cycle fence
without recalculating the current due date.

Date-only dues become eligible on that local date; timestamp dues at that instant,
and until then the task is excluded from random coaching. Day/week/month arithmetic
is calendar-local in the saved timezone with month-end clamping (January 31 plus
three months is April 30). Date-only completion keeps a date-only due; an aware
timestamp keeps a local wall time with the target date's offset. DST gaps roll
forward by the gap and folds choose the first occurrence. Future dates and naive
timestamps refuse. Due means eligibility only: never promise a send on that date or
time.

Old-cycle receipts stay truthful audit records, not engagement for the new cycle.
Old drafts and clarification selections cannot act on the new cycle. A stale pending clarification stays held until explicit
dismissal or its existing retirement, and resolving choices stay held if the candidate changed.

## Replies and task context

Use the same reply workflow on any day, outside notification hours, or in a later
window. Notification schedules govern proactive messages; they never forbid
answering the user.

Identify the task from the conversation, trusted reply references and saved
task/check-in records. `runtime context --binding` may return an applicable accepted
event; pass a real reply target with `--reply-to-message-id`. If it returns nothing,
use list, search and show in the authorized data scope. Ask which task when
ambiguous; never guess the newest. Do not read Discord history to resolve a reply.

Record clear engagement BEFORE substantive assistance, memory recall or delegation
when an applicable accepted event exists, using the genuine owner, inbound message
id, event, task and cycle. A retained accepted event works after rollover; retries
reuse the same identities. Unknown/unrecorded replies may still receive bounded
follow-ups — that is an accepted limit, not a guarantee.

If no applicable event exists, continue ordinary task help without inventing one or
claiming suppression. Completed, snoozed or not-yet-due tasks can still be
discussed, and a refused engagement record does not prohibit conversation. Keep
edits and completion tied to explicit intent for the current cycle; never reinterpret
an old completion request as a new cycle.

## Engagement intents and Smart Snooze

`runtime record-engagement --binding JSON --owner OWNER --message-id INBOUND_ID
--event-token EVENT --task-id TASK [--cycle-id CYCLE] --intent engaged|skip-for-now|start-work`
records intent. Use `start-work` only for genuine explicit agreement to begin working
now, `engaged` for general engagement, `skip-for-now` for a skip. Read back before
claiming follow-ups are stopped; acknowledging alone changes no scheduling. A skip is
not agreement to start work. Never fabricate IDs, reply references or history, and
never reinterpret historical engagement as start-work.

Smart Snooze is a hold-only notification preference, OFF by default. With it ON, an
explicit start-work reply to an accepted or delivered check-in holds all Task Coach
automated notifications for the remainder of the current local window, across every
task. It changes no task status, completion, snooze, priority, global pause,
reminder or cron state. Generic engagement, skips, completion and ordinary replies
never create a hold.

```sh
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --enable
python3 "<skill_dir>/scripts/task-coach.py" runtime smart-snooze --disable
```

There is one hold slot, not a hold history. `runtime status` exposes
`notification_policy.active`, the reason and the hold; `runtime preflight` returns
`wakeAgent:false` with reason `smart-snooze` while one is active. Do not surface
audit ids or diagnostic blocks unless asked. Completion, snooze or cancellation of
the focused task does not release a hold; disabling clears it immediately. Retrying
an old message never recreates, extends or renews a hold. Nothing suppressed is
replayed and stopped sequences never revive. Expiry is the end of the current
allowed local window. Weekdays and DST follow the real-instant window policy;
overnight windows are unsupported. A send already in flight cannot be recalled.

After an approved instruction change, regenerate native-plan artifacts and review
the scoped inbound instructions; previews are side-effect free and cron stays
paused. To refresh cached instructions in a continuing conversation, the supported
command is `hermes sessions refresh-prompts --session ID --json`: it preserves
history and queues refresh for the next turn. Report queued versus verified adoption
separately; do not clear sessions or restart a shared gateway to refresh prompts.
Editing this guide is not installation, refresh or activation approval.

## Local-first policy and lifecycle

Fresh runtime stores are local-first by default, and an existing runtime store
adopts the policy automatically on first ordinary use (including `runtime status`)
after validating config, runtime, route and engine state. No opt-in or second
approval is needed, and help or `runtime native-plan` does not adopt it. Adoption
changes policy only — not tasks, settings, engine state, installation or cron.
Delivery route, installation, live testing and ongoing activation stay separately
explicit: default policy never means automatic sending.

Local eligibility, recorded engagement, windows, spacing, budgets and global pause
authorize both openers and follow-ups. Native Hermes send is the only transport. A
positive `success:true` with a message id persists `accepted` delivery and advances
ordinary work without history — transport acceptance, not verified arrival. An
optional `confirm` enriches the outbox as `confirmed`; its failure is a verification
warning, not a failed send or a scheduling lock. Failed or uncertain attempts are
never retried, their task sequence stops, and unrelated tasks keep their own bounded
opportunities. Report real failures with `[CRON_FAILURE]`, never silent success.

Scheduled turn:

1. Read `runtime status` and `runtime capabilities`; report the caller's optional
   history capability. A missing tool stays absent for a separately authorized test.
2. `runtime preflight`: quiet local guards mean stop. For due work, compose one short
   question for the returned task, store it in a private body file, then run
   `runtime draft --event-token TOKEN --body-file FILE`.
3. Do not read history in routine cron. Enrichment belongs only to an explicitly
   requested, consented operation.
4. `runtime dispatch --event-token TOKEN --fence FENCE --hermes ABSOLUTE_EXECUTABLE`
   performs final local authorization and the only send. Read back `runtime status`.
   `accepted` permits later ordinary work; `sending` or `uncertain` is not success and
   must never be resent. Independent readback warnings do not mean the send failed.
5. For an explicitly requested, consented delivery verification, run
   `runtime confirm --event-token TOKEN --fence FENCE --pages-file FILE --history-plan-file PLAN_FILE`.
   It records confirmed provenance and keeps the original acceptance. Do not wait for
   it before later valid work, and never echo the check-in yourself — the helper owns
   delivery.

Normal inbound turn: matching the confirmed binding, record engagement before
substantive help, using `runtime context --binding` or a trusted
`--reply-to-message-id`, and inspect status if context is empty. Ask which task when
attribution is ambiguous. Read back the sequence or hold before claiming suppression.
Ask before completion, snooze, cancellation or pause changes.

Install/update verification checks helper help and version, capability reporting, the
generated wrapper/prompt/instruction, an initially paused cron job and both local
delivery targets by readback, without running a user-store preflight. Policy adoption
never rewrites wrappers, cron or instructions. Report acceptance and independent
verification separately, and obtain separate ongoing-activation approval.

## Discord history consent

History is OFF by default and a configured route or an available tool is not consent.
Local tasks, accepted delivery and trusted local-first engagement all work without
it. Routine cron must not obtain history, even after opt-in: only an explicitly
requested reply-recovery or delivery-verification may read it.

Read `runtime history-preference` to reuse the saved choice. After confirmed Discord
check-in setup, persist an explicit Yes with
`runtime history-preference --enable --route FULL_CONFIRMED_ROUTE_JSON --confirm-history`;
an explicit No or later revocation uses `runtime history-preference --disable`. Read
back after either change. Consent binds the exact owner/profile/account/chat/thread,
channel and bot; a changed route needs new consent, and re-enabling rotates the grant.

For each requested operation run
`runtime history-plan --purpose reply-recovery|delivery-verification --target DECIMAL_ID --confirm-history`
and keep the returned dict in a private plan file. The grant binds route, generation,
purpose and target: fetch only the latest 25 messages, one page, `before=null`, at
most 131072 bytes total and 8192 bytes per message. Never chase old anchors or fetch
another page. Pass `--history-plan-file PLAN_FILE` with `--pages-file CAPTURE_FILE`
to observe, confirm, engagement, resolve-clarification and dismiss-clarification.
Never fabricate captures or reply references; an absent anchor is a warning, not
permission to read further or block local-first work.

The plan records caller-asserted explicit user intent, not cryptographic proof, and
helper gates do not sandbox arbitrary tools. Review installed instructions and tool
allowlists after changing the preference; persisted core denial is immediate. Deny
history tools in routine cron, never auto-provision a connector, and never claim
verified delivery from availability or consent.

`runtime capabilities --history-availability unknown|unavailable|available` (with
`--history-error TEXT` on failure) separates saved consent, caller-reported
availability and delivery evidence. Unknown means unchecked, unavailable includes a
missing tool or error, and available is caller-reported. Unknown or unavailable is
visibly degraded and nonblocking: do not wait for history or substitute a hosted
connector. No source imports, raw credentials or alternate APIs.

Exact pending clarifications use the documented clarification resolution/dismissal
commands with a matching bounded history plan, never a guessed grant. Never guess the newest task or undo a
resolving/resolved choice; “cancel” is ambiguous between dismissing a question,
cancelling a task and pausing check-ins.

## Guided onboarding

Open naturally, then ask one short question at a time, reusing saved settings from
`setup` readback when a store exists.

1. Mode. If trusted gateway context identifies this conversation as Discord, present
   Yes as the default: “Enable Proactive Mode? Default: Yes.” Follow with: “This is
   where Task Coach shines: instead of waiting for you to remember to ask for help,
   I'll check in here about your tasks, help you get started, and work through what's
   getting in the way, all during the window you choose.” Explain that with it off
   the user can still manage tasks and get coaching on demand. Otherwise ask the same
   question without assuming a platform — a configured route, an available tool or
   message text does not identify the platform. Never treat silence as consent. A Yes
   starts proactive setup; a No continues local-only setup.
2. Local-only. Ask timezone only if dates need it: accept a city or region and
   resolve it with confirmation instead of demanding an IANA name. Run `setup` with
   confirmed flags. Do not ask weekdays, windows, follow-up limits or routes.
3. Route. Check-ins require an already configured Discord connection; do not imply
   other platforms or account provisioning. Confirm the exact route from trusted context,
   then ask: “Send your check-ins here in this conversation? Default: Yes.”
   Explain that this is where check-ins arrive and that a dedicated channel is also
   possible. If the user declines, resolve their named destination through supported
   discovery and confirm the exact match.
4. History. Only after check-ins and a confirmed destination, ask separately: “May I
   read a small amount of Discord history here only when you explicitly ask to
   recover a reply or verify delivery? It can include unrelated messages and adds
   model input tokens, including repeated reads. Task Coach works without it, and
   regular check-ins never scan history. Default: No. Allow it?”
   Local-only setup never asks this question about Discord history.
5. Schedule. Reuse a confirmed timezone; never infer it from the host or the platform.
   UTC in a fresh config is not a confirmed user timezone. Present saved days and
   hours when resuming, otherwise suggest every day 09:00–17:00 with the confirmed
   timezone. If all seven days are enabled, explain that the task-add question will
   ask weekdays, weekends or all, including follow-ups. Once the window is known, ask:

   “How many different tasks would you like me to check in about during that window?
   The default is up to 2 distinct tasks. Keep the default of 2, or customize?”

   Show an existing store's saved maximum instead. Accept 1–10. This is a ceiling,
   not a quota. Then show the saved or default follow-up settings and ask whether to
   keep or customize them; for defaults, state the user's real window and: up to 2
   follow-ups per unanswered task, randomized 30–120 minute spacing, and a reply
   stops further follow-ups for that task while later task check-ins remain scheduled,
   and it never completes the task.
6. Smart Snooze. Separately ask: “Smart Snooze is off by default. If you explicitly
   start working after a check-in, should I hold all Task Coach check-ins until your
   current notification window ends?” Reuse the saved value on resume. This choice
   never activates cron.
7. Task. Reuse an existing open task or the one supplied during setup; ask for one
   real task if none exists. The daily maximum is a ceiling — never ask the user to
   fill every slot. Apply the check-in-days question, then add and verify the task
   before any preflight. If the task is not yet eligible, keep it and explain when it
   can become eligible. Never create a sample task.
8. Install. Inspect existing artifacts, then present one approval covering the
   wrapper, the paused schedule and the exact scoped reply instruction: explain where
   check-ins appear, the saved timing, that replying continues the task, and that
   nothing sends yet. End with “Set up your check-in schedule? Default: Yes.” List
   native cron jobs and inspect the wrapper path and instruction before writing; an
   empty store does not mean artifacts are absent. Reuse matching artifacts and never
   replace SOUL or unrelated instructions. Verify the wrapper (mode 0700), the paused
   job and the instruction by readback without invoking preflight.
9. Test, only when supported. “Send one test check-in now? Default: No. You can skip
   this and turn on regular check-ins next.” Send only after an explicit Yes; a blank
   default is No. If skipped or the window is closed, disclose that live delivery and
   follow-up suppression stay unverified. Keep the schedule paused after a failed or
   uncertain attempt and never bypass a refusal.
10. Activate. Review the actual read-back settings — destination, days, window,
    timezone, maximum tasks, follow-up limits, what a reply stops, Smart Snooze, the
    history choice and scope, and the task with its due date and check-in days — then
    state whether the test was skipped or what it established. Ask “Are you ready to
    start using your Task Coach?” That is the ongoing activation approval. Changes
    keep the schedule paused and return through the affected checkpoint with fresh
    approval; a No leaves it paused. After approval activate through supported cron
    controls and read back the job and the next eligible opportunity.

```sh
python3 "<skill_dir>/scripts/task-coach.py" setup --timezone UTC --weekdays mon,tue,wed,thu,fri,sat,sun --notification-start 09:00 --notification-end 17:00 --max-tasks-per-window 2 --max-unanswered-followups 2 --min-followup-interval 30 --max-followup-interval 120
python3 "<skill_dir>/scripts/task-coach.py" list
```

`max_tasks_per_window` is the saved name for that ceiling; `--max-tasks-per-window`
sets it. Before preflight touches the user store, finish preferences, add and verify
the authorized task, and check the live window: preflight is nonclaiming but not
read-only, and an episode stopped as `task-unavailable` is not revived by adding a
task later. Read [native-runtime.md](references/native-runtime.md) for route binding,
`runtime configure --confirm-setup`, native-plan output and installation scope.

For a separately authorized one-check-in test, keep cron paused and use
`runtime prepare-test --confirm-test` before the first preflight; it prepares one due
opener without sending and refuses pause, any existing episode, any outbox row, an
invalid route, clock regression and an unavailable task or window. Do not reset
storage or use restart as a workaround. A single-event test has no follow-ups, so
engagement is not proof of live follow-up suppression; disclose that limit. A broader
pilot needs its own authorization and a supported pause.

## Checkpoint wording

End each setup or verification checkpoint with one natural sentence about what is
ready and what happens next; do not wait to be asked for a status report.

- Local ready: “You're ready to work on tasks here. What would you like to tackle?”
- Installed paused: “Your check-ins are set up but paused. Would you like to try one
  check-in during your allowed hours? Default: No — you can skip the test and turn on
  regular check-ins next.”
- Test verified, recurring paused: “That check-in arrived and your reply brought us
  back to the task. Regular check-ins are still paused.”
- Active, task awaiting eligibility: “Setup complete. Regular check-ins are on; they
  will begin when your task is eligible during your chosen hours.”
- Active and eligible: “Setup complete — you'll be hearing from me soon!” only after
  readback of the active schedule and a verified upcoming opportunity.

These are conversational instructions, not a background notifier or status
dashboard. In everyday coaching, focus on one task and one useful question. Never
show ids, tokens, status blocks, “engagement recorded” or test bookkeeping unless
asked or needed to explain a problem. Setup summaries and requested status reports
are the exceptions.

Continue the returned task with one useful next-step or blocker question, offer
concrete help and respect a decline. A request to revisit tomorrow is a deferral, not
completion or approval to enable a paused schedule: resolve the date in the
configured timezone and derive that date's offset rather than copying today's. Read
back any snooze, say whether check-ins are still paused, and never promise an exact
send at the snooze boundary. Never complete a task without permission.

## Pause, restart and reset

An explicit pause uses `coach pause` with readback through `coach status`. `coach
resume` clears the pause but never revives today's stopped episode.

For an explicit restart, inspect `coach status`, `runtime status` and the installed
CLI first. If today has no sequence and the whole runtime is clean,
`runtime restart --confirm-restart` can replan the rest of the day from current
tasks. Never use it to escape a failed guard. See the runtime reference for the exact
conditions.

For reset, separate tasks from the installed code and schedule. Never treat a
reinstall as a data reset. Ask before deleting, use the private backup if one is
wanted, and follow the reset notes in the reference.

## Reference map

- [Python launcher](scripts/task-coach.py)
- [Package initialization](scripts/task_coach/__init__.py)
- [Module entry point](scripts/task_coach/__main__.py)
- [Task CLI and storage](scripts/task_coach/cli.py)
- [Transport-neutral coaching engine](scripts/task_coach/coaching.py)
- [Native Hermes driver and Discord history validator](scripts/task_coach/driver.py)
- [Bounded clarification lifecycle](scripts/task_coach/clarification.py)
- [Completion-based recurrence](scripts/task_coach/recurrence.py)
- [Native runtime protocol and setup](references/native-runtime.md)
- [Coaching conversation shape](references/coaching.md)
- [Installation reset procedure](references/installation-reset.md)
- [MIT license](references/LICENSE)

Read the runtime reference before any runtime command; read the coaching reference
when composing an opener, a follow-up or a clarification question. The implementation
is authoritative — read the module rather than guessing a flag.
