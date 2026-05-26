"""Theme discovery workflow service for the Research workbench."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from core.infrastructure.workspace_manager import get_workspace

from .agent_runner import LLMResearchAgentRunner, ResearchAgentRunner
from .agent_templates import RESEARCH_PROMPT_FILES, ensure_research_prompt_defaults, normalize_research_agent_config
from .models import (
    CandidateTheme,
    EvidenceRecord,
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
    ):
        self.repository = repository or ResearchRepository()
        self.search_provider = search_provider or PublicResearchSearchProvider()
        self.agent_runner = agent_runner or LLMResearchAgentRunner(search_provider=self.search_provider)

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
        self._append_search_run(session.session_id, run)
        try:
            execution = self.agent_runner.run_search(
                phase="broad",
                session=session,
                suggested_queries=queries,
                existing_sources=self.repository.load_sources(session.session_id),
                trace_sink=self._search_trace_sink(run),
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
        self._mark_downstream_stale(session.session_id, after_stage="search")
        self._touch_session(session, status="reviewing")
        self._event(
            session.session_id,
            "search.broad.completed",
            {
                "queryCount": len(queries),
                "sourceCount": len(result_sources),
                "sourceCounts": source_counts,
                "failedAttemptCount": failed_count,
                "agentKey": execution.profile.get("agentKey"),
                "agentExecution": execution.profile,
                "trace": execution.trace,
            },
        )
        return self.get_session(session.session_id)

    def run_deep_search(self, session_id: str, evidence_requests: list[str] | None = None) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        queries = self._deep_queries(session, sources, evidence_requests=evidence_requests)
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
        self._append_search_run(session.session_id, run)
        try:
            execution = self.agent_runner.run_search(
                phase="deep",
                session=session,
                suggested_queries=queries,
                existing_sources=sources,
                trace_sink=self._search_trace_sink(run),
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
        self._mark_downstream_stale(session.session_id, after_stage="search")
        self._touch_session(session, status="reviewing")
        self._event(
            session.session_id,
            "search.deep.completed",
            {
                "queryCount": len(queries),
                "sourceCount": len(result_sources),
                "sourceCounts": source_counts,
                "failedAttemptCount": failed_count,
                "evidenceRequests": _string_list(evidence_requests),
                "agentKey": execution.profile.get("agentKey"),
                "agentExecution": execution.profile,
                "trace": execution.trace,
            },
        )
        return self.get_session(session.session_id)

    def extract_evidence(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        evidence = self.repository.load_evidence(session.session_id)
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
        return self.get_session(session.session_id)

    def generate_themes(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        evidence = self.repository.load_evidence(session.session_id)
        if not sources:
            raise ValueError("Run search before generating themes.")
        if not evidence:
            raise ValueError("Extract evidence before generating themes.")
        existing = self.repository.load_candidate_themes(session.session_id)
        for theme in existing:
            if theme.status in {"draft", "shortlisted"}:
                theme.status = "stale"
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
        return self.get_session(session.session_id)

    def select_theme(self, session_id: str, theme_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        theme_id = validate_safe_id(theme_id, label="theme id")
        themes = self.repository.load_candidate_themes(session.session_id)
        target = next((item for item in themes if item.theme_id == theme_id), None)
        if target is None:
            raise FileNotFoundError("Candidate theme not found.")
        if target.status == "stale":
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
            raise FileNotFoundError("Candidate theme not found.")
        if theme.status == "stale":
            raise ValueError("Cannot generate a theme card from a stale candidate theme.")
        cards = self.repository.load_theme_cards(session.session_id)
        for card in cards:
            if card.theme_id == theme_id and card.status == "draft":
                card.status = "stale"
        sources = self.repository.load_sources(session.session_id)
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
        return self.get_session(session.session_id)

    def approve_theme_card(self, session_id: str, card_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        card_id = validate_safe_id(card_id, label="theme card id")
        cards = self.repository.load_theme_cards(session.session_id)
        target = next((item for item in cards if item.card_id == card_id), None)
        if target is None:
            raise FileNotFoundError("Theme card not found.")
        if target.status == "stale":
            raise ValueError("Cannot approve a stale theme card.")
        for card in cards:
            if card.card_id == card_id:
                card.status = "approved"
        self.repository.save_theme_cards(session.session_id, cards)
        self._touch_session(session, status="selected")
        self._event(session.session_id, "theme_card.approved", {"cardId": card_id})
        return self.get_session(session.session_id)

    def run_draft(self, session_id: str) -> dict[str, Any]:
        self.run_broad_search(session_id)
        self.run_deep_search(session_id)
        self.extract_evidence(session_id)
        return self.generate_themes(session_id)

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
            {"errorType": exc.__class__.__name__, "message": str(exc), "queryCount": len(run.queries)},
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
                outcome="failed" if event_code.endswith(".failed") else "succeeded",
                phase=_research_phase_from_event_code(event_code),
                fields=fields,
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
        try:
            raw = workspace.read_research_agent_config()
        except Exception:
            raw = {}
        config = normalize_research_agent_config(raw)
        return {
            "configPath": str(workspace.get_research_agent_config_path()),
            "agents": config["agents"],
        }

    def _research_prompt_profile(self) -> dict[str, Any]:
        workspace = get_workspace()
        ensure_research_prompt_defaults(workspace)
        files = {}
        for key, filename in RESEARCH_PROMPT_FILES.items():
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
    if text.startswith("search.broad."):
        return "broad_search"
    if text.startswith("search.deep."):
        return "deep_search"
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


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


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
