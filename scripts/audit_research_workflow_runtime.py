"""挑战杯科研工作流只读审计：优先 canonical Ledger，兼容旧 JSON。

只读工具。不修改任何 Run、checkpoint、index 或领域数据。

默认 ``--source auto``：存在 ``workflow-ledger.sqlite`` 时审计 canonical
SQLite Ledger 的完整性、schema、Run、授权、预算收据和关键引用计数；仅在
Ledger 不存在时回退 T0 旧 JSON writer 迁移基线。可用 ``--source`` 显式
选择，避免把兼容数据面误当作当前事实源。

旧 JSON 分类语义（每个旧 Run 恰好一类，顺序优先）：
  corrupt                JSON 无法解析或违反 schema（必需字段、事件序列、身份重复）
  duplicate_identity     重复 Handoff 业务身份或同一 runId 的多份文件
  scope_mismatch         teamId 缺失/为空/与 inputSnapshot 不一致
  reconciliation_required 结构可读但存在 orphan reservation、缺 anchor、
                          checkpoint thread 缺失、领域 store 不可读等
  archivable_terminal    终态且仅有 advisory（领域 read-back 不可执行）发现
  migratable             无任何发现

退出码：0 = 审计完成且无硬发现；1 = 审计完成但存在 hard finding；
2 = 数据目录缺失或无法读取。任何 corrupt/duplicate/scope/unclassifiable
记录都会使审计失败（passed=False），绝不静默修补。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts import research_workflow_ledger_audit as ledger_audit
from vibelution_storage import resolve_project_data_home

HARD_CATEGORIES = ("corrupt", "identity", "scope", "reconciliation")

REQUIRED_RUN_FIELDS = (
    "runId",
    "workflowId",
    "workflowVersionId",
    "structureHash",
    "teamId",
    "projectId",
    "questionId",
    "threadId",
    "status",
    "runVersion",
    "createdAt",
    "updatedAt",
    "inputSnapshot",
    "events",
    "nodeRuns",
    "handoffs",
    "sessionBindings",
    "budgetReservations",
    "artifactManifests",
)

RUN_STATUSES = {
    "queued",
    "running",
    "waiting_human",
    "blocked",
    "reconciliation_required",
    "succeeded",
    "failed",
    "cancelled",
    "archived",
}

NODE_RUN_STATUSES = {
    "pending",
    "ready",
    "running",
    "waiting_human",
    "succeeded",
    "failed",
    "blocked",
    "skipped",
    "stale",
    "cancelled",
}

HANDOFF_STATUSES = {
    "pending",
    "ready",
    "waiting_human",
    "accepted",
    "rejected",
    "superseded",
    "failed",
}

RESERVATION_STATUSES = {"reserved", "settled", "released", "failed", "voided"}

BINDING_STATUSES = {"bound", "pending", "degraded", "superseded"}

TERMINAL_RUN_STATUSES = {"succeeded", "failed", "cancelled", "archived"}

ANCHORED_NODE_STATUSES = {"running", "succeeded"}

LEGACY_SURFACE_PATTERNS = {
    "nodeCommandRoute": re.compile(r"nodes/\{node_id\}/commands|nodes/\{nodeId\}/commands|nodes/\$\{nodeId\}/commands"),
    "sessionBindingRoute": re.compile(r"session-binding"),
    "humanTaskResolveRoute": re.compile(r"human-tasks/\{task_id\}/resolve|human-tasks/\{taskId\}/resolve|human-tasks/\$\{taskId\}/resolve"),
    "workflowRunStore": re.compile(r"WorkflowRunStore"),
    "durableWorkflowIndex": re.compile(r"DurableWorkflowIndex"),
    "updateStateAsNode": re.compile(r"update_state\([^\n]*as_node"),
}

LEGACY_SURFACE_ROOTS = ("core", "tests", "web/src")


def default_data_root(project_root: Path | None = None) -> Path:
    return resolve_project_data_home(project_root or PROJECT_ROOT) / "research_workflows"


def _finding(code: str, detail: str, category: str) -> dict[str, str]:
    return {"code": code, "detail": detail, "category": category}


def _run_events(record: dict) -> list[dict]:
    events = record.get("events")
    return events if isinstance(events, list) else []


def _run_node_runs(record: dict) -> list[dict]:
    node_runs = record.get("nodeRuns")
    return node_runs if isinstance(node_runs, list) else []


def audit_record(record: dict, workspace_root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []

    for field in REQUIRED_RUN_FIELDS:
        if field not in record:
            findings.append(_finding("missing_field", f"缺少必需字段 {field}", "corrupt"))
            return findings
        if field in ("events", "nodeRuns", "handoffs", "sessionBindings", "budgetReservations", "artifactManifests"):
            if not isinstance(record[field], (list, dict)):
                findings.append(_finding("bad_type", f"字段 {field} 必须是列表或对象", "corrupt"))
                return findings
        elif field == "inputSnapshot" and not isinstance(record[field], dict):
            findings.append(_finding("bad_type", "inputSnapshot 必须是对象", "corrupt"))
            return findings

    team_id = str(record.get("teamId") or "")
    snapshot_team_id = str((record.get("inputSnapshot") or {}).get("teamId") or "")
    if not team_id:
        findings.append(_finding("team_id_missing", "teamId 缺失或为空", "scope"))
        return findings
    if snapshot_team_id and snapshot_team_id != team_id:
        findings.append(
            _finding(
                "team_id_inconsistent",
                f"record.teamId={team_id} 与 inputSnapshot.teamId={snapshot_team_id} 不一致",
                "scope",
            )
        )
        return findings

    status = str(record.get("status") or "")
    if status not in RUN_STATUSES:
        findings.append(_finding("invalid_run_status", f"未知 Run 状态 {status!r}", "corrupt"))
    run_version = record.get("runVersion")
    if not isinstance(run_version, int) or run_version < 1:
        findings.append(_finding("invalid_run_version", "runVersion 必须是不小于 1 的整数", "corrupt"))

    events = _run_events(record)
    seen_ids: set[str] = set()
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            findings.append(_finding("bad_event", f"事件 {index} 不是对象", "corrupt"))
            continue
        sequence = event.get("sequence")
        if sequence != index:
            findings.append(
                _finding(
                    "event_sequence_gap",
                    f"事件序列在 {index} 处不连续（sequence={sequence!r}）",
                    "corrupt",
                )
            )
            break
        event_id = str(event.get("eventId") or "")
        if not event_id or event_id in seen_ids:
            findings.append(_finding("event_id_duplicate", f"事件 ID 重复: {event_id!r}", "corrupt"))
        seen_ids.add(event_id)

    node_runs = _run_node_runs(record)
    node_identities: set[tuple[str, int]] = set()
    node_run_ids: set[str] = set()
    for node_run in node_runs:
        if not isinstance(node_run, dict):
            findings.append(_finding("bad_node_run", "nodeRuns 含非对象条目", "corrupt"))
            continue
        node_run_id = str(node_run.get("nodeRunId") or "")
        node_id = str(node_run.get("nodeId") or "")
        attempt = node_run.get("attempt")
        if not node_run_id or node_run_id in node_run_ids:
            findings.append(_finding("node_run_id_duplicate", f"nodeRunId 重复: {node_run_id!r}", "corrupt"))
        node_run_ids.add(node_run_id)
        if node_id and isinstance(attempt, int) and attempt >= 1:
            identity = (node_id, attempt)
            if identity in node_identities:
                findings.append(
                    _finding("node_run_identity_duplicate", f"(nodeId, attempt) 重复: {identity!r}", "corrupt")
                )
            node_identities.add(identity)
        node_status = str(node_run.get("status") or "")
        if node_status not in NODE_RUN_STATUSES:
            findings.append(_finding("invalid_node_status", f"未知节点状态 {node_status!r}", "corrupt"))
        if node_status in ANCHORED_NODE_STATUSES:
            actor_type = str(node_run.get("actorType") or "")
            if actor_type == "agent":
                missing = [
                    field
                    for field in ("agentId", "sessionId", "taskId")
                    if not str(node_run.get(field) or "").strip()
                ]
                if missing:
                    findings.append(
                        _finding(
                            "missing_agent_anchor",
                            f"{node_run_id} 为 {node_status} 但缺少 {missing}",
                            "reconciliation",
                        )
                    )
            if actor_type == "system" and not str(node_run.get("nodeRunId") or ""):
                findings.append(
                    _finding("missing_system_anchor", f"{node_run_id} system 节点缺少执行标识", "reconciliation")
                )

    handoffs = record.get("handoffs") if isinstance(record.get("handoffs"), list) else []
    handoff_identities: set[tuple[str, str, str]] = set()
    for handoff in handoffs:
        if not isinstance(handoff, dict):
            findings.append(_finding("bad_handoff", "handoffs 含非对象条目", "corrupt"))
            continue
        identity = (
            str(handoff.get("fromNodeRunId") or ""),
            str(handoff.get("toNodeId") or ""),
            str(handoff.get("inputSnapshotHash") or ""),
        )
        if identity in handoff_identities:
            findings.append(
                _finding(
                    "duplicate_handoff_identity",
                    f"Handoff 业务身份重复: {identity!r}",
                    "identity",
                )
            )
        handoff_identities.add(identity)
        if str(handoff.get("status") or "") not in HANDOFF_STATUSES:
            findings.append(
                _finding(
                    "invalid_handoff_status",
                    f"未知 Handoff 状态 {handoff.get('status')!r}",
                    "corrupt",
                )
            )

    reservations = record.get("budgetReservations") if isinstance(record.get("budgetReservations"), list) else []
    reservation_ids: set[str] = set()
    terminal = status in TERMINAL_RUN_STATUSES
    for reservation in reservations:
        if not isinstance(reservation, dict):
            continue
        reservation_id = str(reservation.get("reservationId") or "")
        if not reservation_id or reservation_id in reservation_ids:
            findings.append(
                _finding("reservation_id_duplicate", f"reservationId 重复: {reservation_id!r}", "corrupt")
            )
        reservation_ids.add(reservation_id)
        reservation_status = str(reservation.get("status") or "")
        if reservation_status not in RESERVATION_STATUSES:
            findings.append(
                _finding(
                    "invalid_reservation_status",
                    f"未知 reservation 状态 {reservation_status!r}",
                    "corrupt",
                )
            )
        if terminal and reservation_status == "reserved":
            findings.append(
                _finding(
                    "orphan_budget_reservation",
                    f"终态 Run 仍有未结算 reservation {reservation_id}",
                    "reconciliation",
                )
            )

    for node_id, binding in (record.get("sessionBindings") or {}).items():
        if not isinstance(binding, dict):
            findings.append(_finding("bad_binding", f"sessionBindings[{node_id}] 不是对象", "corrupt"))
            continue
        binding_status = str(binding.get("status") or "")
        if binding_status not in BINDING_STATUSES:
            findings.append(
                _finding("invalid_binding_status", f"未知 binding 状态 {binding_status!r}", "corrupt")
            )
        if binding_status == "bound":
            missing = [
                field
                for field in ("agentId", "sessionId", "taskId", "turnId")
                if not str(binding.get(field) or "").strip()
            ]
            if missing:
                findings.append(
                    _finding(
                        "binding_incomplete",
                        f"binding {node_id} 为 bound 但缺少 {missing}",
                        "reconciliation",
                    )
                )

    manifests = record.get("artifactManifests") if isinstance(record.get("artifactManifests"), list) else []
    content_hash_pattern = re.compile(r"^[0-9a-f]{64}$")
    for manifest in manifests:
        if not isinstance(manifest, dict):
            continue
        artifact_id = str(manifest.get("artifactId") or "")
        content_hash = str(manifest.get("contentHash") or "")
        if not artifact_id or not content_hash or not content_hash_pattern.match(content_hash):
            findings.append(
                _finding(
                    "artifact_manifest_malformed",
                    f"artifact manifest {artifact_id!r} 缺少 artifactId/64 位 contentHash",
                    "reconciliation",
                )
            )
        if not str(manifest.get("producerNodeRunId") or ""):
            findings.append(
                _finding(
                    "artifact_manifest_missing_producer",
                    f"artifact {artifact_id!r} 缺少 producerNodeRunId",
                    "reconciliation",
                )
            )

    referenced_artifact_refs = False
    for node_run in node_runs:
        for ref in node_run.get("artifactRefs") or []:
            if isinstance(ref, str) and ":" in ref:
                referenced_artifact_refs = True
    if referenced_artifact_refs or manifests:
        domain_findings = audit_domain_readback(str(team_id), workspace_root)
        findings.extend(domain_findings)

    return findings


def audit_domain_readback(team_id: str, workspace_root: Path) -> list[dict[str, str]]:
    candidate_store = workspace_root / "teams" / team_id / "candidate_store" / "index.json"
    if not candidate_store.exists():
        return [_finding("domain_readback_scope_unavailable", "候选 store 不存在", "advisory")]
    try:
        data = json.loads(candidate_store.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return [_finding("domain_store_unreadable", "候选 store 无法解析", "reconciliation")]
    if not isinstance(data, dict) or not isinstance(data.get("candidates"), list):
        return [_finding("domain_store_unreadable", "候选 store 结构非法", "reconciliation")]
    return []


def classify_run(record: dict, findings: list[dict[str, str]]) -> str:
    hard = [finding for finding in findings if finding["category"] in HARD_CATEGORIES]
    if not findings:
        return "migratable"
    if any(finding["category"] == "corrupt" for finding in findings):
        return "corrupt"
    if any(finding["category"] == "identity" for finding in findings):
        return "duplicate_identity"
    if any(finding["category"] == "scope" for finding in findings):
        return "scope_mismatch"
    if hard:
        return "reconciliation_required"
    status = str(record.get("status") or "")
    if status in TERMINAL_RUN_STATUSES:
        return "archivable_terminal"
    return "reconciliation_required"


def _scan_checkpoint_threads(checkpoint_path: Path) -> set[str] | None:
    if not checkpoint_path.exists():
        return None
    try:
        import apsw

        conn = apsw.Connection(str(checkpoint_path), flags=apsw.SQLITE_OPEN_READONLY)
        try:
            rows = conn.execute("SELECT DISTINCT thread_id FROM checkpoints")
            return {str(row[0]) for row in rows}
        finally:
            conn.close()
    except (apsw.Error, OSError):
        return None


def audit_checkpoint(data_root: Path, known_thread_ids: list[str]) -> dict[str, Any]:
    checkpoint_path = data_root / "checkpoints.sqlite"
    threads = _scan_checkpoint_threads(checkpoint_path)
    if threads is None:
        return {
            "path": str(checkpoint_path),
            "found": False,
            "threadCount": 0,
            "missingThreads": list(dict.fromkeys(known_thread_ids)),
        }
    missing = [thread_id for thread_id in dict.fromkeys(known_thread_ids) if thread_id not in threads]
    return {
        "path": str(checkpoint_path),
        "found": True,
        "threadCount": len(threads),
        "missingThreads": missing,
    }


def _read_index(data_root: Path) -> dict[str, Any]:
    index_path = data_root / "runs" / "_index" / "idempotency.json"
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"_unreadable": str(index_path)}
    return data if isinstance(data, dict) else {"_unreadable": str(index_path)}


def audit_runs_store(data_root: Path, workspace_root: Path) -> dict[str, Any]:
    runs_dir = data_root / "runs"
    entries: list[dict[str, Any]] = []
    index = _read_index(data_root)
    seen_run_ids: dict[str, str] = {}

    for path in sorted(runs_dir.glob("run-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict):
                record = {}
        except (json.JSONDecodeError, OSError) as exc:
            entries.append(
                {
                    "runId": path.stem,
                    "file": str(path),
                    "classification": "corrupt",
                    "readable": False,
                    "findings": [_finding("corrupt_json", f"JSON 无法解析: {exc}", "corrupt")],
                }
            )
            continue
        run_id = str(record.get("runId") or path.stem)
        if run_id in seen_run_ids:
            entries.append(
                {
                    "runId": run_id,
                    "file": str(path),
                    "classification": "duplicate_identity",
                    "readable": True,
                    "findings": [
                        _finding(
                            "duplicate_run_file",
                            f"runId {run_id} 同时出现在 {seen_run_ids[run_id]} 与 {path}",
                            "identity",
                        )
                    ],
                }
            )
        else:
            seen_run_ids[run_id] = str(path)
            findings = audit_record(record, workspace_root)
            entries.append(
                {
                    "runId": run_id,
                    "file": str(path),
                    "classification": classify_run(record, findings),
                    "readable": True,
                    "status": str(record.get("status") or ""),
                    "findings": findings,
                }
            )

    index_dangling: list[str] = []
    for key, value in index.items():
        if key.startswith("_"):
            continue
        run_id = str(value)
        if not (runs_dir / f"{run_id}.json").exists():
            index_dangling.append(key)

    summary = {
        "runCount": len(entries),
        "eventCount": 0,
        "handoffCount": 0,
        "humanTaskCount": 0,
        "sessionBindingCount": 0,
        "taskBundleCount": 0,
        "reservationCount": 0,
        "artifactManifestCount": 0,
        "orphanReservations": 0,
        "duplicateHandoffs": 0,
        "missingAnchors": 0,
        "duplicateIdentity": 0,
        "classifications": {},
    }
    known_thread_ids: list[str] = []
    for entry in entries:
        if not entry.get("readable"):
            continue
        if entry["classification"] not in summary["classifications"]:
            summary["classifications"][entry["classification"]] = 0
        summary["classifications"][entry["classification"]] += 1
        record = _read_back_record(entry)
        if record is None:
            continue
        if entry["classification"] == "duplicate_identity":
            summary["duplicateIdentity"] += 1
        summary["eventCount"] += len(_run_events(record))
        summary["handoffCount"] += len(record.get("handoffs") or [])
        summary["humanTaskCount"] += len(record.get("humanTasks") or [])
        summary["sessionBindingCount"] += len(record.get("sessionBindings") or {})
        summary["taskBundleCount"] += len(record.get("taskBundles") or [])
        summary["reservationCount"] += len(record.get("budgetReservations") or [])
        summary["artifactManifestCount"] += len(record.get("artifactManifests") or [])
        known_thread_ids.append(str(record.get("threadId") or ""))
        for finding in entry["findings"]:
            if finding["code"] == "orphan_budget_reservation":
                summary["orphanReservations"] += 1
            if finding["code"] == "duplicate_handoff_identity":
                summary["duplicateHandoffs"] += 1
            if finding["code"] == "missing_agent_anchor":
                summary["missingAnchors"] += 1

    checkpoint = audit_checkpoint(data_root, [thread_id for thread_id in known_thread_ids if thread_id])
    for thread_id in checkpoint["missingThreads"]:
        for entry in entries:
            if not entry.get("readable"):
                continue
            record = _read_back_record(entry)
            if record and str(record.get("threadId") or "") == thread_id:
                entry.setdefault("findings", []).append(
                    _finding(
                        "checkpoint_thread_missing",
                        f"checkpoint 存储中不存在 thread {thread_id}",
                        "reconciliation",
                    )
                )
                entry["classification"] = classify_run(record, entry["findings"])

    for run_id in index_dangling:
        for entry in entries:
            if entry.get("runId") == run_id:
                entry.setdefault("findings", []).append(
                    _finding("index_dangling", f"幂等索引键指向不存在的 run {run_id}", "reconciliation")
                )
                record = _read_back_record(entry)
                if record:
                    entry["classification"] = classify_run(record, entry["findings"])

    return {
        "runs": entries,
        "summary": summary,
        "checkpoint": checkpoint,
        "idempotencyIndex": {
            "found": "_unreadable" not in index,
            "keys": len([key for key in index if not key.startswith("_")]),
            "danglingKeys": index_dangling,
        },
    }


def _read_back_record(entry: dict[str, Any]) -> dict | None:
    path = Path(entry["file"])
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    return record if isinstance(record, dict) else None


def audit_domain_readback_summary(entries: list[dict[str, Any]], workspace_root: Path) -> dict[str, Any]:
    team_ids: set[str] = set()
    for entry in entries:
        if not entry.get("readable"):
            continue
        record = _read_back_record(entry)
        if record and str(record.get("teamId") or ""):
            team_ids.add(str(record["teamId"]))
    stores: dict[str, dict[str, Any]] = {}
    for team_id in sorted(team_ids):
        candidate_store = workspace_root / "teams" / team_id / "candidate_store" / "index.json"
        if not candidate_store.exists():
            stores[team_id] = {"found": False, "candidates": 0}
            continue
        try:
            data = json.loads(candidate_store.read_text(encoding="utf-8"))
            stores[team_id] = {
                "found": True,
                "candidates": len(data.get("candidates")) if isinstance(data, dict) else 0,
            }
        except (json.JSONDecodeError, OSError):
            stores[team_id] = {"found": True, "candidates": -1, "unreadable": True}
    return {"candidateStores": stores}


def inventory_legacy_surface(project_root: Path) -> dict[str, int]:
    counts = {name: 0 for name in LEGACY_SURFACE_PATTERNS}
    for root_name in LEGACY_SURFACE_ROOTS:
        root = project_root / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".py", ".ts", ".tsx"):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name, pattern in LEGACY_SURFACE_PATTERNS.items():
                counts[name] += len(pattern.findall(text))
    return counts


def run_audit(
    data_root: Path,
    *,
    project_root: Path,
    workspace_root: Path,
) -> dict[str, Any]:
    runs_dir = data_root / "runs"
    if not runs_dir.is_dir():
        raise FileNotFoundError(f"数据根目录缺少 runs/: {runs_dir}")

    store_report = audit_runs_store(data_root, workspace_root)
    entries = store_report["runs"]
    store_report["domainReadback"] = audit_domain_readback_summary(entries, workspace_root)
    store_report["legacySurfaceInventory"] = inventory_legacy_surface(project_root)

    hard_findings = [
        (entry["runId"], finding["code"])
        for entry in entries
        for finding in entry.get("findings") or []
        if finding["category"] in HARD_CATEGORIES
    ]
    passed = not hard_findings
    return {
        "schemaVersion": 1,
        "generatedAtMs": 0,
        "source": "legacy-json",
        "dataRoot": str(data_root),
        "passed": passed,
        "runs": entries,
        "summary": store_report["summary"],
        "checkpoint": store_report["checkpoint"],
        "idempotencyIndex": store_report["idempotencyIndex"],
        "domainReadback": store_report["domainReadback"],
        "legacySurfaceInventory": store_report["legacySurfaceInventory"],
        "hardFindings": hard_findings,
    }


def _utc_now_ms() -> int:
    import time

    return int(time.time() * 1000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="挑战杯科研工作流 canonical Ledger 审计（只读）")
    parser.add_argument("--data-root", type=Path, default=None, help="research_workflows 数据根")
    parser.add_argument("--ledger-path", type=Path, default=None, help="canonical workflow-ledger.sqlite 路径")
    parser.add_argument(
        "--source",
        choices=("auto", "ledger", "legacy-json"),
        default="auto",
        help="审计源；auto 优先 canonical Ledger，仅在 Ledger 不存在时回退旧 JSON",
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT, help="仓库根（旧代码面清单）")
    parser.add_argument("--workspace-root", type=Path, default=None, help="workspace 根（领域 read-back，默认 data-root/../workspace）")
    parser.add_argument("--output", type=Path, default=None, help="审计报告 JSON 输出路径")
    args = parser.parse_args(argv)
    data_root = args.data_root or default_data_root(args.project_root)
    ledger_path = args.ledger_path or ledger_audit.default_ledger_path(data_root)

    try:
        workspace_root = args.workspace_root or (data_root.parent / "workspace")
        use_ledger = args.source == "ledger" or (
            args.source == "auto" and ledger_path.is_file()
        )
        if use_ledger:
            report = ledger_audit.audit_ledger(
                ledger_path,
                data_root=data_root,
            )
            report["legacySurfaceInventory"] = inventory_legacy_surface(
                args.project_root
            )
        else:
            report = run_audit(
                data_root,
                project_root=args.project_root,
                workspace_root=workspace_root,
            )
    except FileNotFoundError as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2

    report["generatedAtMs"] = _utc_now_ms()
    if args.output:
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    summary = report["summary"]
    if report["source"] == "workflow-ledger":
        print(
            f"source=workflow-ledger integrity={report['ledger']['integrity']} "
            f"schema={report['ledger']['migration']['actualVersion']}/"
            f"{report['ledger']['migration']['expectedVersion']} "
            f"runs={summary['runCount']} succeeded={summary['successfulRunCount']} "
            f"authorizations={summary['catalogRunAuthorizationCount']} "
            f"reservedBudgets={summary['reservedBudgetReceiptCount']} "
            f"statuses={json.dumps(summary['statusCounts'], ensure_ascii=False)}"
        )
        for entry in report["runs"]:
            if entry["findings"]:
                codes = ",".join(
                    sorted({finding["code"] for finding in entry["findings"]})
                )
                print(f"  {entry['runId']}: {entry['status']} [{codes}]")
        print(
            "legacySurfaceInventory: "
            f"{json.dumps(report['legacySurfaceInventory'])}"
        )
        return 0 if report["passed"] else 1

    print(
        f"runs={summary['runCount']} events={summary['eventCount']} "
        f"handoffs={summary['handoffCount']} humanTasks={summary['humanTaskCount']} "
        f"sessionBindings={summary['sessionBindingCount']} taskBundles={summary['taskBundleCount']} "
        f"reservations={summary['reservationCount']} artifactManifests={summary['artifactManifestCount']} "
        f"classifications={json.dumps(summary['classifications'], ensure_ascii=False)}"
    )
    for entry in report["runs"]:
        if entry["classification"] not in ("migratable", "archivable_terminal"):
            codes = ",".join(sorted({finding["code"] for finding in entry.get("findings") or []}))
            print(f"  {entry['runId']}: {entry['classification']} [{codes}]")
    print(f"checkpoint: {report['checkpoint']}")
    print(f"legacySurfaceInventory: {json.dumps(report['legacySurfaceInventory'])}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
