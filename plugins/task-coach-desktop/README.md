# Task Coach Desktop development

Experimental macOS-first ChatGPT desktop integration, based on Hermes Task Coach
v1.0.1. The plugin has its own version: **0.1.0-alpha.2**. Python 3.11+ with
SQLite and timezone data is required. Cloud and native Windows are out of scope.

## Boundaries

| Concern | Hermes | ChatGPT desktop |
| --- | --- | --- |
| Instructions | `skills/task-coach/SKILL.md` | `plugins/task-coach-desktop/skills/task-coach-desktop/SKILL.md` |
| Runtime | core `driver.py`, Discord transport | plugin `desktop_runtime.py`, native same-chat output |
| Packaging | root `pyproject.toml`, Hermes skill install | `scripts/build-chatgpt-plugin.py`, plugin manifest |
| Storage | Hermes profile/default task directory | `task-coach-chatgpt-desktop` under XDG data directory or `~/.local/share` |
| Tests/data | existing core and Hermes suites | `tests/test_core_desktop.py`, fictional temporary stores only |

The task CLI, coaching engine and recurrence logic are shared. The CLI's default
continues to include the Hermes runtime. The desktop launcher explicitly omits
that parser; the desktop ZIP excludes `driver.py` and `clarification.py` entirely.
The Hermes skill instructions, packaging version and install command stay intact.
The ZIP contains an explicit allowlist, reproducible bytes, shared core version,
task schema version, and a SHA-256 inventory. Neither platform adopts the other's
store. Both use the current task schema (2); the plugin has no migration command.

Shared changes must pass both platforms' suites. Changes to instructions, native
scheduling or output reconciliation belong in the desktop adapter. Do not put
Discord credentials, Linux cron setup or Hermes onboarding in this plugin.
Do not put desktop scheduling or plugin packaging into the Hermes installer.
Future upstream updates should merge into this development branch, followed by
both suites and a rebuilt ZIP; they are not automatically shipped to users.

## Build and verify

From the repository root:

```sh
python3 -m unittest discover -s tests -q
python3 scripts/build-chatgpt-plugin.py --output "$PWD/dist/task-coach-desktop-0.1.0-alpha.2.zip"
```

Tests never install a plugin, create a native schedule, send messages or access
real task data. The extracted-package test runs independently of the checkout,
checks checklist operations, and proves no Hermes adapter is needed.

## Local Mac installation

Use a persistent test folder, for example `~/TaskCoachDesktopTest`. Extract the
**built ZIP** into its `plugin` subfolder. Do not install the source plugin folder
by itself: the builder adds the shared core that a cached plugin needs.

Create `.agents/plugins/marketplace.json` inside that test folder:

```json
{
  "name": "task-coach-desktop-test",
  "interface": {"displayName": "Task Coach Desktop Test"},
  "plugins": [{
    "name": "task-coach-desktop",
    "source": {"source": "local", "path": "./plugin"},
    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
    "category": "Productivity"
  }]
}
```

Open the test folder as a local project in the ChatGPT desktop app. Restart the
app, select **Task Coach Desktop Test** in the Plugins Directory, and install
**Task Coach Desktop (experimental)**. Start with “Help me set up Task Coach
Desktop, one question at a time.” Use a local execution environment. Rebuild,
replace the extracted plugin, and refresh/reinstall it after changes; verify the
installed version. This is a local catalog, not a public directory submission.

See the [official local plugin instructions](https://developers.openai.com/plugins/build/plugins)
and [desktop execution requirements](https://developers.openai.com/plugins/deploy/desktop-only).

## Live acceptance still required

Follow [the runtime protocol](skills/task-coach-desktop/references/desktop-runtime.md).
Validate the installed helper path, genuine conversation identity, scheduler
controls, paused schedule readback, optional test, and final activation on macOS.
The helper generates a schedule plan; it cannot install or independently verify
a native schedule. Without supported native controls, local task management
works but proactive setup must clearly report the blocker.

Native runs may consume model usage even when there is nothing to say. The app
and computer must support running the local schedule. If genuine assistant
message IDs/timestamps are unavailable, automatic follow-ups stay blocked.
Never invent native receipts or promise delivery. An in-flight native response
cannot be recalled after the local output claim.

To uninstall the test, pause the native schedule and local coach, remove the
schedule through native controls, then uninstall the plugin and remove its
catalog entry/test folder. Local task data remains until you explicitly delete
the separate desktop data directory. Hermes data is independent.
