"""Runs in the `ee` CI job, from backend/ with ganek-ee installed into the
backend venv (python -m pytest ../ee/backend/tests)."""

from importlib.metadata import entry_points

from app.core.plans import ENTRY_POINT_GROUP, PlanPolicy, load_plan_policy
from ganek_ee.plans import HostedPolicy


def test_entry_point_is_registered() -> None:
    found = [ep.value for ep in entry_points(group=ENTRY_POINT_GROUP)]
    assert found == ["ganek_ee.plans:HostedPolicy"]


def test_hosted_edition_loads_the_ee_policy() -> None:
    policy = load_plan_policy("hosted")
    assert isinstance(policy, HostedPolicy)


def test_community_edition_keeps_the_core_policy() -> None:
    assert load_plan_policy("community").name == "self_hosted"


def test_hosted_policy_satisfies_the_core_protocol() -> None:
    policy: PlanPolicy = HostedPolicy()
    assert policy.name == "hosted"
