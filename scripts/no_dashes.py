#!/usr/bin/env python3
"""House rule: never an em or en dash anywhere in the repo, plain "-" only.

Walks every tracked text file (lockfiles excluded) and exits non-zero with
file:line for each offender. Run by pre-commit, scripts/ci_local.sh and the
CI question-bank job; the vitest and pytest guards cover their own trees
in the test suites as well.

Usage: python scripts/no_dashes.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DASH = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")  # en dash, em dash
SKIP = ("pnpm-lock.yaml", "uv.lock")


def tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout
    return [ROOT / name for name in out.decode().split("\0") if name]


def main() -> int:
    offenders: list[str] = []
    for path in tracked_files():
        if path.name in SKIP or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue  # binary
        for number, line in enumerate(text.splitlines(), start=1):
            if DASH.search(line):
                offenders.append(
                    f"{path.relative_to(ROOT)}:{number}: {line.strip()[:100]}"
                )
    if offenders:
        print(f"em or en dash in {len(offenders)} line(s); use a plain '-':")
        for item in offenders:
            print(f"  {item}")
        return 1
    print("no em or en dashes in tracked files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
