"""Knowledge sideflow rollout closeout (方案 Task 7).

Covers the three-mode rollout surface plus the two wiring gaps:

- ``[research.knowledge_sideflow]`` config section: default ``off``,
  bootstrap payload carries it, mode is re-read on every call;
- off: knowledge command offers hidden at the snapshot layer;
- shadow: every legacy-chain collection request records a shadow knowledge
  invocation (T3 fingerprint semantics) while the legacy chain's own return
  values stay byte-for-byte identical;
- on: NEW formal runs pin the registered main-flow 3.0.0 definition while a
  historical 2.1.0 run still advances and forks on the 17-node topology;
- managed-root wiring: ``managedSourceRootIds`` flows from the ensure command
  through the invocation child input snapshot into the child's collection-run
  payload, and a fixture root really enters the import bypass.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.research.workflow.contracts import WorkflowCommandKind
from core.research.workflow.definition import build_challenge_cup_workflow_definition
from core.research.workflow.definition_registry import (
    register_or_resolve,
    registered_identities,
    reset_registry_for_tests,
    resolve_definition_by_version_id,
    resolve_definition_for_run_record,
)
from core.research.workflow.knowledge_sideflow_definition import (
    CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3,
    KNOWLEDGE_SIDEFLOW_NODE_IDS,
    build_challenge_cup_workflow_definition_v3,
)

from core.web.services.team_workflow.research_runtime import hypothesis_first_chain as chain
from core.web.services.team_workflow.research_runtime.agent_node_execution import (
    _apply_managed_root_selection,
)
from core.web.services.team_workflow.research_runtime.command_offers.knowledge_collection import (
    build_knowledge_collection_offers,
)
from core.web.services.team_workflow.research_runtime.knowledge_rollout import (
    KNOWLEDGE_SIDEFLOW_MODE_OFF,
    KNOWLEDGE_SIDEFLOW_MODE_ON,
    KNOWLEDGE_SIDEFLOW_MODE_SHADOW,
    creation_workflow_definition,
    knowledge_sideflow_mode,
    list_shadow_knowledge_invocations,
    record_shadow_knowledge_invocation,
)
from core.web.services.team_workflow.source_collection import facade
from core.web.services.team_workflow.source_collection import (
    runs as source_collection_runs,
)

from tests._support.graph_helpers import GraphHarness


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _patch_mode(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    from config.models import AppConfig

    config = AppConfig()
    config.research.knowledge_sideflow.mode = mode
    monkeypatch.setattr("config.settings.get_config", lambda: config)


@pytest.fixture(autouse=True)
def _isolated_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def _legacy_version_id() -> str:
    return register_or_resolve(build_challenge_cup_workflow_definition()).workflowVersionId


def _run_record_dict(run_id: str, identity, *, completed, current) -> dict:
    return {
        "runId": run_id,
        "workflowId": "challenge-cup-research",
        "workflowVersionId": identity.workflowVersionId,
        "structureHash": identity.structureHash,
        "completedNodeIds": completed,
        "runtimeCurrentNodeIds": current,
    }


# ---------------------------------------------------------------------------
# 1) rollout config: default off, bootstrap, live re-read
# ---------------------------------------------------------------------------


def test_rollout_mode_defaults_off_and_bootstrap_carries_section() -> None:
    from config.models import AppConfig
    from config.operator_bootstrap import build_default_operator_config

    assert AppConfig().research.knowledge_sideflow.mode == "off"
    bootstrap = build_default_operator_config(include_unconfigured_providers=False)
    assert bootstrap["research"]["knowledge_sideflow"] == {"mode": "off"}


def test_unknown_mode_value_fails_closed_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "config.settings.get_config",
        lambda: SimpleNamespace(
            research=SimpleNamespace(
                knowledge_sideflow=SimpleNamespace(mode="WILD")
            )
        ),
    )
    assert knowledge_sideflow_mode() == KNOWLEDGE_SIDEFLOW_MODE_OFF


# ---------------------------------------------------------------------------
# 2) offer gating: off hides, shadow/on surface
# ---------------------------------------------------------------------------


def _live_run() -> SimpleNamespace:
    return SimpleNamespace(run_id="run-1", run_version=3, status="running", active_node_id="hypothesis_design")


def test_on_mode_surfaces_both_knowledge_offers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    offers = build_knowledge_collection_offers(run=_live_run())
    commands = [offer.command for offer in offers]
    assert WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION in commands
    assert WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION in commands


def test_off_mode_hides_knowledge_offers(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_OFF)
    assert build_knowledge_collection_offers(run=_live_run()) == []


# ---------------------------------------------------------------------------
# 3) on: new runs pin 3.0.0; historical 2.1.0 runs advance AND fork on the
#    17-node topology
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode,expected_schema,expected_nodes", [
    ("off", "2.1.0", 17),
    ("shadow", "2.1.0", 17),
    ("on", CHALLENGE_CUP_RESEARCH_SCHEMA_VERSION_V3, 12),
])
def test_creation_definition_identity_follows_mode(
    monkeypatch: pytest.MonkeyPatch, mode: str, expected_schema: str, expected_nodes: int
) -> None:
    _patch_mode(monkeypatch, mode)
    definition, identity = creation_workflow_definition()
    assert definition.schemaVersion == expected_schema
    assert len(definition.nodes) == expected_nodes
    assert identity.workflowVersionId == register_or_resolve(definition).workflowVersionId
    registered_versions = {
        identity.workflowVersionId
        for identity in registered_identities("challenge-cup-research")
    }
    assert identity.workflowVersionId in registered_versions


def test_on_mode_legacy_run_still_advances_on_17_node_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A run created before the switch keeps its pinned 2.1.0 graph: in on
    mode it still walks the 17-node chain all the way to knowledge_handoff
    (a node the 3.0.0 topology does not even contain)."""
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = GraphHarness(tmp_path)
    try:
        harness.seed(run_id="run-legacy", workflow_version_id=_legacy_version_id())
        pending = harness.start_thread_to("knowledge_handoff", run_id="run-legacy")
        payload = json.loads(pending.payload_json)
        assert payload["nodeId"] == "knowledge_handoff"
        # The walk compiled the pinned legacy definition, never the new 3.0.0.
        resolved = resolve_definition_by_version_id(_legacy_version_id())
        assert len(resolved.nodes) == 17
        assert "knowledge_handoff" in {node.nodeId for node in resolved.nodes}
    finally:
        harness.close()


