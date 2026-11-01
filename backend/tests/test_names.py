import pytest

from app.services.names import split_name


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Jane Applicant", ("Jane", "Applicant")),
        ("Jane Q. Applicant", ("Jane Q.", "Applicant")),
        ("Madonna", ("", "Madonna")),
        ("  Jane   Q.  Applicant ", ("Jane Q.", "Applicant")),
        ("", ("", "")),
        ("   ", ("", "")),
    ],
)
def test_split_name(name: str, expected: tuple[str, str]) -> None:
    assert split_name(name) == expected
