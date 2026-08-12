"""Pure-logic tests for the privacy helpers feeding emails and the notice."""

import pytest

from app.core.config import settings
from app.models import Company
from app.services.company import controller_name, privacy_notice_url


def _company(**overrides: object) -> Company:
    defaults: dict[str, object] = {"slug": "acme", "name": "Acme Labs", "settings": {}}
    defaults.update(overrides)
    return Company(**defaults)


def test_controller_name_prefers_legal_name() -> None:
    assert controller_name(_company()) == "Acme Labs"
    assert controller_name(_company(settings={"legal_name": "Acme Labs GmbH"})) == "Acme Labs GmbH"
    assert controller_name(_company(settings=None)) == "Acme Labs"


def test_privacy_notice_url_is_mode_aware(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "public_base_url", "https://jobs.example.com/")
    monkeypatch.setattr(settings, "mode", "single")
    assert privacy_notice_url(_company()) == "https://jobs.example.com/privacy"
    monkeypatch.setattr(settings, "mode", "multi")
    assert privacy_notice_url(_company()) == "https://jobs.example.com/c/acme/privacy"
