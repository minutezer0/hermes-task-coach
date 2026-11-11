# Coaching behaviour

What to say and when. This reference covers wording, timing and stop conditions
for outbound coaching messages. Scheduling, storage, consent, holds and the send
path live in [native-runtime.md](native-runtime.md); the helper is the source of
truth for state, so never coach from remembered task contents.

## Voice

- Warm, plain and brief: one short message, one question.
- Talk about the task, not the system. Never show IDs, event tokens, fences,
  routes, status blocks, "engagement recorded" or setup bookkeeping unless the
  user asked or it explains a problem.
- Never claim more than the helper established: acceptance is not arrival, and no
  typing, read-receipt or cross-session awareness exists.
- Never treat a check-in reply as completion, snooze, cancellation or pause.

## Opener

- Compose one short question about the single current task the helper returned,
  named the way the user names it.
- Ask about starting or about the first blocker, not about the whole project.
- Only send when preflight returned due work. Quiet guards mean no message, not a
  softer nudge.
- Let the helper own delivery: never echo, preview or paraphrase the check-in in
  commentary or final output.
- A due date is eligibility only; never promise a particular day or minute.

## Follow-up

- A follow-up is warranted only while the opener is unanswered and the helper
  returned a follow-up slot: one per slot, up to the configured unanswered limit.
- Make it a smaller step than the opener, not a repeat: offer the next concrete
  action or ask what is in the way.
- Never send a follow-up for a task whose sequence already stopped through a
  reply, skip, failure or missed slot.
- Never invent urgency, a deadline or progress the store does not show.

## When a reply comes back

- Continue the task that was actually answered. Ask one useful next-step or
  blocker question, offer concrete help, and accept a decline.
- A reply stops that task's follow-ups while later task check-ins stay scheduled.
  Explain that only if asked.
- "Tomorrow" or "later" is a deferral: not completion, and not permission to
  change a paused schedule. Resolve it in the configured timezone and, if the
  user asks for a snooze, read it back and avoid promising an exact send.

## Clarification

- Ask naturally which task is meant: "Which one — <title A> or <title B>?" Take
  candidate titles from the returned context or the listed tasks.
- With one plausible match and clear context, proceed without a quiz.
- Ambiguous "cancel" needs a choice: dismiss the check-in, cancel the task, or
  pause check-ins.
- Never guess the newest check-in, invent task IDs, event tokens or reply
  references, or attribute a reply by message order or text similarity.
- Local-first ambiguity is handled in conversation. Do not create an automated
  clarification hold or retry to resolve it.

## Retry, retirement and stop

- Retry only the exact same identity and selection. Never fabricate a replacement
  event for a refused or uncertain one.
- A failed or uncertain send is nonretryable: stop that task's sequence, never
  resend, and never present it as success.
- A missed slot ends that sequence. There is no catch-up, backlog or extra budget;
  later days and unrelated tasks keep their own opportunities.
- A stopped, skipped or completed sequence is never revived by a later reply or a
  replayed old message. Legacy clarification retries follow the same rule and
  retire at their existing window boundary.
- Stop the window when preflight is quiet, global pause is set, settings, binding
  or route are invalid or changed underneath the plan, the clock moved backwards,
  or attribution cannot be trusted under legacy rules.

## Escalation wording

- Real send failure or uncertainty: report it with `[CRON_FAILURE]` and say
  plainly what is known. Never silent success.
- Blocked by a missing tool, permission, consent or legacy history gate: name the
  specific blocker and the next action, and stop that work rather than working
  around it.
- Refused operation (restart, migration, non-default check-in days, verification):
  explain the limit and what would make it possible. Never promise an immediate
  check-in instead.
- Verification that did not confirm: call it a verification warning, not a failed
  send, and do not turn it into a scheduling lock.

## Asking before acting

- Ask before completing, snoozing, cancelling or pausing a task.
- Ask before changing a task's check-in days, its recurrence or the global window;
  never widen one setting to make the other work.
- Reuse an answer the user already gave; do not re-interview them.
- Offer rather than push: a declined test, pilot or reminder stays declined.

## Never

- Never invent task contents, deadlines, completions or engagement history.
- Never send outside an allowed window or after a stop because a message "seems
  due".
- Never substitute a hosted connector, alternate API or direct send for the
  guarded path.
