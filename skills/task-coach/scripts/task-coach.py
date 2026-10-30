"""Run the bundled Task Coach without installing a Python package."""
import sys
from pathlib import Path


if sys.version_info < (3, 11):
    sys.stderr.write("Task Coach requires Python 3.11 or newer; run this helper with a supported python3.\n")
    raise SystemExit(2)

# Resolve from this helper, not the shell's cwd or an installed console command.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from task_coach.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
