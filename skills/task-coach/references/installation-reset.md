# Fresh-start installation reset

Use only when the user explicitly requests clearing Task Coach for a fresh setup.
Do not reset storage to evade a runtime refusal, replay protection or uncertainty.

1. Resolve the active profile, installed skill directory and exact approved data
   directory. Explain that tasks, saved settings, coaching episodes, route and send
   journal will be cleared; the installed skill, paused native job and scoped reply
   instruction can remain. Reuse those artifacts on the next onboarding run.
2. Establish whether a backup is wanted. Honor an explicit no-backup instruction;
   do not silently create an archive. A deletion manifest containing paths, sizes
   and hashes is audit metadata, not a copy of the task contents.
3. Finish/review any pending code changes first when the reset is meant to test a
   new onboarding flow. Verify the installed helper and guidance match the reviewed
   candidate. Keep repository publication, deployment and send activation separate.
4. List native cron jobs, locate the exact Task Coach job, and verify it is paused
   with no active execution claim. If it must be paused, use the supported cron
   command and read back that job. Do not pause or modify unrelated reminders.
5. Inventory the approved data directory without following symlinks. The normal
   store contains `config.json`, `tasks.sqlite3`, `coach.sqlite3` and
   `outbox.sqlite3`; actual inventory is authoritative. Stop for unknown files,
   symlinks, hardlinks or active SQLite sidecars rather than broadening deletion.
   Confirm any pending/uncertain send is resolved before destroying its journal.
6. Record the exact deletion allowlist and hashes outside the target directory.
   Record hashes of designated keep files, such as the separate personal-task
   database, wrapper and scoped instruction. Use the same directory flock as the
   helper while revalidating and removing only the approved regular files; remove
   the directory only when empty. Never use an unrestricted recursive deletion
   over an unexplored target.
7. Verify the target is absent, keep files are unchanged, installed skill remains,
   and the exact cron job is still paused. Exercise helper `--help` if needed;
   do not invoke setup/status/preflight against the cleared store as a verification
   shortcut, because initializing commands can destroy the fresh-start condition.
8. Report that the data is cleared, whether a backup exists, and that automatic
   check-ins remain paused. Invite a fresh setup request; do not automatically
   restore earlier preferences or reactivate messaging.
