# Hermes Task Coach

A local task manager for Hermes Agent, with optional proactive check-ins.
Capture a task, pick a small next step, and work through blockers in ordinary
conversation. Tasks live in a local SQLite store and need no messaging account.
Automatic check-ins are optional and off until you configure them.

## What coaching looks like

> **Coach:** You’ve got “replace water filter” on your list. How can I help you get started?
>
> **You:** I don’t know what filter I need.
>
> **Coach:** Let’s figure that out. Can you find the fridge’s model number? It’s usually on a label inside the fridge, near the door. Send it over and I’ll help you find the right filter.

## Requirements and install

You need Python 3.11 or newer with SQLite and timezone data. Linux is the
qualified platform. There are no third-party runtime dependencies. Optional
proactive check-ins also need an existing Discord connection in Hermes.

Install the skill into your Hermes profile:

```sh
hermes skills install minutezer0/hermes-task-coach/skills/task-coach
```

Installing the skill does not itself launch a chat or enable check-ins.
When you are ready, tell Hermes:

> Set up Task Coach

Hermes asks about your preferences and helps you get started with one real task.
If you choose proactive check-ins, it sets up a paused schedule and offers an
optional test message. The test is skipped unless you explicitly approve it.
Regular check-ins start only after your approval.

## Talking to your coach

Talk to it like a person. Hermes reads and writes the same local store, so you
never have to remember command syntax:

> Add take out the garbage to todo

> What's on my task list?

> Let's work on the new laptop task

> Mark the garbage as done

> Skip the invoices today

> I’d like to clean the gutters next weekend.

You can give tasks due dates to help the coach decide what to bring up. These
guide check-ins within your chosen days and hours; they don’t guarantee a reminder
at a specific time.

It asks **which task** when your message could mean more than one, and it never
completes, snoozes, cancels or reprioritises a task without your explicit say-so.
If you ask for something it cannot do, it says what is missing rather than
guessing.

## Features

### Proactive check-ins

Task Coach can send check-ins through an already-configured Discord connection
in Hermes. Local task management and coaching on demand work with check-ins off.
Task Coach never creates a messaging account or asks for credentials.

You choose the days, hours, maximum number of tasks and follow-up limits.
By default, the coach checks in about up to two different tasks per day, with up
to two follow-ups for each unanswered task. That can mean up to six messages if
your notification window has room. Replying stops further follow-ups for that
task; later tasks stay scheduled. You can always adjust both the number of tasks
per day and the number of follow-ups per task.
Missed opportunities are not caught up, and the maximum is a ceiling, not a quota.
You can ask Hermes to pause check-ins at any time.

**Discord history is off by default.** It is read only for an explicitly requested
reply recovery or delivery verification, one bounded page, never during routine
check-ins.

### Smart Snooze

Off by default. With it on, replying to a check-in that you are starting work
right now suppresses all Task Coach notifications for the rest of your current
notification window. It changes no task and expires when that window ends.

### Check-in days per task

Each task can use weekdays, weekends or all of your allowed days, including for
follow-ups. Task days can narrow your global schedule, never widen it. If the two
never overlap, the task stays saved and Task Coach warns you that it cannot get
check-ins. You can still discuss or work on any task at any time.

### Due dates and recurring tasks

Priority and due dates help the coach choose which tasks to bring up. They never
override your chosen check-in days or hours.

Recurring tasks have a first due date and an interval in days, weeks or months.
Unlike ordinary dated tasks, they are held out of check-ins until they become
due. Only an explicit completion advances the next due date, calculated from
when you actually finished. Missed occurrences do not build up a backlog.

## Troubleshooting

- **No messages arrive** — ask Hermes to check that your check-in schedule is
  active, a Discord destination is configured, and global pause is off.
- **A task never gets check-ins** — its days may not overlap your global schedule,
  or a recurring task may not be due yet.
- **Fewer check-ins than the maximum** — the maximum is a ceiling, not a quota;
  task eligibility and available time can reduce the number.
- **Check-ins in the TUI** — reply in your configured Discord conversation;
  the TUI is a working surface, not a notification target.

For direct commands, setup defaults, storage details, scheduling mechanics and
reset instructions, see the
[command reference](https://github.com/minutezer0/hermes-task-coach/blob/main/docs/command-reference.md).
The guide also covers direct installation with pip and detailed troubleshooting.

## License

MIT. See [LICENSE](https://github.com/minutezer0/hermes-task-coach/blob/main/LICENSE).

## Experimental ChatGPT desktop integration

The separate [desktop development guide](plugins/task-coach-desktop/README.md)
covers the macOS prototype, its package, and live-test limitations. The Hermes
installation above continues to use the Hermes skill and runtime.
