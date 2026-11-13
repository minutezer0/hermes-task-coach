"""Isolated desktop entry point; the release builder vendors the unchanged core."""
import argparse
import os
from pathlib import Path
import sqlite3
import sys


def main():
    if sys.version_info < (3, 11):
        raise ValueError('Task Coach Desktop requires Python 3.11 or newer')
    if os.name != 'posix':
        raise ValueError('this prototype requires macOS or a Linux host; native Windows is not qualified')
    here = Path(__file__).resolve().parent
    # Release ZIPs contain the core alongside this launcher. Development uses
    # exactly the repository core without copying or changing Hermes sources.
    core = here if (here / 'task_coach').is_dir() else here.parents[4] / 'skills' / 'task-coach' / 'scripts'
    if not (core / 'task_coach' / 'cli.py').is_file():
        raise ValueError('shared core is missing; install the built desktop plugin ZIP')
    sys.path.insert(0, str(core))
    sys.path.insert(0, str(here))
    from desktop_runtime import DesktopRuntime, default_directory, check_scope, run_desktop
    from task_coach.cli import main as task_main

    parser = argparse.ArgumentParser(description='Task Coach Desktop: separate local tasks and guarded chat output.')
    parser.add_argument('--data-dir', type=Path, default=default_directory())
    parser.add_argument('command', nargs='?', choices=['init', 'setup', 'add', 'list', 'export', 'search',
                        'show', 'update', 'done', 'snooze', 'checklist', 'desktop'])
    parser.add_argument('arguments', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    rest = args.arguments
    if args.command is None:
        parser.print_help()
        return 0
    if not args.data_dir.is_absolute():
        raise ValueError('data directory must be absolute')
    if args.command == 'desktop' and ('--help' in rest or '-h' in rest):
        return run_desktop(args.data_dir, rest)
    if args.command == 'desktop':
        check_scope(args.data_dir)
        return run_desktop(args.data_dir, rest)
    if any(v == '--interactive' or v == '--destination' or v.startswith('--destination=') for v in rest):
        raise ValueError('desktop setup uses confirmed flags; no interactive stdin or Hermes destination')
    check_scope(args.data_dir, initializing=args.command in ('init', 'setup'))
    if (args.data_dir / 'desktop.sqlite3').exists():
        # Refuse corrupt/unknown runtime state before a shared task write.
        DesktopRuntime(args.data_dir).status()
    result = task_main(['--data-dir', str(args.data_dir), args.command, *rest], include_runtime=False)
    if result == 0 and args.command in ('init', 'setup') and not any(v in ('--help', '-h') for v in rest):
        DesktopRuntime(args.data_dir).initialize()
    return result


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, ValueError, sqlite3.Error) as error:
        sys.stderr.write('task-coach-desktop: error: ' + str(error) + '\n')
        raise SystemExit(2)
