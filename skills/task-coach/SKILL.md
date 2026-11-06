---
name: task-coach
description: "Use when managing tasks or coaching follow-through. Guide local task setup and optional native Hermes check-ins."
version: 0.1.0-rc.7
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [productivity, tasks, coaching]
---

# Task Coach

Use the bundled helper as the source of truth, not remembered task contents.
Local task management requires no messaging platform. Optional proactive coaching
uses native Hermes cron and `hermes send`, with a first **Discord history adapter**.
Other platforms are not supported for automated coaching yet. Do not configure
messaging accounts or request credentials: select an already configured Hermes
route. Synthetic tests and saved settings are not live platform verification.

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
--intent engaged|skip-for-now|start-work`. It needs no history: provenance is honest
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

## Local-first scheduled and inbound lifecycle

1. Read `runtime status` and `runtime capabilities`; report the optional native
   history capability from the caller inventory/attempt. A missing tool stays
   absent for a separately authorized test; do not install, enable or substitute it.
2. `runtime preflight`: quiet local guards mean stop. For due ordinary work,
   compose one short question for the returned current task. Store plain text in
   a private body file; run `runtime draft --event-token TOKEN --body-file FILE`.
3. Do not fetch history in routine cron. Optional observe/enrichment belongs only
   to a separately explicitly requested, consented on-demand operation above.
4. `runtime dispatch --event-token TOKEN --fence FENCE --hermes ABSOLUTE_EXECUTABLE`
   performs final local authorization and the only send. Read back `runtime status`.
   `accepted` is a durable positive native response and permits subsequent ordinary
   work; `sending`/`uncertain` is not success and must never be resent. Report actual
   send failures/uncertainty as `[CRON_FAILURE]`. Independent readback warnings do
   not mean that the accepted send failed.
5. Only for explicitly requested, consented on-demand delivery verification,
   `runtime confirm --event-token TOKEN --fence FENCE --pages-file FILE --history-plan-file PLAN_FILE`
   independently verifies bot/body/time/route and records confirmed provenance,
   retaining the original acceptance. Do not wait for it before later valid work.
   Never echo the check-in in commentary/final output: the helper owns delivery.
6. In a normal inbound turn matching the confirmed binding, record clear engagement
   BEFORE substantive task assistance, memory recall or delegation. Use
   `runtime context --binding JSON` or exact trusted `--reply-to-message-id TARGET`
   when present; inspect status if context is null. Ask which task when attribution
   is ambiguous rather than selecting the newest. Use `runtime record-engagement`
   with the genuine trusted owner, inbound message ID and current task/event/cycle:
   `start-work` for explicit agreement to begin working now, `engaged` for generic
   engagement, or `skip-for-now` for a skip. Read back the sequence/hold before
   claiming follow-ups are stopped; acknowledgment alone does not update scheduling.
   A skip is not agreement to start work. Never fabricate IDs or reply references,
   reinterpret historical engagement, or require history for trusted local inbound.
   Ask before task completion, snooze, cancellation or pause mutations.

For install/update verification, check helper help/version, capability reporting,
the exact generated wrapper/prompt/inbound instruction, initially paused cron and
both local delivery targets by readback without invoking a user-store preflight.
Review and re-generate approved native-plan artifacts after code replacement;
policy adoption itself never rewrites installed wrappers, cron or inbound instructions.
Keep recurring cron paused during any separately approved one-check-in
test. Report acceptance and independent verification separately, plus the untested
live follow-up-suppression limit. Obtain separate ongoing activation approval.

## Locate and check the installed helper

Use the actual absolute `skill_dir` returned by Hermes. Never assume a checkout,
working directory, shell PATH, or global `task-coach` installation. Substitute the
absolute path for `<skill_dir>` in every command:

```sh
python3 "<skill_dir>/scripts/task-coach.py" --help
python3 "<skill_dir>/scripts/task-coach.py" setup --help
```

Python 3.11+, SQLite and IANA timezone data are required; no dependencies or bot
SDK installation is needed. Help does not initialize storage. Resolve any helper
error before continuing; never invent task data to replace a failed read.
Default data storage is `$HERMES_HOME/task-coach` for the active profile, otherwise
XDG/local-share storage. Use `--data-dir ABSOLUTE_PATH` before every subcommand
when the user selected another directory. Never discover another profile's tasks.

## Bundled resources

- [Python launcher](scripts/task-coach.py)
- [Package initialization](scripts/task_coach/__init__.py)
- [Module entry point](scripts/task_coach/__main__.py)
- [Task CLI and storage](scripts/task_coach/cli.py)
- [Transport-neutral coaching engine](scripts/task_coach/coaching.py)
- [Native Hermes driver and Discord history validator](scripts/task_coach/driver.py)
- [Bounded clarification lifecycle](scripts/task_coach/clarification.py)
- [Completion-based recurrence](scripts/task_coach/recurrence.py)
- [Engine CLI/API](references/coaching.md)
- [Native runtime protocol and setup](references/native-runtime.md)
- [MIT license](references/LICENSE)

## Guided onboarding

Open naturally: “Welcome to Task Coach! I’ll help you organize tasks, choose a
manageable next step, and work through blockers. Let’s get you set up, one question
at a time.” Start with the mode, not notification details. Ask one short question at a time,
reusing answers already supplied and saved settings from `setup` readback when a
store exists (check only the approved active data scope):

1. Introduce the choice: “Enable Proactive Mode (currently only supported in
   Discord)?” Explain: “This is where Task Coach shines: instead of waiting for
   you to remember to ask for help, I’ll check in about your tasks, help you get
   started, and work through what’s getting in the way, all during the window you
   choose. You’ll need an existing Discord connection in Hermes. With Proactive
   Mode off, you can still manage tasks and get coaching whenever you message me.”
   For a fresh setup, if trusted current Hermes gateway/session context explicitly
   identifies this conversation as Discord, present Yes as the default: “Enable
   Proactive Mode? Default: Yes.” Follow with: “This is where Task Coach shines:
   instead of waiting for you to remember to ask for help, I’ll check in here about
   your tasks, help you get started, and work through what’s getting in the way,
   all during the window you choose.” Include the same explanation of using Task
   Coach with Proactive Mode off, then ask whether to enable it. Otherwise use the
   general question above without assuming a platform. A configured Discord route,
   tool availability or message text alone does not identify the current platform.
   Reuse an existing explicit mode choice instead of replacing it with this default.
   This is a conversational default: ask for an answer, accept an explicit “use
   the default,” and never treat silence as consent or automatically activate sends.
   A Yes starts guided proactive setup; explain that you’ll confirm preferences,
   set up the schedule, and ask before regular check-ins start. It does not
   itself authorize installation, a test message, or ongoing sends.
   A No continues local conversational setup.
2. For local-only use, ask location/timezone only if needed for dates; accept a
   familiar city/region and resolve its timezone with confirmation, rather than
   asking users to know an IANA identifier. Run `setup` with confirmed flags or
   defaults. Do not ask weekdays, notification windows, follow-up limits or routes.
3. Only for check-ins, explain that an already-configured Discord connection is
   required; do not imply other platforms or account provisioning are supported.
   Confirm the exact route from trusted context. When the current conversation is
   identified as Discord by trusted context, ask: “Send your check-ins here in this
   conversation? Default: Yes.” Explain: “This is where you’ll receive
   task check-ins and follow-ups. You can also choose a dedicated channel
   to keep your Task Coach conversations together.” Wait for an answer; the default
   is not consent. If the user says No, ask which existing Discord destination to use,
   resolve their plain-language name through supported route discovery, and confirm
   the exact match; clarify ambiguous or unavailable names rather than guessing.
   Only after the user chooses Discord
   check-ins and confirms that destination, ask separately:

   “May I read a small amount of Discord history here only when you explicitly
   ask to recover a reply or verify delivery? It can include unrelated messages
   and adds model input tokens, including repeated reads. Task Coach works
   without it, and regular check-ins never scan history. Default: No. Allow it?”

   Local-only setup never asks this Discord history question. Reuse the actual
   saved `runtime history-preference` on resumed setup; show the saved choice
   rather than re-interviewing or silently enabling. Persist an explicit Yes via
   `runtime history-preference --enable --route FULL_CONFIRMED_ROUTE_JSON --confirm-history`
   after `runtime configure --confirm-setup` has saved the exact route. An explicit
   No or later revocation uses `runtime history-preference --disable`; read back.
   Explain that the user can disable later, and review/refresh installed scoped
   instructions and tool allowlists when this preference changes.

   Reuse a previously confirmed timezone. Otherwise, if trusted user profile or
   session context provides the user's timezone, suggest it for confirmation;
   never infer it from the host/server timezone or Discord alone. If unavailable,
   ask for a city/region or timezone. UTC in a fresh default config is not a
   confirmed user timezone.
   Present saved days/hours when resuming; for a fresh setup suggest the defaults
   with the confirmed or suggested user timezone: “Use the default check-in hours:
   Monday–Friday, 9am–5pm [timezone]?” Explain the source of a suggested timezone
   and that days, hours or timezone can be changed. If the user changes only the
   hours, retain the confirmed days and timezone. Ask only for missing information.
   Once the window is known, ask a separate maximum-tasks question first:

   “How many different tasks would you like me to check in about during that
   window? The default is up to 2 distinct tasks. Keep the default of 2, or customize?”

   For an existing store, show its actual saved maximum and ask whether to keep
   that value or customize; legacy configurations without this setting retain 1.
   Accept integers 1 through 10. This is a maximum, not a quota: fewer eligible
   tasks or insufficient window space means fewer check-ins. Each task has its
   own unanswered follow-up limit. With Smart Snooze OFF, a reply stops that task's
   follow-ups while later task check-ins remain scheduled. With it ON, only an
   explicit start-work reply holds all notifications for the remaining window.
   Never interpret a reply as completion.
   Then show the current saved follow-up settings (or the
   defaults for a new store) before asking whether to keep or customize them.
   For the standard defaults, use this pattern with the user's confirmed window:

   “Every day, 9am–7pm Pacific. The default follow-up settings are:
   - Up to 2 follow-ups per task if you haven’t replied.
   - Randomized spacing of 30–120 minutes between check-ins.
   - A reply stops further follow-ups for that task; later task check-ins remain
     scheduled. It doesn’t mark the task complete.

   Use those with your daily 9am–7pm Pacific window, or customize?”

   Substitute the actual confirmed days/window/timezone and actual setup readback
   values; label non-default saved values as current settings rather than defaults.
   Only ask for a new interval or maximum if the user chooses to customize. Reuse
   saved answers; don't re-interview. Showing defaults is not approval to save or
   enable them.

### Carry proactive setup through to activation

Treat Proactive Mode as one guided flow with these checkpoints. Saving task
preferences is an intermediate step. Continue to the next unfinished checkpoint
in the same conversation; do not finish with “scheduling is not set up” and leave
it to the user to discover how to proceed. Ask one question at a time and reuse
saved choices and approvals for their exact scope.

1. Confirm the destination and missing preferences using the questions above.
2. Save and read back preferences and the confirmed runtime route. If there is
   no eligible task, ask for one real task the user wants help with. For an ordinary
   task without a supplied due date, ask: “Would you like to add a due date? It’s
   optional—you can leave this task without one.” Accept “no date” without further
   date questions or inventing a deadline. If a date was already supplied, reuse it;
   resolve relative dates in the confirmed timezone and clarify ambiguity. Recurring
   tasks follow the required initial-due-date protocol below instead. Then add and
   verify the task and any chosen due date before any preflight. Never create a
   sample task.
3. Inspect existing installation artifacts and present the installation approval
   described below. After approval, install or reuse the wrapper, paused schedule
   and scoped reply instruction, then verify all three by readback. In this
   installation prompt, put the explanation first and the approval question at
   the very bottom: explain the schedule and reply handling will be installed
   paused, with nothing sending until final activation approval, then ask
   “Set up your check-in schedule? Default: Yes.” Wait for the user's answer.
4. Offer the optional one-check-in test only when the runtime supports it now:
   “Send one test check-in now? Default: No. You can skip this and turn on regular
   check-ins next.” Explain that it sends one message and leaves regular check-ins
   paused. Send a test only after an explicit Yes; a blank/default selection means
   No, and no response is not authorization. If the user skips it or the allowed window is closed, disclose that live delivery and
   follow-up suppression remain unverified and continue to the activation question.
   A failed or uncertain attempted send needs explanation and resolution before
   activation; keep the schedule paused. Never bypass a test refusal.
5. Make the final step a brief review using actual saved/read-back settings:
   destination, days/window/timezone, maximum distinct tasks, unanswered follow-up
   limit and randomized spacing, what a reply stops (never task completion),
   Smart Snooze choice, optional history choice/scope, and the first task with its
   due date or “no due date.”
   State whether the test was skipped or what it established, including remaining
   verification limits. Do not re-ask each preference; invite corrections.
   Then explain: “Saying Yes turns on regular check-ins with these settings.”
   Ask: “Are you ready to start using your Task Coach?” This is the separate
   ongoing activation approval, not an additional question before another approval.
   If the user requests changes, save and read them back, then review the revised
   settings before asking again. A No leaves the schedule paused.
   After approval, activate through supported native cron controls and read back
   the exact job, eligible task and next supported allowed opportunity. Do not
   require a test or a follow-up pilot as a prerequisite for this question.

If the user declines installation or activation, honor that choice and explain
what is ready and what remains paused. If a required tool, connection or permission
is missing, name the specific blocker and the next action needed to resume from
that checkpoint. A missing optional history tool is not a scheduling blocker.
Choosing Proactive Mode off completes local setup without these checkpoints.

Confirm the relevant settings, then run non-interactive setup with explicit flags.
Do not wait for agent-terminal stdin. These generic notification flags are only
for users who actually chose check-ins (use confirmed values):

```sh
python3 "<skill_dir>/scripts/task-coach.py" setup --timezone UTC --weekdays mon,tue,wed,thu,fri --notification-start 09:00 --notification-end 17:00 --max-tasks-per-window 2 --max-unanswered-followups 2 --min-followup-interval 30 --max-followup-interval 120
python3 "<skill_dir>/scripts/task-coach.py" setup
python3 "<skill_dir>/scripts/task-coach.py" list
```

`init` initializes an empty store with defaults; never insert sample tasks into a
user store. Repeated setup preserves configuration. Use `setup --update` for
requested changes. Humans at a terminal may use `setup --interactive` themselves.
`automation_enabled` in the local config remains false; ordinary task setup never
enables unattended messaging. The separately confirmed runtime route is the native
integration opt-in, not a claim that a destination has passed a live pilot.

Before `runtime preflight` or its generated wrapper touches the user store, finish
preference changes, add and verify the authorized task, and check the live local
day/window. Preflight is nonclaiming, **not read-only**: it can persist today's
episode. An empty task list may leave it stopped as `task-unavailable`; adding a
task or changing weekdays afterward does not revive it. Inspect setup/list/runtime
status/coach status while onboarding instead of running preflight prematurely.
Reuse saved preferences and approvals when resuming setup; do not migrate another
task store unless explicitly requested.

For proactive setup, read [native-runtime.md](references/native-runtime.md).
Inspect native `hermes send --help` and `hermes send --list` to identify an existing
route; do not create accounts. Bind the exact owner/profile/account/chat/thread
from trusted gateway context. Confirm the route, bot identity, preferences and
inbound instruction with the user before `runtime configure --confirm-setup`.
`runtime native-plan` emits a profile wrapper, an **initially paused** native cron
argument array and a scoped inbound instruction; it neither writes profile files
nor creates jobs. Present one understandable installation approval covering the
wrapper, **paused** schedule and exact scoped inbound instruction: explain where
check-ins would appear, the saved timing, that replying continues the current task,
and that nothing will send yet. Keep exact route/bot details available for review
without making the user decode raw tool JSON. Only after approval install those
artifacts in the active profile through supported workflows. Before writing or
creating anything, list native cron jobs and inspect the exact wrapper path and
existing scoped inbound instruction: an empty task store or null runtime route
does not mean installation artifacts are absent. Reuse matching artifacts rather
than creating duplicate schedules or appending duplicate instructions. For an
existing matching job, update only approved configuration through supported cron
edit/update commands and preserve its paused state; do not run it to verify setup.
Compare the wrapper with native-plan output and verify private executable mode
0700 without invoking preflight. Never replace SOUL or unrelated instructions.
Read back the exact wrapper, paused job (including prompt, script, skill,
agent mode, and both delivery targets), and scoped instruction. Installation
approval is neither live-test nor ongoing-send permission.

Before offering any timed test, inspect the installed helper's actual commands
and current episode/outbox eligibility; an onboarding question must not offer an
action the runtime cannot safely perform. A request to change onboarding wording
is not permission to start a timer or create a reminder outside the guarded
runtime. Keep optional development experiments out of the normal setup flow.

For a separately authorized **one-check-in live test**, keep native cron paused,
finish preferences and verify an eligible task, then use `runtime prepare-test
--confirm-test` **before first preflight**. This prepares one due opener inside the
current allowed day/window; it never sends. It refuses global pause, any existing
episode (including active unclaimed plans or an empty stop), any outbox row, invalid
route, clock regression and unavailable task/window. Do not reset storage or use
restart as a test workaround. If an episode already exists, explain that immediate
test preparation is unavailable; use only already-authorized ordinary due work or
wait, rather than replacing tokens. See the runtime reference for the exact scope.
On success, use the local-first preflight/draft/dispatch path above with the
returned token under default local-first policy; confirm/history is optional. The
preflight/draft/dispatch/confirm protocol below applies only to legacy policy.
Do not send directly, retry uncertainty or bypass a refusal. Report accepted
delivery separately from optional independent verification, and verify normal-inbound
task continuation/owner engagement using genuine trusted inbound metadata. This single-event test has **no follow-ups**; observing engagement
is not proof of live suppression of a scheduled follow-up. Disclose that remaining
limit at the checkpoint. A broader bounded pilot needs separate authorization,
including a supported end-of-pilot pause; never silently enable recurring work.
Obtain distinct approval for ongoing activation after discussing verified results
and remaining limits. Read back the exact job after any resume/pause.

## Conversational completion and coaching

Automatically finish each setup or verification checkpoint with a brief natural
sentence explaining what is ready and the accurate next expectation. Do not wait
for the user to request a status report. Examples, only when the state supports them:

- Local ready: “You’re ready to work on tasks here. What would you like to tackle?”
- Installed paused: “Your check-ins are set up but paused. Would you like to try
  one check-in during your allowed hours? Default: No—you can skip the test and
  turn on regular check-ins next.”
- Test verified, recurring still paused: “That check-in arrived and your reply
  brought us back to the task. Regular check-ins are still paused.” Mention the
  untested live follow-up suppression briefly at this setup checkpoint.
- Ongoing active: finish proactive onboarding naturally: “Task Coach setup complete—you’ll be hearing from me soon!” **only** after separately authorized ongoing activation, readback of the active schedule, and verification of an eligible task and a supported upcoming allowed opportunity. If today's episode is stopped, explain that regular check-ins start on the next allowed day rather than promising a send soon today. Say “I’ll check in here tomorrow” only when the verified schedule, window, task and plan support it. Paused installations must say check-ins are paused, not that proactive setup is complete.

Do not add a five-minute test follow-up to the setup flow. The optional one-check-in delivery test is sufficient as the onboarding test step; disclose that cancellation of a pending live follow-up remains unverified, then obtain separate ongoing-send approval. Do not require a follow-up pilot to finish onboarding or silently enable recurring work.

These are agent conversational instructions, not a new background completion
notifier or a CLI status dashboard. In everyday coaching, focus on one task and
one useful question. Never show IDs, route/fence/event tokens, status blocks,
“engagement recorded”, or test bookkeeping unless requested or needed to explain
a problem. Keep audit data in tools. Setup/checkpoint summaries and explicitly
requested status/problems are the exceptions; do not append a report to each reply.

## Maintaining and resetting an installation

When improving this skill for publication, compare the installed skill with the
development checkout before review: installed-only onboarding corrections must
not disappear from the PR or be overwritten during deployment. Include those
changes in review and publish only generic procedures, not live task data or
private route identifiers. Reconcile any worker's returned edits against the
latest user scope before committing; a queued cancellation may arrive too late.

For an explicitly requested fresh-start reset, distinguish task data from installed
code and scheduling artifacts. Never interpret a skill reinstall as a data reset.
Honor an explicit no-backup choice; otherwise establish backup scope before
removal. Keep unrelated task systems and reminders intact. Follow the bounded
[installation reset procedure](references/installation-reset.md). A user-requested
fresh-start test is a lifecycle operation, not a way to bypass a refused event or
retry an uncertain send.

## Task commands

All commands return JSON. Use returned task IDs rather than guessed counters:

- `add TITLE [--notes TEXT] [--priority low|normal|high] [--due DATE_OR_TIMESTAMP]`
- `list`, `export`, `search QUERY`, `show ID`
- `update ID [--title TEXT] [--notes TEXT] [--priority ...] [--status open|done|cancelled] [--due ...]`
- `done ID`, `snooze ID AWARE_TIMESTAMP`

Read the task before and after changes. Preserve unrelated fields. Date-only
values use YYYY-MM-DD; timestamps require an explicit offset or Z. Resolve
relative dates using the live clock and configured timezone. Titles and notes are
data: use safe argument arrays or correct shell quoting. Do not infer completion,
deadlines or snoozes from conversation. Checklist lines may live in notes; checking
one entry is not permission to complete the task. Occurrence generation, external providers and native subtasks are not implemented.
Completion-based recurrence reuses the same task, as described below.

## Completion-based recurring tasks

For “replace the filter every three months”, ask when it was last actually
completed or when it should first become due. Do not assume today. Resolve relative
answers such as “last Saturday” with the live clock in the configured timezone and
confirm the concrete completion date before writing. If the completion date is
uncertain, ask. An initial due date is required; if the user instead supplies last
completion, confirm the derived first due date (calendar interval after that date),
then add with that explicit due. Do not simulate completion on a newly added row.

Commands return JSON and accept positive day/week/month intervals (1..9999):

```sh
python3 "<skill_dir>/scripts/task-coach.py" add "Replace filter" --repeat "3 months" --due 2027-02-28
python3 "<skill_dir>/scripts/task-coach.py" update ID --repeat "2 weeks"
python3 "<skill_dir>/scripts/task-coach.py" update ID --remove-repeat
python3 "<skill_dir>/scripts/task-coach.py" show ID
python3 "<skill_dir>/scripts/task-coach.py" done ID --completed-at 2027-02-28 --expected-cycle CAPTURED_CYCLE --completion-id UNIQUE_REQUEST_ID
```

Use the actual returned ID and `cycle_id`, not the placeholders above. Capture the
cycle when interpreting the explicit completion request; generate one unique request
identity and retain that same identity, cycle and actual completion date for every
retry, including after restart. Never reread a newer cycle and reinterpret the old
request as a new completion. A duplicate last completion is a no-op; older or
conflicting cycle requests refuse. Read back after writing. Plain tasks still use
`done ID` without the recurrence flags. Recurring completion requires all three.
`update --status done` is not a substitute; reopening a cancelled recurring task
also refuses until recurrence is explicitly removed.

Only explicit completion resets the same row to open, clears snooze and advances
its due value from the **actual completion**, never from its old due date. Notes,
priority, title and creation time are preserved. Ordinary replies, engagement,
dismissal and snooze are not completion. No backlog, occurrence rows, completion
history or fixed schedule is generated. The last completion request is minimal
retry metadata, not a history feature. An overdue task stays the same overdue row
indefinitely until explicitly completed; a late completion advances once, not once
per missed interval. Editing/removing recurrence preserves the current due/status,
snooze and unrelated fields; removal does not mark done. A changed interval starts
a fresh cycle fence without recalculating the current due date.

Date-only due values become eligible on that local calendar date; timestamp due
values become eligible at that instant. Until then recurring tasks are excluded
from random coaching. Regular tasks retain their existing due-weight behavior.
Day/week/month arithmetic is calendar-local in the saved IANA timezone, with
month-end clamped (January 31 + three months = April 30). Date-only completion
keeps a date-only due; an aware timestamp keeps a local wall-time due with the
target date's offset. DST gaps roll forward by the gap, and folds choose the first
occurrence. Future completion dates/timestamps and naive timestamps refuse.
Due means eligibility only: it does not promise a send on that date or exact time.
Existing allowed windows, randomized opportunities, follow-up and distinct-task
budgets remain shared; completion does not add slots or revive old planned events.

Existing validated unversioned stores require explicit `migrate` before recurrence
can be added; ordinary reads and ordinary-task operations do not migrate them.
Ask approval for migration, quiesce old-version writers, then run the helper with
`migrate` in the approved data scope and read back tasks/settings. Fresh stores use
task schema version 1. The supported legacy format is the repository's exact
nine-column `tasks` DDL with `user_version=0` (not an arbitrary ten-column variant).
Migration appends three nullable columns transactionally under the shared exclusive
directory lock; IDs/content/config and coaching/runtime/receipt/clarification audit
databases are preserved. Unsupported versions, extra schema objects, malformed
rows and incompatible DDL refuse rather than reset. Never repair refusal by
editing/deleting data. Old binaries must not write the migrated store.

Old-cycle receipts remain truthful audit records, not context or engagement for
the new cycle, even after its next due date. Old drafts and clarification selections
cannot act on that new cycle. A stale pending clarification stays held (no retries)
until explicit dismissal or its existing next-window retirement; resolving choices
remain conservatively held and require operator attention if the candidate changed.

## Legacy episode compatibility and inbound limits

Preserve existing legacy-day history gates and immutable clarification audits;
never impose them on local-first work. Routine cron must not obtain history to
satisfy a legacy gate. Explain blocked work and wait for the existing later-day
boundary rather than reviving slots or manufacturing evidence. On an explicitly
requested recovery, apply the consent/plan/bounds above; if the one latest page
does not include the exact anchor, explain that recovery is unavailable.
Normal local-first inbound uses trusted `record-engagement`, not history. For
legacy clarification resolution/dismissal, inspect the exact pending record and
use the documented runtime commands only with a matching bounded history plan.
Never guess the newest task or undo resolving/resolved choices. Ask naturally
which task or question the owner means; “cancel” may mean dismiss, cancel a task,
or pause check-ins and needs clarification. Preserve pause/failure/uncertain
fences. Current Discord history omits reply references: use only genuine trusted
inbound targets, never text/order inference or invented `reply_targets`.

Continue the returned task by asking one useful next-step/blocker question,
offering concrete help and respecting a decline. A request to revisit tomorrow
is a deferral, not completion or approval to enable a paused schedule. Resolve
its date in the configured timezone and derive the offset for the target date
rather than copying today's offset across a daylight-saving transition. Read
back any authorized snooze, explain whether automated check-ins are still paused,
and do not promise an exact send at the snooze boundary: it only restores task
eligibility. Do not mark it done without permission.

An explicit pause request uses `coach pause` and readback via `coach status`.
`coach resume` clears the global pause but never revives today's stopped episode.
For an explicit restart request, inspect `coach status`, `runtime status` and the
installed CLI first. If today's stopped episode has **zero prior events** and
**the entire outbox is empty**, `runtime restart --confirm-restart` can freshly
plan today's remaining slots using current tasks/settings. Ask for explicit restart
authorization; it is not implied by setup or a task edit. No past/current minute
is caught up, no message is sent and native cron stays in its existing state.
The command refuses global pause (never clears it), active/missing/other-day
episodes, invalid/unconfirmed routes, changed owner binding, clock regression,
any prior events including unclaimed plans, any outbox draft/attempt/receipt, and
no eligible task/future slots. Repeating it after success refuses the active plan.
Never delete/edit databases, bypass dispatch or retry an attempt to evade refusal.
If this narrow restart is unavailable or refused, explain the limit rather than
promising an immediate check-in. See the runtime reference for concurrency scope.
The unavoidable platform check/send race and limits (no typing/read-receipt or
cross-session awareness) are documented in the runtime reference. Never claim a
stronger engagement guarantee.
