"""The demo jobs must not contradict themselves: free-text location vs the
remote policy enum (issue #364, the SRE job once read "Berlin or remote (EU)"
next to an On-site chip). Pure check over the specs, no database needed."""

import re

import pytest

from app.models import RemotePolicy
from app.services.demo_seed import JOBS

REMOTE_WORDS = re.compile(r"\b(remote|anywhere|hybrid|home office|work from home)\b", re.I)
ONSITE_WORDS = re.compile(r"\b(on-?site|in-office|hybrid)\b", re.I)


@pytest.mark.parametrize("spec", JOBS, ids=lambda s: s.title)
def test_demo_job_location_matches_remote_policy(spec) -> None:
    if spec.remote_policy is RemotePolicy.ONSITE:
        assert not REMOTE_WORDS.search(spec.location), spec.location
    if spec.remote_policy is RemotePolicy.REMOTE:
        assert not ONSITE_WORDS.search(spec.location), spec.location
