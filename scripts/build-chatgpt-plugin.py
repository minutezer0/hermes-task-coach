"""Build a portable desktop plugin ZIP from the isolated adapter and pinned core.

No user storage, virtualenv, symlinks or untracked runtime artifacts are packaged.
The Hermes skill remains the sole source of the shared core in this repository.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
import tomllib

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / 'plugins' / 'task-coach-desktop'
CORE = ROOT / 'skills' / 'task-coach' / 'scripts' / 'task_coach'
MODULES = ('__init__.py', '__main__.py', 'cli.py', 'coaching.py', 'recurrence.py')
SKILL = 'skills/task-coach-desktop/'


def build(output):
    output = Path(output)
    if not output.is_absolute() or output.is_symlink():
        raise ValueError('output must be an absolute, non-symlink path')
    files = {'plugin.json': PLUGIN / 'plugin.json', 'LICENSE': ROOT / 'LICENSE'}
    files.update({SKILL + name: PLUGIN / SKILL / name for name in (
        'SKILL.md', 'references/desktop-runtime.md', 'scripts/task-coach-desktop.py', 'scripts/desktop_runtime.py')})
    files.update({SKILL + 'scripts/task_coach/' + name: CORE / name for name in MODULES})
    manifest = json.loads(files['plugin.json'].read_text())
    if manifest['extensions']['com.openai']['requires_local_executor'] is not True:
        raise ValueError('desktop plugin must require a local executor')
    contents = {}
    for name, source in files.items():
        if source.is_symlink() or not source.is_file():
            raise ValueError('missing or symlinked package source: ' + str(source))
        contents[name] = source.read_bytes()
    # Trace exactly which core bytes shipped, without depending on Git at runtime.
    inventory = {name: hashlib.sha256(data).hexdigest() for name, data in sorted(contents.items())}
    contents['build-manifest.json'] = (json.dumps(dict(version=manifest['version'], core_version=tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version'], task_schema=2, sha256=inventory), indent=2) + '\n').encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(contents.items()):
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = (0o100644 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    return dict(path=str(output), version=manifest['version'], files=len(contents),
                sha256=hashlib.sha256(output.read_bytes()).hexdigest())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output)))
