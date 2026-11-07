#!/usr/bin/env python3
"""Validate the Ganek question bank: JSON Schema + cross-file invariants.

Usage: python questions/validate.py
Exits non-zero on any error. Requires: pyyaml, jsonschema.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).parent
schema = json.loads((ROOT / "schema.json").read_text())
validator = Draft202012Validator(schema)

errors: list[str] = []
all_ids: Counter[str] = Counter()
# house rule: never an em or en dash in any copy, plain "-" only
DASH = re.compile("[" + chr(0x2013) + chr(0x2014) + "]")  # en dash, em dash

# Test-wise candidates pick the longest option. An active question fails when
# its correct option is longer than every distractor by more than this many
# characters: lengthen a distractor (or tighten the answer) instead.
LONGEST_MARGIN = 10
# Questions where the longest correct option is unavoidable: id -> reason.
LONGEST_ALLOWLIST: dict[str, str] = {}
n_active = 0
n_correct_longest = 0
files = sorted(ROOT.glob("*/*.yaml"))

if not files:
    errors.append("no question files found under questions/*/")

for path in files:
    rel = path.relative_to(ROOT)
    try:
        data = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        errors.append(f"{rel}: YAML parse error: {e}")
        continue

    for number, line in enumerate(path.read_text().splitlines(), start=1):
        if DASH.search(line):
            errors.append(f"{rel}:{number}: em or en dash in copy; use a plain '-'")

    for err in validator.iter_errors(data):
        errors.append(f"{rel}: {'/'.join(map(str, err.path))}: {err.message}")
        continue

    if not isinstance(data, dict):
        continue

    # Cross-checks
    if data.get("domain") != path.parent.name:
        errors.append(
            f"{rel}: domain '{data.get('domain')}' != directory '{path.parent.name}'"
        )
    if data.get("tag") != path.stem:
        errors.append(f"{rel}: tag '{data.get('tag')}' != filename '{path.stem}'")

    for q in data.get("questions", []):
        if not isinstance(q, dict):
            continue
        qid = q.get("id", "?")
        all_ids[qid] += 1
        opts = q.get("options", {})
        if isinstance(opts, dict):
            texts = [str(v).strip().lower() for v in opts.values()]
            if len(set(texts)) != len(texts):
                errors.append(f"{rel}: {qid}: duplicate option texts")
            correct = q.get("correct")
            if q.get("status", "active") == "active" and correct in opts:
                n_active += 1
                answer = len(str(opts[correct]).strip())
                longest_other = max(
                    (len(str(v).strip()) for k, v in opts.items() if k != correct),
                    default=0,
                )
                if answer > longest_other:
                    n_correct_longest += 1
                margin = answer - longest_other
                if margin > LONGEST_MARGIN and qid not in LONGEST_ALLOWLIST:
                    errors.append(
                        f"{rel}: {qid}: correct option is the longest by {margin} "
                        f"chars (max {LONGEST_MARGIN}); lengthen a distractor"
                    )

for qid, n in all_ids.items():
    if n > 1:
        errors.append(f"duplicate question id across bank: {qid} ({n}x)")
for qid in LONGEST_ALLOWLIST:
    if qid not in all_ids:
        errors.append(f"LONGEST_ALLOWLIST names unknown question id: {qid}")

if errors:
    print(f"✗ {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

n_files = len(files)
n_q = sum(all_ids.values())
print(f"✓ question bank valid: {n_files} file(s), {n_q} question(s)")
if n_active:
    share = 100 * n_correct_longest / n_active
    print(
        f"  correct option is the strict longest in {n_correct_longest}/{n_active}"
        f" active question(s) ({share:.0f}%; 25% is chance)"
    )
