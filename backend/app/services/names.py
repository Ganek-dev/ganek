"""Name split used by the ATS handoff.

This is the split every ATS import tool uses: everything before the last
space is the first name, the last token is the last name. The full name
travels next to it everywhere.
"""


def split_name(name: str) -> tuple[str, str]:
    """Split a full name into ``(first, last)``.

    Runs of whitespace collapse to one space. A single token is treated as
    a last name with an empty first name; an empty or blank string gives
    ``("", "")``.
    """
    tokens = name.split()
    if not tokens:
        return "", ""
    if len(tokens) == 1:
        return "", tokens[0]
    return " ".join(tokens[:-1]), tokens[-1]