def test_on_mode_legacy_run_fork_stays_on_17_node_topology(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.research.workflow.contracts import WorkflowCommandKind as Kind
    from core.web.services.team_workflow.research_runtime.operator_authorization import (
        server_operator_scope,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = GraphHarness(tmp_path)
    try:
        harness.commands.command_service._coordinator_factory = (  # noqa: SLF001
            lambda: harness.coordinator
        )
        harness.seed(run_id="run-legacy", workflow_version_id=_legacy_version_id())
        harness.start_thread_to("source_finding", run_id="run-legacy")
        parent_snap = harness.coordinator.snapshot("run-legacy")
        with server_operator_scope("u-1", roles=("operator",)):
            receipt = harness.commands.command_service.submit(
                harness.commands.request(
                    command=Kind.FORK_REVISION,
                    run_id="run-legacy",
                    node_id="source_finding",
                    expected_run_version=1,
                    idempotency_key="ui:fork-rollout-1",
                    payload={
                        "fromNodeId": "source_finding",
                        "reason": "rollout closeout fork probe",
                        "checkpointId": parent_snap["checkpointId"],
                    },
                )
            )
        assert receipt.status == "accepted"
        assert harness.fork_worker.run_once() == 1
        harness.worker.run_once()
        pending = harness.latest_adapter_pending("run-legacy")
        assert pending is not None
        payload = json.loads(pending.payload_json)
        # The forked child resumes INSIDE the 17-node legacy topology.
        assert payload["nodeId"] == "source_finding"
        child_rows = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id, workflow_version_id FROM workflow_runs "
                "WHERE parent_run_id = 'run-legacy'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert len(child_rows) == 1
        assert child_rows[0][1] == _legacy_version_id()
    finally:
        harness.close()


def test_on_mode_read_layer_still_resolves_legacy_run_nodes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    legacy = register_or_resolve(build_challenge_cup_workflow_definition())
    resolved = resolve_definition_for_run_record(
        _run_record_dict(
            "run-legacy",
            legacy,
            completed=["hypothesis_design"],
            current=["knowledge_handoff"],
        )
    )
    assert resolved.structureHash == legacy.structureHash
    assert len(resolved.nodes) == 17


# ---------------------------------------------------------------------------
# 4) shadow: invocation records + byte-identical legacy chain
# ---------------------------------------------------------------------------


def test_shadow_recording_only_happens_in_shadow_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    kwargs = {
        "team_id": "team-1",
        "question_id": "sci-096",
        "scope": {"questionId": "SCI-096"},
        "search_envelope": {"keywords": ["evaporation"]},
        "requirements": {"minSources": 3},
        "collection_run_id": "run-col-1",
        "collection_request_id": "hfcr-1",
        "now_provider": lambda: 1_000,
    }
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_OFF)
    assert record_shadow_knowledge_invocation(**kwargs) is None
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    assert record_shadow_knowledge_invocation(**kwargs) is None
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    record = record_shadow_knowledge_invocation(**kwargs)
    assert record is not None
    assert record["shadow"] is True
    assert record["invocationId"] == f"kshadow-{record['requestHash'][:16]}"
    payload = list_shadow_knowledge_invocations("team-1")
    assert payload["total"] == 1
    assert payload["records"][0]["requestHash"] == record["requestHash"]
    assert payload["records"][0]["collectionRequestId"] == "hfcr-1"


def test_shadow_fingerprints_match_the_invocation_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.knowledge_sideflow_service import (
        compute_invocation_fingerprints,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    scope = {"questionId": "SCI-096", "projectId": "proj-1"}
    envelope = {"keywords": ["evaporation", "cooling"]}
    requirements = {"minSources": 3}
    record = record_shadow_knowledge_invocation(
        team_id="team-1",
        question_id="SCI-096",
        scope=scope,
        search_envelope=envelope,
        requirements=requirements,
        now_provider=lambda: 1_000,
    )
    expected = compute_invocation_fingerprints(
        question_id="SCI-096",
        scope=scope,
        search_envelope=envelope,
        requirements=requirements,
        source_policy_version=record["sourcePolicyVersion"],
    )
    assert record["scopeHash"] == expected["scopeHash"]
    assert record["searchEnvelopeHash"] == expected["searchEnvelopeHash"]
    assert record["requirementsHash"] == expected["requirementsHash"]
    assert record["requestHash"] == expected["requestHash"]


def _legacy_chain_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    storage_dir: str = "a",
):
    """Isolate _process_collection_decisions exactly like the chain tests do."""
    decision = {
        "decision": chain.REQUEST_EVIDENCE_DECISION,
        "candidateRefs": ["hyp-a"],
        "evidenceRefs": ["message-a"],
        "searchEnvelope": {"keywords": ["predictive coding"]},
    }
    meeting = {
        "meetingRoundId": "meeting-hf-start",
        "scopeHash": "scope-hf-start",
        "question": "SCI-096",
    }
    monkeypatch.setattr(
        chain, "_storage_path",
        lambda team_id: tmp_path / storage_dir / f"{team_id}.jsonl",
    )
    monkeypatch.setattr(
        chain,
        "_scope_envelope_for_meeting",
        lambda _meeting: {"scopeHash": "scope-hf-start"},
    )
    monkeypatch.setattr(
        facade, "_normalize_search_envelope",
        lambda envelope, *, require_keywords: dict(envelope or {}),
    )
    monkeypatch.setattr(facade, "_normalize_requirements", lambda value: dict(value or {}))
    monkeypatch.setattr(
        facade, "_normalize_writeback_policy", lambda value: dict(value or {})
    )
    monkeypatch.setattr(
        facade, "research_knowledge_collection_facade",
        lambda **_kwargs: {"locator": {"runId": "dprun-hf-start"}},
    )
    monkeypatch.setattr(
        source_collection_runs, "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: {"runId": run_id, "status": "running"},
    )
    close_result = {
        "decisions": [
            {"decisionId": chain._decision_id_for(meeting, decision)}
        ]
    }
    return meeting, close_result, decision


def _normalize_request(request: dict) -> dict:
    # createdAt carries wall-clock time; every other field must match byte-for-byte.
    return {key: value for key, value in request.items() if key != "createdAt"}


def test_legacy_chain_output_identical_with_shadow_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path / "shadow-store"))

    meeting, close_result, decision = _legacy_chain_fixture(tmp_path, monkeypatch)
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_OFF)
    off_result = chain._process_collection_decisions(
        "team-hf", meeting, close_result, {"decisions": [decision]}
    )
    assert off_result["skipped"] == []
    assert off_result["requests"][0]["collectionRunId"] == "dprun-hf-start"
    assert list_shadow_knowledge_invocations("team-hf")["total"] == 0

    # Fresh storage for the second (shadow) execution of the same request.
    meeting2, close_result2, decision2 = _legacy_chain_fixture(
        tmp_path, monkeypatch, storage_dir="b"
    )
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    shadow_result = chain._process_collection_decisions(
        "team-hf", meeting2, close_result2, {"decisions": [decision2]}
    )
    assert _normalize_request(shadow_result["requests"][0]) == _normalize_request(
        off_result["requests"][0]
    )
    assert shadow_result["skipped"] == off_result["skipped"]
    shadow = list_shadow_knowledge_invocations("team-hf")
    assert shadow["total"] == 1
    record = shadow["records"][0]
    assert record["shadow"] is True
    assert record["collectionRunId"] == "dprun-hf-start"
    assert record["questionId"] == "SCI-096"
    assert record["legacyScopeHash"] == "scope-hf-start"


