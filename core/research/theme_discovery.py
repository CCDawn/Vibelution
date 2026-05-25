"""Theme discovery workflow service for the Research workbench."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from time import monotonic
from typing import Any, Iterable

from core.infrastructure.workspace_manager import get_workspace

from .models import (
    CandidateTheme,
    EvidenceRecord,
    ResearchDiscoverySession,
    ResearchSource,
    SearchRun,
    ThemeCard,
    new_id,
    utcnow_iso,
    validate_safe_id,
)
from .providers import (
    PublicResearchSearchProvider,
    ResearchSearchProvider,
    SearchResult,
    new_session_id,
    stable_evidence_id,
    stable_source_id,
)
from .repository import ResearchRepository
from .scoring import calculate_recommendation_score, deduplicate_themes


@dataclass
class SearchExecution:
    results: list[SearchResult] = field(default_factory=list)
    attempts: list[dict[str, Any]] = field(default_factory=list)


class ResearchThemeDiscoveryService:
    def __init__(
        self,
        *,
        repository: ResearchRepository | None = None,
        search_provider: ResearchSearchProvider | None = None,
    ):
        self.repository = repository or ResearchRepository()
        self.search_provider = search_provider or PublicResearchSearchProvider()

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
            execution = self._search_all(queries)
        except Exception as exc:
            self._fail_search_run(run, exc)
            raise
        result_sources = self._sources_from_results(session.session_id, run.run_id, execution.results)
        source_counts = dict(Counter(item.kind for item in execution.results))
        failed_count = sum(1 for item in execution.attempts if item.get("status") == "failed")
        sources = self.repository.load_sources(session.session_id)
        sources.extend(result_sources)
        run.status = "completed"
        run.completed_at = utcnow_iso()
        run.model_profile.update(
            {
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
            },
        )
        return self.get_session(session.session_id)

    def run_deep_search(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        queries = self._deep_queries(session, sources)
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
            execution = self._search_all(queries)
        except Exception as exc:
            self._fail_search_run(run, exc)
            raise
        result_sources = self._sources_from_results(session.session_id, run.run_id, execution.results)
        source_counts = dict(Counter(item.kind for item in execution.results))
        failed_count = sum(1 for item in execution.attempts if item.get("status") == "failed")
        merged_sources = self.repository.load_sources(session.session_id)
        merged_sources.extend(result_sources)
        run.status = "completed"
        run.completed_at = utcnow_iso()
        run.model_profile.update(
            {
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
            },
        )
        return self.get_session(session.session_id)

    def extract_evidence(self, session_id: str) -> dict[str, Any]:
        session = self.repository.load_session(session_id)
        sources = self.repository.load_sources(session.session_id)
        evidence = self.repository.load_evidence(session.session_id)
        known_ids = {item.evidence_id for item in evidence}
        extracted = [item for source in sources for item in self._evidence_from_source(source)]
        for item in extracted:
            if item.evidence_id not in known_ids:
                evidence.append(item)
                known_ids.add(item.evidence_id)
        self.repository.save_evidence(session.session_id, evidence)
        self._mark_downstream_stale(session.session_id, after_stage="evidence")
        self._touch_session(session, status="reviewing")
        self._event(
            session.session_id,
            "evidence.extracted",
            {
                "evidenceCount": len(evidence),
                "evidenceCounts": dict(Counter(item.evidence_type for item in evidence)),
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
        selected = deduplicate_themes(
            self._candidate_themes(session, sources, evidence),
            limit=session.candidate_count,
        )
        for theme in selected:
            theme.status = "shortlisted"
        self.repository.save_candidate_themes(session.session_id, [*existing, *selected])
        self._mark_theme_cards_stale(session.session_id)
        self._touch_session(session, status="reviewing")
        self._event(session.session_id, "themes.generated", {"candidateCount": len(selected)})
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
        card = self._theme_card(session, theme, sources)
        cards.append(card)
        self.repository.save_theme_cards(session.session_id, cards)
        self._touch_session(session, status="selected")
        self._event(session.session_id, "theme_card.generated", {"themeId": theme_id, "cardId": card.card_id})
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

    def _search_all(self, queries: Iterable[str]) -> SearchExecution:
        tasks = []
        query_list = list(queries)
        if not query_list:
            return SearchExecution()
        execution = SearchExecution()
        with ThreadPoolExecutor(max_workers=min(12, max(1, len(query_list) * 4))) as executor:
            for query in query_list:
                tasks.extend(
                    [
                        executor.submit(self._provider_search, "paper", query),
                        executor.submit(self._provider_search, "github", query),
                        executor.submit(self._provider_search, "dataset", query),
                        executor.submit(self._provider_search, "web", query),
                    ]
                )
            for task in as_completed(tasks):
                try:
                    results, attempt = task.result()
                    execution.results.extend(results)
                    execution.attempts.append(attempt)
                except ValueError:
                    raise
                except Exception as exc:
                    execution.attempts.append(
                        {
                            "kind": "unknown",
                            "query": "",
                            "status": "failed",
                            "resultCount": 0,
                            "durationMs": 0,
                            "error": str(exc)[:500],
                        }
                    )
                    continue
        execution.attempts.sort(key=lambda item: (str(item.get("query") or ""), str(item.get("kind") or "")))
        return execution

    def _provider_search(self, kind: str, query: str) -> tuple[list[SearchResult], dict[str, Any]]:
        started = monotonic()
        method = {
            "paper": self.search_provider.search_papers,
            "github": self.search_provider.search_github,
            "dataset": self.search_provider.search_datasets,
            "web": self.search_provider.search_web,
        }[kind]
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

    def _evidence_from_source(self, source: ResearchSource) -> list[EvidenceRecord]:
        if source.kind == "paper":
            return [
                EvidenceRecord(
                    evidence_id=stable_evidence_id(source.source_id, "gap"),
                    session_id=source.session_id,
                    source_id=source.source_id,
                    claim=f"{source.title} suggests a research gap or method question around {source.snippet[:180]}",
                    evidence_type="gap",
                    confidence="medium",
                    note="Academic source treated as verified, but the extracted gap still needs literature confirmation.",
                ),
                EvidenceRecord(
                    evidence_id=stable_evidence_id(source.source_id, "method"),
                    session_id=source.session_id,
                    source_id=source.source_id,
                    claim=f"{source.title} can inform a method-transfer path for AI Scientist theme discovery.",
                    evidence_type="method",
                    confidence="medium",
                    note="Method evidence is a candidate bridge, not proof of novelty.",
                ),
            ]
        if source.kind == "dataset":
            return [
                EvidenceRecord(
                    evidence_id=stable_evidence_id(source.source_id, "dataset"),
                    session_id=source.session_id,
                    source_id=source.source_id,
                    claim=f"{source.title} indicates a possible public validation or benchmark path.",
                    evidence_type="dataset",
                    confidence="high",
                    note="Dataset source supports feasibility, not final experimental sufficiency.",
                )
            ]
        if source.kind == "github":
            return [
                EvidenceRecord(
                    evidence_id=stable_evidence_id(source.source_id, "implementation"),
                    session_id=source.session_id,
                    source_id=source.source_id,
                    claim=f"{source.title} indicates implementation or baseline clues for a prototype.",
                    evidence_type="implementation",
                    confidence="high",
                    note="GitHub evidence supports buildability and baseline exploration.",
                )
            ]
        return [
            EvidenceRecord(
                evidence_id=stable_evidence_id(source.source_id, "background"),
                session_id=source.session_id,
                source_id=source.source_id,
                claim=f"{source.title} provides background context for competition fit and domain framing.",
                evidence_type="background",
                confidence="medium" if source.reliability == "normal" else "low",
                note="Web background should not independently prove scientific novelty.",
            )
        ]

    def _candidate_themes(
        self,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        evidence: list[EvidenceRecord],
    ) -> list[CandidateTheme]:
        source_ids = [item.source_id for item in sources[:8]]
        evidence_ids = [item.evidence_id for item in evidence[:12]]
        anchors = self._theme_anchors(session, sources, evidence)
        themes: list[CandidateTheme] = []
        novelty_paths = [
            "problem_perspective",
            "method_transfer",
            "discipline_combination",
            "application_scenario",
            "problem_perspective",
            "method_transfer",
            "discipline_combination",
            "application_scenario",
        ]
        for index, anchor in enumerate(anchors[:12]):
            novelty_path = novelty_paths[index % len(novelty_paths)]
            scores = self._scores_for_anchor(index, novelty_path, anchor, session)
            themes.append(
                CandidateTheme(
                    theme_id=new_id("theme"),
                    session_id=session.session_id,
                    title=anchor["title"],
                    one_line=anchor["oneLine"],
                    interdisciplinary_combination=anchor["disciplines"],
                    core_question=anchor["question"],
                    novelty_path=novelty_path,  # type: ignore[arg-type]
                    scores=scores,
                    recommendation_score=calculate_recommendation_score(scores),
                    source_ids=source_ids,
                    evidence_ids=evidence_ids,
                    uncertainty=anchor["uncertainty"],
                    agent_review=anchor["agentReview"],
                    status="draft",
                    version=1,
                    parent_run_id=self._latest_run_id(session.session_id),
                )
            )
        return themes

    def _theme_anchors(
        self,
        session: ResearchDiscoverySession,
        sources: list[ResearchSource],
        evidence: list[EvidenceRecord],
    ) -> list[dict[str, Any]]:
        keywords = self._keywords([session.open_goal, session.constraints, session.preferences, *[s.title for s in sources]])
        primary = keywords[0] if keywords else "scientific discovery"
        secondary = keywords[1] if len(keywords) > 1 else "causal reasoning"
        tertiary = keywords[2] if len(keywords) > 2 else "open-source agents"
        dataset_count = sum(1 for item in evidence if item.evidence_type == "dataset")
        implementation_count = sum(1 for item in evidence if item.evidence_type == "implementation")
        feasibility_note = (
            "Dataset and implementation clues are present."
            if dataset_count and implementation_count
            else "Validation evidence is still thin and needs deeper search."
        )
        return [
            {
                "title": f"Mechanism-gap discovery for {primary}",
                "oneLine": "Use AI Scientist to find mechanism-level gaps rather than only summarizing literature.",
                "disciplines": ["computer science", "science of science", "causal reasoning"],
                "question": f"Can an AI Scientist identify under-specified mechanisms in {primary} and turn them into falsifiable questions?",
                "uncertainty": "Novelty depends on whether deep literature search finds existing mechanism-gap benchmarks.",
                "agentReview": f"I recommend this because it makes the research problem about mechanisms, not a generic tool. {feasibility_note}",
            },
            {
                "title": f"Causal falsifiability filters for {secondary} hypothesis generation",
                "oneLine": "Transfer causal counterfactual thinking into AI-generated scientific hypothesis review.",
                "disciplines": ["computer science", "causal science", "research methodology"],
                "question": f"Can counterfactual constraints make AI-generated hypotheses about {secondary} more falsifiable and less speculative?",
                "uncertainty": "Requires checking whether comparable causal filters already exist in AI Scientist systems.",
                "agentReview": "This is strong on problem perspective and method transfer; the main gap is finding a clean benchmark.",
            },
            {
                "title": f"Scientific blind-spot mapping across {primary} and {tertiary}",
                "oneLine": "Build a theme around finding unexamined intersections instead of optimizing known benchmarks.",
                "disciplines": ["computer science", "scientometrics", "open-source software"],
                "question": f"Can source, paper, and dataset evidence reveal blind spots between {primary} and {tertiary}?",
                "uncertainty": "Risk: it may look like literature mining unless framed around scientific question discovery.",
                "agentReview": "The evidence mix supports a discovery workflow, but the final topic must keep a mechanism question visible.",
            },
            {
                "title": f"Validation-first theme selection for AI Scientist in {primary}",
                "oneLine": "Study how AI Scientist should choose topics by novelty while preserving minimum verifiability.",
                "disciplines": ["computer science", "experimental design", "AI evaluation"],
                "question": f"How can AI Scientist rank novel {primary} topics without selecting ideas that cannot be tested?",
                "uncertainty": "This may be meta-scientific; competition fit is high, but domain specificity must be sharpened.",
                "agentReview": "This fits the current workbench exactly and can be shown clearly, though it risks being too self-referential.",
            },
            {
                "title": f"Cognitive-control inspired uncertainty review for {secondary}",
                "oneLine": "Borrow metacognitive uncertainty review to make AI Scientist topic proposals more rigorous.",
                "disciplines": ["computer science", "cognitive neuroscience", "metacognition"],
                "question": f"Can metacognitive review signals improve how AI Scientist rejects weakly evidenced {secondary} themes?",
                "uncertainty": "Needs evidence that cognitive-control concepts transfer beyond metaphor.",
                "agentReview": "This is novel by problem perspective and interdisciplinary lens; validation may require careful operationalization.",
            },
            {
                "title": f"Open-source reproducibility gaps as AI Scientist research opportunities",
                "oneLine": "Use GitHub and dataset evidence to find research questions hidden in reproducibility failures.",
                "disciplines": ["computer science", "software engineering", "open science"],
                "question": "Can AI Scientist turn reproducibility gaps in open-source projects into scientific hypotheses?",
                "uncertainty": "May become engineering-heavy unless hypotheses explain why reproducibility breaks.",
                "agentReview": "GitHub evidence makes this buildable; the scientific frame needs causal or mechanism language.",
            },
            {
                "title": f"Dataset-absence as a signal for under-studied {primary} problems",
                "oneLine": "Treat missing public datasets as a structured clue for scientific opportunity discovery.",
                "disciplines": ["computer science", "data-centric AI", "science of science"],
                "question": f"When does dataset absence reveal a real research gap rather than a poor search strategy in {primary}?",
                "uncertainty": "The system must distinguish evidence absence from search failure.",
                "agentReview": "This is conceptually sharp and honest about novelty limits, but first-stage results must expose uncertainty.",
            },
            {
                "title": f"Competition-fit aware AI Scientist topic discovery for {primary}",
                "oneLine": "Model how an AI Scientist balances scientific value, novelty, and feasibility under contest constraints.",
                "disciplines": ["computer science", "decision science", "research planning"],
                "question": f"Can contest constraints guide AI Scientist toward better {primary} research questions without overfitting to scoring rubrics?",
                "uncertainty": "Strong for this project, but needs a specific scientific domain later.",
                "agentReview": "This is useful for selection, but less novel than mechanism or causal-filter themes.",
            },
        ]

    def _scores_for_anchor(
        self,
        index: int,
        novelty_path: str,
        anchor: dict[str, Any],
        session: ResearchDiscoverySession,
    ) -> dict[str, float]:
        novelty_bonus = {
            "problem_perspective": 9,
            "method_transfer": 6,
            "discipline_combination": 3,
            "application_scenario": 0,
        }.get(novelty_path, 0)
        preference_bonus = 4 if "novel" in session.preferences.lower() or "新" in session.preferences else 0
        base = 72 - min(index, 7) * 2
        return {
            "noveltyGap": min(96, base + novelty_bonus + preference_bonus),
            "scientificValue": min(94, base + 7 if "mechanism" in anchor["title"].lower() else base + 4),
            "technicalDepth": min(90, base + 5 if novelty_path in {"method_transfer", "problem_perspective"} else base),
            "interdisciplinaryAuthenticity": min(92, base + 6 if len(anchor["disciplines"]) >= 3 else base),
            "verifiability": min(88, base + 2),
            "competitionFit": min(94, base + 8),
            "implementationFeasibility": min(84, base + 1),
        }

    def _theme_card(
        self,
        session: ResearchDiscoverySession,
        theme: CandidateTheme,
        sources: list[ResearchSource],
    ) -> ThemeCard:
        references = [f"{source.title} - {source.url}" for source in sources if source.source_id in theme.source_ids][:8]
        if not references:
            references = [f"{source.title} - {source.url}" for source in sources[:5]]
        return ThemeCard(
            card_id=new_id("theme-card"),
            session_id=session.session_id,
            theme_id=theme.theme_id,
            title=theme.title,
            one_line=theme.one_line,
            core_scientific_question=theme.core_question,
            why_novel=(
                f"This theme prioritizes {theme.novelty_path.replace('_', ' ')}. "
                "It is framed as a candidate research gap, not as a proven undiscovered problem."
            ),
            why_competition_fit=(
                "It fits AI Scientist because the system discovers a research question from sources, "
                "keeps evidence provenance, and prepares a next-step scientific plan."
            ),
            interdisciplinary_combination=theme.interdisciplinary_combination,
            possible_datasets=[
                "Public benchmark or dataset source identified during discovery",
                "Small curated validation set built from verified sources",
            ],
            possible_methods=[
                "Evidence-grounded literature and source synthesis",
                "Novelty-first scoring with uncertainty review",
                "Human approval before deeper research planning",
            ],
            possible_experiments=[
                "Compare selected theme quality against generic literature-search baselines",
                "Ask domain reviewers to judge novelty, falsifiability, and evidence grounding",
            ],
            risks=[
                "Current search evidence may miss prior work.",
                "Novelty must be confirmed by deeper literature review before final submission.",
                "Conceptual interdisciplinarity must become an operational hypothesis later.",
            ],
            references=references,
            next_research_steps=[
                "Run deeper paper search around the exact core question.",
                "Verify dataset and benchmark availability.",
                "Draft a falsifiable hypothesis and concept-level research plan.",
            ],
            agent_review=theme.agent_review,
            status="draft",
            version=self._next_card_version(session.session_id, theme.theme_id),
        )

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
        self.repository.append_event(
            session_id,
            {
                "eventCode": event_code,
                "timestamp": utcnow_iso(),
                "fields": fields,
            },
        )

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

    def _deep_queries(self, session: ResearchDiscoverySession, sources: list[ResearchSource]) -> list[str]:
        keywords = self._keywords([session.open_goal, session.constraints, session.preferences, *[item.title for item in sources]])
        if not keywords:
            keywords = ["AI Scientist", "causal hypothesis", "scientific discovery"]
        base = " ".join(keywords[:4])
        return [
            f"{base} falsifiable scientific hypothesis",
            f"{base} causal mechanism research gap",
            f"{base} public dataset benchmark open source",
        ]

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
        return {
            "provider": "configured-vibelution-provider",
            "mode": "research-theme-discovery",
            "agentRole": "theme-discovery-research-agent",
            "runtimeDataPolicy": "live-public-network-only-by-default",
            "promptSource": prompts["root"],
            "promptFiles": prompts["files"],
            "note": "MVP uses live public research search by default; tests may inject deterministic providers.",
        }

    def _research_prompt_profile(self) -> dict[str, Any]:
        workspace = get_workspace()
        files = {}
        for key, filename in {
            "broad": "broad.md",
            "deep": "deep.md",
            "review": "review.md",
            "themes": "themes.md",
            "card": "card.md",
        }.items():
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
