#!/usr/bin/env python3
"""Validate the Vetd question bank: JSON Schema + cross-file invariants.

Usage: python questions/validate.py
Exits non-zero on any error. Requires: pyyaml, jsonschema.
"""
from __future__ import annotations

import json
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

    for err in validator.iter_errors(data):
        errors.append(f"{rel}: {'/'.join(map(str, err.path))}: {err.message}")
        continue

    if not isinstance(data, dict):
        continue

    # Cross-checks
    if data.get("domain") != path.parent.name:
        errors.append(f"{rel}: domain '{data.get('domain')}' != directory '{path.parent.name}'")
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

for qid, n in all_ids.items():
    if n > 1:
        errors.append(f"duplicate question id across bank: {qid} ({n}x)")

if errors:
    print(f"✗ {len(errors)} error(s):")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)

n_files = len(files)
n_q = sum(all_ids.values())
print(f"✓ question bank valid: {n_files} file(s), {n_q} question(s)")