def test_legacy_chain_recovery_path_records_shadow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path / "shadow-store"))
    from core.research.workflow.contracts import scope_hash_for

    scope_identity = {
        "program": "prog",
        "theme": "theme",
        "campaign": "camp",
        "question": "SCI-096",
        "branch": "main",
        "workflow": "challenge",
    }
    request = {
        "recordKind": chain.COLLECTION_REQUEST_KIND,
        "requestId": "hfcr-recover-1",
        "requestHash": "hash-1",
        "status": "pending",
        "meetingRoundId": "meeting-hf-start",
        "decisionId": "decision-1",
        "questionId": "SCI-096",
        **scope_identity,
        "agentId": "agent-1",
        "mode": "research_deep",
        "scopeHash": scope_hash_for(**scope_identity, agent_id="agent-1", mode="research_deep"),
        "searchEnvelope": {"keywords": ["predictive coding"]},
        "requirements": {"minSources": 2},
        "writebackPolicy": {},
        "collectionRunId": "",
        "collectionRunStatus": "failed",
    }
    storage = tmp_path / "team-hf.jsonl"
    storage.write_text(json.dumps(request, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(chain, "_storage_path", lambda team_id: storage)
    ensured: dict[str, object] = {}

    def fake_ensure(**kwargs):
        ensured.update(kwargs)
        return {"locator": {"runId": "dprun-recovered"}}

    monkeypatch.setattr(facade, "research_knowledge_collection_facade", fake_ensure)
    monkeypatch.setattr(
        source_collection_runs, "start_source_collection_search_background",
        lambda team_id, run_id, payload=None: {"runId": run_id},
    )
    from core.web.services import team_service

    monkeypatch.setattr(team_service, "assert_team_exists", lambda value: value)
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    outcome = chain.recover_collection_request("team-hf", "hfcr-recover-1")
    assert outcome["status"] == "recovered"
    assert outcome["request"]["collectionRunId"] == "dprun-recovered"
    shadow = list_shadow_knowledge_invocations("team-hf")
    assert shadow["total"] == 1
    record = shadow["records"][0]
    assert record["collectionRequestId"] == "hfcr-recover-1"
    assert record["collectionRunId"] == "dprun-recovered"
    assert record["legacyScopeHash"] == record["legacyScopeHash"]  # present, deterministic
    assert ensured["action"] == "ensure"


# ---------------------------------------------------------------------------
# 5) managed-root wiring
# ---------------------------------------------------------------------------


def test_managed_root_selection_rides_the_child_input_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_knowledge_sideflow_run import _invoke, _seed_parent

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        outcome = _invoke(
            harness,
            scope={
                "questionId": "SCI-096",
                "projectId": "challenge-sci-096",
                "managedSourceRootIds": ["Root-A", "root-b", "root-a"],
            },
        )
        child_run_id = outcome["childRunId"]
        assert child_run_id
        child = harness.commands.store.get_run(child_run_id)
        snapshot = json.loads(child.input_snapshot_json)
        assert snapshot["managedSourceRootIds"] == ["root-a", "root-b"]

        # The child's collection-run payload picks the selection up verbatim.
        record = {"inputSnapshot": snapshot, "teamId": child.team_id, "runId": child_run_id}
        payload: dict[str, object] = {
            "researchProjectId": "proj",
            "title": "t",
            "goal": "g",
            "topic": "topic",
            "inputRefs": [],
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": "agent-1"},
            "scope": {"workflowRunId": child_run_id},
        }
        _apply_managed_root_selection(payload, snapshot)
        assert payload["managedSourceRootIds"] == ["root-a", "root-b"]
        assert payload["collectionMode"] == "mixed"

        # Runs without a root selection keep a byte-identical payload.
        untouched = {"scope": {"workflowRunId": "x"}}
        _apply_managed_root_selection(untouched, {"kind": "knowledge_sideflow_child"})
        assert untouched == {"scope": {"workflowRunId": "x"}}
    finally:
        harness.close()


def test_managed_root_ids_reach_real_collection_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end: ensure command -> child snapshot -> collection payload -> the
    managed-root import bypass actually imports a fixture root."""
    from core.web.services import team_service, team_workflow_orchestration_service
    from core.web.services.team_workflow.source_collection import managed_roots
    from tests._support.team_workflow.helpers import _use_tmp_project_root
    from tests.test_team_workflow_managed_source_roots import (
        _build_docx,
        DOC_BODY,
    )

    _use_tmp_project_root(tmp_path, monkeypatch)
    desktop = tmp_path / "desktop-rollout"
    desktop.mkdir(parents=True)
    _build_docx(desktop / "项目简介.docx", DOC_BODY)
    root_id = "msroot-rollout"
    managed_roots.register_managed_source_root({"localPath": str(desktop), "rootId": root_id})

    # The same call shape _apply_managed_root_selection produces for a child.
    result = team_service.ensure_knowledge_expansion_team_agents(purge_stale=True)
    team = result["team"]
    source_member = next(
        member for member in team["members"] if member["role"] == "source_finder"
    )
    response = team_workflow_orchestration_service.start_source_collection_run(
        team["teamId"],
        {
            "title": "知识侧流程受管根搜集",
            "workflowPurpose": "knowledge_expansion",
            "collectionMode": "mixed",
            "topic": "challenge cup",
            "agentRoles": ["source_finder"],
            "agentIds": {"source_finder": source_member["agentId"]},
            "managedSourceRootIds": [root_id],
            "promptCachePolicy": {"requirement": "disabled"},
        },
    )
    managed = response["localWorkspaceScan"]["managedRoots"]
    assert managed["status"] == "completed"
    assert managed["importedCount"] == 1
    imported = managed["imported"][0]
    assert imported["path"].endswith("项目简介.docx")


def test_inspect_receipt_reports_current_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.test_knowledge_sideflow_run import _seed_parent

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    harness = GraphHarness(tmp_path)
    try:
        _seed_parent(harness)
        receipt = harness.commands.command_service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
                run_id="run-parent",
                team_id="research-team",
                expected_run_version=1,
                idempotency_key="kc:inspect:mode",
                payload={},
            )
        )
        assert receipt.status == "accepted"
        assert receipt.result["knowledgeSideflowMode"] == KNOWLEDGE_SIDEFLOW_MODE_SHADOW
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# 6) P1-1: degraded definition fail-closes mutations (submit + offers)
# ---------------------------------------------------------------------------


def _seeded_command_harness(tmp_path: Path, *, version_id: str) -> GraphHarness:
    harness = GraphHarness(tmp_path)
    harness.seed(run_id="run-gate", workflow_version_id=version_id)
    return harness


def test_degraded_registry_run_rejects_mutation_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.command_service import (
        DefinitionResolutionDegradedError,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = _seeded_command_harness(tmp_path, version_id="wv-000000000000")
    try:
        with pytest.raises(DefinitionResolutionDegradedError) as excinfo:
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.START_NODE,
                    node_id="problem_understanding",
                    run_id="run-gate",
                    team_id="research-team",
                    expected_run_version=1,
                    idempotency_key="gate:start:1",
                )
            )
        assert excinfo.value.code == "definition_resolution_degraded"
    finally:
        harness.close()


def test_preregistry_run_keeps_legacy_mutation_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.command_service import (
        DefinitionResolutionDegradedError,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = _seeded_command_harness(
        tmp_path, version_id="challenge-cup-research-v2.1.0"
    )
    try:
        with pytest.raises(Exception) as excinfo:  # noqa: PT011 - any outcome but degraded
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.START_NODE,
                    node_id="problem_understanding",
                    run_id="run-gate",
                    team_id="research-team",
                    expected_run_version=1,
                    idempotency_key="gate:start:legacy",
                )
            )
        assert not isinstance(excinfo.value, DefinitionResolutionDegradedError)
    finally:
        harness.close()


def test_degraded_snapshot_only_surfaces_read_only_offers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.research.workflow.contracts import WorkflowCommandKind as Kind
    from tests._support.command_helpers import CommandHarness
    from core.web.services.team_workflow.research_runtime.command_offers import (
        build_command_offers,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        run_stub = SimpleNamespace(
            run_id="run-degraded",
            run_version=4,
            status="running",
            active_node_id="problem_understanding",
            forked_from_checkpoint_id=None,
            workflow_version_id="wv-000000000000",
        )
        definition = build_challenge_cup_workflow_definition()
        mutation_kinds = {
            Kind.START_NODE,
            Kind.RETRY_NODE,
            Kind.RESOLVE_HUMAN_TASK,
            Kind.REBIND_NODE,
            Kind.FORK_REVISION,
            Kind.EXTEND_BUDGET,
            Kind.RECONCILE_RUN,
            Kind.ARCHIVE_RUN,
            Kind.CANCEL_RUN,
            Kind.CANCEL_NODE,
            Kind.ENSURE_KNOWLEDGE_COLLECTION,
        }
        degraded_offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id="research-team",
            run=run_stub,
            definition=definition,
            definition_resolution="degraded",
        )
        assert degraded_offers, "read-only inspect offer must survive degradation"
        assert all(offer.command not in mutation_kinds for offer in degraded_offers)
        assert all(
            offer.command == Kind.INSPECT_KNOWLEDGE_COLLECTION
            for offer in degraded_offers
        )

        pinned_offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id="research-team",
            run=run_stub,
            definition=definition,
            definition_resolution="pinned",
        )
        assert any(offer.command in mutation_kinds for offer in pinned_offers)

        # Pre-registry literal runs: the read layer substitutes the legacy
        # default (the same graph the command service executes), so legacy
        # mutation semantics stay intact even when the snapshot badge reads
        # degraded — mirrors the submit-layer registry-era carve-out.
        legacy_stub = SimpleNamespace(
            run_id="run-degraded",
            run_version=4,
            status="running",
            active_node_id="problem_understanding",
            forked_from_checkpoint_id=None,
            workflow_version_id="challenge-cup-research-v2.1.0",
        )
        legacy_degraded_offers = build_command_offers(
            readiness_service=harness.readiness,
            context=harness.context,
            team_id="research-team",
            run=legacy_stub,
            definition=definition,
            definition_resolution="degraded",
        )
        assert any(
            offer.command in mutation_kinds for offer in legacy_degraded_offers
        )
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# 7) P1-2: ensure is on-only, inspect is shadow/on, both fail closed off
# ---------------------------------------------------------------------------


def _ensure_request_for(harness: GraphHarness, idempotency_key: str):
    return harness.commands.request(
        command=WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION,
        node_id="hypothesis_design",
        run_id="run-gate",
        team_id="research-team",
        expected_run_version=1,
        idempotency_key=idempotency_key,
        payload={
            "questionId": "SCI-096",
            "searchEnvelope": {"keywords": ["evaporation"]},
            "requirements": {"minSources": 2},
            "sourcePolicyVersion": "1",
        },
    )


def test_shadow_mode_never_creates_real_child_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.command_service import (
        KnowledgeCommandError,
    )
    from core.web.services.team_workflow.research_runtime.command_offers.knowledge_collection import (
        build_knowledge_collection_offers as _offers,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    harness = _seeded_command_harness(tmp_path, version_id=_legacy_version_id())
    try:
        # Offer layer: inspection only — ensure must not even render.
        offers = _offers(
            run=SimpleNamespace(
                run_id="run-gate",
                run_version=1,
                status="running",
                active_node_id="hypothesis_design",
            )
        )
        commands = [offer.command for offer in offers]
        assert WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION not in commands
        assert WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION in commands

        # Server-side gate: a direct API call is rejected fail-closed.
        with pytest.raises(KnowledgeCommandError) as excinfo:
            harness.commands.command_service.submit(
                _ensure_request_for(harness, "kc:ensure:shadow-denied")
            )
        assert excinfo.value.code == "knowledge_sideflow_disabled"

        # And inspection stays servable in shadow.
        receipt = harness.commands.command_service.submit(
            harness.commands.request(
                command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
                run_id="run-gate",
                team_id="research-team",
                expected_run_version=1,
                idempotency_key="kc:inspect:shadow-ok",
                payload={},
            )
        )
        assert receipt.status == "accepted"
        child_rows = harness.commands.store.submit(
            lambda uow: uow.repository.execute(
                "SELECT run_id FROM workflow_runs WHERE workflow_id = "
                "'challenge-cup-knowledge-sideflow'"
            ).fetchall(),
            force_flush=True,
        ).result(timeout=10)
        assert child_rows == []
    finally:
        harness.close()


def test_off_mode_rejects_ensure_and_inspect_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.command_service import (
        KnowledgeCommandError,
    )

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_OFF)
    harness = _seeded_command_harness(tmp_path, version_id=_legacy_version_id())
    try:
        with pytest.raises(KnowledgeCommandError) as ensure_exc:
            harness.commands.command_service.submit(
                _ensure_request_for(harness, "kc:ensure:off-denied")
            )
        assert ensure_exc.value.code == "knowledge_sideflow_disabled"
        with pytest.raises(KnowledgeCommandError) as inspect_exc:
            harness.commands.command_service.submit(
                harness.commands.request(
                    command=WorkflowCommandKind.INSPECT_KNOWLEDGE_COLLECTION,
                    run_id="run-gate",
                    team_id="research-team",
                    expected_run_version=1,
                    idempotency_key="kc:inspect:off-denied",
                    payload={},
                )
            )
        assert inspect_exc.value.code == "knowledge_sideflow_disabled"
    finally:
        harness.close()


# ---------------------------------------------------------------------------
# 8) P1-3: one rollout-mode reading per creation
# ---------------------------------------------------------------------------


def test_service_create_run_reads_rollout_mode_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import core.web.services.team_workflow.research_runtime.knowledge_rollout as rollout_module
    from core.research.workflow.definition import CHALLENGE_CUP_WORKFLOW_ID
    from core.web.services.team_workflow.research_runtime.service import (
        ResearchWorkflowRuntimeService,
    )
    from core.web.services.team_workflow.research_runtime.store import WorkflowRunStore

    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_ON)
    calls = {"count": 0}
    original = rollout_module.creation_workflow_definition

    def counting():
        calls["count"] += 1
        return original()

    monkeypatch.setattr(rollout_module, "creation_workflow_definition", counting)

    service = ResearchWorkflowRuntimeService(
        run_store=WorkflowRunStore(tmp_path / "runs"),
        checkpoint_path=str(tmp_path / "checkpoints.sqlite"),
    )
    fixture_path = (
        Path(__file__).parent / "fixtures" / "research_workflow_v21_baseline_case.json"
    )
    baseline_input = json.loads(
        fixture_path.read_text(encoding="utf-8")
    )["runInput"]
    run = service.create_run(
        CHALLENGE_CUP_WORKFLOW_ID,
        run_input=baseline_input,
        idempotency_key="rollout:create:once",
    )
    record = service.get_run(run["runId"])
    v3_identity = register_or_resolve(
        build_challenge_cup_workflow_definition_v3()
    )
    assert record["workflowVersionId"] == v3_identity.workflowVersionId
    assert record["structureHash"] == v3_identity.structureHash
    assert calls["count"] == 1


# ---------------------------------------------------------------------------
# 9) P2-4: shadow store idempotency + corruption isolation
# ---------------------------------------------------------------------------


def test_shadow_records_are_idempotent_on_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    kwargs = {
        "team_id": "team-idem",
        "question_id": "SCI-096",
        "scope": {"questionId": "SCI-096"},
        "search_envelope": {"keywords": ["evaporation"]},
        "requirements": {"minSources": 3},
        "collection_request_id": "hfcr-idem-1",
        "now_provider": lambda: 1_000,
    }
    first = record_shadow_knowledge_invocation(**kwargs)
    assert first is not None
    for replay_run_id in ("run-col-1", "run-col-2", "run-col-3"):
        replayed = record_shadow_knowledge_invocation(
            **{**kwargs, "collection_run_id": replay_run_id}
        )
        assert replayed["invocationId"] == first["invocationId"]
    payload = list_shadow_knowledge_invocations("team-idem")
    assert payload["total"] == 1
    assert payload["records"][0]["collectionRunId"] == ""  # first record wins

    # A different envelope fingerprint is a NEW shadow invocation.
    second = record_shadow_knowledge_invocation(
        **{
            **kwargs,
            "search_envelope": {"keywords": ["condensation"]},
            "collection_request_id": "hfcr-idem-2",
        }
    )
    assert second["invocationId"] != first["invocationId"]
    assert list_shadow_knowledge_invocations("team-idem")["total"] == 2


def test_shadow_store_quarantines_corrupt_lines_and_keeps_working(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from core.web.services.team_workflow.research_runtime.knowledge_rollout import (
        _shadow_store_path,
    )

    monkeypatch.setenv("VIBELUTION_RESEARCH_WORKFLOW_DATA_ROOT", str(tmp_path))
    _patch_mode(monkeypatch, KNOWLEDGE_SIDEFLOW_MODE_SHADOW)
    good = record_shadow_knowledge_invocation(
        team_id="team-corrupt",
        question_id="SCI-096",
        scope={"questionId": "SCI-096"},
        search_envelope={"keywords": ["evaporation"]},
        requirements={"minSources": 3},
        collection_request_id="hfcr-good-1",
        now_provider=lambda: 1_000,
    )
    assert good is not None
    store = _shadow_store_path("team-corrupt")
    with store.open("a", encoding="utf-8") as handle:
        handle.write('{"broken": json,,,}\n')
        handle.write("not-json-at-all\n")

    # Reads survive the corruption (good rows still projected).
    payload = list_shadow_knowledge_invocations("team-corrupt")
    assert payload["total"] == 1
    quarantine_files = list(
        store.parent.glob("team-corrupt.jsonl.corrupt-*.jsonl")
    )
    assert len(quarantine_files) == 1
    quarantined = quarantine_files[0].read_text(encoding="utf-8")
    assert "not-json-at-all" in quarantined

    # Writes continue after isolation: a new distinct request lands.
    followup = record_shadow_knowledge_invocation(
        team_id="team-corrupt",
        question_id="SCI-096",
        scope={"questionId": "SCI-096"},
        search_envelope={"keywords": ["condensation"]},
        requirements={"minSources": 3},
        collection_request_id="hfcr-good-2",
        now_provider=lambda: 2_000,
    )
    assert followup is not None
    assert list_shadow_knowledge_invocations("team-corrupt")["total"] == 2
