"""Every schemas module and every `python -m` entry point imports on its own.

The test session imports app.main first, which hides import cycles that only
bite when a module is the first one loaded: `python -m app.services.demo_seed`
died on schemas.scorecards -> services.scorecards -> ... -> schemas.company ->
schemas.scorecards while the whole suite stayed green."""

import subprocess
import sys
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
ENTRY_POINTS = ["app.main", "app.worker", "app.services.seed", "app.services.demo_seed"]
SCHEMAS = sorted(
    f"app.schemas.{path.stem}"
    for path in (BACKEND / "app" / "schemas").glob("*.py")
    if path.stem != "__init__"
)


@pytest.mark.parametrize("module", ENTRY_POINTS + SCHEMAS)
def test_module_imports_first(module: str) -> None:
    result = subprocess.run(  # noqa: S603 - our interpreter, our module names
        [sys.executable, "-c", f"import {module}"],
        cwd=BACKEND,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr[-2000:]
