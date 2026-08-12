"""T0 基线审计：audit_research_workflow_runtime.py 的合同测试。

RED/GREEN 合同：
- 损坏 JSON、重复 Handoff 身份、scope mismatch、缺 Agent anchor 的 fixture
  必须被审计分类（corrupt / duplicate_identity / scope_mismatch /
  reconciliation_required），且审计整体失败（passed=False / 非零退出码）。
- 完整一致的历史 Run 必须分类为 migratable；终态且仅有 advisory finding
  的 Run 分类为 archivable_terminal。
- 审计输出必须包含旧 Run 数、event/handoff/task/binding 计数、checkpoint
  thread 可解析性、领域 ref 可读性、orphan reservation、旧 route/import
  清单。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import audit_research_workflow_runtime as audit


def _build_run_record(**overrides) -> dict:
    """构造与旧 writer 最小兼容的正式 Run 记录（schema 镜像 run_lifecycle）。"""
    run_id = "run-audittest"
    node_run_id = f"nr-{run_id}-source_finding-a1"
    record = {
        "runId": run_id,
        "workflowId": "challenge-cup-research",
        "workflowVersionId": "challenge-cup-research-v2.1.0",
        "structureHash": "a" * 64,
        "teamId": "research-team",
        "projectId": "challenge-sci-096",
        "questionId": "SCI-096",
        "threadId": "thread-audittest",
        "status": "queued",
        "runVersion": 1,
        "createdAt": "2026-08-12T00:00:00Z",
        "updatedAt": "2026-08-12T00:00:00Z",
        "inputSnapshot": {
            "teamId": "research-team",
            "projectId": "challenge-sci-096",
            "questionId": "SCI-096",
            "workflowVersionId": "challenge-cup-research-v2.1.0",
            "snapshotHash": "b" * 64,
            "budgetPolicy": {},
            "agentBindingSnapshot": [],
        },
        "bindingSnapshots": [],
        "events": [
            {
                "eventId": "evt-audit1",
                "sequence": 1,
                "occurredAt": "2026-08-12T00:00:00Z",
                "runId": run_id,
                "type": "run.queued",
                "summary": {},
            }
        ],
        "humanTasks": [],
        "handoffs": [],
        "sessionBindings": {},
        "iterationDecisions": [],
        "taskLeases": [],
        "commandReceipts": [],
        "outbox": [],
        "budgetLedgers": [],
        "budgetReservations": [],
        "artifactManifests": [],
        "nodeRuns": [
            {
                "nodeRunId": node_run_id,
                "runId": run_id,
                "nodeId": "source_finding",
                "attempt": 1,
                "actorType": "agent",
                "agentId": "agent-sci-096-finder",
                "taskId": "",
                "sessionId": "",
                "status": "ready",
                "inputSnapshotHash": "b" * 64,
                "idempotencyKey": f"{run_id}:source_finding:1",
                "artifactRefs": [],
                "checkpointId": "",
                "startedAt": "",
                "finishedAt": "",
            }
        ],
        "completionKind": "",
        "terminalReason": "",
        "createIdempotencyKey": f"create:{run_id}",
        "createInputFingerprint": "c" * 64,
        "langGraph": {"engine": "challenge_cup_graph", "checkpointId": "", "completedNodeIds": []},
    }
    record.update(overrides)
    return record


def _write_run(data_root: Path, record: dict) -> Path:
    path = data_root / "runs" / f"{record['runId']}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


@pytest.fixture()
def data_root(tmp_path: Path) -> Path:
    root = tmp_path / "research_workflows"
    (root / "runs").mkdir(parents=True)
    return root


@pytest.fixture()
def empty_checkpoint(data_root: Path) -> Path:
    path = data_root / "checkpoints.sqlite"
    # 预置标准 thread，使默认 fixture run 的 threadId 可解析。
    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE checkpoints (thread_id TEXT NOT NULL)")
    conn.execute("INSERT INTO checkpoints (thread_id) VALUES ('thread-audittest')")
    conn.commit()
    conn.close()
    return path


def _audit(tmp_path: Path, data_root: Path, workspace_root: Path | None = None) -> dict:
    return audit.run_audit(
        data_root=data_root,
        project_root=tmp_path,
        workspace_root=workspace_root or (tmp_path / "workspace"),
    )


class TestAuditCorrupt:
    def test_corrupt_json_classified_and_fails(self, tmp_path: Path, data_root: Path) -> None:
        bad = data_root / "runs" / "run-corrupt.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = _audit(tmp_path, data_root)
        entry = report["runs"][0]
        assert entry["classification"] == "corrupt"
        assert report["passed"] is False

    def test_missing_required_field_classified_corrupt(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record()
        record.pop("workflowVersionId")
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        assert report["runs"][0]["classification"] == "corrupt"
        assert report["passed"] is False

    def test_event_sequence_gap_classified_corrupt(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(
            status="running",
            events=[
                {"eventId": "evt-1", "sequence": 1, "type": "a", "occurredAt": "x", "summary": {}},
                {"eventId": "evt-3", "sequence": 3, "type": "b", "occurredAt": "x", "summary": {}},
            ],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        assert report["runs"][0]["classification"] == "corrupt"


class TestAuditDuplicate:
    def test_duplicate_handoff_identity_classified(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        handoff = {
            "handoffId": "ho-1",
            "fromNodeRunId": "nr-a",
            "toNodeId": "source_extraction",
            "edgeId": "edge-1",
            "inputSnapshotHash": "d" * 64,
            "status": "pending",
            "offeredAt": "2026-08-12T00:00:00Z",
        }
        record = _build_run_record(
            status="running",
            nodeRuns=[
                {
                    "nodeRunId": "nr-a",
                    "runId": "run-audittest",
                    "nodeId": "source_finding",
                    "attempt": 1,
                    "actorType": "agent",
                    "agentId": "a",
                    "status": "succeeded",
                    "inputSnapshotHash": "d" * 64,
                    "idempotencyKey": "k",
                    "artifactRefs": [],
                }
            ],
            handoffs=[handoff, {**handoff, "handoffId": "ho-2"}],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        assert report["runs"][0]["classification"] == "duplicate_identity"
        assert report["passed"] is False

    def test_two_files_same_run_id_classified_duplicate(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record()
        _write_run(data_root, record)
        dup = dict(record)
        dup["runVersion"] = 2
        dup_path = data_root / "runs" / "run-other.json"
        dup_path.write_text(json.dumps(dup), encoding="utf-8")
        report = _audit(tmp_path, data_root)
        # 两份文件声明同一 runId 视为 identity 冲突，不能成为两份独立记录。
        assert report["summary"]["duplicateIdentity"] >= 1
        assert report["passed"] is False


class TestAuditScope:
    def test_team_id_missing_classified_scope_mismatch(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(teamId="")
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        assert report["runs"][0]["classification"] == "scope_mismatch"
        assert report["passed"] is False

    def test_team_id_inconsistent_classified_scope_mismatch(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(teamId="research-team")
        record["inputSnapshot"]["teamId"] = "other-team"
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        assert report["runs"][0]["classification"] == "scope_mismatch"


class TestAuditAnchor:
    def test_missing_agent_anchor_classified_reconciliation(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(
            status="running",
            nodeRuns=[
                {
                    "nodeRunId": "nr-a",
                    "runId": "run-audittest",
                    "nodeId": "source_finding",
                    "attempt": 1,
                    "actorType": "agent",
                    "agentId": "agent-x",
                    "taskId": "",
                    "sessionId": "",
                    "status": "succeeded",
                    "inputSnapshotHash": "b" * 64,
                    "idempotencyKey": "k",
                    "artifactRefs": [],
                }
            ],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        entry = report["runs"][0]
        assert entry["classification"] == "reconciliation_required"
        assert any(f["code"] == "missing_agent_anchor" for f in entry["findings"])
        assert report["passed"] is False

    def test_orphan_budget_reservation_classified_reconciliation(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(
            status="cancelled",
            budgetReservations=[
                {
                    "reservationId": "res-1",
                    "nodeRunId": "nr-a",
                    "runId": "run-audittest",
                    "status": "reserved",
                    "budgetLedgerId": "budget-1",
                    "stageId": "knowledge_collection",
                    "reservedAt": "2026-08-12T00:00:00Z",
                }
            ],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        entry = report["runs"][0]
        assert entry["classification"] == "reconciliation_required"
        assert any(f["code"] == "orphan_budget_reservation" for f in entry["findings"])

    def test_checkpoint_thread_missing_classified_reconciliation(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(status="running", threadId="thread-missing")
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        entry = report["runs"][0]
        assert entry["classification"] == "reconciliation_required"
        assert any(f["code"] == "checkpoint_thread_missing" for f in entry["findings"])


class TestAuditClean:
    def test_clean_run_migratable(self, tmp_path: Path, data_root: Path, empty_checkpoint: Path) -> None:
        record = _build_run_record(status="cancelled")
        record["threadId"] = "thread-audittest"
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        entry = report["runs"][0]
        assert entry["classification"] == "migratable"
        assert report["passed"] is True

    def test_terminal_run_with_unverified_domain_refs_archivable(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(
            status="cancelled",
            artifactManifests=[
                {
                    "artifactId": "source_candidate_batch:abc123",
                    "contentHash": "a" * 64,
                    "producerNodeRunId": "nr-a",
                    "producerAttempt": 1,
                    "inputSnapshotHash": "b" * 64,
                    "createdAt": "2026-08-12T00:00:00Z",
                }
            ],
        )
        _write_run(data_root, record)
        # workspace_root 为空：领域 read-back 不可执行 -> 终态 Run 归档。
        report = audit.run_audit(
            data_root=data_root,
            project_root=tmp_path,
            workspace_root=tmp_path / "no-such-workspace",
        )
        assert report["runs"][0]["classification"] == "archivable_terminal"

    def test_candidate_store_readback(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        candidate_store = workspace / "teams" / "research-team" / "candidate_store"
        candidate_store.mkdir(parents=True)
        (candidate_store / "index.json").write_text(
            json.dumps(
                {
                    "storeKind": "candidate_store",
                    "teamId": "research-team",
                    "schemaVersion": 1,
                    "createdAt": "x",
                    "updatedAt": "x",
                    "candidates": [
                        {
                            "candidateId": "candidate-1",
                            "candidateType": "paper_note",
                            "teamId": "research-team",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        record = _build_run_record(
            status="running",
            artifactManifests=[
                {
                    "artifactId": "source_candidate_batch:abc123",
                    "contentHash": "a" * 64,
                    "producerNodeRunId": "nr-a",
                    "producerAttempt": 1,
                    "inputSnapshotHash": "b" * 64,
                    "createdAt": "2026-08-12T00:00:00Z",
                }
            ],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root, workspace_root=workspace)
        # 领域 store 可解析：不再因 read-back 不可用而降级。
        assert report["domainReadback"]["candidateStores"] == {
            "research-team": {"found": True, "candidates": 1}
        }

    def test_corrupt_candidate_store_classified(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        workspace = tmp_path / "workspace"
        candidate_store = workspace / "teams" / "research-team" / "candidate_store"
        candidate_store.mkdir(parents=True)
        (candidate_store / "index.json").write_text("{{bad", encoding="utf-8")
        record = _build_run_record(
            status="running",
            artifactManifests=[
                {
                    "artifactId": "source_candidate_batch:abc123",
                    "contentHash": "a" * 64,
                    "producerNodeRunId": "nr-a",
                    "producerAttempt": 1,
                    "inputSnapshotHash": "b" * 64,
                    "createdAt": "2026-08-12T00:00:00Z",
                }
            ],
        )
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root, workspace_root=workspace)
        entry = report["runs"][0]
        assert entry["classification"] == "reconciliation_required"
        assert any(f["code"] == "domain_store_unreadable" for f in entry["findings"])


class TestAuditCheckpoint:
    def test_checkpoint_thread_resolvable(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(status="cancelled")
        _write_run(data_root, record)
        report = _audit(tmp_path, data_root)
        cp = report["checkpoint"]
        assert cp["threadCount"] == 1
        assert report["runs"][0]["classification"] == "migratable"


class TestAuditInventory:
    def test_legacy_surface_inventory_counts_patterns(self, tmp_path: Path) -> None:
        core = tmp_path / "core"
        (core / "web" / "routes").mkdir(parents=True)
        (core / "web" / "routes" / "research_runtime.py").write_text(
            'router.post("/research/workflow-runs/{run_id}/nodes/{node_id}/commands")\n'
            'router.put("/research/workflow-runs/{run_id}/nodes/{node_id}/session-binding")\n'
            'router.post("/research/workflow-runs/{run_id}/human-tasks/{task_id}/resolve")\n',
            encoding="utf-8",
        )
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_x.py").write_text("WorkflowRunStore\nDurableWorkflowIndex\n", encoding="utf-8")
        inv = audit.inventory_legacy_surface(tmp_path)
        assert inv["nodeCommandRoute"] == 1
        assert inv["sessionBindingRoute"] == 1
        assert inv["humanTaskResolveRoute"] == 1
        assert inv["workflowRunStore"] == 1
        assert inv["durableWorkflowIndex"] == 1

    def test_legacy_surface_inventory_clean(self, tmp_path: Path) -> None:
        inv = audit.inventory_legacy_surface(tmp_path)
        assert inv["nodeCommandRoute"] == 0
        assert inv["sessionBindingRoute"] == 0
        assert inv["humanTaskResolveRoute"] == 0


class TestAuditCli:
    def test_cli_clean_fixture_exit_zero(
        self, tmp_path: Path, data_root: Path, empty_checkpoint: Path
    ) -> None:
        record = _build_run_record(status="cancelled")
        _write_run(data_root, record)
        code = audit.main(["--data-root", str(data_root), "--project-root", str(tmp_path)])
        assert code == 0

    def test_cli_corrupt_fixture_exit_nonzero(
        self, tmp_path: Path, data_root: Path
    ) -> None:
        (data_root / "runs" / "run-corrupt.json").write_text("{{", encoding="utf-8")
        code = audit.main(["--data-root", str(data_root), "--project-root", str(tmp_path)])
        assert code == 1

    def test_cli_missing_data_root_exit_two(self, tmp_path: Path) -> None:
        code = audit.main(["--data-root", str(tmp_path / "missing"), "--project-root", str(tmp_path)])
        assert code == 2
