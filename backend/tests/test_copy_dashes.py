"""Owner rule: never an em or en dash in any copy, plain "-" only, and no
arrow glyph either (words instead). Email bodies, API error details and
template strings live in app/, so the whole package stays clear (board
card "Copy sweep")."""

import re
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
DASH = re.compile("[" + chr(0x2013) + chr(0x2014) + chr(0x2192) + "]")  # en, em dash, arrow


def test_app_has_no_em_or_en_dashes_or_arrows() -> None:
    offenders = [
        f"{path.relative_to(APP.parent)}:{number}: {line.strip()}"
        for path in sorted(APP.rglob("*.py"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if DASH.search(line)
    ]
    assert offenders == []
