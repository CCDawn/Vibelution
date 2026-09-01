"""LLM-backed research agents for theme discovery."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any, Callable, Iterable

from langchain_core.messages import ToolMessage

from core.infrastructure.workspace_manager import get_workspace
from core.infrastructure.llm_utils import build_cacheable_system_message
from core.llm import LLMInvocationContext, get_llm_client, invoke_llm
from core.llm.agent_runtime import AgentLlmResolutionError, resolve_agent_llm
from config.settings import get_config
from core.web.services import agent_directory_service, agent_mode_binding_service, prompt_template_service

from .models import (
    CandidateTheme,
    EvidenceRecord,
    ResearchDiscoverySession,
    ResearchSource,
    ThemeCard,
    new_id,
    utcnow_iso,
)
from .providers import ResearchSearchProvider, SearchResult, stable_evidence_id
from .scoring import calculate_recommendation_score

TraceSink = Callable[[dict[str, Any]], None]


@dataclass
class AgentSearchResult:
    results: list[SearchResult] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentEvidenceResult:
    evidence: list[EvidenceRecord] = field(default_factory=list)
    missing_evidence_requests: list[str] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentThemeResult:
    themes: list[CandidateTheme] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCardResult:
    card: ThemeCard | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)
    profile: dict[str, Any] = field(default_factory=dict)


class ResearchAgentRunner:
    def run_search(
        self,
        *,
        phase: str,
        session: ResearchDiscoverySession,
        suggested_queries: list[str],
        existing_sources: list[ResearchSource],
        knowledge_context: dict[str, Any] | None = None,
        trace_sink: TraceSink | None = None,
    ) -> AgentSearchResult:
        raise NotImplementedError

    def extract_evidence(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        existing_evidence: list[EvidenceRecord],
        trace_sink: TraceSink | None = None,
    ) -> AgentEvidenceResult:
        raise NotImplementedError

    def generate_themes(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        evidence: list[EvidenceRecord],
        parent_run_id: str,
        trace_sink: TraceSink | None = None,
    ) -> AgentThemeResult:
        raise NotImplementedError

    def generate_card(
        self,
        *,
        session: ResearchDiscoverySession,
        theme: CandidateTheme,
        sources: list[ResearchSource],
        version: int,
        trace_sink: TraceSink | None = None,
    ) -> AgentCardResult:
        raise NotImplementedError


class LLMResearchAgentRunner(ResearchAgentRunner):
    """Run research stages through configured LLM agents and explicit search tools."""

    def __init__(self, *, search_provider: ResearchSearchProvider):
        self.search_provider = search_provider

    def run_search(
        self,
        *,
        phase: str,
        session: ResearchDiscoverySession,
        suggested_queries: list[str],
        existing_sources: list[ResearchSource],
        knowledge_context: dict[str, Any] | None = None,
        trace_sink: TraceSink | None = None,
    ) -> AgentSearchResult:
        agent_key = "broad" if phase == "broad" else "deep"
        profile = self._agent_profile(agent_key)
        collected: list[SearchResult] = []
        attempts: list[dict[str, Any]] = []
        trace: list[dict[str, Any]] = []
        resolved_llm = _resolve_research_agent_llm(profile)
        profile_id = resolved_llm["profileId"]
        _append_trace(
            trace,
            _trace(
                "agent",
                f"{profile.get('label') or agent_key} 启动",
                f"使用 LLM `{resolved_llm['label']}`，准备围绕 {len(suggested_queries)} 个建议查询进行工具检索。",
            ),
            trace_sink,
        )
        _append_trace(
            trace,
            _trace("prompt", "读取阶段提示词", f"载入 `{profile.get('promptFilename') or ''}`，并附加结构化 JSON 输出契约。"),
            trace_sink,
        )
        _append_trace(trace, _trace("plan", "准备搜索种子", " / ".join(suggested_queries[:4])), trace_sink)
        tools = _search_tools()
        messages: list[Any] = [
            build_cacheable_system_message(self._system_prompt(agent_key, _search_output_contract())),
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": f"Run the {phase} research-search agent. You must call search tools before final JSON.",
                        "openGoal": session.open_goal,
                        "constraints": session.constraints,
                        "preferences": session.preferences,
                        "suggestedQueries": suggested_queries,
                        "existingSources": [_source_context(item) for item in existing_sources[:16]],
                        "knowledgeContext": knowledge_context or {},
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        client = resolved_llm["client"]
        final_payload: dict[str, Any] | None = None
        tool_call_count = 0
        cache_partition = _research_prompt_cache_partition(session.session_id, agent_key, phase)
        for _turn in range(6):
            response = invoke_llm(
                client,
                messages,
                tools=tools,
                context=LLMInvocationContext(
                    surface="research_agent",
                    run_kind="research_search",
                    session_id=session.session_id,
                    agent_id=agent_key,
                    llm_slot="dialogue",
                    cache_scope="research",
                    cache_partition=cache_partition,
                    prompt_purpose=phase,
                    conversation_bound=False,
                    metadata={"phase": phase},
                ),
                metadata={"researchAgent": agent_key},
            )
            calls = list(getattr(response, "tool_calls", []) or [])
            messages.append(response)
            if calls:
                tool_call_count += len(calls)
                _append_trace(trace, _trace("agent", "Agent 请求调用搜索工具", f"本轮提出 {len(calls)} 个工具调用。"), trace_sink)
                for call in calls:
                    tool_name = str(call.get("name") or "").strip()
                    args = call.get("args") if isinstance(call.get("args"), dict) else {}
                    query = str(args.get("query") or "").strip()
                    _append_trace(trace, _trace("tool", f"调用 {tool_name}", query or "缺少 query"), trace_sink)
                    results, attempt = self._execute_search_tool(tool_name, args)
                    collected.extend(results)
                    attempts.append(attempt)
                    _append_trace(
                        trace,
                        _trace(
                            "observation",
                            f"{tool_name} 返回 {len(results)} 条结果",
                            _attempt_summary(attempt),
                        ),
                        trace_sink,
                    )
                    messages.append(
                        ToolMessage(
                            content=json.dumps([_search_result_dict(item) for item in results], ensure_ascii=False),
                            tool_call_id=str(call.get("id") or tool_name),
                        )
                    )
                continue
            final_payload = _extract_json_object(str(getattr(response, "content", "") or ""))
            _append_trace(trace, _trace("agent", "Agent 输出阶段总结", _compact_json(final_payload)), trace_sink)
            break
        if tool_call_count <= 0:
            raise ValueError(f"{agent_key} agent did not call any search tools.")
        if not collected:
            raise ValueError(f"{agent_key} agent completed without usable search results.")
        return AgentSearchResult(
            results=_dedupe_search_results(collected),
            attempts=attempts,
            profile={
                "agentKey": agent_key,
                "templateId": profile["templateId"],
                "profileId": profile_id,
                "llmModelId": resolved_llm.get("modelId", ""),
                "llmBindingSource": resolved_llm.get("source", ""),
                "toolCallCount": tool_call_count,
                "final": final_payload or {},
                "executionMode": "llm_agent_with_search_tools",
                "knowledgeContextDecision": (knowledge_context or {}).get("decision") or "",
                "trace": trace,
            },
            trace=trace,
        )

    def extract_evidence(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        existing_evidence: list[EvidenceRecord],
        trace_sink: TraceSink | None = None,
    ) -> AgentEvidenceResult:
        payload, trace, profile = self._invoke_json_agent(
            "review",
            {
                "sessionId": session.session_id,
                "task": "Review sources and extract evidence records. Return JSON only.",
                "openGoal": session.open_goal,
                "constraints": session.constraints,
                "preferences": session.preferences,
                "sources": [_source_context(item) for item in sources],
                "existingEvidence": [item.to_dict() for item in existing_evidence],
            },
            _evidence_output_contract(),
            trace_sink=trace_sink,
        )
        items = payload.get("evidence") if isinstance(payload.get("evidence"), list) else []
        missing_requests = _string_list(payload.get("missingEvidenceRequests") or payload.get("missing_evidence_requests"))
        evidence: list[EvidenceRecord] = []
        known = {item.evidence_id for item in existing_evidence}
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("sourceId") or item.get("source_id") or "").strip()
            if not source_id:
                continue
            evidence_type = _choice(item.get("evidenceType") or item.get("evidence_type"), "background", _EVIDENCE_TYPES)
            evidence_id = str(item.get("evidenceId") or item.get("evidence_id") or "").strip()
            if not evidence_id:
                evidence_id = stable_evidence_id(source_id, f"{evidence_type}-{index}")
            if evidence_id in known:
                continue
            evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    session_id=session.session_id,
                    source_id=source_id,
                    claim=str(item.get("claim") or "").strip(),
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    confidence=_choice(item.get("confidence"), "medium", {"high", "medium", "low"}),  # type: ignore[arg-type]
                    note=str(item.get("note") or "").strip(),
                )
            )
            known.add(evidence_id)
        if not evidence:
            raise ValueError("review agent returned no usable evidence records.")
        final_evidence = [*existing_evidence, *evidence]
        _append_trace(trace, _trace("observation", "写入证据记录", f"新增 {len(evidence)} 条证据，当前共 {len(final_evidence)} 条。"), trace_sink)
        if missing_requests:
            _append_trace(
                trace,
                _trace("agent", "发现缺失证据请求", " / ".join(missing_requests[:5])),
                trace_sink,
            )
        profile["missingEvidenceRequests"] = missing_requests
        return AgentEvidenceResult(
            evidence=final_evidence,
            missing_evidence_requests=missing_requests,
            trace=trace,
            profile=profile,
        )

    def generate_themes(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        evidence: list[EvidenceRecord],
        parent_run_id: str,
        trace_sink: TraceSink | None = None,
    ) -> AgentThemeResult:
        payload, trace, profile = self._invoke_json_agent(
            "themes",
            {
                "sessionId": session.session_id,
                "task": f"Generate {session.candidate_count} candidate themes. Return JSON only.",
                "openGoal": session.open_goal,
                "constraints": session.constraints,
                "preferences": session.preferences,
                "sources": [_source_context(item) for item in sources[:40]],
                "evidence": [item.to_dict() for item in evidence[:80]],
            },
            _themes_output_contract(),
            trace_sink=trace_sink,
        )
        raw_themes = payload.get("themes") if isinstance(payload.get("themes"), list) else []
        themes: list[CandidateTheme] = []
        source_ids = {item.source_id for item in sources}
        evidence_ids = {item.evidence_id for item in evidence}
        for item in raw_themes:
            if not isinstance(item, dict):
                continue
            scores = _scores(item.get("scores"))
            recommendation = calculate_recommendation_score(scores)
            themes.append(
                CandidateTheme(
                    theme_id=new_id("theme"),
                    session_id=session.session_id,
                    title=str(item.get("title") or "").strip(),
                    one_line=str(item.get("oneLine") or item.get("one_line") or "").strip(),
                    interdisciplinary_combination=_string_list(
                        item.get("interdisciplinaryCombination") or item.get("interdisciplinary_combination")
                    ),
                    core_question=str(item.get("coreQuestion") or item.get("core_question") or "").strip(),
                    novelty_path=_choice(
                        item.get("noveltyPath") or item.get("novelty_path"),
                        "problem_perspective",
                        _NOVELTY_PATHS,
                    ),  # type: ignore[arg-type]
                    scores=scores,
                    recommendation_score=recommendation,
                    source_ids=[value for value in _string_list(item.get("sourceIds") or item.get("source_ids")) if value in source_ids],
                    evidence_ids=[
                        value for value in _string_list(item.get("evidenceIds") or item.get("evidence_ids")) if value in evidence_ids
                    ],
                    uncertainty=str(item.get("uncertainty") or "").strip(),
                    agent_review=str(item.get("agentReview") or item.get("agent_review") or "").strip(),
                    status="draft",
                    version=1,
                    parent_run_id=parent_run_id,
                )
            )
        if not themes:
            raise ValueError("themes agent returned no usable candidate themes.")
        _append_trace(trace, _trace("observation", "生成候选主题", f"Agent 返回 {len(themes)} 个可入库主题。"), trace_sink)
        return AgentThemeResult(themes=themes, trace=trace, profile=profile)

    def generate_card(
        self,
        *,
        session: ResearchDiscoverySession,
        theme: CandidateTheme,
        sources: list[ResearchSource],
        version: int,
        trace_sink: TraceSink | None = None,
    ) -> AgentCardResult:
        payload, trace, profile = self._invoke_json_agent(
            "card",
            {
                "sessionId": session.session_id,
                "task": "Create a concept-level research theme card. Return JSON only.",
                "openGoal": session.open_goal,
                "constraints": session.constraints,
                "preferences": session.preferences,
                "theme": theme.to_dict(),
                "sources": [_source_context(item) for item in sources[:30]],
            },
            _card_output_contract(),
            trace_sink=trace_sink,
        )
        card = ThemeCard(
            card_id=new_id("theme-card"),
            session_id=session.session_id,
            theme_id=theme.theme_id,
            title=str(payload.get("title") or theme.title).strip(),
            one_line=str(payload.get("oneLine") or payload.get("one_line") or theme.one_line).strip(),
            core_scientific_question=str(
                payload.get("coreScientificQuestion") or payload.get("core_scientific_question") or theme.core_question
            ).strip(),
            why_novel=str(payload.get("whyNovel") or payload.get("why_novel") or "").strip(),
            why_competition_fit=str(payload.get("whyCompetitionFit") or payload.get("why_competition_fit") or "").strip(),
            interdisciplinary_combination=_string_list(
                payload.get("interdisciplinaryCombination") or payload.get("interdisciplinary_combination")
            )
            or theme.interdisciplinary_combination,
            possible_datasets=_string_list(payload.get("possibleDatasets") or payload.get("possible_datasets")),
            possible_methods=_string_list(payload.get("possibleMethods") or payload.get("possible_methods")),
            possible_experiments=_string_list(payload.get("possibleExperiments") or payload.get("possible_experiments")),
            risks=_string_list(payload.get("risks")),
            references=_string_list(payload.get("references")),
            next_research_steps=_string_list(payload.get("nextResearchSteps") or payload.get("next_research_steps")),
            agent_review=str(payload.get("agentReview") or payload.get("agent_review") or "").strip(),
            status="draft",
            version=version,
        )
        _append_trace(trace, _trace("observation", "生成主题卡", f"主题卡 `{card.title}` v{card.version} 已生成。"), trace_sink)
        return AgentCardResult(card=card, trace=trace, profile=profile)

    def _invoke_json_agent(
        self,
        agent_key: str,
        payload: dict[str, Any],
        contract: str,
        *,
        trace_sink: TraceSink | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
        profile = self._agent_profile(agent_key)
        resolved_llm = _resolve_research_agent_llm(profile)
        profile_id = resolved_llm["profileId"]
        trace: list[dict[str, Any]] = []
        _append_trace(
            trace,
            _trace("agent", f"{profile.get('label') or agent_key} 启动", f"使用 LLM `{resolved_llm['label']}`。"),
            trace_sink,
        )
        _append_trace(trace, _trace("prompt", "读取阶段提示词", f"载入 `{profile.get('promptFilename') or ''}`，并附加结构化 JSON 输出契约。"), trace_sink)
        _append_trace(trace, _trace("input", "整理阶段输入", _payload_summary(payload)), trace_sink)
        client = resolved_llm["client"]
        session_id = str(payload.get("sessionId") or "").strip()
        cache_partition = _research_prompt_cache_partition(session_id, agent_key, "json")
        response = invoke_llm(
            client,
            [
                build_cacheable_system_message(self._system_prompt(agent_key, contract)),
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            context=LLMInvocationContext(
                surface="research_agent",
                run_kind="research_json",
                session_id=session_id,
                agent_id=agent_key,
                llm_slot="dialogue",
                cache_scope="research",
                cache_partition=cache_partition,
                prompt_purpose="json",
                conversation_bound=False,
            ),
            metadata={"researchAgent": agent_key},
        )
        result = _extract_json_object(str(getattr(response, "content", "") or ""))
        _append_trace(trace, _trace("agent", "Agent 输出结构化结果", _compact_json(result)), trace_sink)
        return result, trace, {
            "agentKey": agent_key,
            "templateId": profile["templateId"],
            "profileId": profile_id,
            "llmModelId": resolved_llm.get("modelId", ""),
            "llmBindingSource": resolved_llm.get("source", ""),
            "executionMode": "llm_agent_structured_json",
            "trace": trace,
        }

    def _execute_search_tool(self, tool_name: str, args: dict[str, Any]) -> tuple[list[SearchResult], dict[str, Any]]:
        query = str(args.get("query") or "").strip()
        if not query:
            return [], {"kind": tool_name, "query": "", "status": "failed", "resultCount": 0, "durationMs": 0, "error": "query is required"}
        method_by_tool = {
            "research_search_papers": ("paper", self.search_provider.search_papers),
            "research_search_github": ("github", self.search_provider.search_github),
            "research_search_datasets": ("dataset", self.search_provider.search_datasets),
            "research_search_web": ("web", self.search_provider.search_web),
        }
        if tool_name not in method_by_tool:
            return [], {"kind": tool_name, "query": query, "status": "failed", "resultCount": 0, "durationMs": 0, "error": "unknown tool"}
        kind, method = method_by_tool[tool_name]
        started = monotonic()
        try:
            results = method(query)
        except ValueError:
            raise
        except Exception as exc:
            return [], {
                "kind": kind,
                "query": query,
                "status": "failed",
                "resultCount": 0,
                "durationMs": round((monotonic() - started) * 1000),
                "error": str(exc)[:500],
            }
        return results, {
            "kind": kind,
            "query": query,
            "status": "completed",
            "resultCount": len(results),
            "durationMs": round((monotonic() - started) * 1000),
            "error": "",
        }

    def _agent_profile(self, agent_key: str) -> dict[str, Any]:
        workspace = get_workspace()
        mode_bound_agent = self._mode_bound_agent_profile(agent_key, workspace)
        if mode_bound_agent:
            return mode_bound_agent
        project_root = _workspace_project_root(workspace)
        matches: list[dict[str, Any]] = []
        expected_role = f"research_{agent_key}"
        for agent in agent_directory_service.list_agents(
            include_archived=False,
            detail="full",
            project_root=project_root,
        ):
            metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            if str(metadata.get("challengeCupTeamId") or "").strip():
                continue
            research_key = str(metadata.get("researchAgentKey") or "").strip()
            role_key = str(agent.get("roleKey") or "").strip()
            if research_key == agent_key or role_key == expected_role:
                matches.append(agent)
        if len(matches) > 1:
            raise ValueError(
                f"Research AgentDirectory binding is duplicated: {agent_key}"
            )
        if matches:
            return _profile_from_agent_instance(agent_key, matches[0])
        raise ValueError(f"Unknown research agent: {agent_key}")

    def _mode_bound_agent_profile(self, agent_key: str, workspace: Any) -> dict[str, Any] | None:
        project_root = _workspace_project_root(workspace)
        if project_root is None:
            return None
        payload = agent_mode_binding_service.get_mode_bindings_payload(project_root=project_root)
        research_mode = (payload.get("modes") or {}).get("research") or {}
        agent_id = str((research_mode.get("flowBindings") or {}).get(agent_key) or "").strip()
        if not agent_id and agent_key in {"broad", "deep", "review", "themes", "card"}:
            role_key = f"research_{agent_key}"
            for candidate_id in list(research_mode.get("pool") or []):
                candidate = agent_directory_service.get_agent(
                    str(candidate_id or ""),
                    include_archived=False,
                    project_root=project_root,
                )
                if candidate and str(candidate.get("roleKey") or "").strip() == role_key:
                    agent_id = str(candidate.get("agentId") or "").strip()
                    break
        if not agent_id:
            return None
        agent = agent_directory_service.get_agent(agent_id, include_archived=False, project_root=project_root)
        if not agent:
            return None
        return _profile_from_agent_instance(agent_key, agent)

    def _system_prompt(self, agent_key: str, contract: str) -> str:
        workspace = get_workspace()
        profile = self._agent_profile(agent_key)
        prompt_template_id = str(profile.get("promptTemplateId") or "").strip()
        if prompt_template_id:
            project_root = _workspace_project_root(workspace)
            template = prompt_template_service.get_prompt_template(
                prompt_template_id,
                project_root=project_root,
            )
            if not template:
                raise ValueError(f"Research agent {agent_key} prompt template not found: {prompt_template_id}")
            prompt = str(template.get("content") or "")
            if not prompt.strip():
                raise ValueError(f"Research agent {agent_key} prompt template is empty: {prompt_template_id}")
            return f"{prompt.strip()}\n\n{contract.strip()}\n\nReturn valid JSON only. Do not wrap it in Markdown."
        filename = str(profile.get("promptFilename") or "").strip()
        if not filename:
            raise ValueError(f"Research agent {agent_key} has no prompt file configured.")
        prompt = workspace.read_research_prompt(filename)
        return f"{prompt.strip()}\n\n{contract.strip()}\n\nReturn valid JSON only. Do not wrap it in Markdown."

    def _resolve_agent_instance_profile(self, profile: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(profile.get("agentId") or profile.get("agentInstanceId") or "").strip()
        if not agent_id:
            return profile
        project_root = _workspace_project_root(get_workspace())
        agent = agent_directory_service.get_agent(agent_id, include_archived=False, project_root=project_root)
        if not agent:
            return profile
        resolved = dict(profile)
        resolved.update(_profile_from_agent_instance(str(profile.get("key") or ""), agent))
        return resolved


def _research_agent_profile_id(profile: dict[str, Any]) -> str:
    """Resolve the runtime LLM profile from the unified Agent profile shape."""

    return str(profile.get("profileId") or profile.get("llmConfigId") or "primary").strip() or "primary"


def _research_prompt_cache_partition(session_id: str, agent_key: str, phase: str) -> str:
    parts = [
        "research",
        str(session_id or "session").strip() or "session",
        str(agent_key or "agent").strip() or "agent",
        str(phase or "stage").strip() or "stage",
    ]
    return ":".join(parts)


def _resolve_research_agent_llm(profile: dict[str, Any]) -> dict[str, Any]:
    agent = profile.get("agent") if isinstance(profile.get("agent"), dict) else None
    if isinstance(agent, dict) and agent_directory_service.agent_dialogue_model_id(agent):
        try:
            resolved = resolve_agent_llm(agent, "dialogue", config=get_config())
        except AgentLlmResolutionError as exc:
            raise ValueError(f"Research Agent LLM binding is invalid: {exc}") from exc
        return {
            "client": get_llm_client(profile_id=resolved.runtime_profile_id, config=resolved.config),
            "profileId": resolved.runtime_profile_id,
            "modelId": resolved.model_id,
            "label": resolved.model_id or resolved.model,
            "source": resolved.source,
            "resolved": resolved,
        }
    profile_id = _research_agent_profile_id(profile)
    return {
        "client": get_llm_client(profile_id=profile_id),
        "profileId": profile_id,
        "modelId": "",
        "label": profile_id,
        "source": "legacy_profile",
        "resolved": None,
    }


def _profile_from_agent_instance(agent_key: str, agent: dict[str, Any]) -> dict[str, Any]:
    normalized_agent_key = str(agent_key or "").strip()
    metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
    template_id = str(agent.get("templateId") or metadata.get("researchTemplateId") or "").strip()
    prompt_filename = str(metadata.get("researchPromptFilename") or "").strip()
    return {
        "key": normalized_agent_key or str(metadata.get("researchAgentKey") or "").strip(),
        "label": str(agent.get("displayName") or normalized_agent_key or "").strip(),
        "promptFilename": prompt_filename,
        "templateId": template_id,
        "profileId": str(metadata.get("researchProfileId") or "").strip(),
        "enabled": str(agent.get("status") or "active").strip() != "archived",
        "agentId": str(agent.get("agentId") or "").strip(),
        "agentInstanceId": str(agent.get("agentId") or "").strip(),
        "agentCode": str(agent.get("agentCode") or "").strip(),
        "roleKey": str(agent.get("roleKey") or "").strip(),
        "primaryMode": str(agent.get("primaryMode") or "").strip(),
        "promptTemplateId": str(agent.get("promptTemplateId") or "").strip(),
        "agentDisplayName": str(agent.get("displayName") or "").strip(),
        "llmBindings": agent_directory_service.normalize_agent_llm_bindings(agent.get("llmBindings")),
        "agent": agent,
    }


def _workspace_project_root(workspace: Any) -> Path | None:
    for attr in ("project_root",):
        value = getattr(workspace, attr, None)
        if value:
            try:
                return Path(value).resolve()
            except OSError:
                return None
    root = getattr(workspace, "root", None)
    if root:
        try:
            root_path = Path(root).resolve()
        except OSError:
            return None
        if root_path.name == "workspace":
            return root_path.parent
        return root_path
    return None


class DeterministicResearchAgentRunner(ResearchAgentRunner):
    """Explicit test double; not used by production defaults."""

    def __init__(self, *, search_provider: ResearchSearchProvider):
        self.search_provider = search_provider

    def run_search(
        self,
        *,
        phase: str,
        session: ResearchDiscoverySession,
        suggested_queries: list[str],
        existing_sources: list[ResearchSource],
        knowledge_context: dict[str, Any] | None = None,
        trace_sink: TraceSink | None = None,
    ) -> AgentSearchResult:
        results: list[SearchResult] = []
        attempts: list[dict[str, Any]] = []
        for query in suggested_queries:
            for kind, method in [
                ("paper", self.search_provider.search_papers),
                ("github", self.search_provider.search_github),
                ("dataset", self.search_provider.search_datasets),
                ("web", self.search_provider.search_web),
            ]:
                started = monotonic()
                items = method(query)
                results.extend(items)
                attempts.append(
                    {
                        "kind": kind,
                        "query": query,
                        "status": "completed",
                        "resultCount": len(items),
                        "durationMs": round((monotonic() - started) * 1000),
                        "error": "",
                    }
                )
        trace = [
            _trace("agent", f"测试 {phase} 搜索 agent 启动", "使用 deterministic test double。"),
            _trace("tool", "执行测试搜索工具", f"对 {len(suggested_queries)} 个查询调用 paper/github/dataset/web 搜索。"),
            _trace("observation", "测试搜索完成", f"得到 {len(results)} 条搜索结果。"),
        ]
        for item in trace:
            if trace_sink:
                trace_sink(item)
        return AgentSearchResult(
            results=results,
            attempts=attempts,
            profile={
                "executionMode": "deterministic_test_double",
                "agentKey": "broad" if phase == "broad" else "deep",
                "knowledgeContextDecision": (knowledge_context or {}).get("decision") or "",
                "trace": trace,
            },
            trace=trace,
        )

    def extract_evidence(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        existing_evidence: list[EvidenceRecord],
        trace_sink: TraceSink | None = None,
    ) -> AgentEvidenceResult:
        known_ids = {item.evidence_id for item in existing_evidence}
        evidence = list(existing_evidence)
        for source in sources:
            evidence_type = {"paper": "gap", "dataset": "dataset", "github": "implementation"}.get(source.kind, "background")
            evidence_id = stable_evidence_id(source.source_id, evidence_type)
            if evidence_id in known_ids:
                continue
            evidence.append(
                EvidenceRecord(
                    evidence_id=evidence_id,
                    session_id=session.session_id,
                    source_id=source.source_id,
                    claim=f"{source.title} provides {evidence_type} evidence for AI Scientist theme discovery.",
                    evidence_type=evidence_type,  # type: ignore[arg-type]
                    confidence="medium",
                    note="Deterministic test evidence.",
                )
            )
            known_ids.add(evidence_id)
        trace = [
            _trace("agent", "测试审查 agent 启动", "使用 deterministic test double。"),
            _trace("observation", "生成测试证据", f"当前共 {len(evidence)} 条证据。"),
        ]
        for item in trace:
            if trace_sink:
                trace_sink(item)
        return AgentEvidenceResult(
            evidence=evidence,
            missing_evidence_requests=[],
            trace=trace,
            profile={
                "agentKey": "review",
                "executionMode": "deterministic_test_double",
                "trace": trace,
                "missingEvidenceRequests": [],
            },
        )

    def generate_themes(
        self,
        *,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        evidence: list[EvidenceRecord],
        parent_run_id: str,
        trace_sink: TraceSink | None = None,
    ) -> AgentThemeResult:
        source_ids = [item.source_id for item in sources[:8]]
        evidence_ids = [item.evidence_id for item in evidence[:12]]
        themes: list[CandidateTheme] = []
        variants = [
            (
                "mechanism-gap discovery",
                "Can an AI Scientist agent identify under-specified mechanisms from public scientific evidence?",
                ["computer science", "science of science", "causal reasoning"],
            ),
            (
                "causal falsifiability review",
                "Can causal constraints reduce speculative hypotheses in agent-generated research plans?",
                ["computer science", "causal science", "research methodology"],
            ),
            (
                "open-source reproducibility mining",
                "Can repository failures reveal scientific questions that improve agent implementation ability?",
                ["computer science", "software engineering", "open science"],
            ),
            (
                "dataset-absence opportunity detection",
                "Can missing datasets distinguish under-studied problems from shallow search coverage?",
                ["computer science", "data-centric AI", "scientometrics"],
            ),
            (
                "metacognitive uncertainty control",
                "Can metacognitive review signals help agents reject weakly evidenced research themes?",
                ["computer science", "cognitive neuroscience", "metacognition"],
            ),
        ]
        for index in range(session.candidate_count):
            label, question, disciplines = variants[index % len(variants)]
            scores = {
                "noveltyGap": 88 - index,
                "scientificValue": 84 - index,
                "technicalDepth": 82 - index,
                "interdisciplinaryAuthenticity": 86 - index,
                "verifiability": 80 - index,
                "competitionFit": 90 - index,
                "implementationFeasibility": 78 - index,
            }
            themes.append(
                CandidateTheme(
                    theme_id=new_id("theme"),
                    session_id=session.session_id,
                    title=f"Agent-generated test theme {index + 1}: {label}",
                    one_line=f"A deterministic test double theme about {label}.",
                    interdisciplinary_combination=disciplines,
                    core_question=question,
                    novelty_path="problem_perspective",
                    scores=scores,
                    recommendation_score=calculate_recommendation_score(scores),
                    source_ids=source_ids,
                    evidence_ids=evidence_ids,
                    uncertainty="Deterministic test uncertainty.",
                    agent_review="Generated by explicit test double.",
                    status="draft",
                    version=1,
                    parent_run_id=parent_run_id,
                )
            )
        trace = [
            _trace("agent", "测试主题生成 agent 启动", "使用 deterministic test double。"),
            _trace("observation", "生成测试主题", f"返回 {len(themes)} 个候选主题。"),
        ]
        for item in trace:
            if trace_sink:
                trace_sink(item)
        return AgentThemeResult(
            themes=themes,
            trace=trace,
            profile={"agentKey": "themes", "executionMode": "deterministic_test_double", "trace": trace},
        )

    def generate_card(
        self,
        *,
        session: ResearchDiscoverySession,
        theme: CandidateTheme,
        sources: list[ResearchSource],
        version: int,
        trace_sink: TraceSink | None = None,
    ) -> AgentCardResult:
        card = ThemeCard(
            card_id=new_id("theme-card"),
            session_id=session.session_id,
            theme_id=theme.theme_id,
            title=theme.title,
            one_line=theme.one_line,
            core_scientific_question=theme.core_question,
            why_novel="Generated by explicit test double for a novelty-first AI Scientist workflow.",
            why_competition_fit="Fits AI Scientist because it uses an agentic research workflow with evidence provenance.",
            interdisciplinary_combination=theme.interdisciplinary_combination,
            possible_datasets=["Public sources collected during test search"],
            possible_methods=["Agentic source synthesis", "Evidence review", "Theme scoring"],
            possible_experiments=["Compare selected themes against baseline search outputs"],
            risks=["Test double output is not production research evidence."],
            references=[f"{source.title} - {source.url}" for source in sources[:5]],
            next_research_steps=["Run the production LLM research agents."],
            agent_review=theme.agent_review,
            status="draft",
            version=version,
        )
        trace = [
            _trace("agent", "测试主题卡 agent 启动", "使用 deterministic test double。"),
            _trace("observation", "生成测试主题卡", f"主题卡 `{card.title}` v{card.version} 已生成。"),
        ]
        for item in trace:
            if trace_sink:
                trace_sink(item)
        return AgentCardResult(
            card=card,
            trace=trace,
            profile={"agentKey": "card", "executionMode": "deterministic_test_double", "trace": trace},
        )


def _search_tools() -> list[dict[str, Any]]:
    return [
        _tool_schema("research_search_papers", "Search public scholarly papers for a query."),
        _tool_schema("research_search_github", "Search GitHub repositories for a query."),
        _tool_schema("research_search_datasets", "Search public datasets for a query."),
        _tool_schema("research_search_web", "Search the public web for a query."),
    ]


def _tool_schema(name: str, description: str) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query."}},
                "required": ["query"],
            },
        },
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Research agent did not return valid JSON.")
        payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Research agent JSON must be an object.")
    return payload


def _search_result_dict(item: SearchResult) -> dict[str, Any]:
    return {
        "kind": item.kind,
        "title": item.title,
        "url": item.url,
        "snippet": item.snippet,
        "reliability": item.reliability,
    }


def _source_context(item: ResearchSource) -> dict[str, Any]:
    return {
        "sourceId": item.source_id,
        "kind": item.kind,
        "title": item.title,
        "url": item.url,
        "snippet": item.snippet,
        "reliability": item.reliability,
    }


def _dedupe_search_results(items: Iterable[SearchResult]) -> list[SearchResult]:
    deduped: dict[tuple[str, str], SearchResult] = {}
    for item in items:
        if item.url:
            deduped[(item.kind, item.url)] = item
    return list(deduped.values())


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item or "").strip()]
    if str(value or "").strip():
        return [str(value).strip()]
    return []


def _choice(value: Any, fallback: str, allowed: set[str]) -> str:
    normalized = str(value or "").strip()
    return normalized if normalized in allowed else fallback


def _scores(value: Any) -> dict[str, float]:
    raw = value if isinstance(value, dict) else {}
    keys = [
        "noveltyGap",
        "scientificValue",
        "technicalDepth",
        "interdisciplinaryAuthenticity",
        "verifiability",
        "competitionFit",
        "implementationFeasibility",
    ]
    return {key: _score(raw.get(key), 70.0) for key in keys}


def _score(value: Any, fallback: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(100.0, parsed))


def _search_output_contract() -> str:
    return """Output schema:
{"summary":"string","observations":["string"],"warnings":["string"],"nextQueries":["string"]}"""


def _evidence_output_contract() -> str:
    return """Output schema:
{"evidence":[{"sourceId":"existing source id","claim":"string","evidenceType":"method|dataset|result|gap|implementation|background","confidence":"high|medium|low","note":"string"}],"missingEvidenceRequests":["specific follow-up search question when evidence is insufficient"]}"""


def _themes_output_contract() -> str:
    return """Output schema:
{"themes":[{"title":"string","oneLine":"string","interdisciplinaryCombination":["string"],"coreQuestion":"string","noveltyPath":"problem_perspective|method_transfer|discipline_combination|application_scenario","scores":{"noveltyGap":0,"scientificValue":0,"technicalDepth":0,"interdisciplinaryAuthenticity":0,"verifiability":0,"competitionFit":0,"implementationFeasibility":0},"sourceIds":["existing source id"],"evidenceIds":["existing evidence id"],"uncertainty":"string","agentReview":"string"}]}"""


def _card_output_contract() -> str:
    return """Output schema:
{"title":"string","oneLine":"string","coreScientificQuestion":"string","whyNovel":"string","whyCompetitionFit":"string","interdisciplinaryCombination":["string"],"possibleDatasets":["string"],"possibleMethods":["string"],"possibleExperiments":["string"],"risks":["string"],"references":["string"],"nextResearchSteps":["string"],"agentReview":"string"}"""


def _trace(kind: str, title: str, detail: str = "") -> dict[str, Any]:
    return {
        "kind": str(kind or "agent"),
        "title": str(title or "").strip()[:180],
        "detail": str(detail or "").strip()[:1200],
        "timestamp": utcnow_iso(),
    }


def _append_trace(trace: list[dict[str, Any]], item: dict[str, Any], trace_sink: TraceSink | None = None) -> None:
    trace.append(item)
    if trace_sink:
        trace_sink(item)


def _attempt_summary(attempt: dict[str, Any]) -> str:
    status = str(attempt.get("status") or "unknown")
    count = attempt.get("resultCount", 0)
    query = str(attempt.get("query") or "").strip()
    error = str(attempt.get("error") or "").strip()
    text = f"status={status}; resultCount={count}; query={query}"
    if error:
        text = f"{text}; error={error}"
    return text


def _compact_json(payload: Any) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)[:1200]
    except TypeError:
        return str(payload)[:1200]


def _payload_summary(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("task", "openGoal", "constraints", "preferences"):
        if payload.get(key):
            parts.append(f"{key}: {str(payload[key])[:180]}")
    for key in ("sources", "evidence", "existingEvidence"):
        value = payload.get(key)
        if isinstance(value, list):
            parts.append(f"{key}: {len(value)} items")
    if payload.get("theme"):
        parts.append("theme: selected candidate theme")
    return " | ".join(parts)[:1200]


_EVIDENCE_TYPES = {"method", "dataset", "result", "gap", "implementation", "background"}
_NOVELTY_PATHS = {"problem_perspective", "method_transfer", "discipline_combination", "application_scenario"}
