"""T5.1-3 RED: real readiness providers + agent resolvability.

Production RealDomainReadinessContext must query domain authorities without
depending on domain_overrides, return a real domain_revision_vector, and
resolve agents via Agent Directory (not bool(agent_id)).
"""

from __future__ import annotations

from pathlib import Path

from core.web.services.team_workflow.research_runtime.real_readiness_context import (
    RealDomainReadinessContext,
)
from tests._support.command_helpers import CommandHarness


def test_agent_resolvable_rejects_unknown_nonempty_id(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        ctx = RealDomainReadinessContext(harness.store)
        assert ctx.agent_resolvable("") is False
        assert ctx.agent_resolvable("agent-definitely-missing-t513") is False
    finally:
        harness.close()


def test_domain_revision_vector_is_not_permanently_empty(tmp_path: Path) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ctx = RealDomainReadinessContext(harness.store)
        vector = dict(ctx.domain_revision_vector("research-team", "run-test"))
        assert vector, "production readiness must expose a real domain revision vector"
        assert all(str(v).strip() for v in vector.values())
    finally:
        harness.close()


def test_candidate_stats_uses_provider_not_only_override(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        calls: list[tuple[str, str]] = []

        def fake_stats(team_id: str, run_id: str, **_kwargs):
            calls.append((team_id, run_id))
            return {"record_count": 4}

        original = readiness_providers.fetch_candidate_stats
        readiness_providers.fetch_candidate_stats = fake_stats  # type: ignore[assignment]
        try:
            ctx = RealDomainReadinessContext(harness.store)  # no domain_overrides
            stats = ctx.candidate_stats("research-team", "run-test")
            assert stats == {"record_count": 4}
            assert calls == [("research-team", "run-test")]
        finally:
            readiness_providers.fetch_candidate_stats = original  # type: ignore[assignment]
    finally:
        harness.close()


def test_evidence_cards_stats_provider_wired(tmp_path: Path) -> None:
    from core.web.services.team_workflow.research_runtime import readiness_providers

    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        original = readiness_providers.fetch_evidence_cards_stats

        def fake_cards(team_id: str, run_id: str, **_kwargs):
            return {"card_count": 2, "missing_minimal_fields": []}

        readiness_providers.fetch_evidence_cards_stats = fake_cards  # type: ignore[assignment]
        try:
            ctx = RealDomainReadinessContext(harness.store)
            assert ctx.evidence_cards_stats("research-team", "run-test") == {
                "card_count": 2,
                "missing_minimal_fields": [],
            }
        finally:
            readiness_providers.fetch_evidence_cards_stats = original  # type: ignore[assignment]
    finally:
        harness.close()


def test_production_context_does_not_require_domain_overrides_for_revision(
    tmp_path: Path,
) -> None:
    harness = CommandHarness(tmp_path / "ledger.sqlite3")
    try:
        harness.seed_run()
        ctx = RealDomainReadinessContext(harness.store, service_overrides=None)
        # Must not crash and must not return empty forever.
        vector = ctx.domain_revision_vector("research-team", "run-test")
        assert isinstance(vector, dict)
        assert len(vector) >= 1
    finally:
        harness.close()
