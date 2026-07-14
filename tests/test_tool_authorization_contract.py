import json
from pathlib import Path

from core.web.services import agent_directory_service, agent_role_tool_profile_service


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "tool_authorization"
REQUIRED_RUN_KINDS = {
    "direct_session",
    "chat_room",
    "team_workflow",
    "research",
    "supervised",
    "self_evolution",
    "replay",
    "parallel",
    "subagent",
}


def _load_fixture(name: str) -> dict:
    return json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))


def test_agent_policy_baselines_are_complete_and_internally_consistent():
    payload = _load_fixture("agent_policy_baselines.json")
    cases = list(payload["cases"])

    assert payload["schema_version"] == 1
    assert len({case["case_id"] for case in cases}) == len(cases)
    assert {
        "default_session_agent",
        "explicit_zero_tool_agent",
        "research_source_finder",
        "team_operation_agent",
        "self_evolution_executor",
        "supervised_observer",
        "legacy_wide_private_policy",
        "missing_policy",
        "corrupt_policy",
    } == {case["case_id"] for case in cases}

    for case in cases:
        allowed = set(case.get("expected_allowed_tools") or case.get("expected_required_tools") or [])
        preferred = set(case.get("expected_preferred_tools") or [])
        forbidden = set(case.get("expected_forbidden_tools") or [])
        assert preferred.issubset(allowed), case["case_id"]
        assert allowed.isdisjoint(forbidden), case["case_id"]
        if case["visibility_semantics"] == "deny_all":
            assert not allowed
            assert case["expected_resolution"] in {"policy_missing", "policy_invalid"}


def test_default_session_fixture_matches_the_current_product_contract():
    payload = _load_fixture("agent_policy_baselines.json")
    case = next(item for item in payload["cases"] if item["case_id"] == "default_session_agent")

    assert case["expected_allowed_tools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_ALLOWED_TOOLS)
    assert case["expected_preferred_tools"] == list(agent_directory_service.DEFAULT_SESSION_AGENT_PREFERRED_TOOLS)
    assert case["migration_expectation"] == "preserve_exact_assignment"


def test_fixed_role_fixtures_match_current_role_policy_sources():
    payload = _load_fixture("agent_policy_baselines.json")
    cases = [item for item in payload["cases"] if item["visibility_semantics"] == "role_profile"]

    for case in cases:
        policy = agent_role_tool_profile_service.resolve_role_tool_policy(
            role_key=case["role_key"],
            primary_mode=case["primary_mode"],
            policy_id=f"tool-fixture-{case['case_id']}",
        )
        assert policy is not None, case["case_id"]
        allowed = set(policy["allowedTools"])
        assert set(case["expected_required_tools"]).issubset(allowed), case["case_id"]
        assert set(case["expected_forbidden_tools"]).isdisjoint(allowed), case["case_id"]


def test_runtime_entrypoint_fixture_covers_every_run_kind_and_both_gate_layers():
    payload = _load_fixture("runtime_entrypoints.json")
    bindings = list(payload["binding_entrypoints"])
    dispatches = list(payload["dispatch_entrypoints"])
    all_entries = bindings + dispatches

    assert payload["schema_version"] == 1
    assert set(payload["required_run_kinds"]) == REQUIRED_RUN_KINDS
    assert len({entry["entrypoint_id"] for entry in all_entries}) == len(all_entries)
    assert REQUIRED_RUN_KINDS.issubset({kind for entry in bindings for kind in entry["run_kinds"]})
    assert REQUIRED_RUN_KINDS.issubset({kind for entry in dispatches for kind in entry["run_kinds"]})
    assert all(entry["module"] and entry["symbol"] and entry["target_owner"] for entry in all_entries)
    assert len(payload["known_bypass_risks"]) >= 5
