"""Agent directory registry repair / load-save / normalize helpers.

Claim scope: repair_agent_directory, load/save state, registry shrink guards,
LLM binding repair/migration, and related storage helpers.

Late-bound facade keeps monkeypatches stable.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import stat
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

# _workspace_path / load_state 进程内缓存：
# - _workspace_path 以 (路由根, parts, intent, seed) 为 key，以
#   developer_sandbox.workspace_routing_fingerprint（配置/活跃沙箱/环境变量签名）
#   为校验值；仅缓存 dev mode 关闭时的正式路由结果，dev 模式下 seeded 语义
#   依赖实时文件存在性，保持实时计算。路由根含显式 project_root 维度，
#   不同根的缓存条目互不命中。
# - load_state 在 _STATE_LOCK 内以注册表文件签名 (path, exists, mtime_ns, size)
#   校验；签名含注册表绝对路径，天然按根分区；读取前后签名一致才缓存，
#   写入点经 _invalidate_repaired_state_cache 显式失效。
_WORKSPACE_PATH_CACHE_LOCK = threading.RLock()
_WORKSPACE_PATH_CACHE: dict[tuple[object, ...], tuple[tuple[object, ...], Path]] = {}
_WORKSPACE_PATH_CACHE_LIMIT = 512
_LOAD_STATE_CACHE_SIGNATURE: tuple[str, bool, int, int] | None = None
_LOAD_STATE_CACHE_STATE: dict[str, Any] | None = None


def _copy_json_value(value: Any) -> Any:
    """Deep-copy plain JSON values without copy.deepcopy's memo bookkeeping.

    注册表状态只含 JSON 类型（dict/list/标量），无共享引用、无循环；
    直接递归拷贝比 copy.deepcopy 快数倍，且保持「每次调用返回独立副本」的契约。
    """

    if isinstance(value, dict):
        return {key: _copy_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_json_value(item) for item in value]
    return value


def _service():
    from core.web.services import agent_directory_service

    return agent_directory_service


def _agent_creation_missing_fields(
    *,
    display_name: str,
    llm_bindings: dict[str, Any],
    primary_mode: str,
    role_key: str,
    prompt_template_id: str,
    persona_profile: dict[str, Any],
    task_profile: dict[str, Any],
    tool_policy_id: str,
    tool_policy: dict[str, Any],
    memory_policy_id: str,
    memory_policy: dict[str, Any],
) -> list[str]:
    s = _service()
    missing: list[str] = []
    if not str(display_name or "").strip():
        missing.append("displayName")
    if not s.agent_dialogue_model_id({"llmBindings": llm_bindings}):
        missing.append("llmBindings")
    if not str(primary_mode or "").strip():
        missing.append("primaryMode")
    is_work_session = s._is_session_agent_primary_mode(primary_mode)
    if not is_work_session and not str(role_key or "").strip():
        missing.append("roleKey")
    if not str(prompt_template_id or "").strip():
        missing.append("promptTemplateId")
    if not is_work_session and not s._persona_profile_has_content(persona_profile):
        missing.append("personaProfile")
    if not is_work_session and not s._task_profile_has_content(task_profile):
        missing.append("taskProfile")
    allowed_tools = list(tool_policy.get("allowedTools") or []) if isinstance(tool_policy, dict) else []
    if str(tool_policy_id or "").strip() == s.DEFAULT_TOOL_POLICY_ID and not allowed_tools:
        missing.append("toolPolicy")
    if not str(memory_policy_id or "").strip() or not isinstance(memory_policy, dict) or not memory_policy:
        missing.append("memoryPolicy")
    return missing


def _agent_directory_storage_signature(state: dict[str, Any]) -> str:
    s = _service()
    payload = s._build_agent_registry_payload_for_storage(state)
    payload.pop("updatedAt", None)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _agent_has_functional_identity(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if any(str(metadata.get(key) or "").strip() for key in ("agentMode", "selfEvolutionRole", "supervisedRole", "researchAgentKey")):
        return True
    if bool(metadata.get("fixedRole")):
        return True
    return s._normalize_primary_mode(agent.get("primaryMode")) in {"research", "self_evolution", "supervised_evolution"}


def _agent_public_display_name(
    seed: str,
    *,
    existing_agents: list[Any],
    agent_id: str,
    metadata: dict[str, Any] | None = None,
) -> str:
    s = _service()
    del existing_agents
    responsibility_name = s.trim_lines(
        str((metadata or {}).get("functionalDisplayName") or seed or ""),
        max_lines=1,
    ).strip()
    return responsibility_name[:120].rstrip() or s._fallback_agent_code(agent_id)


def _agent_workspace_relative_path(agent_id: str) -> str:
    s = _service()
    return f"workspace/agents/{s._safe_fragment(agent_id)}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    s = _service()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        deadline = time.monotonic() + s.WRITE_RETRY_TIMEOUT_SECONDS
        attempt = 0
        while True:
            try:
                os.replace(temp_path, path)
                if attempt:
                    s._record_state_write_event(
                        "agent_directory.state_write_retried",
                        level="warning",
                        outcome="recovered",
                        fields={"attempts": attempt, "pathName": path.name},
                    )
                return
            except PermissionError as exc:
                attempt += 1
                if time.monotonic() >= deadline:
                    s._record_state_write_event(
                        "agent_directory.state_write_failed",
                        level="error",
                        outcome="failed",
                        fields={"attempts": attempt, "pathName": path.name, "errorType": type(exc).__name__},
                    )
                    raise
                time.sleep(min(0.05 * attempt, 0.25))
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _build_agent_registry_payload_for_storage(state: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    payload = s.default_state()
    payload.update(state if isinstance(state, dict) else {})
    payload["version"] = s.AGENT_REGISTRY_VERSION
    payload["updatedAt"] = s.utc_now_iso()
    raw_agents = list(payload.get("agents") or []) if isinstance(payload.get("agents"), list) else []
    payload["agents"] = [
        normalized
        for item in raw_agents
        if isinstance(item, dict)
        for normalized in [s._normalize_agent_record_for_storage(item)]
    ]
    payload["toolPolicies"] = s._tool_policies(payload)
    payload["memoryPolicies"] = s._memory_policies(payload)
    return payload


def _challenge_cup_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    s = _service()
    profiles = {
        "challenge_cup_coordinator": {
            "personaProfile": {
                "personality": "清醒、克制，擅长把挑战杯科研流程压缩成下一步行动。",
                "communicationStyle": "先给阶段判断，再列证据位置、角色分工和用户下一步。",
                "background": f"{functional_name} 是挑战杯 ai 科研团队的协调 Agent，负责读状态和组织交接，不直接执行资料搜集。",
                "collaborationPreference": "把执行任务交给资料寻找、资料提炼、资料关系整理和资料入库 Agent，不越权声称已执行。",
                "expertise": ["挑战杯科研流程", "阶段协调", "任务交接"],
            },
            "taskProfile": {
                "mission": "协调挑战杯知识搜集阶段，整理当前状态、角色交接和用户下一步。",
                "responsibilities": "读取项目/会话上下文、任务状态和最近变更；判断阶段位置；把输入输出交接给对应执行 Agent。",
                "preferredTasks": "阶段判断、交接清单、阻塞归因、用户确认项整理。",
                "avoidTasks": "不要声称已启动资料搜集、联网搜索、提炼、审查或入库；不要执行 Shell/Git/正式知识写入。",
                "successCriteria": "用户能清楚看到当前阶段、证据位置、哪个 Agent 该做什么、下一步点击或确认什么。",
                "deliverables": "Stage Status、Agent Handoff、User Next Step、Boundaries。",
                "constraints": "只基于可读上下文和已有状态协调；执行动作交给具备对应工具和权限的 Agent 或 UI/API。",
                "handoffNotes": "需要真实资料处理时交给 source_finder/source_extractor/source_relation_mapper/source_ingestor。",
                "taskTypes": ["challenge_cup", "coordination", "stage_status"],
            },
        },
        "source_finder": {
            "personaProfile": {
                "personality": "敏锐、证据优先，擅长把赛题和 query seeds 展开成可追踪资料记录。",
                "communicationStyle": "先给寻找范围，再列已找到资料、下载/登记状态、无效来源和下一批建议。",
                "background": f"{functional_name} 是挑战杯资料寻找 Agent，负责搜索、获取、下载到本地和登记来源记录。",
                "collaborationPreference": "把可读资料交给资料提炼 Agent；无法获得的来源要记录原因，避免后续重复搜集。",
                "expertise": ["资料寻找", "公开资料检索", "来源获取", "本地登记"],
            },
            "taskProfile": {
                "mission": "围绕挑战杯赛题寻找、获取并登记高价值资料。",
                "responsibilities": "读取本轮资料上下文；执行公开搜索和 DOI/URL 校验；登记 DataRecord、locator、来源类型、可读性和无效原因。",
                "preferredTasks": "query seeds 扩展、候选来源寻找、公开来源获取、本地文件/URL/DOI 登记、无效来源归档。",
                "avoidTasks": "不要提炼正文结论、不要审查入库价值、不要写正式知识库/RAG/official graph。",
                "successCriteria": "每条资料都有标题、来源类型、URL/DOI/本地路径、访问状态、价值说明或无效原因。",
                "deliverables": "Finding Summary、DataRecords、Invalid Source Notes、Extraction Handoff。",
                "constraints": "阶段私聊任务先用 source_collection_context_tool 读取上下文；完成、阻塞或失败都用 source_collection_stage_writeback_tool 回写。",
                "handoffNotes": "可读资料交给 source_extractor；无效资料写明来源和排除原因。",
                "taskTypes": ["challenge_cup", "source_finding", "source_records"],
            },
        },
        "source_extractor": {
            "personaProfile": {
                "personality": "细致、克制，能把资料内容和质量判断合并成可复核结果。",
                "communicationStyle": "先说明覆盖率，再逐条列保留、退回、无效和需补信息的依据。",
                "background": f"{functional_name} 是挑战杯资料提炼 Agent，负责内容提炼和资料审查两个动作的一体化闭环。",
                "collaborationPreference": "把保留资料交给资料关系整理 Agent；把无效资料连同来源和原因从流程中移出。",
                "expertise": ["内容提炼", "来源质量评估", "候选资料筛选"],
            },
            "taskProfile": {
                "mission": "从已找到资料中提炼有效内容，并判断是否保留进入后续关系整理。",
                "responsibilities": "分页读取候选资料；对每条资料提炼摘要、证据锚点、相关性、质量风险和保留/无效决定。",
                "preferredTasks": "candidateExtractions、candidateDecisions、无效来源原因、待补资料建议。",
                "avoidTasks": "不要发现新检索方向、不要生成关系图、不要写正式知识库/RAG/official graph。",
                "successCriteria": "每条输入资料都有真实 candidateId 或 recordId 的提炼/审查结论；有价值但不完整的资料可保留并说明缺口；没有有效内容的一律移出流程。",
                "deliverables": "Extraction Coverage、Kept Sources、Invalid Sources、Relation Mapping Handoff。",
                "constraints": "默认使用 source_collection_context_tool 的 evidence 分页；摘要仅代表搜集阶段保存的摘要/元数据，不等于全文；覆盖不足只补缺失 ID，证据不足只补 evidenceGapCandidateIds。",
                "handoffNotes": "通过或保留资料交给 source_relation_mapper；无效资料记录来源用于后续去重排除。",
                "taskTypes": ["challenge_cup", "source_extraction", "source_review"],
            },
        },
        "source_relation_mapper": {
            "personaProfile": {
                "personality": "结构化、谨慎，擅长把资料、主题和证据关系整理成候选图。",
                "communicationStyle": "先给关系覆盖，再列节点、关系、缺口和不能正式同步的边界。",
                "background": f"{functional_name} 是挑战杯资料关系整理 Agent，负责候选关系预览，不写 official graph。",
                "collaborationPreference": "把候选关系和缺口交给资料入库 Agent 做最终审核。",
                "expertise": ["资料关系整理", "候选图谱", "证据链"],
            },
            "taskProfile": {
                "mission": "把已保留资料整理成候选级主题、来源和证据关系。",
                "responsibilities": "读取已保留资料；生成候选节点、关系、缺口和可入库预览。",
                "preferredTasks": "candidate-only 关系整理、主题聚类、证据链预览、断链说明。",
                "avoidTasks": "不要搜索新资料、不要审查保留价值、不要写正式知识库/RAG/official graph。",
                "successCriteria": "关系整理可解释、可追溯，并明确哪些节点/边仍缺证据。",
                "deliverables": "Relation Map、Missing Links、Ingestion Handoff。",
                "constraints": "只使用候选资料和上下文工具；输出仍是候选边界。",
                "handoffNotes": "关系预览交给 source_ingestor 做最终入库审核。",
                "taskTypes": ["challenge_cup", "source_relations", "candidate_graph"],
            },
        },
        "source_ingestor": {
            "personaProfile": {
                "personality": "审慎、负责，重视正式知识的可追溯和治理边界。",
                "communicationStyle": "先给入库结论，再列通过项、退回项、正式知识写入结果和风险。",
                "background": f"{functional_name} 是挑战杯资料入库 Agent，负责最终审核并把通过资料写入团队知识库。",
                "collaborationPreference": "只处理已提炼、已保留并有关系上下文的资料；缺证据则退回对应阶段。",
                "expertise": ["资料入库", "知识治理", "正式知识审查"],
            },
            "taskProfile": {
                "mission": "对资料寻找/提炼/关系整理结果做最终审核，并将通过资料纳入正式 Team Knowledge。",
                "responsibilities": "读取 approved/kept 候选、关系预览和 writebackContract；执行受控入库或回写明确失败原因。",
                "preferredTasks": "入库审核、正式知识写入、退回原因、治理门禁说明。",
                "avoidTasks": "不要重新搜索资料、不要替资料提炼阶段补审全部候选、不要绕过 source_collection_stage_writeback_tool。",
                "successCriteria": "用户能看到哪些资料已正式入库、哪些被退回、为什么失败以及下一轮该带给 Agent 的建议。",
                "deliverables": "Ingestion Decision、Formal Knowledge Result、Returned Sources、Next Retry Advice。",
                "constraints": "正式入库只能在本角色执行；完成必须以 writeback 和 materializedKnowledgeIngestion 结果为准。",
                "handoffNotes": "入库失败时，把失败原因和建议带回下一轮资料寻找或提炼。",
                "taskTypes": ["challenge_cup", "source_ingestion", "knowledge_governance"],
            },
        },
        "challenge_cup_experiment_planner": {
            "personaProfile": {
                "personality": "克制、结构化，擅长把算法假设转成可复核实验计划。",
                "communicationStyle": "先列计划状态，再给 dataset、metric、baseline、smoke gate 和人工门禁。",
                "background": f"{functional_name} 是挑战杯实验规划 Agent，负责写实验计划账本，不执行训练。",
                "collaborationPreference": "从候选假设和实验账本读取状态，把证据登记交给实验证据 Agent，把入库交给 知识库管理员。",
                "expertise": ["实验规划", "baseline 选择", "指标与 smoke gate"],
            },
            "taskProfile": {
                "mission": "把已审查的算法假设转成挑战杯实验计划草稿。",
                "responsibilities": "读取实验规划上下文；生成或修复 experiment plan；明确 dataset、metric、baseline、smokePlan、风险和用户确认点。",
                "preferredTasks": "实验计划草稿、baseline/metric 对齐、smoke gate 设计、实验阻塞归因。",
                "avoidTasks": "不要运行训练、不要执行命令、不要登记虚假结果、不要写正式 Team Knowledge/RAG/official graph。",
                "successCriteria": "实验计划能被用户审查，且所有执行前置条件、人工门禁和不能自动执行的边界都明确。",
                "deliverables": "Experiment Plan、Readiness Checklist、Risk Controls、User Gate。",
                "constraints": "先用 challenge_cup_experiment_context_tool 读取实验账本；仅用 challenge_cup_experiment_writeback_tool 写计划/账本记录；不自动执行训练或 smoke runner。",
                "handoffNotes": "计划就绪后交给 challenge_cup_experiment_ledger 登记 baseline、smoke/full-run 证据。",
                "taskTypes": ["challenge_cup", "experiment_planning", "ledger_writeback"],
            },
        },
        "challenge_cup_experiment_ledger": {
            "personaProfile": {
                "personality": "严谨、保守，重视实验结果的可复现证据链。",
                "communicationStyle": "先给证据账本状态，再列 artifact、metric、logRef、复现命令和缺口。",
                "background": f"{functional_name} 是挑战杯实验证据 Agent，负责登记实验账本证据，不运行实验。",
                "collaborationPreference": "只登记用户或外部执行后提供的结果；实验结果入库交给 知识库管理员 审核。",
                "expertise": ["实验账本", "复现实证", "结果证据登记"],
            },
            "taskProfile": {
                "mission": "登记 baseline artifact、smoke result、full-run result 和实验结果入库申请。",
                "responsibilities": "读取实验计划账本；核对 artifactPath、metricValue、logRef、reproductionCommand；登记结果和下一步阻塞。",
                "preferredTasks": "baseline artifact 登记、smoke/full-run 结果登记、实验结果包整理、知识库管理员 通知申请。",
                "avoidTasks": "不要执行训练/评估命令，不伪造结果，不直接写正式知识库或 RAG。",
                "successCriteria": "每条实验记录都有来源、指标、工件路径、复现说明和用户决策边界。",
                "deliverables": "Experiment Ledger Update、Evidence Trace、Ingestion Request Draft、Blockers。",
                "constraints": "先用 challenge_cup_experiment_context_tool 读取状态；只用 challenge_cup_experiment_writeback_tool 登记账本；只登记证据账本，不自动执行。",
                "handoffNotes": "full-run 通过后可请求 知识库管理员 审核实验结果包。",
                "taskTypes": ["challenge_cup", "experiment_ledger", "evidence_writeback"],
            },
        },
        "challenge_cup_iteration_planner": {
            "personaProfile": {
                "personality": "冷静、迭代导向，擅长把实验结论转成下一轮修复计划。",
                "communicationStyle": "先给 Research Loop 状态，再列证据、决策、下一轮模板和用户门禁。",
                "background": f"{functional_name} 是挑战杯迭代决策 Agent，负责 Research Loop 账本，不自动应用改动。",
                "collaborationPreference": "读取实验状态和 Research Loop，版本变更交给版本治理 Agent，正式知识交给 知识库管理员。",
                "expertise": ["Research Loop", "实验复盘", "迭代决策"],
            },
            "taskProfile": {
                "mission": "围绕实验结果创建或推进 Research Loop，形成下一轮迭代决策。",
                "responsibilities": "读取 Research Loop/实验上下文；创建 loop；登记证据；记录 repair/repeat/promote/archive 等决策。",
                "preferredTasks": "Research Loop 创建、证据登记、迭代决策、下一轮行动建议。",
                "avoidTasks": "不要运行命令、不要自动改代码/模型/数据、不要把提案直接写成正式结论。",
                "successCriteria": "每次迭代决策都有证据、rationale、下一步和需要用户确认的动作。",
                "deliverables": "Research Loop Record、Evidence Decision、Iteration Proposal、User Gate。",
                "constraints": "先用 challenge_cup_iteration_context_tool 读取模板和状态；用 challenge_cup_iteration_writeback_tool 写 Research Loop；不自动 apply。",
                "handoffNotes": "需要记录候选版本、supersedes 或 rejectionArchive 时交给 challenge_cup_versioning。",
                "taskTypes": ["challenge_cup", "iteration_planning", "research_loop"],
            },
        },
        "challenge_cup_versioning": {
            "personaProfile": {
                "personality": "细致、守边界，擅长维护候选版本、替代关系和拒绝归档。",
                "communicationStyle": "先给版本链状态，再列 versionHistory、supersededBy、derived_from、rejectionArchive。",
                "background": f"{functional_name} 是挑战杯版本治理 Agent，负责候选版本账本，不写官方图谱。",
                "collaborationPreference": "接收迭代决策和实验结论，只维护候选层版本关系；正式图谱/知识入库交给专门门禁。",
                "expertise": ["候选版本治理", "拒绝归档", "迭代追溯"],
            },
            "taskProfile": {
                "mission": "维护挑战杯候选方案版本历史、派生/替代关系和拒绝归档。",
                "responsibilities": "读取版本账本；登记 candidate version；记录 supersedes、derived_from、reject 关系；保持拒绝原因可追溯。",
                "preferredTasks": "versionHistory 维护、supersededBy/derived_from 记录、rejectionArchive 归档、候选变更摘要。",
                "avoidTasks": "不要写 official graph、不要写正式 Team Knowledge/RAG、不要自动应用候选变更。",
                "successCriteria": "每个版本/拒绝/替代关系都有 candidateId、原因、证据引用和记录 Agent。",
                "deliverables": "Version History、Relation Records、Rejection Archive、Traceability Gaps。",
                "constraints": "先用 challenge_cup_versioning_context_tool 读取账本；只用 challenge_cup_versioning_writeback_tool 写候选版本账本；不写 official graph。",
                "handoffNotes": "版本决策依据不足时退回 challenge_cup_iteration_planner 补 Research Loop 证据。",
                "taskTypes": ["challenge_cup", "candidate_versioning", "iteration_trace"],
            },
        },
    }
    return profiles.get(role, s._generic_research_agent_profile_defaults(role, functional_name))


def _clear_agent_runtime_state(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    agent_id = str(agent.get("agentId") or "").strip()
    workspace_path = str(agent.get("workspacePath") or s._agent_workspace_relative_path(agent_id)).strip()
    runtime_subdirs = ("inbox", "outbox", "events", "tmp", "logs", "runs", "scratch", "artifacts")
    if not agent_id or not workspace_path:
        return {"deletedPaths": [], "skippedPaths": [workspace_path or agent_id]}
    try:
        resolved = s._resolve_project_path(workspace_path)
        expected_private = s._resolve_project_path(s._agent_workspace_relative_path(agent_id))
        agents_root = s._workspace_path("agents").resolve()
    except Exception:
        return {"deletedPaths": [], "skippedPaths": [workspace_path]}
    if resolved != expected_private:
        return {"deletedPaths": [], "skippedPaths": [s._relative_project_path(resolved)]}
    try:
        if not resolved.is_relative_to(agents_root):
            return {"deletedPaths": [], "skippedPaths": [s._relative_project_path(resolved)]}
    except ValueError:
        return {"deletedPaths": [], "skippedPaths": [s._relative_project_path(resolved)]}

    resolved.mkdir(parents=True, exist_ok=True)
    deleted_paths: list[str] = []
    skipped_paths: list[str] = []
    for subdir in runtime_subdirs:
        target = (resolved / subdir).resolve()
        relative_path = s._relative_project_path(target)
        try:
            if not target.is_relative_to(resolved):
                skipped_paths.append(relative_path)
                continue
        except ValueError:
            skipped_paths.append(relative_path)
            continue
        try:
            if target.exists():
                shutil.rmtree(target)
                deleted_paths.append(relative_path)
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            skipped_paths.append(f"{relative_path} ({type(exc).__name__})")
    return {"deletedPaths": deleted_paths, "skippedPaths": skipped_paths}


def _configured_model_library_ids() -> set[str]:
    s = _service()
    try:
        from config.settings import get_config

        model_library = getattr(get_config().llm, "model_library", {}) or {}
    except Exception:
        return set()
    if not isinstance(model_library, dict):
        return set()
    return {str(model_id or "").strip() for model_id in model_library if str(model_id or "").strip()}


def _count_jsonl_matching_status(path: Path, *, status: str = "") -> int:
    s = _service()
    normalized_status = str(status or "").strip().lower()
    if not path.exists():
        return 0
    cache_key = (*s._jsonl_signature(path), normalized_status)
    cached = s._JSONL_COUNT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    count = 0
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(payload, dict):
                    continue
                if normalized_status and str(payload.get("status") or "pending").strip().lower() != normalized_status:
                    continue
                count += 1
    except OSError:
        return 0
    s._remember_jsonl_count(cache_key, count)
    return count


def _developer_sandbox_module():
    s = _service()
    from core.infrastructure import developer_sandbox

    return developer_sandbox


def _display_name_needs_responsibility_repair(display_name: str, agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source = str(metadata.get("displayNameSource") or "").strip()
    normalized = str(display_name or "").strip()
    if source in {"user", "responsibility"}:
        return False
    if source == "generated_person_name":
        return True
    return not normalized or _service()._AGENT_ID_LIKE_PATTERN.match(normalized) is not None


def _is_challenge_cup_agent_config_authority(agent: dict[str, Any]) -> bool:
    """Return whether an Agent record is a Challenge Cup config SSOT asset.

    Current and legacy assets are recognized from durable Agent-owned metadata,
    not from their mutable roleKey/displayName. These records are intentionally
    opaque to generic registry repair: an incomplete value is surfaced to the
    Agent configuration UI instead of being overwritten from role defaults.
    """

    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    return bool(
        str(metadata.get("challengeCupTeamId") or "").strip() == "research-team"
        or str(metadata.get("challengeCupTeamRole") or "").strip()
        or str(metadata.get("managedDomain") or "").strip()
        == "challenge_cup_neuro_algorithm"
        or str(agent.get("createdBy") or "").strip() == "challenge_cup_team"
    )


def _ensure_agent_workspace(path_value: str, *, ensure_shared: bool = True) -> Path:
    s = _service()
    path = s._resolve_project_path(path_value)
    agents_root = s._workspace_path("agents").resolve()
    if not path.is_relative_to(agents_root):
        raise s.AgentDirectoryError(f"Invalid agent workspace path: {path}")
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True)
    for subdir in s.AGENT_WORKSPACE_SUBDIRS:
        target = path / subdir
        if not target.is_dir():
            target.mkdir(parents=True, exist_ok=True)
    if ensure_shared:
        s.ensure_agent_shared_workspace()
    return path


def _ensure_fixed_role_profiles(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = dict(agent.get("metadata") or {})
    if str(metadata.get("challengeCupTeamId") or "").strip():
        return False
    defaults = s._fixed_role_profile_defaults(agent, metadata)
    if not defaults:
        return False

    changed = False
    persona = s.normalize_persona_profile(metadata.get("personaProfile") if isinstance(metadata.get("personaProfile"), dict) else {})
    persona_defaults_disabled = bool(metadata.get("personaProfileDefaultsDisabled"))
    replace_generic_persona = s._should_replace_generic_challenge_cup_persona(agent, metadata, persona)
    if not persona_defaults_disabled and (not s._persona_profile_has_content(persona) or replace_generic_persona):
        default_persona = s.normalize_persona_profile(defaults.get("personaProfile"))
        if s._persona_profile_has_content(default_persona):
            metadata["personaProfile"] = default_persona
            changed = True

    task = s.normalize_task_profile(metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {})
    task_defaults_disabled = bool(metadata.get("taskProfileDefaultsDisabled"))
    replace_challenge_cup_task = (
        s._should_replace_generic_challenge_cup_task(agent, metadata, task)
        or s._should_replace_incomplete_challenge_cup_task(agent, metadata, task)
    )
    if not task_defaults_disabled and (not s._task_profile_has_content(task) or replace_challenge_cup_task):
        default_task = s.normalize_task_profile(defaults.get("taskProfile"))
        if s._task_profile_has_content(default_task):
            metadata["taskProfile"] = default_task
            changed = True

    if changed:
        agent["metadata"] = metadata
    return changed


def _ensure_knowledge_steward_agent(
    state: dict[str, Any],
    *,
    ensure_shared_workspace: bool = True,
    available_avatar_filenames: list[str] | None = None,
    normalized_tool_policies: dict[str, Any] | None = None,
) -> dict[str, Any]:
    s = _service()
    agents = list(state.get("agents") or [])
    tool_policies = normalized_tool_policies if normalized_tool_policies is not None else s._tool_policies(state)
    memory_policies = s._memory_policies(state)
    now = s.utc_now_iso()
    agent = s._find_agent(state, s.KNOWLEDGE_STEWARD_AGENT_ID)
    created = False
    changed = False
    repaired_fields: list[str] = []
    workspace_path = s._agent_workspace_relative_path(s.KNOWLEDGE_STEWARD_AGENT_ID)

    if agent is None:
        metadata = s._knowledge_steward_metadata()
        llm_bindings = s.normalize_agent_llm_bindings(
            {s.DEFAULT_AGENT_LLM_SLOT: {"modelId": s._profile_id_to_model_id("primary")}}
        )
        agent = {
            "agentId": s.KNOWLEDGE_STEWARD_AGENT_ID,
            "agentCode": s._next_agent_code(agents),
            "displayName": s._agent_public_display_name(
                s.KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
                existing_agents=agents,
                agent_id=s.KNOWLEDGE_STEWARD_AGENT_ID,
                metadata=metadata,
            ),
            "kind": s.DEFAULT_AGENT_KIND,
            "primaryMode": "general",
            "roleKey": s.KNOWLEDGE_STEWARD_ROLE_KEY,
            "llmBindings": llm_bindings,
            "promptTemplateId": s.KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID,
            "directSessionId": s.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID,
            "workspacePath": workspace_path,
            "toolPolicyId": s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
            "memoryPolicyId": s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
            "createdBy": "system_repair",
            "status": "active",
            "metadata": metadata,
            "createdAt": now,
            "updatedAt": now,
        }
        s._ensure_agent_default_avatar(
            agent,
            available_avatar_filenames=available_avatar_filenames,
        )
        agents.append(agent)
        state["agents"] = agents
        created = True
        changed = True
        repaired_fields.append("agent")

    if not isinstance(agent, dict):
        return {"changed": False, "created": False, "agent": {}, "repairedFields": []}

    expected = {
        "kind": s.DEFAULT_AGENT_KIND,
        "primaryMode": "general",
        "roleKey": s.KNOWLEDGE_STEWARD_ROLE_KEY,
        "promptTemplateId": s.KNOWLEDGE_STEWARD_PROMPT_TEMPLATE_ID,
        "directSessionId": s.KNOWLEDGE_STEWARD_DIRECT_SESSION_ID,
        "workspacePath": workspace_path,
        "toolPolicyId": s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID,
        "memoryPolicyId": s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID,
        "status": "active",
    }
    for key, value in expected.items():
        if str(agent.get(key) or "").strip() != value:
            agent[key] = value
            changed = True
            repaired_fields.append(key)

    llm_repair = s._migrate_agent_llm_bindings_to_new_design(agent)
    if llm_repair.get("changed"):
        changed = True
        repaired_fields.append("llmBindings")

    if not s._normalize_agent_code(agent.get("agentCode")):
        agent["agentCode"] = s._next_agent_code(agents, exclude_agent_id=s.KNOWLEDGE_STEWARD_AGENT_ID)
        changed = True
        repaired_fields.append("agentCode")

    title = str(agent.get("displayName") or "").strip()
    display_name_needs_repair = not title or s._display_name_needs_responsibility_repair(title, agent)
    metadata = dict(agent.get("metadata") or {})
    merged_metadata = s._knowledge_steward_merged_metadata(metadata)
    if metadata != merged_metadata:
        agent["metadata"] = merged_metadata
        changed = True
        repaired_fields.append("metadata")

    if display_name_needs_repair:
        agent["displayName"] = s._agent_public_display_name(
            s.KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
            existing_agents=agents,
            agent_id=s.KNOWLEDGE_STEWARD_AGENT_ID,
            metadata=dict(agent.get("metadata") or {}),
        )
        changed = True
        repaired_fields.append("displayName")

    avatar_changed = s._ensure_agent_default_avatar(
        agent,
        available_avatar_filenames=available_avatar_filenames,
    )
    if avatar_changed:
        changed = True
        repaired_fields.append("avatar")

    s._ensure_agent_workspace(
        workspace_path,
        ensure_shared=ensure_shared_workspace,
    )
    tool_policy = s._knowledge_steward_tool_policy()
    memory_policy = s._knowledge_steward_memory_policy(workspace_path)
    if tool_policies.get(s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID) != tool_policy:
        tool_policies[s.KNOWLEDGE_STEWARD_TOOL_POLICY_ID] = tool_policy
        changed = True
        repaired_fields.append("toolPolicy")
    if agent.get("toolPolicy") != tool_policy:
        agent["toolPolicy"] = tool_policy
        changed = True
        repaired_fields.append("toolPolicy")
    if memory_policies.get(s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID) != memory_policy:
        memory_policies[s.KNOWLEDGE_STEWARD_MEMORY_POLICY_ID] = memory_policy
        changed = True
        repaired_fields.append("memoryPolicy")
    state["toolPolicies"] = tool_policies
    state["memoryPolicies"] = memory_policies
    if changed:
        agent["updatedAt"] = now
    return {
        "changed": changed,
        "created": created,
        "agent": dict(agent),
        "repairedFields": sorted(set(repaired_fields)),
    }


def _find_agent(state: dict[str, Any], agent_id: str) -> dict[str, Any] | None:
    s = _service()
    normalized = str(agent_id or "").strip()
    if not normalized:
        return None
    for item in state.get("agents") or []:
        if isinstance(item, dict) and str(item.get("agentId") or "").strip() == normalized:
            return item
    return None


def _fixed_role_profile_defaults(agent: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    role = s._fixed_role_profile_key(agent, metadata)
    if not role:
        return {}

    functional_name = str(
        metadata.get("functionalDisplayName")
        or metadata.get("selfEvolutionRoleLabel")
        or metadata.get("supervisedRoleLabel")
        or agent.get("displayName")
        or role
    ).strip()
    responsibilities = s._unique_string_list(metadata.get("responsibilities"))

    if role.startswith("self_evolution:"):
        return s._self_evolution_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("supervised_evolution:"):
        return s._supervised_evolution_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("research_org:"):
        return s._research_org_profile_defaults(role.split(":", 1)[1], functional_name, responsibilities)
    if role.startswith("challenge_cup:"):
        return s._challenge_cup_agent_profile_defaults(role.split(":", 1)[1], functional_name)
    if role.startswith("research_agent:"):
        return s._research_agent_profile_defaults(role.split(":", 1)[1], functional_name)
    return {}


def _fixed_role_profile_key(agent: dict[str, Any], metadata: dict[str, Any]) -> str:
    s = _service()
    primary_mode = s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent))
    self_role = s._normalize_role_key(metadata.get("selfEvolutionRole") or "")
    if primary_mode == "self_evolution" or self_role:
        return f"self_evolution:{self_role or s._normalize_role_key(agent.get('roleKey')) or 'member'}"

    supervised_role = s._normalize_role_key(metadata.get("supervisedRole") or "")
    if primary_mode == "supervised_evolution" or supervised_role:
        return f"supervised_evolution:{supervised_role or s._normalize_role_key(agent.get('roleKey')) or 'member'}"

    research_org_role = s._normalize_role_key(metadata.get("researchOrgRole") or metadata.get("systemRole") or "")
    if research_org_role in {"ceo", "organization_advisor", "capability_steward"}:
        return f"research_org:{research_org_role}"

    research_agent_key = s._normalize_role_key(metadata.get("researchAgentKey") or "")
    role_key = s._normalize_role_key(agent.get("roleKey") or "")
    if role_key in s.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return f"challenge_cup:{role_key}"
    if research_agent_key or role_key.startswith("research_") or primary_mode == "research":
        return f"research_agent:{research_agent_key or role_key}"

    return ""


def _generic_research_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    s = _service()
    role_label = role.replace("_", " ").strip() or "research agent"
    return {
        "personaProfile": {
            "personality": "细致、证据优先，避免把未验证来源当成结论。",
            "communicationStyle": "先列可用证据和不确定性，再给研究建议。",
            "background": f"{functional_name} 是研究流程中的功能型 Agent。",
            "collaborationPreference": "围绕来源、证据、引用和结论边界与研究团队协作。",
            "expertise": ["研究检索", "证据整理", role_label],
        },
        "taskProfile": {
            "mission": f"承担 {functional_name} 的研究分工，输出可追溯证据。",
            "responsibilities": "阅读资料；提取关键证据；标注来源质量；把发现交给研究组织或团队成员复核。",
            "preferredTasks": "文献阅读、来源比对、证据摘录和研究问题拆解。",
            "avoidTasks": "不要编造来源、不要把未经复核的发现写成确定结论。",
            "successCriteria": "输出包含来源、证据片段、可信度和待复核问题。",
            "deliverables": "资料摘要、证据清单、引用线索和复核建议。",
            "constraints": "保留来源边界，遵守研究工具和知识库权限。",
            "handoffNotes": "结论性判断交给研究负责人或评审 Agent 复核。",
            "taskTypes": ["research", role],
        },
    }


def _guard_against_suspicious_registry_shrink(next_payload: dict[str, Any]) -> None:
    s = _service()
    path = s.registry_path()
    if not path.exists():
        return
    previous_payload = s._load_existing_registry_payload_or_raise(path)
    previous_agents = [item for item in previous_payload.get("agents") or [] if isinstance(item, dict)]
    next_agents = [item for item in next_payload.get("agents") or [] if isinstance(item, dict)]
    previous_count = len(previous_agents)
    next_count = len(next_agents)
    if previous_count < s.SUSPICIOUS_REGISTRY_SHRINK_MIN_AGENTS:
        return
    if next_count > max(2, previous_count // 4):
        return
    next_agent_ids = {str(item.get("agentId") or "").strip() for item in next_agents}
    previous_direct_agents = [
        item
        for item in previous_agents
        if str(item.get("agentId") or "").strip()
        and str(item.get("directSessionId") or "").strip()
        and str(item.get("status") or "active").strip().lower() != "archived"
    ]
    removed_direct_agents = [
        item for item in previous_direct_agents if str(item.get("agentId") or "").strip() not in next_agent_ids
    ]
    if len(removed_direct_agents) < s.SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS:
        return
    if len(removed_direct_agents) < max(s.SUSPICIOUS_REGISTRY_SHRINK_MIN_DIRECT_AGENTS, len(previous_direct_agents) // 2):
        return
    fields = {
        "previousAgentCount": previous_count,
        "nextAgentCount": next_count,
        "previousDirectSessionAgentCount": len(previous_direct_agents),
        "removedDirectSessionAgentCount": len(removed_direct_agents),
        "sampleRemovedAgentIds": [
            str(item.get("agentId") or "").strip()
            for item in removed_direct_agents[:8]
        ],
        "pathName": path.name,
    }
    s._record_state_write_event(
        "agent_directory.state_write_rejected_suspicious_shrink",
        level="error",
        outcome="blocked",
        fields=fields,
    )
    raise s.AgentDirectoryError(
        "Refused suspicious Agent registry shrink: "
        f"{previous_count} agents would become {next_count}, "
        f"removing {len(removed_direct_agents)} active direct-session Agents."
    )


def _infer_agent_primary_mode(agent: dict[str, Any]) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    mode = str(metadata.get("agentMode") or metadata.get("primaryMode") or "").strip()
    if mode:
        return s._normalize_primary_mode(mode)
    if str(metadata.get("researchAgentKey") or "").strip():
        return "research"
    if str(metadata.get("supervisedRole") or "").strip():
        return "supervised_evolution"
    created_by = str(agent.get("createdBy") or metadata.get("createdBy") or "").strip().lower()
    if "research" in created_by:
        return "research"
    if "supervised" in created_by:
        return "supervised_evolution"
    if "self_evolution" in created_by or "self-evolution" in created_by:
        return "self_evolution"
    return s.DEFAULT_AGENT_PRIMARY_MODE


def _infer_agent_prompt_template_id(agent: dict[str, Any]) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    role_prompt_template_id = s._prompt_template_id_for_role(agent.get("roleKey"), metadata=metadata)
    if role_prompt_template_id:
        return role_prompt_template_id
    research_key = str(metadata.get("researchAgentKey") or "").strip()
    if research_key:
        return s._normalize_prompt_template_id(f"prompt-research-{research_key}")
    supervised_role = str(metadata.get("supervisedRole") or "").strip()
    if supervised_role:
        return s._normalize_prompt_template_id(f"prompt-supervised-{supervised_role}")
    if s._infer_agent_primary_mode(agent) == "chat":
        if s._is_operation_chat_agent(agent):
            return "prompt-chat-operation-default"
        return "prompt-chat-default"
    return ""


def _infer_agent_role_key(agent: dict[str, Any]) -> str:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    research_key = str(metadata.get("researchAgentKey") or "").strip()
    if research_key:
        return s._normalize_role_key(f"research_{research_key}")
    supervised_role = str(metadata.get("supervisedRole") or "").strip()
    if supervised_role:
        return s._normalize_role_key(supervised_role)
    return ""


def _invalidate_repaired_state_cache() -> None:
    global _LOAD_STATE_CACHE_SIGNATURE, _LOAD_STATE_CACHE_STATE
    s = _service()
    s._REPAIRED_STATE_CACHE = None
    s._REPAIRED_STATE_CACHE_SIGNATURE = None
    _LOAD_STATE_CACHE_SIGNATURE = None
    _LOAD_STATE_CACHE_STATE = None
    with _WORKSPACE_PATH_CACHE_LOCK:
        _WORKSPACE_PATH_CACHE.clear()


def _is_agent_private_workspace_path(path_value: str, agent_id: str) -> bool:
    s = _service()
    normalized_agent_id = str(agent_id or "").strip()
    if not normalized_agent_id:
        return False
    normalized_path = str(path_value or "").strip().replace("\\", "/").strip("/")
    expected_path = s._agent_workspace_relative_path(normalized_agent_id).strip("/")
    if normalized_path == expected_path:
        return True
    try:
        actual = s._resolve_project_path(path_value)
        expected = s._resolve_project_path(expected_path)
    except Exception:
        return False
    return actual == expected


def _is_operation_chat_agent(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    if bool(metadata.get("operationChat")):
        return True
    if str(metadata.get("agentBoundary") or "").strip() == "operation_chat":
        return True
    return False


def _is_profileless_session_agent(agent: dict[str, Any]) -> bool:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    creation_tool_bundle_ids = {
        str(item or "").strip()
        for item in list(metadata.get("creationToolBundleIds") or [])
        if str(item or "").strip()
    }
    # A virtual-human Agent is still a native chat Session, but its persona is
    # product state consumed by the shared Agent prompt context.  The creation
    # bundle marker keeps this exception local to the plugin-created person;
    # ordinary role-less chat Sessions remain intentionally profileless.
    if "virtual_human_life" in creation_tool_bundle_ids:
        return False
    primary_mode = s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent))
    role_key = s._normalize_role_key(agent.get("roleKey") or s._infer_agent_role_key(agent))
    return s._is_session_agent_primary_mode(primary_mode) and not role_key


def _is_session_agent_primary_mode(primary_mode: str) -> bool:
    s = _service()
    return str(primary_mode or "").strip() in {"", "chat"}


def _iter_text_lines_reverse(path: Path) -> Iterable[str]:
    """Yield text lines from a file newest-first without reading it all."""
    s = _service()

    chunk_size = 8192
    remainder = b""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while position > 0:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                data = handle.read(read_size) + remainder
                parts = data.split(b"\n")
                remainder = parts[0]
                for raw_line in reversed(parts[1:]):
                    if raw_line.endswith(b"\r"):
                        raw_line = raw_line[:-1]
                    line = raw_line.decode("utf-8", errors="ignore")
                    if line.strip():
                        yield line
            if remainder.strip():
                yield remainder.decode("utf-8", errors="ignore")
    except OSError:
        return


def _jsonl_signature(path: Path) -> tuple[str, bool, int, int]:
    s = _service()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


def _knowledge_steward_merged_metadata(current: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = dict(current or {})
    for key in (
        "teamId",
        "challengeCupTeamId",
        "challengeCupTeamManagedVersion",
        "challengeCupTeamRole",
        "challengeCupTeamRoleKey",
        "knowledgeExpansionTeamId",
        "knowledgeExpansionTeamManagedVersion",
        "knowledgeExpansionTeamRole",
        "knowledgeExpansionTeamRoleKey",
        "researchTeamRole",
        "researchTeamRoleKey",
        "researchAgentKey",
        "teamRole",
        "teamRoleKey",
    ):
        metadata.pop(key, None)
    return s._merge_system_agent_metadata(metadata, s._knowledge_steward_metadata())


def _knowledge_steward_metadata() -> dict[str, Any]:
    s = _service()
    return {
        "systemRole": s.KNOWLEDGE_STEWARD_ROLE_KEY,
        "fixedRole": True,
        "protected": True,
        "conversationIndexKind": s.CONVERSATION_INDEX_KIND_PERSONAL_AGENT,
        "conversationIndexVisibility": s.CONVERSATION_INDEX_VISIBILITY_USER_VISIBLE,
        "showInSessionIndex": True,
        "functionalDisplayName": s.KNOWLEDGE_STEWARD_FUNCTIONAL_NAME,
        "displayNameSource": "responsibility",
        "agentMode": "general",
        "managedDomain": "team_knowledge",
        "governanceRole": "knowledge_steward",
        "phaseIntroduced": "memory_platform_phase3",
        "permissionBoundary": "governed_stage_writeback_ingestion",
        "personaProfile": {
            "personality": "审慎、耐心、重视证据链和权限边界。",
            "communicationStyle": "先给治理结论，再列来源、风险和需要审核的动作。",
            "background": "长期维护团队知识库、来源登记、精炼提案、评级建议和复审队列。",
            "collaborationPreference": "通过 source_collection_stage_writeback_tool 和 Team Knowledge 治理门禁筛选来源；通过的来源可直接形成正式知识项。",
            "expertise": ["团队知识治理", "来源溯源", "知识评级", "治理任务队列"],
        },
        "taskProfile": {
            "mission": "维护团队知识库质量，筛选来源证据并把通过的内容直接沉淀为可检索正式知识。",
            "responsibilities": (
                "查看知识治理任务；整理来源摄取包；筛选通过后直接入库；提交评级建议；"
                "生成复审摘要；发现权限、证据或高风险缺口时上报。"
            ),
            "preferredTasks": "来源登记、候选知识整理、评级建议、证据链追踪、治理队列巡检。",
            "avoidTasks": "不要绕过阶段回写和知识治理门禁、删除知识、跨团队授权、修改 ACL 或覆盖已有正式知识。",
            "successCriteria": "每条入库知识都有来源、时间戳、目标知识库、筛选理由和可追溯审计。",
            "deliverables": "治理任务摘要、来源摄取包、正式 KnowledgeItem、评级建议、复审风险清单。",
            "constraints": "阶段私聊任务先用 source_collection_context_tool 读取资料上下文；memory/knowledge_steward 阶段 approved 回写和 owner source review 会由后端通过 Team Knowledge 治理门禁直接创建 SourceArtifact 与正式 KnowledgeItem，其他阶段仍只更新任务结果。",
            "handoffNotes": "高风险、跨 owner、ACL、删除或覆盖已有正式知识时交给 Team owner/lead/steward/coordinator 或用户。",
            "taskTypes": ["knowledge_governance", "source_ingestion", "rating_suggestion", "review_preparation"],
        },
    }


def _load_existing_registry_payload_or_raise(path: Path) -> dict[str, Any]:
    s = _service()
    try:
        raw_payload = path.read_text(encoding="utf-8")
    except OSError as exc:
        s._record_agent_registry_load_failure(
            "agent_directory.state_read_rejected_unreadable_registry",
            path,
            reason="unreadable",
            error_type=type(exc).__name__,
        )
        raise s.AgentDirectoryError(f"Agent registry could not be loaded: {type(exc).__name__}.") from exc
    try:
        payload = json.loads(raw_payload)
    except json.JSONDecodeError as exc:
        s._record_agent_registry_load_failure(
            "agent_directory.state_read_rejected_corrupt_registry",
            path,
            reason="invalid_json",
            error_type=type(exc).__name__,
        )
        raise s.AgentDirectoryError("Agent registry could not be loaded: invalid JSON.") from exc
    if not isinstance(payload, dict):
        s._record_agent_registry_load_failure(
            "agent_directory.state_read_rejected_invalid_registry",
            path,
            reason="invalid_payload_type",
            error_type=type(payload).__name__,
        )
        raise s.AgentDirectoryError("Agent registry could not be loaded: payload must be a JSON object.")
    return payload


def _load_repaired_state_for_read() -> tuple[dict[str, Any], bool]:
    """Return a repaired registry snapshot without repeating repair on every read."""
    s = _service()

    signature = s._registry_state_signature()
    if s._REPAIRED_STATE_CACHE is not None and s._REPAIRED_STATE_CACHE_SIGNATURE == signature:
        return s._REPAIRED_STATE_CACHE, True
    state = s.repair_agent_directory()
    s._REPAIRED_STATE_CACHE = state
    s._REPAIRED_STATE_CACHE_SIGNATURE = s._registry_state_signature()
    return state, False


def _mark_display_name_responsibility(metadata: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    result = dict(metadata or {})
    if force or str(result.get("displayNameSource") or "").strip() != "user":
        result["displayNameSource"] = "responsibility"
    return result


def _memory_policies(state: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    raw = state.get("memoryPolicies")
    policies = dict(raw) if isinstance(raw, dict) else {}
    return {
        str(policy_id): s.normalize_memory_policy(policy if isinstance(policy, dict) else {}, str(policy_id), "")
        for policy_id, policy in policies.items()
    }


def _merge_system_agent_metadata(current: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    merged = dict(current or {})
    for key, value in defaults.items():
        if isinstance(value, dict):
            nested = dict(merged.get(key) or {}) if isinstance(merged.get(key), dict) else {}
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return merged


def _migrate_agent_llm_bindings_to_new_design(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    old_profile_id = str(agent.get("profileId") or agent.get("profile_id") or "").strip()
    old_template_id = str(agent.get("templateId") or agent.get("template_id") or "").strip()
    before = s.normalize_agent_llm_bindings(agent.get("llmBindings"))
    after = dict(before)
    migrated = False
    if not str(after.get(s.DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip():
        model_id = s._profile_id_to_model_id(old_profile_id or old_template_id)
        if model_id:
            after[s.DEFAULT_AGENT_LLM_SLOT] = {"modelId": model_id}
            migrated = True
    had_legacy_fields = any(key in agent for key in ("profileId", "profile_id", "templateId", "template_id"))
    agent["llmBindings"] = after
    for key in ("profileId", "profile_id", "templateId", "template_id"):
        agent.pop(key, None)
    if migrated or before != after or had_legacy_fields:
        metadata = dict(agent.get("metadata") or {})
        migration = dict(metadata.get("llmBindingMigration") or {})
        migration.update(
            {
                "schemaVersion": 1,
                "source": "agent_registry_repair",
                "migratedAt": s.utc_now_iso(),
                "legacyModelSourceId": old_profile_id,
                "legacyTemplateId": old_template_id,
                "dialogueModelId": str(after.get(s.DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip(),
            }
        )
        metadata["llmBindingMigration"] = migration
        agent["metadata"] = metadata
        agent["updatedAt"] = s.utc_now_iso()
        return {
            "changed": True,
            "migrated": migrated,
            "legacyModelSourceId": old_profile_id,
            "legacyTemplateId": old_template_id,
            "dialogueModelId": str(after.get(s.DEFAULT_AGENT_LLM_SLOT, {}).get("modelId") or "").strip(),
        }
    return {"changed": False}


def _next_agent_code(
    agents: list[Any],
    *,
    used_codes: set[str] | None = None,
    exclude_agent_id: str = "",
) -> str:
    s = _service()
    used = set(used_codes or set())
    for item in list(agents or []):
        if not isinstance(item, dict):
            continue
        if exclude_agent_id and str(item.get("agentId") or "").strip() == exclude_agent_id:
            continue
        code = s._normalize_agent_code(item.get("agentCode"))
        if code:
            used.add(code)
    index = 1
    while True:
        candidate = f"{s.AGENT_CODE_PREFIX}{index:03d}"
        if candidate not in used:
            return candidate
        index += 1


def _normalize_agent_code(value: Any) -> str:
    s = _service()
    normalized = re.sub(r"\s+", "", str(value or "").strip().upper())
    if s._AGENT_CODE_PATTERN.match(normalized):
        return normalized
    return ""


def _normalize_agent_legacy_metadata_fields(agent: dict[str, Any]) -> bool:
    s = _service()
    before = json.dumps(agent, ensure_ascii=False, sort_keys=True)
    normalized = s._normalize_agent_record_for_storage(agent)
    agent.clear()
    agent.update(normalized)
    after = json.dumps(agent, ensure_ascii=False, sort_keys=True)
    return before != after


def _normalize_agent_record_for_storage(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    normalized = dict(agent or {})
    normalized["llmBindings"] = s.normalize_agent_llm_bindings(normalized.get("llmBindings"))
    normalized["contextCompressionPolicy"] = s.normalize_agent_context_compression_policy(
        normalized.get("contextCompressionPolicy") if isinstance(normalized.get("contextCompressionPolicy"), dict) else None
    )
    metadata = dict(normalized.get("metadata") or {})
    avatar_path = s._canonical_agent_avatar_metadata_path(metadata, normalized)
    for stale_key in (
        "agentAvatarImagePath",
        "agentAvatarImageUrl",
        "agentAvatarImageSource",
        "avatarPath",
        "avatarImageUrl",
    ):
        metadata.pop(stale_key, None)
    if avatar_path:
        metadata["avatarImagePath"] = avatar_path
    if s._is_profileless_session_agent({**normalized, "metadata": metadata}):
        if isinstance(metadata.get("personaProfile"), dict):
            metadata.pop("personaProfile", None)
        if isinstance(metadata.get("taskProfile"), dict):
            metadata.pop("taskProfile", None)
    creation_spec = dict(metadata.get("creationSpec") or {})
    required_fields = list(creation_spec.get("requiredFields") or []) if isinstance(creation_spec.get("requiredFields"), list) else []
    if required_fields:
        creation_spec["requiredFields"] = [
            "llmBindings" if str(item or "").strip() == "profileId" else str(item or "").strip()
            for item in required_fields
            if str(item or "").strip() and str(item or "").strip() not in {"templateId", "profile_id", "template_id"}
        ]
        metadata["creationSpec"] = creation_spec
    migration = dict(metadata.get("llmBindingMigration") or {})
    legacy_profile_id = str(migration.pop("legacyProfileId", "") or "").strip()
    if legacy_profile_id and not str(migration.get("legacyModelSourceId") or "").strip():
        migration["legacyModelSourceId"] = legacy_profile_id
    if migration:
        metadata["llmBindingMigration"] = migration
    normalized["metadata"] = metadata
    normalized.pop("profileId", None)
    normalized.pop("profile_id", None)
    normalized.pop("templateId", None)
    normalized.pop("template_id", None)
    normalized.pop("avatarImagePath", None)
    normalized.pop("avatarImageUrl", None)
    normalized.pop("agentAvatarImagePath", None)
    normalized.pop("agentAvatarImageUrl", None)
    normalized.pop("avatarPath", None)
    return normalized


def _normalize_primary_mode(value: Any) -> str:
    s = _service()
    normalized = str(value or "").strip().lower().replace("-", "_")
    return normalized if normalized in s.KNOWN_AGENT_PRIMARY_MODES else "general"


def _normalize_prompt_template_id(value: Any) -> str:
    s = _service()
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return s._safe_fragment(normalized)


def _normalize_role_key(value: Any) -> str:
    s = _service()
    return s._safe_fragment(value).lower().replace("-", "_") if str(value or "").strip() else ""


def _persona_profile_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw = metadata.get("personaProfile") if isinstance(metadata.get("personaProfile"), dict) else {}
    return s.normalize_persona_profile(raw)


def _profile_id_to_model_id(profile_id: str) -> str:
    s = _service()
    normalized = str(profile_id or "").strip()
    candidates = [normalized] if normalized else []
    if "primary" not in candidates:
        candidates.append("primary")
    try:
        from config.settings import get_config

        config = get_config()
        for candidate in candidates:
            try:
                profile = config.llm.get_profile(profile_id=candidate)
                model_id, _entry = config.llm.get_model_library_entry_for_profile(profile)
            except Exception:
                continue
            if model_id:
                return str(model_id).strip()
        model_library = getattr(config.llm, "model_library", {}) or {}
        if isinstance(model_library, dict):
            for model_id, item in model_library.items():
                if isinstance(item, dict) and str(model_id or "").strip():
                    return str(model_id).strip()
    except Exception:
        return ""
    return ""


def _project_root() -> Path:
    s = _service()
    root = Path(s._active_project_root()).resolve()
    return root.parent if root.name.lower() == "workspace" else root


def _prompt_template_id_for_role(role_key: Any, *, metadata: dict[str, Any] | None = None) -> str:
    s = _service()
    return s.agent_role_tool_profile_service.role_prompt_template_id(s._normalize_role_key(role_key), metadata=metadata)


def _read_recent_jsonl(
    path: Path,
    *,
    limit: int,
    status: str = "",
    prompt_eligible_only: bool = False,
) -> list[dict[str, Any]]:
    """Read only the recent JSONL window needed for Agent Center previews."""
    s = _service()

    normalized_limit = max(1, int(limit or 1))
    if not path.exists():
        return []
    normalized_status = str(status or "").strip().lower()
    cache_key = (*s._jsonl_signature(path), normalized_limit, normalized_status, bool(prompt_eligible_only))
    cached = s._JSONL_RECENT_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached]
    events: list[dict[str, Any]] = []
    for line in s._iter_text_lines_reverse(path):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if normalized_status and str(payload.get("status") or "pending").strip().lower() != normalized_status:
            continue
        if prompt_eligible_only and not bool(payload.get("promptEligible", True)):
            continue
        events.append(payload)
        if len(events) >= normalized_limit:
            break
    result = list(reversed(events))
    s._remember_jsonl_recent(cache_key, result)
    return [dict(item) for item in result]


def _read_recent_jsonl_with_count(
    path: Path,
    *,
    limit: int,
    status: str = "",
) -> tuple[list[dict[str, Any]], int]:
    """Single reverse pass returning both the recent matching window and the
    total matching count, so callers do not parse the same JSONL twice."""
    s = _service()

    normalized_limit = max(1, int(limit or 1))
    if not path.exists():
        return [], 0
    normalized_status = str(status or "").strip().lower()
    cache_key = (*s._jsonl_signature(path), normalized_limit, normalized_status)
    cached = s._JSONL_RECENT_COUNT_CACHE.get(cache_key)
    if cached is not None:
        return [dict(item) for item in cached[0]], cached[1]
    recent: list[dict[str, Any]] = []
    count = 0
    for line in s._iter_text_lines_reverse(path):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if normalized_status and str(payload.get("status") or "pending").strip().lower() != normalized_status:
            continue
        count += 1
        if len(recent) < normalized_limit:
            recent.append(payload)
    result = list(reversed(recent))
    if len(s._JSONL_RECENT_COUNT_CACHE) > 512:
        s._JSONL_RECENT_COUNT_CACHE.clear()
    s._JSONL_RECENT_COUNT_CACHE[cache_key] = ([dict(item) for item in result], count)
    return [dict(item) for item in result], count


def _record_agent_llm_binding_migration_event(agents: list[dict[str, Any]]) -> None:
    s = _service()
    try:
        migrated_count = sum(1 for item in agents if item.get("migrated"))
        unresolved = [
            str(item.get("agentId") or "").strip()
            for item in agents
            if not str(item.get("dialogueModelId") or "").strip()
        ][:20]
        s.record_runtime_scene_event(
            "agent_directory",
            "agent_llm_bindings",
            "agent.llm_bindings_migrated",
            message="Agent llmBindings were migrated or repaired.",
            level="warning" if unresolved else "info",
            outcome="repaired" if not unresolved else "partial",
            fields={
                "agentCount": len(agents),
                "migratedCount": migrated_count,
                "unresolvedCount": len(unresolved),
                "unresolvedAgentIds": unresolved,
                "sample": agents[:12],
            },
        )
    except Exception:
        return


def _record_agent_registry_load_failure(
    event_code: str,
    path: Path,
    *,
    reason: str,
    error_type: str,
) -> None:
    s = _service()
    s._record_state_write_event(
        event_code,
        level="error",
        outcome="blocked",
        fields={"pathName": path.name, "reason": reason, "errorType": error_type},
    )


def _record_knowledge_steward_repaired_event(
    agent: dict[str, Any],
    *,
    created: bool = False,
    repaired_fields: list[str] | None = None,
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "agent",
            "agent.knowledge_steward.repaired",
            message="知识库管理员已创建或修复。",
            level="info",
            outcome="created" if created else "repaired",
            fields={
                "agentId": str(agent.get("agentId") or "").strip(),
                "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                "roleKey": s._normalize_role_key(agent.get("roleKey")),
                "toolPolicyId": str(agent.get("toolPolicyId") or "").strip(),
                "memoryPolicyId": str(agent.get("memoryPolicyId") or "").strip(),
                "directSessionId": str(agent.get("directSessionId") or "").strip(),
                "repairedFields": list(repaired_fields or []),
                "permissionBoundary": "governed_stage_writeback_ingestion",
            },
            lifecycle=True,
        )
    except Exception:
        return


def _record_state_write_event(
    event_code: str,
    *,
    level: str,
    outcome: str,
    fields: dict[str, Any],
) -> None:
    s = _service()
    try:
        s.record_runtime_scene_event(
            "agent_directory",
            "state_write",
            event_code,
            message=event_code,
            level=level,
            outcome=outcome,
            fields=fields,
        )
    except Exception:
        return


def _refresh_agent_onboarding_metadata(
    state: dict[str, Any],
    agent: dict[str, Any],
    *,
    normalized_tool_policies: dict[str, Any] | None = None,
    normalized_memory_policies: dict[str, Any] | None = None,
) -> None:
    s = _service()
    metadata = dict(agent.get("metadata") or {})
    if not isinstance(metadata.get("creationSpec"), dict):
        return
    agent_id = str(agent.get("agentId") or "").strip()
    tool_policy_id = str(agent.get("toolPolicyId") or s.DEFAULT_TOOL_POLICY_ID).strip() or s.DEFAULT_TOOL_POLICY_ID
    memory_policy_id = str(agent.get("memoryPolicyId") or "").strip()
    tool_policies = normalized_tool_policies if normalized_tool_policies is not None else s._tool_policies(state)
    memory_policies = (
        normalized_memory_policies if normalized_memory_policies is not None else s._memory_policies(state)
    )
    missing = s._agent_creation_missing_fields(
        display_name=str(agent.get("displayName") or "").strip(),
        llm_bindings=s.normalize_agent_llm_bindings(agent.get("llmBindings")),
        primary_mode=s._normalize_primary_mode(agent.get("primaryMode")),
        role_key=s._normalize_role_key(agent.get("roleKey")),
        prompt_template_id=s._normalize_prompt_template_id(agent.get("promptTemplateId")),
        persona_profile=s._persona_profile_for_agent(agent),
        task_profile=s._task_profile_for_agent(agent),
        tool_policy_id=tool_policy_id,
        tool_policy=tool_policies.get(tool_policy_id) if isinstance(tool_policies.get(tool_policy_id), dict) else {},
        memory_policy_id=memory_policy_id,
        memory_policy=memory_policies.get(memory_policy_id) if isinstance(memory_policies.get(memory_policy_id), dict) else {},
    )
    metadata["onboardingStatus"] = "incomplete" if missing else "complete"
    metadata["onboardingMissing"] = missing
    if agent_id:
        creation_spec = dict(metadata.get("creationSpec") or {})
        creation_spec["agentId"] = agent_id
        metadata["creationSpec"] = creation_spec
    agent["metadata"] = metadata


def _registry_state_signature() -> tuple[str, bool, int, int]:
    s = _service()
    path = s.registry_path()
    try:
        stat = path.stat()
    except OSError:
        return (str(path), False, 0, 0)
    return (str(path), True, int(stat.st_mtime_ns), int(stat.st_size))


def _relative_project_path(path: Path) -> str:
    s = _service()
    resolved = Path(path).resolve()
    workspace_root = s._workspace_path().resolve()
    try:
        return f"workspace/{resolved.relative_to(workspace_root).as_posix()}"
    except ValueError:
        pass
    root = s._project_root().resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def _remember_jsonl_count(key: tuple[str, bool, int, int, str], value: int) -> None:
    s = _service()
    if len(s._JSONL_COUNT_CACHE) > 512:
        s._JSONL_COUNT_CACHE.clear()
    s._JSONL_COUNT_CACHE[key] = int(value or 0)


def _remember_jsonl_recent(key: tuple[str, bool, int, int, int, str, bool], value: list[dict[str, Any]]) -> None:
    s = _service()
    if len(s._JSONL_RECENT_CACHE) > 512:
        s._JSONL_RECENT_CACHE.clear()
    s._JSONL_RECENT_CACHE[key] = [dict(item) for item in value if isinstance(item, dict)]


def _repair_agent_llm_binding_model_refs(agent: dict[str, Any], *, model_library_ids: set[str]) -> dict[str, Any]:
    s = _service()
    if not model_library_ids:
        return {"changed": False}
    before = s.normalize_agent_llm_bindings(agent.get("llmBindings"))
    after = dict(before)
    repairs: list[dict[str, str]] = []
    for slot, binding in before.items():
        if not isinstance(binding, dict):
            continue
        model_id = str(binding.get("modelId") or "").strip()
        canonical_model_id = s._resolve_legacy_agent_model_id(model_id, model_library_ids=model_library_ids)
        if canonical_model_id and canonical_model_id != model_id:
            updated_binding = dict(binding)
            updated_binding["modelId"] = canonical_model_id
            after[slot] = updated_binding
            repairs.append(
                {
                    "slot": str(slot or "").strip(),
                    "legacyModelId": model_id,
                    "canonicalModelId": canonical_model_id,
                }
            )
    if not repairs:
        return {"changed": False}

    metadata = dict(agent.get("metadata") or {})
    history = list(metadata.get("llmBindingModelIdRepairs") or [])
    now = s.utc_now_iso()
    for item in repairs:
        history.append(
            {
                "schemaVersion": 1,
                "source": "agent_registry_repair",
                "repairedAt": now,
                **item,
            }
        )
    metadata["llmBindingModelIdRepairs"] = history[-20:]
    agent["metadata"] = metadata
    agent["llmBindings"] = after
    agent["updatedAt"] = now
    return {"changed": True, "repairs": repairs}


def _research_agent_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    s = _service()
    if role in s.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return s._challenge_cup_agent_profile_defaults(role, functional_name)
    return s._generic_research_agent_profile_defaults(role, functional_name)


def _research_org_profile_defaults(role: str, functional_name: str, responsibilities: list[str]) -> dict[str, Any]:
    s = _service()
    role_labels = {
        "ceo": ("把研究目标转成组织任务", "研究组织决策、任务分派、用户沟通"),
        "organization_advisor": ("设计和维护临时研究组织", "组织结构设计、权限建议、成员治理"),
        "capability_steward": ("维护 Agent 能力和权限边界", "能力审计、工具策略、记忆策略"),
    }
    mission, expertise = role_labels.get(role, ("维护研究组织运行", "研究组织治理"))
    responsibility_text = "；".join(responsibilities) if responsibilities else f"{functional_name} 负责{mission}。"
    return {
        "personaProfile": {
            "personality": "冷静、结构化，优先保持研究组织边界清晰。",
            "communicationStyle": "先给组织判断，再列依据、风险和需要用户确认的动作。",
            "background": f"{functional_name} 是研究组织中的受保护治理角色。",
            "collaborationPreference": "通过提案、审核和显式用户门禁推进高风险组织变更。",
            "expertise": ["研究组织", expertise, "Agent 治理"],
        },
        "taskProfile": {
            "mission": mission,
            "responsibilities": responsibility_text,
            "preferredTasks": "研究任务拆解、组织调度、能力边界审查和治理建议。",
            "avoidTasks": "不要擅自删除核心 Agent、绕过权限审批或直接执行高风险工具变更。",
            "successCriteria": "组织建议可审查、可回滚，且每个高风险动作都有明确用户门禁。",
            "deliverables": "组织方案、能力审计、权限建议、协作边界说明。",
            "constraints": "保持研究组织图、Agent Directory 和 mode binding 一致。",
            "handoffNotes": "需要执行破坏性或权限升级动作时交给用户或主线治理流程确认。",
            "taskTypes": ["research_organization", role],
        },
    }


def _resolve_legacy_agent_model_id(model_id: str, *, model_library_ids: set[str]) -> str:
    s = _service()
    normalized = str(model_id or "").strip()
    if not normalized or normalized in model_library_ids:
        return normalized
    if normalized in s.LEGACY_AGENT_PRIMARY_MODEL_IDS:
        primary_model_id = s._profile_id_to_model_id("primary")
        if primary_model_id and primary_model_id in model_library_ids:
            return primary_model_id
    alias_target = s.LEGACY_AGENT_MODEL_ID_ALIASES.get(normalized, "")
    if alias_target and alias_target in model_library_ids:
        return alias_target
    try:
        from config.settings import _compact_repeated_token_halves

        compacted = _compact_repeated_token_halves(normalized)
    except Exception:
        compacted = normalized
    if compacted and compacted != normalized and compacted in model_library_ids:
        return compacted
    return normalized


def _resolve_project_path(path_value: str) -> Path:
    s = _service()
    raw = str(path_value or "").strip()
    path = Path(raw)
    if path.parts and path.parts[0].lower() == "workspace":
        return s._workspace_path(*path.parts[1:]).resolve()
    if not path.is_absolute():
        path = s._project_root() / path
    return path.resolve()


def _retired_self_evolution_role(agent: dict[str, Any]) -> str:
    s = _service()
    primary_mode = s._normalize_primary_mode(agent.get("primaryMode") or s._infer_agent_primary_mode(agent))
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    self_role = s._normalize_role_key(metadata.get("selfEvolutionRole") or agent.get("roleKey") or "")
    prompt_template_id = s._normalize_prompt_template_id(agent.get("promptTemplateId"))
    if primary_mode != "self_evolution" and not self_role:
        return ""
    if self_role in s.SELF_EVOLUTION_RETIRED_ROLES:
        return self_role
    if primary_mode == "self_evolution" and prompt_template_id in s.SELF_EVOLUTION_RETIRED_PROMPT_TEMPLATE_IDS:
        return self_role or "summarizer"
    return ""


def _safe_fragment(value: Any) -> str:
    s = _service()
    raw = str(value or "").strip()
    token = s._SAFE_ID_FRAGMENT.sub("-", raw).strip("._-")
    return token or "agent"


def _self_evolution_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    s = _service()
    labels = {
        "executor": ("执行候选改进", "实现、验证和记录自进化候选变更。", "实现、测试、回滚准备"),
        "reviewer": ("评审候选变更", "从证据、风险和可回滚性角度审查自进化候选。", "代码评审、风险评估、证据复核"),
        "observer": ("旁路观察自进化", "不携带角色提示词，不调用工具，只记录自进化运行的风险信号。", "过程观察、风险信号、证据完整性"),
    }
    mission, responsibilities, expertise = labels.get(
        role,
        ("维护自进化流程", "按固定角色职责处理自进化运行中的分工。", "自进化协作"),
    )
    return {
        "personaProfile": {
            "personality": "审慎、可复核，优先保护主线稳定。",
            "communicationStyle": "先给结论，再列证据、风险和下一步。",
            "background": f"{functional_name} 是 Vibelution 自进化流程中的固定系统角色。",
            "collaborationPreference": "围绕候选变更、验证证据和回滚边界与其他系统 Agent 协作。",
            "expertise": ["自进化", expertise, "运行证据"],
        },
        "taskProfile": {
            "mission": mission,
            "responsibilities": responsibilities,
            "preferredTasks": "边界清晰、可验证、可回滚的自进化子任务。",
            "avoidTasks": "不要绕过监督门禁、不要直接发布远端变更、不要处理缺少证据的破坏性操作。",
            "successCriteria": "输出包含行为变化、证据、风险和回滚条件的可审查结果。",
            "deliverables": "候选实现、评审意见、运行摘要或证据索引。",
            "constraints": "遵守自进化事务边界和主线稳定要求。",
            "handoffNotes": "高风险或需发布的动作交给监督/用户确认。",
            "taskTypes": ["self_evolution", role],
        },
    }


def _should_repair_agent_prompt_template_id(current: str, expected: str) -> bool:
    s = _service()
    normalized_current = s._normalize_prompt_template_id(current)
    normalized_expected = s._normalize_prompt_template_id(expected)
    return bool(normalized_expected and not normalized_current)


def _should_repair_public_display_name(agent: dict[str, Any]) -> bool:
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    source = str(metadata.get("displayNameSource") or "").strip()
    if source in {"user", "responsibility"} and str(agent.get("displayName") or "").strip():
        return False
    current = str(agent.get("displayName") or "").strip()
    return not current or source == "generated_person_name" or _service()._AGENT_ID_LIKE_PATTERN.match(current) is not None


def _should_replace_generic_challenge_cup_persona(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    s = _service()
    role_key = s._normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in s.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return (
        str(profile.get("personality") or "").strip() == "细致、证据优先，避免把未验证来源当成结论。"
        and str(profile.get("communicationStyle") or "").strip() == "先列可用证据和不确定性，再给研究建议。"
        and str(profile.get("collaborationPreference") or "").strip() == "围绕来源、证据、引用和结论边界与研究团队协作。"
    )


def _should_replace_generic_challenge_cup_task(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    s = _service()
    role_key = s._normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in s.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return (
        str(profile.get("responsibilities") or "").strip()
        == "阅读资料；提取关键证据；标注来源质量；把发现交给研究组织或团队成员复核。"
        and str(profile.get("preferredTasks") or "").strip() == "文献阅读、来源比对、证据摘录和研究问题拆解。"
        and str(profile.get("constraints") or "").strip() == "保留来源边界，遵守研究工具和知识库权限。"
    )


def _should_replace_incomplete_challenge_cup_task(
    agent: dict[str, Any],
    metadata: dict[str, Any],
    profile: dict[str, Any],
) -> bool:
    s = _service()
    role_key = s._normalize_role_key(agent.get("roleKey") or metadata.get("researchAgentKey") or "")
    if role_key not in s.CHALLENGE_CUP_ROLE_PROMPT_TEMPLATE_IDS:
        return False
    return not any(str(profile.get(field) or "").strip() for field in s.AGENT_TASK_PROFILE_TEXT_FIELDS)


def _supervised_evolution_profile_defaults(role: str, functional_name: str) -> dict[str, Any]:
    s = _service()
    return {
        "personaProfile": {
            "personality": "严谨、保守，重视对照实验和可复现证据。",
            "communicationStyle": "用明确判定说明通过、失败、风险和证据缺口。",
            "background": f"{functional_name} 是监督进化评测和晋升流程中的固定系统角色。",
            "collaborationPreference": "围绕基线、候选、评审、审计和判定证据协作。",
            "expertise": ["监督进化", "评测证据", role],
        },
        "taskProfile": {
            "mission": "支撑监督进化的候选比较、风险评审和晋升判定。",
            "responsibilities": "收集评测证据；比较候选与基线；标注风险、退化和晋升条件。",
            "preferredTasks": "候选评测、审计、对照比较和晋升门禁判断。",
            "avoidTasks": "不要绕过用户门禁或把未验证候选提升为稳定行为。",
            "successCriteria": "每个判定都能追溯到测试、日志或人工评审证据。",
            "deliverables": "评测结论、风险说明、晋升或回滚建议。",
            "constraints": "SemVer、回滚和证据链要求必须保留。",
            "handoffNotes": "需要合入或发布时交给主线集成流程。",
            "taskTypes": ["supervised_evolution", role],
        },
    }


def _task_profile_for_agent(agent: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    raw = metadata.get("taskProfile") if isinstance(metadata.get("taskProfile"), dict) else {}
    return s.normalize_task_profile(raw)


def _unique_string_list(values: Any) -> list[str]:
    s = _service()
    if values is None or isinstance(values, (str, bytes)):
        return []
    try:
        iterator = iter(values)
    except TypeError:
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in iterator:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _with_functional_display_name(metadata: dict[str, Any], title: str) -> dict[str, Any]:
    s = _service()
    result = dict(metadata or {})
    normalized = s.trim_lines(title or "", max_lines=1).strip()
    if normalized and not result.get("functionalDisplayName"):
        result["functionalDisplayName"] = normalized
    return result


def _workspace_path(*parts: str, intent: str = "state", seed: bool = True) -> Path:
    s = _service()
    sandbox = s._developer_sandbox_module()
    root = s._project_root()
    fingerprint = sandbox.workspace_routing_fingerprint(root)
    # 缓存键必须携带实际路由根（显式 project_root 或默认根），
    # 否则不同根的解析结果会在并发下互相命中，形成新的串线口。
    cache_key = (str(root), tuple(str(part) for part in parts), str(intent), bool(seed))
    with _WORKSPACE_PATH_CACHE_LOCK:
        cached = _WORKSPACE_PATH_CACHE.get(cache_key)
        if cached is not None and cached[0] == fingerprint:
            return cached[1]
    path = sandbox.route_workspace_path(
        root,
        "agent_directory",
        *parts,
        intent=intent,
        seed=seed,
    )
    if not sandbox.is_developer_mode_enabled():
        with _WORKSPACE_PATH_CACHE_LOCK:
            if len(_WORKSPACE_PATH_CACHE) >= _WORKSPACE_PATH_CACHE_LIMIT:
                _WORKSPACE_PATH_CACHE.clear()
            _WORKSPACE_PATH_CACHE[cache_key] = (fingerprint, path)
    return path


def default_state() -> dict[str, Any]:
    s = _service()
    return {
        "version": s.AGENT_REGISTRY_VERSION,
        "updatedAt": s.utc_now_iso(),
        "agents": [],
        "toolPolicies": {
            s.DEFAULT_TOOL_POLICY_ID: s.default_tool_policy(s.DEFAULT_TOOL_POLICY_ID),
        },
        "memoryPolicies": {},
    }


def load_state() -> dict[str, Any]:
    global _LOAD_STATE_CACHE_SIGNATURE, _LOAD_STATE_CACHE_STATE
    s = _service()
    with s._STATE_LOCK:
        before = s._registry_state_signature()
        if _LOAD_STATE_CACHE_STATE is not None and _LOAD_STATE_CACHE_SIGNATURE == before:
            # 缓存保存的是规范化后的快照；返回独立副本，调用方（如 repair）可自由修改。
            return _copy_json_value(_LOAD_STATE_CACHE_STATE)
        path = s.registry_path()
        if not path.exists():
            state = s.default_state()
        else:
            payload = s._load_existing_registry_payload_or_raise(path)
            state = s.default_state()
            state.update(payload)
            state["agents"] = list(state.get("agents") or []) if isinstance(state.get("agents"), list) else []
            state["toolPolicies"] = s._tool_policies(state)
            state["memoryPolicies"] = s._memory_policies(state)
        after = s._registry_state_signature()
        if before == after:
            # 读取期间签名未变，缓存内容与磁盘严格对应；否则放弃本次缓存。
            _LOAD_STATE_CACHE_SIGNATURE = after
            _LOAD_STATE_CACHE_STATE = _copy_json_value(state)
        return state


def repair_agent_directory() -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        state = s.load_state()
        state_signature = s._agent_directory_storage_signature(state)
        changed = False
        s.ensure_agent_shared_workspace()
        available_agent_avatar_filenames = s._available_agent_avatar_filenames()
        normalized_tool_policies = s._tool_policies(state)
        knowledge_steward_result = s._ensure_knowledge_steward_agent(
            state,
            ensure_shared_workspace=False,
            available_avatar_filenames=available_agent_avatar_filenames,
            normalized_tool_policies=normalized_tool_policies,
        )
        if knowledge_steward_result.get("changed"):
            changed = True
        display_name_repaired_agents: list[dict[str, Any]] = []
        avatar_defaulted_agents: list[dict[str, Any]] = []
        territory_repaired_agents: list[dict[str, Any]] = []
        llm_binding_migrated_agents: list[dict[str, Any]] = []
        profile_repaired_agents: list[dict[str, Any]] = []
        tool_policy_repaired_agents: list[tuple[dict[str, Any], dict[str, Any]]] = []
        retired_self_evolution_agents: list[dict[str, Any]] = []
        model_library_ids = s._configured_model_library_ids()
        used_agent_codes: set[str] = set()
        policies = s._memory_policies(state)
        for agent in state.get("agents") or []:
            if not isinstance(agent, dict):
                continue
            if _is_challenge_cup_agent_config_authority(agent):
                # Preserve every Agent-owned configuration field exactly as
                # stored. Keep its existing code reserved only to avoid giving
                # the same code to another Agent later in this repair pass.
                protected_code = s._normalize_agent_code(agent.get("agentCode"))
                if protected_code:
                    used_agent_codes.add(protected_code)
                continue
            llm_migration = s._migrate_agent_llm_bindings_to_new_design(agent)
            if llm_migration.get("changed"):
                llm_binding_migrated_agents.append(
                    {
                        "agentId": str(agent.get("agentId") or "").strip(),
                        "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                        "legacyModelSourceId": str(llm_migration.get("legacyModelSourceId") or "").strip(),
                        "legacyTemplateId": str(llm_migration.get("legacyTemplateId") or "").strip(),
                        "dialogueModelId": str(llm_migration.get("dialogueModelId") or "").strip(),
                        "migrated": bool(llm_migration.get("migrated")),
                    }
                )
                changed = True
            model_ref_repair = s._repair_agent_llm_binding_model_refs(agent, model_library_ids=model_library_ids)
            if model_ref_repair.get("changed"):
                for item in list(model_ref_repair.get("repairs") or []):
                    llm_binding_migrated_agents.append(
                        {
                            "agentId": str(agent.get("agentId") or "").strip(),
                            "agentCode": s._normalize_agent_code(agent.get("agentCode")),
                            "legacyModelId": str(item.get("legacyModelId") or "").strip(),
                            "dialogueModelId": str(s.agent_dialogue_model_id(agent) or "").strip(),
                            "canonicalModelId": str(item.get("canonicalModelId") or "").strip(),
                            "slot": str(item.get("slot") or "").strip(),
                            "migrated": True,
                            "repairKind": "legacy_model_id_alias",
                        }
                    )
                changed = True
            if s._normalize_agent_legacy_metadata_fields(agent):
                changed = True
            if s._ensure_fixed_role_profiles(agent):
                profile_repaired_agents.append(dict(agent))
                changed = True
            territory_changed = False
            if not str(agent.get("primaryMode") or "").strip():
                agent["primaryMode"] = s._infer_agent_primary_mode(agent)
                changed = True
            else:
                normalized_mode = s._normalize_primary_mode(agent.get("primaryMode"))
                if agent.get("primaryMode") != normalized_mode:
                    agent["primaryMode"] = normalized_mode
                    changed = True
            if not str(agent.get("roleKey") or "").strip():
                role_key = s._infer_agent_role_key(agent)
                if role_key:
                    agent["roleKey"] = role_key
                    changed = True
            else:
                normalized_role_key = s._normalize_role_key(agent.get("roleKey"))
                if agent.get("roleKey") != normalized_role_key:
                    agent["roleKey"] = normalized_role_key
                    changed = True
            agent_metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            challenge_cup_agent = bool(
                str(agent_metadata.get("challengeCupTeamId") or "").strip()
            )
            prompt_template_id = s._infer_agent_prompt_template_id(agent)
            current_prompt_template_id = str(agent.get("promptTemplateId") or "").strip()
            if (
                not challenge_cup_agent
                and prompt_template_id
                and s._should_repair_agent_prompt_template_id(
                    current_prompt_template_id,
                    prompt_template_id,
                )
            ):
                agent["promptTemplateId"] = prompt_template_id
                changed = True
            elif current_prompt_template_id:
                normalized_prompt_template_id = s._normalize_prompt_template_id(current_prompt_template_id)
                if agent.get("promptTemplateId") != normalized_prompt_template_id:
                    agent["promptTemplateId"] = normalized_prompt_template_id
                    changed = True
            retired_self_evolution_role = s._retired_self_evolution_role(agent)
            if retired_self_evolution_role and s._archive_retired_self_evolution_agent(agent, retired_self_evolution_role):
                retired_self_evolution_agents.append(dict(agent))
                changed = True
            metadata = dict(agent.get("metadata") or {})
            display_name = str(agent.get("displayName") or "").strip()
            display_name_is_sealed = str(agent.get("status") or "active").strip() == "archived"
            if not display_name_is_sealed and display_name and s._display_name_needs_responsibility_repair(display_name, agent):
                responsibility_name = str(metadata.get("functionalDisplayName") or display_name).strip()
                metadata = s._with_functional_display_name(metadata, responsibility_name)
                agent["displayName"] = s._agent_public_display_name(
                    responsibility_name,
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                metadata = s._mark_display_name_responsibility(metadata, force=True)
                agent["metadata"] = metadata
                display_name_repaired_agents.append(dict(agent))
                changed = True
            elif not display_name_is_sealed and not display_name:
                responsibility_name = str(
                    metadata.get("functionalDisplayName")
                    or agent.get("roleKey")
                    or agent.get("agentCode")
                    or agent.get("agentId")
                    or "Agent"
                ).strip()
                agent["displayName"] = s._agent_public_display_name(
                    responsibility_name,
                    existing_agents=state.get("agents") or [],
                    agent_id=str(agent.get("agentId") or ""),
                    metadata=metadata,
                )
                agent["metadata"] = s._mark_display_name_responsibility(metadata, force=True)
                changed = True
            avatar_result = s._ensure_agent_default_avatar(
                agent,
                available_avatar_filenames=available_agent_avatar_filenames,
            )
            if avatar_result:
                avatar_defaulted_agents.append(dict(agent))
                changed = True
            normalized_code = s._normalize_agent_code(agent.get("agentCode"))
            if normalized_code and normalized_code not in used_agent_codes:
                if agent.get("agentCode") != normalized_code:
                    agent["agentCode"] = normalized_code
                    changed = True
                used_agent_codes.add(normalized_code)
            else:
                agent["agentCode"] = s._next_agent_code(
                    state.get("agents") or [],
                    used_codes=used_agent_codes,
                    exclude_agent_id=str(agent.get("agentId") or ""),
                )
                used_agent_codes.add(str(agent["agentCode"]))
                changed = True
            workspace_path = str(agent.get("workspacePath") or "").strip()
            expected_workspace_path = s._agent_workspace_relative_path(str(agent.get("agentId") or "agent"))
            if not workspace_path or not s._is_agent_private_workspace_path(workspace_path, str(agent.get("agentId") or "")):
                metadata = dict(agent.get("metadata") or {})
                if workspace_path:
                    metadata["legacyWorkspacePath"] = workspace_path
                    agent["metadata"] = metadata
                workspace_path = expected_workspace_path
                agent["workspacePath"] = workspace_path
                changed = True
                territory_changed = True
            s._ensure_agent_workspace(workspace_path, ensure_shared=False)
            memory_policy_id = str(agent.get("memoryPolicyId") or "").strip() or f"memory-{agent.get('agentId')}"
            if str(agent.get("memoryPolicyId") or "").strip() != memory_policy_id:
                agent["memoryPolicyId"] = memory_policy_id
                changed = True
                territory_changed = True
            normalized_policy = s.normalize_memory_policy(
                policies.get(memory_policy_id, {}) if isinstance(policies.get(memory_policy_id), dict) else {},
                memory_policy_id,
                workspace_path,
            ) if memory_policy_id else {}
            if memory_policy_id and policies.get(memory_policy_id) != normalized_policy:
                policies[memory_policy_id] = normalized_policy
                changed = True
                territory_changed = True
            if territory_changed:
                territory_repaired_agents.append(dict(agent))
            if s._ensure_session_agent_tool_policy(
                state,
                agent,
                normalized_tool_policies=normalized_tool_policies,
            ):
                changed = True
            fixed_role_policy = s._ensure_fixed_role_tool_policy(
                state,
                agent,
                normalized_tool_policies=normalized_tool_policies,
            )
            if fixed_role_policy is not None:
                tool_policy_repaired_agents.append((dict(agent), dict(fixed_role_policy)))
                changed = True
            s._refresh_agent_onboarding_metadata(
                state,
                agent,
                normalized_tool_policies=normalized_tool_policies,
                normalized_memory_policies=policies,
            )
        state["memoryPolicies"] = policies
        if changed and s._agent_directory_storage_signature(state) != state_signature:
            s.save_state(state)
            for repaired_agent in display_name_repaired_agents:
                s._record_agent_event("agent.display_name_repaired", repaired_agent)
            if avatar_defaulted_agents:
                s._record_agent_avatar_defaults_event(avatar_defaulted_agents)
            if knowledge_steward_result.get("changed"):
                s._record_knowledge_steward_repaired_event(
                    knowledge_steward_result.get("agent") or {},
                    created=bool(knowledge_steward_result.get("created")),
                    repaired_fields=list(knowledge_steward_result.get("repairedFields") or []),
                )
            if llm_binding_migrated_agents:
                s._record_agent_llm_binding_migration_event(llm_binding_migrated_agents)
            for repaired_agent in profile_repaired_agents:
                s._record_agent_event("agent.profile_repaired", repaired_agent)
            for repaired_agent, repaired_policy in tool_policy_repaired_agents:
                s._record_agent_tool_policy_event(repaired_agent, repaired_policy)
            for repaired_agent in territory_repaired_agents:
                s._record_agent_territory_event("agent_territory.resolved", repaired_agent, outcome="repaired")
            for retired_agent in retired_self_evolution_agents:
                s._record_agent_event("agent.self_evolution_retired_role.archived", retired_agent, lifecycle=True)
        return state


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    s = _service()
    with s._STATE_LOCK:
        payload = s._build_agent_registry_payload_for_storage(state)
        s._guard_against_suspicious_registry_shrink(payload)
        s._atomic_write_json(s.registry_path(), payload)
        s._invalidate_repaired_state_cache()
        return payload
