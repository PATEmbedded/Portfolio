"""Wait until files are added, changed or removed in private/projects, then list them and exit.

    python tools/watch.py --save   remember the current state (after the new files are handled and published)
    python tools/watch.py          wait for a change, let copying finish (no change for 20 s), print it, exit
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "private" / "projects"
STATE = ROOT / "private" / "_watch.json"
POLL, SETTLE = 5, 20


def snapshot():
    files = {}
    for path in PROJECTS.rglob("*"):
        if path.is_file() and not path.name.startswith(("~$", ".")) and ".tmp." not in path.name:
            stat = path.stat()
            files[path.relative_to(PROJECTS).as_posix()] = [stat.st_size, int(stat.st_mtime)]
    return files


def main():
    if "--save" in sys.argv:
        STATE.write_text(json.dumps(snapshot(), ensure_ascii=False, indent=0), encoding="utf-8")
        return
    saved = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}
    current = snapshot()
    while current == saved:
        time.sleep(POLL)
        current = snapshot()
    stable_since = time.time()
    while time.time() - stable_since < SETTLE:
        time.sleep(POLL)
        latest = snapshot()
        if latest != current:
            current, stable_since = latest, time.time()
    for name in sorted(set(saved) | set(current)):
        if name not in saved:
            print(f"added: {name}")
        elif name not in current:
            print(f"removed: {name}")
        elif saved[name] != current[name]:
            print(f"changed: {name}")


if __name__ == "__main__":
    main()
