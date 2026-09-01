"""Theme discovery workflow service for the Research workbench."""

from __future__ import annotations

import re
from collections import Counter
from inspect import Parameter, signature
from typing import Any, Iterable

from core.infrastructure.workspace_manager import get_workspace
from core.web.services import agent_directory_service

from .agent_runner import (
    LLMResearchAgentRunner,
    ResearchAgentRunner,
    _profile_from_agent_instance,
    _workspace_project_root,
)
from .agent_templates import RESEARCH_PROMPT_FILES, ensure_research_prompt_defaults
from .knowledge_base import ResearchKnowledgeBase
from .models import (
    ResearchDiscoverySession,
    ResearchSource,
    SearchRun,
    new_id,
    utcnow_iso,
    validate_safe_id,
)
from .providers import (
    PublicResearchSearchProvider,
    ResearchSearchProvider,
    SearchResult,
    new_session_id,
    stable_source_id,
)
from .repository import ResearchRepository
from .scoring import deduplicate_themes


class ResearchThemeDiscoveryService:
    def __init__(
        self,
        *,
        repository: ResearchRepository | None = None,
        search_provider: ResearchSearchProvider | None = None,
        agent_runner: ResearchAgentRunner | None = None,
        knowledge_base: ResearchKnowledgeBase | None = None,
    ):
        self.repository = repository or ResearchRepository()
        self.search_provider = search_provider or PublicResearchSearchProvider()
        self.agent_runner = agent_runner or LLMResearchAgentRunner(search_provider=self.search_provider)
        self.knowledge_base = knowledge_base or ResearchKnowledgeBase(path=self.repository.root.parent / "knowledge_base.json")

    def list_sessions(self) -> dict[str, Any]:
        sessions = self.repository.list_sessions()
        return {
            "sessions": [self._session_summary(session) for session in sessions],
            "summary": {
                "sessionCount": len(sessions),
                "selectedCount": sum(1 for item in sessions if item.selected_theme_id),
            },
        }

    def create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        now = utcnow_iso()
        session = ResearchDiscoverySession(
            session_id=new_session_id(),
            open_goal=payload.get("openGoal") or payload.get("open_goal") or ResearchDiscoverySession.open_goal,
            constraints=payload.get("constraints") or ResearchDiscoverySession.constraints,
            preferences=payload.get("preferences") or ResearchDiscoverySession.preferences,
            candidate_count=int(payload.get("candidateCount") or payload.get("candidate_count") or 5),
            status="draft",
            created_at=now,
            updated_at=now,
        )
        self.repository.save_session(session)
        self._event(session.session_id, "session.created", {"candidateCount": session.candidate_count})
        return self.get_session(session.session_id)

    def get_session(self, session_id: str) -> dict[str, Any]:
        snapshot = self.repository.load_snapshot(validate_safe_id(session_id, label="session id"))
        snapshot["summary"] = self._snapshot_summary(snapshot)
        snapshot["agentReport"] = self._agent_report(snapshot)
        return snapshot

    def delete_session(self, session_id: str) -> dict[str, Any]:
        session_id = validate_safe_id(session_id, label="session id")
        self.repository.delete_session(session_id)
        return {
            "deleted": True,
            "sessionId": session_id,
            **self.list_sessions(),
        }

    def run_broad_search(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        queries = self._broad_queries(session)
        existing_sources = self.repository.load_sources(session.session_id)
        knowledge_preflight = self._knowledge_preflight(
            session=session,
            phase="broad",
            queries=queries,
            existing_sources=existing_sources,
        )
        run = SearchRun(
            run_id=new_id("broad-search"),
            session_id=session.session_id,
            phase="broad",
            queries=queries,
            provider=self.search_provider.provider_name,
            status="running",
            model_profile=self._model_profile(),
        )
        run.model_profile.update(self._agent_plan(session, phase="broad", queries=queries))
        run.model_profile["knowledgePreflight"] = knowledge_preflight
        self._append_search_run(session.session_id, run)
        self._event(
            session.session_id,
            "search.broad.started",
            {
                "runId": run.run_id,
                "phase": run.phase,
                "queryCount": len(queries),
                "provider": run.provider,
                "agentKey": "broad",
                "knowledgePreflight": knowledge_preflight,
            },
        )
        trace_sink = self._search_trace_sink(run)
        trace_sink(self._knowledge_preflight_trace(knowledge_preflight))
        try:
            execution = self._run_agent_search(
                phase="broad",
                session=session,
                suggested_queries=queries,
                existing_sources=existing_sources,
                knowledge_context=knowledge_preflight,
                trace_sink=trace_sink,
            )
        except Exception as exc:
            self._fail_search_run(run, exc)
            raise
        execution.trace = _merge_trace(run.model_profile.get("liveTrace"), execution.trace)
        execution.profile["trace"] = execution.trace
        result_sources = self._sources_from_results(session.session_id, run.run_id, execution.results)
        source_counts = dict(Counter(item.kind for item in execution.results))
        failed_count = sum(1 for item in execution.attempts if item.get("status") == "failed")
        sources = self.repository.load_sources(session.session_id)
        sources.extend(result_sources)
        run.status = "completed"
        run.completed_at = utcnow_iso()
        run.model_profile.update(
            {
                "agentExecution": execution.profile,
                "searchExecution": {
                    "attempts": execution.attempts,
                    "sourceCounts": source_counts,
                    "failedAttemptCount": failed_count,
                }
            }
        )
        self._replace_search_run(run)
        self.repository.save_sources(session.session_id, self._dedupe_sources(sources))
        try:
            knowledge_summary = self._archive_sources_to_knowledge_base(
                session=session,
                phase="broad",
                sources=result_sources,
                search_run=run,
            )
        except Exception as exc:
            self._event(
                session.session_id,
                "knowledge_base.ingest.failed",
                {
                    "runId": run.run_id,
                    "phase": "broad",
                    "sourceCount": len(result_sources),
                    "agentKey": "broad",
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        self._mark_downstream_stale(session.session_id, after_stage="search")
        self._touch_session(session, status="reviewing")
        self._event(
            session.session_id,
            "search.broad.completed",
            {
                "runId": run.run_id,
                "phase": "broad",
                "queryCount": len(queries),
                "sourceCount": len(result_sources),
                "sourceCounts": source_counts,
                "failedAttemptCount": failed_count,
                "agentKey": execution.profile.get("agentKey"),
                "agentExecution": execution.profile,
                "knowledgePreflight": knowledge_preflight,
                "knowledgeBase": knowledge_summary,
                "trace": execution.trace,
            },
        )
        return self.get_session(session.session_id)

    def run_deep_search(self, session_id: str, evidence_requests: list[str] | None = None) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        queries = self._deep_queries(session, sources, evidence_requests=evidence_requests)
        knowledge_preflight = self._knowledge_preflight(
            session=session,
            phase="deep",
            queries=queries,
            existing_sources=sources,
        )
        run = SearchRun(
            run_id=new_id("deep-search"),
            session_id=session.session_id,
            phase="deep",
            queries=queries,
            provider=self.search_provider.provider_name,
            status="running",
            model_profile=self._model_profile(),
        )
        run.model_profile.update(self._agent_plan(session, phase="deep", queries=queries))
        run.model_profile["knowledgePreflight"] = knowledge_preflight
        self._append_search_run(session.session_id, run)
        self._event(
            session.session_id,
            "search.deep.started",
            {
                "runId": run.run_id,
                "phase": run.phase,
                "queryCount": len(queries),
                "provider": run.provider,
                "agentKey": "deep",
                "evidenceRequests": _string_list(evidence_requests),
                "knowledgePreflight": knowledge_preflight,
            },
        )
        trace_sink = self._search_trace_sink(run)
        trace_sink(self._knowledge_preflight_trace(knowledge_preflight))
        try:
            execution = self._run_agent_search(
                phase="deep",
                session=session,
                suggested_queries=queries,
                existing_sources=sources,
                knowledge_context=knowledge_preflight,
                trace_sink=trace_sink,
            )
        except Exception as exc:
            self._fail_search_run(run, exc)
            raise
        execution.trace = _merge_trace(run.model_profile.get("liveTrace"), execution.trace)
        execution.profile["trace"] = execution.trace
        result_sources = self._sources_from_results(session.session_id, run.run_id, execution.results)
        source_counts = dict(Counter(item.kind for item in execution.results))
        failed_count = sum(1 for item in execution.attempts if item.get("status") == "failed")
        merged_sources = self.repository.load_sources(session.session_id)
        merged_sources.extend(result_sources)
        run.status = "completed"
        run.completed_at = utcnow_iso()
        run.model_profile.update(
            {
                "agentExecution": execution.profile,
                "searchExecution": {
                    "attempts": execution.attempts,
                    "sourceCounts": source_counts,
                    "failedAttemptCount": failed_count,
                }
            }
        )
        self._replace_search_run(run)
        self.repository.save_sources(session.session_id, self._dedupe_sources(merged_sources))
        try:
            knowledge_summary = self._archive_sources_to_knowledge_base(
                session=session,
                phase="deep",
                sources=result_sources,
                search_run=run,
            )
        except Exception as exc:
            self._event(
                session.session_id,
                "knowledge_base.ingest.failed",
                {
                    "runId": run.run_id,
                    "phase": "deep",
                    "sourceCount": len(result_sources),
                    "agentKey": "deep",
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        self._mark_downstream_stale(session.session_id, after_stage="search")
        self._touch_session(session, status="reviewing")
        self._event(
            session.session_id,
            "search.deep.completed",
            {
                "runId": run.run_id,
                "phase": "deep",
                "queryCount": len(queries),
                "sourceCount": len(result_sources),
                "sourceCounts": source_counts,
                "failedAttemptCount": failed_count,
                "evidenceRequests": _string_list(evidence_requests),
                "agentKey": execution.profile.get("agentKey"),
                "agentExecution": execution.profile,
                "knowledgePreflight": knowledge_preflight,
                "knowledgeBase": knowledge_summary,
                "trace": execution.trace,
            },
        )
        return self.get_session(session.session_id)

    def get_knowledge_base(self, *, query: str = "", kind: str = "", category: str = "", limit: int = 100) -> dict[str, Any]:
        return self.knowledge_base.payload(query=query, kind=kind, category=category, limit=limit)

    def extract_evidence(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        evidence = self.repository.load_evidence(session.session_id)
        self._event(
            session.session_id,
            "evidence.extraction.started",
            {
                "sourceCount": len(sources),
                "evidenceCount": len(evidence),
                "agentKey": "review",
            },
        )
        try:
            evidence_result = self.agent_runner.extract_evidence(
                session=session,
                sources=sources,
                existing_evidence=evidence,
                trace_sink=self._stage_trace_sink(session.session_id, "evidence.extracting", "review"),
            )
            evidence = evidence_result.evidence
            self.repository.save_evidence(session.session_id, evidence)
            self._mark_downstream_stale(session.session_id, after_stage="evidence")
            self._touch_session(session, status="reviewing")
            self._event(
                session.session_id,
                "evidence.extracted",
                {
                    "evidenceCount": len(evidence),
                    "evidenceCounts": dict(Counter(item.evidence_type for item in evidence)),
                    "missingEvidenceRequests": evidence_result.missing_evidence_requests,
                    "agentKey": "review",
                    "agentExecution": evidence_result.profile,
                    "trace": evidence_result.trace,
                },
            )
        except Exception as exc:
            self._event(
                session.session_id,
                "evidence.extraction.failed",
                {
                    "sourceCount": len(sources),
                    "evidenceCount": len(evidence),
                    "agentKey": "review",
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        return self.get_session(session.session_id)

    def generate_themes(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        evidence = self.repository.load_evidence(session.session_id)
        if not sources:
            self._event(
                session.session_id,
                "themes.generation.failed",
                {
                    "agentKey": "themes",
                    "reason": "missing_sources",
                    "sourceCount": 0,
                    "evidenceCount": len(evidence),
                    "errorType": "ValueError",
                    "message": "Run search before generating themes.",
                },
            )
            raise ValueError("Run search before generating themes.")
        if not evidence:
            self._event(
                session.session_id,
                "themes.generation.failed",
                {
                    "agentKey": "themes",
                    "reason": "missing_evidence",
                    "sourceCount": len(sources),
                    "evidenceCount": 0,
                    "errorType": "ValueError",
                    "message": "Extract evidence before generating themes.",
                },
            )
            raise ValueError("Extract evidence before generating themes.")
        existing = self.repository.load_candidate_themes(session.session_id)
        for theme in existing:
            if theme.status in {"draft", "shortlisted"}:
                theme.status = "stale"
        self._event(
            session.session_id,
            "themes.generation.started",
            {
                "agentKey": "themes",
                "sourceCount": len(sources),
                "evidenceCount": len(evidence),
                "candidateCount": session.candidate_count,
            },
        )
        try:
            theme_result = self.agent_runner.generate_themes(
                session=session,
                sources=sources,
                evidence=evidence,
                parent_run_id=self._latest_run_id(session.session_id),
                trace_sink=self._stage_trace_sink(session.session_id, "themes.generating", "themes"),
            )
            selected = deduplicate_themes(
                theme_result.themes,
                limit=session.candidate_count,
            )
            for theme in selected:
                theme.status = "shortlisted"
            self.repository.save_candidate_themes(session.session_id, [*existing, *selected])
            self._mark_theme_cards_stale(session.session_id)
            self._touch_session(session, status="reviewing")
            self._event(
                session.session_id,
                "themes.generated",
                {
                    "candidateCount": len(selected),
                    "agentKey": "themes",
                    "agentExecution": theme_result.profile,
                    "trace": theme_result.trace,
                },
            )
        except Exception as exc:
            self._event(
                session.session_id,
                "themes.generation.failed",
                {
                    "agentKey": "themes",
                    "sourceCount": len(sources),
                    "evidenceCount": len(evidence),
                    "candidateCount": session.candidate_count,
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        return self.get_session(session.session_id)

    def select_theme(self, session_id: str, theme_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        theme_id = validate_safe_id(theme_id, label="theme id")
        themes = self.repository.load_candidate_themes(session.session_id)
        target = next((item for item in themes if item.theme_id == theme_id), None)
        if target is None:
            self._event(
                session.session_id,
                "theme.selection.failed",
                {
                    "themeId": theme_id,
                    "candidateCount": len(themes),
                    "errorType": "FileNotFoundError",
                    "message": "Candidate theme not found.",
                },
            )
            raise FileNotFoundError("Candidate theme not found.")
        if target.status == "stale":
            self._event(
                session.session_id,
                "theme.selection.failed",
                {
                    "themeId": theme_id,
                    "candidateCount": len(themes),
                    "reason": "stale_theme",
                    "errorType": "ValueError",
                    "message": "Cannot select a stale candidate theme without rerunning or restoring it.",
                },
            )
            raise ValueError("Cannot select a stale candidate theme without rerunning or restoring it.")
        for theme in themes:
            if theme.theme_id == theme_id:
                theme.status = "selected"
            elif theme.status == "selected":
                theme.status = "shortlisted"
        session.selected_theme_id = theme_id
        self.repository.save_candidate_themes(session.session_id, themes)
        self._touch_session(session, status="selected")
        self._event(session.session_id, "theme.selected", {"themeId": theme_id})
        return self.get_session(session.session_id)

    def generate_theme_card(self, session_id: str, theme_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        theme_id = validate_safe_id(theme_id, label="theme id")
        themes = self.repository.load_candidate_themes(session.session_id)
        theme = next((item for item in themes if item.theme_id == theme_id), None)
        if theme is None:
            self._event(
                session.session_id,
                "theme_card.generation.failed",
                {
                    "themeId": theme_id,
                    "agentKey": "card",
                    "errorType": "FileNotFoundError",
                    "message": "Candidate theme not found.",
                },
            )
            raise FileNotFoundError("Candidate theme not found.")
        if theme.status == "stale":
            self._event(
                session.session_id,
                "theme_card.generation.failed",
                {
                    "themeId": theme_id,
                    "agentKey": "card",
                    "reason": "stale_theme",
                    "errorType": "ValueError",
                    "message": "Cannot generate a theme card from a stale candidate theme.",
                },
            )
            raise ValueError("Cannot generate a theme card from a stale candidate theme.")
        cards = self.repository.load_theme_cards(session.session_id)
        for card in cards:
            if card.theme_id == theme_id and card.status == "draft":
                card.status = "stale"
        sources = self.repository.load_sources(session.session_id)
        self._event(
            session.session_id,
            "theme_card.generation.started",
            {
                "themeId": theme_id,
                "agentKey": "card",
                "sourceCount": len(sources),
                "themeCardCount": len(cards),
            },
        )
        try:
            card_result = self.agent_runner.generate_card(
                session=session,
                theme=theme,
                sources=sources,
                version=self._next_card_version(session.session_id, theme.theme_id),
                trace_sink=self._stage_trace_sink(session.session_id, "theme_card.generating", "card"),
            )
            if card_result.card is None:
                raise ValueError("card agent returned no usable theme card.")
            card = card_result.card
            cards.append(card)
            self.repository.save_theme_cards(session.session_id, cards)
            self._touch_session(session, status="selected")
            self._event(
                session.session_id,
                "theme_card.generated",
                {
                    "themeId": theme_id,
                    "cardId": card.card_id,
                    "agentKey": "card",
                    "agentExecution": card_result.profile,
                    "trace": card_result.trace,
                },
            )
        except Exception as exc:
            self._event(
                session.session_id,
                "theme_card.generation.failed",
                {
                    "themeId": theme_id,
                    "agentKey": "card",
                    "sourceCount": len(sources),
                    "themeCardCount": len(cards),
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        return self.get_session(session.session_id)

    def approve_theme_card(self, session_id: str, card_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        card_id = validate_safe_id(card_id, label="theme card id")
        cards = self.repository.load_theme_cards(session.session_id)
        target = next((item for item in cards if item.card_id == card_id), None)
        if target is None:
            self._event(
                session.session_id,
                "theme_card.approval.failed",
                {
                    "cardId": card_id,
                    "themeCardCount": len(cards),
                    "errorType": "FileNotFoundError",
                    "message": "Theme card not found.",
                },
            )
            raise FileNotFoundError("Theme card not found.")
        if target.status == "stale":
            self._event(
                session.session_id,
                "theme_card.approval.failed",
                {
                    "cardId": card_id,
                    "themeCardCount": len(cards),
                    "reason": "stale_theme_card",
                    "errorType": "ValueError",
                    "message": "Cannot approve a stale theme card.",
                },
            )
            raise ValueError("Cannot approve a stale theme card.")
        for card in cards:
            if card.card_id == card_id:
                card.status = "approved"
        self.repository.save_theme_cards(session.session_id, cards)
        self._touch_session(session, status="selected")
        self._event(session.session_id, "theme_card.approved", {"cardId": card_id})
        return self.get_session(session.session_id)

    def run_draft(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        self._event(session.session_id, "draft.started", {"agentKey": "draft"})
        try:
            self.run_broad_search(session.session_id)
            self.run_deep_search(session.session_id)
            self.extract_evidence(session.session_id)
            payload = self.generate_themes(session.session_id)
        except Exception as exc:
            self._event(
                session.session_id,
                "draft.failed",
                {
                    "agentKey": "draft",
                    "errorType": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        self._event(
            session.session_id,
            "draft.completed",
            {
                "agentKey": "draft",
                "sourceCount": summary.get("sourceCount") or 0,
                "evidenceCount": summary.get("evidenceCount") or 0,
                "candidateCount": summary.get("candidateThemeCount") or 0,
                "themeCardCount": summary.get("themeCardCount") or 0,
            },
        )
        return payload

    def _append_search_run(self, session_id: str, run: SearchRun) -> None:
        runs = self.repository.load_search_runs(session_id)
        runs.append(run)
        self.repository.save_search_runs(session_id, runs)

    def _replace_search_run(self, run: SearchRun) -> None:
        runs = self.repository.load_search_runs(run.session_id)
        replaced = False
        for index, item in enumerate(runs):
            if item.run_id == run.run_id:
                runs[index] = run
                replaced = True
                break
        if not replaced:
            runs.append(run)
        self.repository.save_search_runs(run.session_id, runs)

    def _run_agent_search(
        self,
        *,
        phase: str,
        session: ResearchDiscoverySession,
        suggested_queries: list[str],
        existing_sources: list[ResearchSource],
        knowledge_context: dict[str, Any],
        trace_sink,
    ):
        kwargs = {
            "phase": phase,
            "session": session,
            "suggested_queries": suggested_queries,
            "existing_sources": existing_sources,
            "trace_sink": trace_sink,
        }
        if _accepts_kwarg(self.agent_runner.run_search, "knowledge_context"):
            kwargs["knowledge_context"] = knowledge_context
        return self.agent_runner.run_search(**kwargs)

    def _search_trace_sink(self, run: SearchRun):
        def sink(item: dict[str, Any]) -> None:
            trace = _trace_list(run.model_profile.get("liveTrace"))
            trace.append(item)
            run.model_profile["liveTrace"] = trace
            run.model_profile["agentExecution"] = {
                **dict(run.model_profile.get("agentExecution") or {}),
                "agentKey": "broad" if run.phase == "broad" else "deep",
                "executionMode": "running",
                "trace": trace,
            }
            self._replace_search_run(run)

        return sink

    def _knowledge_preflight(
        self,
        *,
        session: ResearchDiscoverySession,
        phase: str,
        queries: list[str],
        existing_sources: list[ResearchSource],
    ) -> dict[str, Any]:
        library = self.knowledge_base.payload(limit=250)
        summary = library.get("summary") if isinstance(library.get("summary"), dict) else {}
        tokens = _knowledge_tokens(
            " ".join(
                [
                    session.open_goal,
                    session.constraints,
                    session.preferences,
                    phase,
                    *queries,
                ]
            )
        )
        entries = _rank_knowledge_entries(library.get("entries"), tokens, limit=12)
        claims = _rank_knowledge_records(library.get("claims"), tokens, limit=8)
        evidence = _rank_knowledge_records(library.get("evidence"), tokens, limit=8)
        gaps = _rank_knowledge_records(library.get("gaps"), tokens, limit=8)
        total_entries = int(summary.get("entryCount") or 0)
        if total_entries <= 0:
            decision = "kb_empty_search_required"
            reason = "科研知识库还没有可复用来源，本阶段需要继续真实联网搜索。"
        elif entries or claims or evidence or gaps:
            decision = "reuse_and_search"
            reason = "科研知识库已有相关来源和认知记录，先复用这些线索，再继续真实联网补齐缺口。"
        else:
            decision = "search_required"
            reason = "科研知识库已有内容，但没有找到与本阶段查询明显相关的记录，需要继续真实联网搜索。"
        matched_kinds = Counter(str(item.get("kind") or "unknown") for item in entries)
        known_kinds = {str(source.kind) for source in existing_sources}
        missing_kinds = [
            kind
            for kind in ["paper", "github", "dataset", "web"]
            if kind not in known_kinds and kind not in matched_kinds
        ]
        return {
            "phase": phase,
            "decision": decision,
            "reason": reason,
            "checkedAt": utcnow_iso(),
            "queryCount": len(queries),
            "queryTokens": sorted(tokens)[:40],
            "existingSessionSourceCount": len(existing_sources),
            "knowledgeBasePath": library.get("path") or "",
            "totalEntryCount": total_entries,
            "totalClaimCount": int(summary.get("claimCount") or 0),
            "totalEvidenceCount": int(summary.get("evidenceCount") or 0),
            "totalGapCount": int(summary.get("gapCount") or 0),
            "matchedEntryCount": len(entries),
            "matchedClaimCount": len(claims),
            "matchedEvidenceCount": len(evidence),
            "matchedGapCount": len(gaps),
            "sourceKindCounts": dict(matched_kinds),
            "missingSourceKinds": missing_kinds,
            "recentQueries": _unique_strings(
                query
                for entry in entries
                for query in [str(item) for item in entry.get("queries") or []]
                if query
            )[:12],
            "recentSources": [_knowledge_source_view(item) for item in entries[:8]],
            "matchedClaims": [_knowledge_record_view(item) for item in claims[:5]],
            "matchedEvidence": [_knowledge_record_view(item) for item in evidence[:5]],
            "matchedGaps": [_knowledge_record_view(item) for item in gaps[:5]],
            "reuseGuidance": [
                "把 matchedClaims/matchedEvidence/matchedGaps 当作已知上下文，不要重复把同一来源当成新发现。",
                "仍然调用真实搜索工具，优先补齐 missingSourceKinds、陈旧证据和未验证 gap。",
                "如果搜索结果与知识库重复，要更新溯源和 hitCount，而不是生成重复结论。",
            ],
        }

    def _knowledge_preflight_trace(self, preflight: dict[str, Any]) -> dict[str, Any]:
        return {
            "kind": "memory",
            "title": "科研知识库预检",
            "detail": (
                f"{preflight.get('reason')} matchedSources={preflight.get('matchedEntryCount')}; "
                f"matchedClaims={preflight.get('matchedClaimCount')}; "
                f"matchedEvidence={preflight.get('matchedEvidenceCount')}; "
                f"matchedGaps={preflight.get('matchedGapCount')}; "
                f"missingKinds={', '.join(preflight.get('missingSourceKinds') or []) or 'none'}"
            )[:1200],
            "timestamp": utcnow_iso(),
        }

    def _stage_trace_sink(self, session_id: str, event_code: str, agent_key: str):
        event: dict[str, Any] | None = None

        def sink(item: dict[str, Any]) -> None:
            nonlocal event
            trace = _trace_list((event or {}).get("fields", {}).get("trace") if event else [])
            trace.append(item)
            fields = {
                "agentKey": agent_key,
                "agentExecution": {
                    "agentKey": agent_key,
                    "executionMode": "running",
                    "trace": trace,
                },
                "trace": trace,
            }
            if event is None:
                event = {
                    "eventCode": event_code,
                    "timestamp": utcnow_iso(),
                    "fields": fields,
                }
                self.repository.append_event(session_id, event)
                return
            event["timestamp"] = utcnow_iso()
            event["fields"] = fields
            self.repository.replace_event(session_id, event_code, event)

        return sink

    def _fail_search_run(self, run: SearchRun, exc: Exception) -> None:
        run.status = "failed"
        run.completed_at = utcnow_iso()
        run.model_profile.update(
            {
                "failure": {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                }
            }
        )
        self._replace_search_run(run)
        self._event(
            run.session_id,
            f"search.{run.phase}.failed",
            {
                "runId": run.run_id,
                "phase": run.phase,
                "agentKey": "broad" if run.phase == "broad" else "deep",
                "errorType": exc.__class__.__name__,
                "message": str(exc),
                "queryCount": len(run.queries),
                "knowledgePreflight": run.model_profile.get("knowledgePreflight") or {},
            },
        )

    def _sources_from_results(self, session_id: str, run_id: str, results: list[SearchResult]) -> list[ResearchSource]:
        return [
            ResearchSource(
                source_id=stable_source_id(session_id, run_id, result),
                session_id=session_id,
                search_run_id=run_id,
                kind=result.kind,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                reliability=result.reliability,
            )
            for result in results
        ]

    def _dedupe_sources(self, sources: Iterable[ResearchSource]) -> list[ResearchSource]:
        deduped: dict[tuple[str, str], ResearchSource] = {}
        for source in sources:
            deduped[(source.kind, source.url)] = source
        return list(deduped.values())

    def _archive_sources_to_knowledge_base(
        self,
        *,
        session: ResearchDiscoverySession,
        phase: str,
        sources: list[ResearchSource],
        search_run: SearchRun | None = None,
    ) -> dict[str, Any]:
        if not sources:
            return {"added": 0, "updated": 0, "total": len(self.knowledge_base.payload(limit=1)["entries"])}
        return self.knowledge_base.ingest_sources(session=session, phase=phase, sources=sources, search_run=search_run)

    def _mark_downstream_stale(self, session_id: str, *, after_stage: str) -> None:
        if after_stage in {"search", "evidence"}:
            themes = self.repository.load_candidate_themes(session_id)
            changed = False
            for theme in themes:
                if theme.status in {"draft", "shortlisted", "selected"}:
                    theme.status = "stale"
                    changed = True
            if changed:
                self.repository.save_candidate_themes(session_id, themes)
            self._mark_theme_cards_stale(session_id)

    def _mark_theme_cards_stale(self, session_id: str) -> None:
        cards = self.repository.load_theme_cards(session_id)
        changed = False
        for card in cards:
            if card.status in {"draft", "approved"}:
                card.status = "stale"
                changed = True
        if changed:
            self.repository.save_theme_cards(session_id, cards)

    def _touch_session(self, session: ResearchDiscoverySession, *, status: str | None = None) -> None:
        session.updated_at = utcnow_iso()
        if status:
            session.status = status  # type: ignore[assignment]
        self.repository.save_session(session)

    def _event(self, session_id: str, event_code: str, fields: dict[str, Any]) -> None:
        timestamp = utcnow_iso()
        self.repository.append_event(
            session_id,
            {
                "eventCode": event_code,
                "timestamp": timestamp,
                "fields": fields,
            },
        )
        try:
            from core.web.services.runtime_scene_service import record_research_scene_event

            record_research_scene_event(
                event_code,
                message=event_code,
                level="error" if event_code.endswith(".failed") else "info",
                outcome=_research_outcome_from_event_code(event_code),
                phase=_research_phase_from_event_code(event_code),
                fields=_research_runtime_scene_fields(event_code, fields),
                session_id=session_id,
                agent_key=str(fields.get("agentKey") or ""),
                occurred_at=timestamp,
            )
        except Exception:
            pass

    def _session_summary(self, session: ResearchDiscoverySession) -> dict[str, Any]:
        snapshot = self.repository.load_snapshot(session.session_id)
        summary = self._snapshot_summary(snapshot)
        return {
            **session.to_dict(),
            "summary": summary,
        }

    def _snapshot_summary(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        themes = snapshot.get("candidateThemes") if isinstance(snapshot.get("candidateThemes"), list) else []
        cards = snapshot.get("themeCards") if isinstance(snapshot.get("themeCards"), list) else []
        current_themes = [item for item in themes if str(item.get("status") or "") in {"shortlisted", "selected"}]
        return {
            "searchRunCount": len(snapshot.get("searchRuns") or []),
            "sourceCount": len(snapshot.get("sources") or []),
            "evidenceCount": len(snapshot.get("evidence") or []),
            "candidateThemeCount": len(current_themes),
            "staleThemeCount": sum(1 for item in themes if str(item.get("status") or "") == "stale"),
            "themeCardCount": len(cards),
            "approvedThemeCardCount": sum(1 for item in cards if str(item.get("status") or "") == "approved"),
        }

    def _agent_report(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        runs = snapshot.get("searchRuns") if isinstance(snapshot.get("searchRuns"), list) else []
        sources = snapshot.get("sources") if isinstance(snapshot.get("sources"), list) else []
        evidence = snapshot.get("evidence") if isinstance(snapshot.get("evidence"), list) else []
        themes = snapshot.get("candidateThemes") if isinstance(snapshot.get("candidateThemes"), list) else []
        latest_run = runs[-1] if runs else {}
        source_counts = Counter(str(item.get("kind") or "unknown") for item in sources if isinstance(item, dict))
        evidence_counts = Counter(str(item.get("evidenceType") or "unknown") for item in evidence if isinstance(item, dict))
        providers = [str(item.get("provider") or "") for item in runs if isinstance(item, dict)]
        legacy_count = self._legacy_source_count(sources, runs)
        failure_attempts = self._failure_attempts(runs)
        mode = "live_public_network"
        status = "ready"
        warnings: list[str] = []
        if not runs:
            status = "idle"
            warnings.append("No search run has been executed yet.")
        if any(provider.startswith("deterministic") or "fallback" in provider for provider in providers):
            mode = "mixed_or_legacy"
            status = "legacy_data"
            warnings.append("This session contains deterministic or old fallback search data. Create a new session for live-only evidence.")
        if legacy_count:
            mode = "mixed_or_legacy"
            status = "legacy_data"
            warnings.append(f"{legacy_count} sources look like legacy placeholder/test sources.")
        if failure_attempts:
            status = "partial"
            warnings.append(f"{len(failure_attempts)} provider calls failed; inspect the failed attempts before trusting coverage.")
        observations = self._agent_observations(source_counts, evidence_counts, themes)
        plan = latest_run.get("modelProfile", {}).get("agentPlan", []) if isinstance(latest_run.get("modelProfile"), dict) else []
        return {
            "mode": mode,
            "status": status,
            "provider": str(latest_run.get("provider") or self.search_provider.provider_name),
            "lastRunAt": latest_run.get("completedAt") or latest_run.get("startedAt") or "",
            "queries": latest_run.get("queries") if isinstance(latest_run.get("queries"), list) else [],
            "plan": plan,
            "observations": observations,
            "warnings": warnings,
            "sourceKindCounts": {kind: int(source_counts.get(kind, 0)) for kind in ["paper", "github", "dataset", "web"]},
            "evidenceTypeCounts": dict(evidence_counts),
            "failedAttempts": failure_attempts[:8],
            "summary": self._agent_report_summary(mode, source_counts, evidence_counts, themes, failure_attempts),
        }

    def _legacy_source_count(self, sources: list[Any], runs: list[Any]) -> int:
        run_provider = {
            str(run.get("runId") or ""): str(run.get("provider") or "") for run in runs if isinstance(run, dict)
        }
        count = 0
        for source in sources:
            if not isinstance(source, dict):
                continue
            provider = run_provider.get(str(source.get("searchRunId") or ""), "")
            url = str(source.get("url") or "")
            if provider.startswith("deterministic") or "fallback" in provider or "example.org" in url:
                count += 1
        return count

    def _failure_attempts(self, runs: list[Any]) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for run in runs:
            if not isinstance(run, dict):
                continue
            model_profile = run.get("modelProfile") if isinstance(run.get("modelProfile"), dict) else {}
            execution = model_profile.get("searchExecution") if isinstance(model_profile.get("searchExecution"), dict) else {}
            attempts = execution.get("attempts") if isinstance(execution.get("attempts"), list) else []
            for attempt in attempts:
                if not isinstance(attempt, dict) or attempt.get("status") != "failed":
                    continue
                failures.append(
                    {
                        "runId": run.get("runId"),
                        "phase": run.get("phase"),
                        "kind": attempt.get("kind"),
                        "query": attempt.get("query"),
                        "error": attempt.get("error"),
                    }
                )
        return failures

    def _agent_observations(
        self,
        source_counts: Counter[str],
        evidence_counts: Counter[str],
        themes: list[Any],
    ) -> list[str]:
        observations = [
            f"Source coverage: {int(source_counts.get('paper', 0))} papers, {int(source_counts.get('github', 0))} GitHub repositories, {int(source_counts.get('dataset', 0))} datasets, {int(source_counts.get('web', 0))} web sources.",
            f"Evidence coverage: {sum(evidence_counts.values())} extracted records across {len([key for key, value in evidence_counts.items() if value])} evidence types.",
        ]
        current_themes = [item for item in themes if isinstance(item, dict) and item.get("status") in {"shortlisted", "selected"}]
        if current_themes:
            best = max(current_themes, key=lambda item: float(item.get("recommendationScore") or 0))
            observations.append(
                f"Current strongest theme is '{best.get('title')}' with recommendation score {round(float(best.get('recommendationScore') or 0))}."
            )
        if not source_counts.get("dataset"):
            observations.append("Dataset coverage is still weak; treat feasibility as unconfirmed.")
        if not source_counts.get("paper"):
            observations.append("Paper coverage is missing; novelty cannot be trusted yet.")
        return observations

    def _agent_report_summary(
        self,
        mode: str,
        source_counts: Counter[str],
        evidence_counts: Counter[str],
        themes: list[Any],
        failure_attempts: list[dict[str, Any]],
    ) -> str:
        source_total = sum(source_counts.values())
        current_theme_count = sum(
            1 for item in themes if isinstance(item, dict) and item.get("status") in {"shortlisted", "selected"}
        )
        mode_label = "live public network" if mode == "live_public_network" else "mixed or legacy data"
        failure_text = "with partial provider failures" if failure_attempts else "without recorded provider failures"
        return (
            f"Research agent used {mode_label}, collected {source_total} sources, "
            f"extracted {sum(evidence_counts.values())} evidence records, and produced {current_theme_count} active themes "
            f"{failure_text}."
        )

    def _broad_queries(self, session: ResearchDiscoverySession) -> list[str]:
        return [
            f"{session.open_goal} AI Scientist interdisciplinary research",
            f"{session.open_goal} scientific discovery datasets GitHub",
            f"{session.open_goal} novel research gaps hypothesis generation",
        ]

    def _deep_queries(
        self,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        *,
        evidence_requests: list[str] | None = None,
    ) -> list[str]:
        keywords = self._keywords([session.open_goal, session.constraints, session.preferences, *[item.title for item in sources]])
        if not keywords:
            keywords = ["AI Scientist", "causal hypothesis", "scientific discovery"]
        base = " ".join(keywords[:4])
        queries = [
            f"{base} falsifiable scientific hypothesis",
            f"{base} causal mechanism research gap",
            f"{base} public dataset benchmark open source",
        ]
        for request in _string_list(evidence_requests)[:3]:
            queries.append(f"{request} evidence public dataset benchmark open source")
        return queries

    def _keywords(self, texts: list[str]) -> list[str]:
        words: list[str] = []
        for text in texts:
            words.extend(
                token
                for token in re.findall(r"[A-Za-z][A-Za-z-]{3,}", str(text).lower())
                if token
                not in {
                    "with",
                    "from",
                    "that",
                    "this",
                    "should",
                    "research",
                    "theme",
                    "scientist",
                    "related",
                    "suitable",
                }
            )
        counts = Counter(words)
        return [word for word, _count in counts.most_common(12)]

    def _latest_run_id(self, session_id: str) -> str:
        runs = self.repository.load_search_runs(session_id)
        return runs[-1].run_id if runs else ""

    def _next_card_version(self, session_id: str, theme_id: str) -> int:
        cards = [item for item in self.repository.load_theme_cards(session_id) if item.theme_id == theme_id]
        return max([item.version for item in cards], default=0) + 1

    def _model_profile(self) -> dict[str, Any]:
        prompts = self._research_prompt_profile()
        agent_bindings = self._research_agent_template_profile()
        return {
            "provider": "configured-vibelution-provider",
            "mode": "research-theme-discovery",
            "agentRole": "theme-discovery-research-agent",
            "runtimeDataPolicy": "live-public-network-only-by-default",
            "promptSource": prompts["root"],
            "promptFiles": prompts["files"],
            "agentTemplateConfigPath": agent_bindings["configPath"],
            "agentBindings": agent_bindings["agents"],
            "note": "MVP uses live public research search by default; tests may inject deterministic providers.",
        }

    def _research_agent_template_profile(self) -> dict[str, Any]:
        workspace = get_workspace()
        project_root = _workspace_project_root(workspace)
        agents: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for agent in agent_directory_service.list_agents(
            include_archived=False,
            detail="full",
            project_root=project_root,
        ):
            metadata = agent.get("metadata") if isinstance(agent.get("metadata"), dict) else {}
            if str(metadata.get("challengeCupTeamId") or "").strip():
                continue
            role_key = str(agent.get("roleKey") or "").strip()
            key = str(metadata.get("researchAgentKey") or "").strip()
            if not key and role_key.startswith("research_"):
                key = role_key.removeprefix("research_")
            if key:
                if key in seen_keys:
                    raise ValueError(
                        f"Research AgentDirectory binding is duplicated: {key}"
                    )
                seen_keys.add(key)
                agents.append(_profile_from_agent_instance(key, agent))
        agents.sort(key=lambda item: str(item.get("key") or ""))
        return {
            "configPath": str(agent_directory_service.registry_path(project_root=project_root)),
            "agents": agents,
        }

    def _research_prompt_profile(self) -> dict[str, Any]:
        workspace = get_workspace()
        ensure_research_prompt_defaults(workspace)
        agent_config = self._research_agent_template_profile()
        files = {}
        prompt_files = dict(RESEARCH_PROMPT_FILES)
        for agent in agent_config["agents"]:
            key = str(agent.get("key") or "").strip()
            filename = str(agent.get("promptFilename") or "").strip()
            if key and filename:
                prompt_files[key] = filename
        for key, filename in prompt_files.items():
            content = workspace.read_research_prompt(filename)
            files[key] = {
                "filename": filename,
                "path": str(workspace.get_research_prompt_path(filename)),
                "contentLength": len(content),
                "hasContent": bool(content.strip()),
            }
        return {
            "root": str(workspace.research_prompts_dir()),
            "files": files,
        }

    def _agent_plan(self, session: ResearchDiscoverySession, *, phase: str, queries: list[str]) -> dict[str, Any]:
        if phase == "broad":
            plan = [
                "Map the open research space before locking a theme.",
                "Search papers, GitHub projects, datasets, and general web context for each query.",
                "Preserve source provenance and expose provider failures instead of replacing them with fallback data.",
            ]
        else:
            plan = [
                "Use discovered source titles and user preferences to sharpen the search space.",
                "Look for falsifiable questions, causal mechanisms, public datasets, and implementation baselines.",
                "Prepare evidence for novelty-first candidate generation.",
            ]
        return {
            "agentPlan": plan,
            "agentInputs": {
                "openGoal": session.open_goal,
                "constraints": session.constraints,
                "preferences": session.preferences,
                "queries": queries,
            },
        }


def _research_phase_from_event_code(event_code: str) -> str:
    text = str(event_code or "").strip()
    if text.startswith("draft."):
        return "draft"
    if text.startswith("search.broad."):
        return "broad_search"
    if text.startswith("search.deep."):
        return "deep_search"
    if text.startswith("knowledge_base."):
        return "knowledge_base"
    if text.startswith("evidence."):
        return "evidence"
    if text.startswith("themes."):
        return "theme_generation"
    if text.startswith("theme_card."):
        return "theme_card"
    if text.startswith("theme."):
        return "theme_selection"
    if text.startswith("session."):
        return "session"
    return "theme_discovery"


def _research_outcome_from_event_code(event_code: str) -> str:
    text = str(event_code or "").strip()
    if text.endswith(".failed"):
        return "failed"
    if text.endswith(".started") or text.endswith(".extracting") or text.endswith(".generating"):
        return "started"
    if text.endswith(".blocked"):
        return "blocked"
    return "succeeded"


def _research_runtime_scene_fields(event_code: str, fields: dict[str, Any]) -> dict[str, Any]:
    """Keep runtime-scene research events compact and non-duplicative."""

    if not isinstance(fields, dict):
        return {}
    payload: dict[str, Any] = {}
    passthrough_keys = (
        "sessionId",
        "runId",
        "phase",
        "agentKey",
        "provider",
        "themeId",
        "cardId",
        "candidateCount",
        "queryCount",
        "sourceCount",
        "evidenceCount",
        "themeCardCount",
        "failedAttemptCount",
        "errorType",
        "message",
        "reason",
    )
    for key in passthrough_keys:
        if key in fields:
            payload[key] = fields.get(key)

    if "sourceCounts" in fields:
        payload["sourceCounts"] = fields.get("sourceCounts")
    if "evidenceCounts" in fields:
        payload["evidenceCounts"] = fields.get("evidenceCounts")
    if "evidenceRequests" in fields:
        payload["evidenceRequests"] = _string_list(fields.get("evidenceRequests"))[:8]
    if "missingEvidenceRequests" in fields:
        payload["missingEvidenceRequests"] = _string_list(fields.get("missingEvidenceRequests"))[:8]

    preflight = fields.get("knowledgePreflight")
    if isinstance(preflight, dict):
        payload["knowledgePreflight"] = {
            "decision": preflight.get("decision") or "",
            "queryCount": preflight.get("queryCount") or 0,
            "matchedEntryCount": preflight.get("matchedEntryCount") or 0,
            "matchedClaimCount": preflight.get("matchedClaimCount") or 0,
            "matchedEvidenceCount": preflight.get("matchedEvidenceCount") or 0,
            "matchedGapCount": preflight.get("matchedGapCount") or 0,
            "missingSourceKinds": _string_list(preflight.get("missingSourceKinds"))[:8],
        }

    knowledge_base = fields.get("knowledgeBase")
    if isinstance(knowledge_base, dict):
        payload["knowledgeBase"] = {
            "added": knowledge_base.get("added") or 0,
            "updated": knowledge_base.get("updated") or 0,
            "total": knowledge_base.get("total") or 0,
            "claims": knowledge_base.get("claims") or 0,
            "evidence": knowledge_base.get("evidence") or 0,
            "gaps": knowledge_base.get("gaps") or 0,
            "path": knowledge_base.get("path") or "",
        }

    agent_execution = fields.get("agentExecution")
    if isinstance(agent_execution, dict):
        payload["agentExecution"] = _research_agent_execution_summary(agent_execution)

    trace = fields.get("trace")
    if trace is None and isinstance(agent_execution, dict):
        trace = agent_execution.get("trace")
    trace_summary = _research_trace_summary(trace)
    if trace_summary:
        payload["trace"] = trace_summary

    if not payload:
        payload["eventCode"] = event_code
    return payload


def _research_agent_execution_summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "agentKey": profile.get("agentKey") or "",
        "templateId": profile.get("templateId") or "",
        "profileId": profile.get("profileId") or profile.get("llmConfigId") or "",
        "executionMode": profile.get("executionMode") or "",
        "toolCallCount": profile.get("toolCallCount") or 0,
        "knowledgeContextDecision": profile.get("knowledgeContextDecision") or "",
        "missingEvidenceRequestCount": len(_string_list(profile.get("missingEvidenceRequests"))),
        "traceCount": len(_trace_list(profile.get("trace"))),
    }


def _research_trace_summary(value: Any) -> dict[str, Any]:
    trace = _trace_list(value)
    if not trace:
        return {}
    latest = trace[-1]
    return {
        "count": len(trace),
        "latest": {
            "kind": str(latest.get("kind") or "")[:80],
            "title": str(latest.get("title") or "")[:160],
            "timestamp": str(latest.get("timestamp") or "")[:80],
        },
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _accepts_kwarg(callable_object, name: str) -> bool:
    try:
        parameters = signature(callable_object).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(item.kind == Parameter.VAR_KEYWORD for item in parameters.values())


def _knowledge_tokens(text: str) -> set[str]:
    stopwords = {
        "about",
        "after",
        "agent",
        "based",
        "benchmark",
        "candidate",
        "current",
        "dataset",
        "datasets",
        "evidence",
        "from",
        "github",
        "hypothesis",
        "interdisciplinary",
        "model",
        "novel",
        "open",
        "paper",
        "public",
        "research",
        "science",
        "scientific",
        "scientist",
        "search",
        "source",
        "theme",
        "with",
    }
    tokens = {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}|[\u4e00-\u9fff]{2,}", str(text or ""))
    }
    return {token for token in tokens if token not in stopwords}


def _rank_knowledge_entries(records: Any, tokens: set[str], *, limit: int) -> list[dict[str, Any]]:
    return _rank_knowledge_items(
        records,
        tokens,
        limit=limit,
        fields=("title", "summary", "kind", "reliability"),
        list_fields=("tags", "categories", "queries"),
        tie_breaker="lastSeenAt",
    )


def _rank_knowledge_records(records: Any, tokens: set[str], *, limit: int) -> list[dict[str, Any]]:
    return _rank_knowledge_items(
        records,
        tokens,
        limit=limit,
        fields=("content", "summary", "status", "type"),
        list_fields=("tags",),
        tie_breaker="updatedAt",
    )


def _rank_knowledge_items(
    records: Any,
    tokens: set[str],
    *,
    limit: int,
    fields: tuple[str, ...],
    list_fields: tuple[str, ...],
    tie_breaker: str,
) -> list[dict[str, Any]]:
    if not isinstance(records, list):
        return []
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        haystack_parts = [str(item.get(field) or "") for field in fields]
        for field in list_fields:
            haystack_parts.extend(str(value) for value in item.get(field) or [])
        haystack = " ".join(haystack_parts).lower()
        score = sum(1 for token in tokens if token in haystack)
        if not tokens:
            score = 1
        if score <= 0:
            continue
        ranked.append((score, str(item.get(tie_breaker) or ""), item))
    ranked.sort(key=lambda value: (value[0], value[1]), reverse=True)
    return [item for _score, _date, item in ranked[: max(1, min(50, int(limit or 10)))]]


def _knowledge_source_view(entry: dict[str, Any]) -> dict[str, Any]:
    return {
        "knowledgeId": entry.get("knowledgeId"),
        "kind": entry.get("kind"),
        "title": entry.get("title"),
        "url": entry.get("url"),
        "summary": str(entry.get("summary") or "")[:500],
        "reliability": entry.get("reliability"),
        "lastSeenAt": entry.get("lastSeenAt"),
        "hitCount": entry.get("hitCount"),
        "tags": (entry.get("tags") or [])[:8],
        "sourceIds": (entry.get("sourceIds") or [])[:8],
    }


def _knowledge_record_view(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "recordId": record.get("recordId"),
        "type": record.get("type"),
        "summary": record.get("summary"),
        "content": str(record.get("content") or "")[:600],
        "status": record.get("status"),
        "confidence": record.get("confidence"),
        "knowledgeIds": (record.get("knowledgeIds") or [])[:8],
        "sourceIds": (record.get("sourceIds") or [])[:8],
        "tags": (record.get("tags") or [])[:8],
        "updatedAt": record.get("updatedAt"),
    }


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    for value in values:
        item = str(value or "").strip()
        if item and item not in result:
            result.append(item)
    return result


def _trace_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _merge_trace(*values: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for value in values:
        for item in _trace_list(value):
            key = (
                str(item.get("timestamp") or ""),
                str(item.get("kind") or ""),
                str(item.get("title") or ""),
                str(item.get("detail") or ""),
            )
            if key in seen:
                continue
            merged.append(item)
            seen.add(key)
    return merged
