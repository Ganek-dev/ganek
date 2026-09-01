# scripts/

- `ci_local.sh` - mirror the full GitHub CI pipeline locally before
  pushing: question-bank validation, advisory audits, frontend
  lint/typecheck/test/build under Node 22 (nvm), the backend matrix
  (ruff + mypy + pytest on py3.12 AND py3.14 against throwaway
  postgres/minio containers - never touches dev data), and both e2e
  legs on a scratch compose stack (stops a running dev stack and
  restores it afterwards). Stage-selectable: `scripts/ci_local.sh
  --help`. Full run is ~6-7 minutes; run at least the stages your
  diff touches - runtime-dependency changes warrant the full run.
- `e2e_smoke.sh` - curl smoke suite against a running stack (used by
  CI and by `ci_local.sh`'s e2e stage).
- `migrate_dev_data_ganek.sh` - one-time migration of a pre-rename dev
  environment (vetd-* volumes, postgres role/db, minio bucket) to the
  ganek names. Copies volumes; the old ones stay behind as backups.

Operational helpers. Planned:

- `delete_candidate.py` - GDPR wipe of a candidate: rows + CV objects + attempts (M2)
- `dev_seed.py` - demo company + jobs + fake applications for local dev (M1)
