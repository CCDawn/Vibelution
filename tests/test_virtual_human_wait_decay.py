"""Unanswered-wait mood decay, feedback clamps and relationship tone guidance."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.agent_plugins.virtual_human_life.affect import (
    unanswered_wait_valence_dip,
)
from core.agent_plugins.virtual_human_life.relationship_events import (
    clamp_relationship_feedback_deltas,
    relationship_tone_guidance,
)
from core.agent_plugins.virtual_human_life.service import VirtualHumanLifeService

UTC = timezone.utc


def _make_service(tmp_path, now: datetime) -> VirtualHumanLifeService:
    agent = {
        "agentId": "agent-a",
        "status": "active",
        "directSessionId": "session-a",
    }
    service = VirtualHumanLifeService(
        project_root=tmp_path,
        agent_loader=lambda agent_id, include_archived=False: (
            agent if agent_id == "agent-a" else None
        ),
        agent_lister=lambda: [agent],
        plugin_root_resolver=lambda agent_id: tmp_path / "agents" / agent_id,
        now_provider=lambda: now,
    )
    service.set_binding("agent-a", enabled=True, expected_version=0)
    return service


class TestUnansweredWaitValenceDip:
    def test_grace_window_keeps_the_dip_at_zero(self) -> None:
        delivered = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        now = delivered + timedelta(hours=5, minutes=59)
        assert unanswered_wait_valence_dip(delivered, now=now) == 0

    def test_dip_grows_with_elapsed_time_and_caps(self) -> None:
        delivered = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        early = unanswered_wait_valence_dip(
            delivered, now=delivered + timedelta(hours=12)
        )
        later = unanswered_wait_valence_dip(
            delivered, now=delivered + timedelta(hours=30)
        )
        much_later = unanswered_wait_valence_dip(
            delivered, now=delivered + timedelta(days=7)
        )
        assert -12 <= later < early < 0
        assert early == -3
        assert later == -12 == much_later

    def test_same_wall_clock_is_heartbeat_independent(self) -> None:
        delivered = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        now = delivered + timedelta(hours=20)
        # Re-deriving the wait any number of times in the same instant yields
        # the same dip: heartbeats cannot accelerate the decay.
        assert [unanswered_wait_valence_dip(delivered, now=now) for _ in range(5)] == [
            unanswered_wait_valence_dip(delivered, now=now)
        ] * 5

    def test_future_delivery_evidence_never_dips(self) -> None:
        delivered = datetime(2026, 10, 18, 0, 0, tzinfo=UTC)
        now = delivered - timedelta(hours=3)
        assert unanswered_wait_valence_dip(delivered, now=now) == 0


class TestRelationshipFeedbackClamps:
    def test_boundary_feedback_never_drops_intimacy_or_trust(self) -> None:
        assert clamp_relationship_feedback_deltas(
            "用户表达了边界：先不要打扰",
            intimacy_delta=-6,
            trust_delta=-4,
        ) == (0, 0)
        assert clamp_relationship_feedback_deltas(
            "user set a boundary: not_now",
            intimacy_delta=-6,
            trust_delta=-4,
        ) == (0, 0)

    def test_positive_deltas_pass_through_for_boundary_feedback(self) -> None:
        assert clamp_relationship_feedback_deltas(
            "边界：诚实表达了需要空间", intimacy_delta=2, trust_delta=3
        ) == (2, 3)

    def test_single_misunderstanding_protects_intimacy_only(self) -> None:
        assert clamp_relationship_feedback_deltas(
            "一次误解：会错意了", intimacy_delta=-5, trust_delta=-3
        ) == (0, -3)

    def test_repeated_misunderstanding_pattern_may_drop(self) -> None:
        assert clamp_relationship_feedback_deltas(
            "又一次误解",
            intimacy_delta=-5,
            trust_delta=-3,
            recent_kinds=["误解：上次会错意"],
        ) == (-5, -3)

    def test_ordinary_conflict_is_not_clamped(self) -> None:
        assert clamp_relationship_feedback_deltas(
            "争执：意见不合", intimacy_delta=-7, trust_delta=-7
        ) == (-7, -7)


class TestRelationshipToneGuidance:
    def test_bands_follow_intimacy_and_trust(self) -> None:
        close = relationship_tone_guidance(80, 70)
        shallow = relationship_tone_guidance(20, 60)
        low_trust = relationship_tone_guidance(50, 20)
        natural = relationship_tone_guidance(50, 60)
        assert close.startswith("关系亲近")
        assert shallow.startswith("关系尚浅")
        assert low_trust.startswith("信任正在建立")
        assert natural.startswith("关系自然")

    def test_invalid_values_fall_back_to_the_natural_band(self) -> None:
        assert relationship_tone_guidance(None, "x").startswith("关系自然")


class TestServiceWaitBaseline:
    def _write_candidates(self, service: VirtualHumanLifeService, rows: list[dict]) -> None:
        service.store.write_jsonl("agent-a", "proactive/candidates.jsonl", rows)

    def test_delivered_unanswered_wait_shifts_the_projection_baseline(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        delivered_at = (now - timedelta(hours=30)).isoformat()
        self._write_candidates(service, [
            {
                "candidateId": "candidate-1",
                "status": "delivered",
                "deliveredAt": delivered_at,
                "topicKey": "walk-plan",
            }
        ])
        baseline = service._affect_baseline("agent-a")
        adjusted = service._unanswered_wait_baseline(
            "agent-a", now=now, baseline=baseline
        )
        assert adjusted["valence"] == baseline["valence"] - 12

    def test_selected_without_delivery_receipt_never_waits(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        self._write_candidates(service, [
            {
                "candidateId": "candidate-2",
                "status": "selected",
                "selectedAt": (now - timedelta(hours=30)).isoformat(),
                "topicKey": "walk-plan",
            }
        ])
        baseline = service._affect_baseline("agent-a")
        assert service._unanswered_wait_baseline(
            "agent-a", now=now, baseline=baseline
        )["valence"] == baseline["valence"]

    def test_user_reply_clears_the_wait(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        self._write_candidates(service, [
            {
                "candidateId": "candidate-3",
                "status": "delivered",
                "deliveredAt": (now - timedelta(hours=30)).isoformat(),
                "userRepliedAt": (now - timedelta(hours=28)).isoformat(),
                "topicKey": "walk-plan",
            }
        ])
        baseline = service._affect_baseline("agent-a")
        assert service._unanswered_wait_baseline(
            "agent-a", now=now, baseline=baseline
        )["valence"] == baseline["valence"]

    def test_stale_wait_beyond_three_days_is_ignored(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        self._write_candidates(service, [
            {
                "candidateId": "candidate-4",
                "status": "delivered",
                "deliveredAt": (now - timedelta(days=4)).isoformat(),
                "topicKey": "walk-plan",
            }
        ])
        baseline = service._affect_baseline("agent-a")
        assert service._unanswered_wait_baseline(
            "agent-a", now=now, baseline=baseline
        )["valence"] == baseline["valence"]

    def test_multiple_unanswered_waits_use_the_oldest_only(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        self._write_candidates(service, [
            {
                "candidateId": "candidate-5",
                "status": "delivered",
                "deliveredAt": (now - timedelta(hours=30)).isoformat(),
                "topicKey": "walk-plan",
            },
            {
                "candidateId": "candidate-6",
                "status": "delivered",
                "deliveredAt": (now - timedelta(hours=10)).isoformat(),
                "topicKey": "reading-share",
            },
        ])
        baseline = service._affect_baseline("agent-a")
        # Only the oldest wait counts: two unanswered messages must not stack.
        assert service._unanswered_wait_baseline(
            "agent-a", now=now, baseline=baseline
        )["valence"] == baseline["valence"] - 12

    def test_snapshot_causal_projection_carries_wait_and_tone(self, tmp_path) -> None:
        now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
        service = _make_service(tmp_path, now)
        self._write_candidates(service, [
            {
                "candidateId": "candidate-7",
                "status": "delivered",
                "deliveredAt": (now - timedelta(hours=30)).isoformat(),
                "topicKey": "walk-plan",
            }
        ])
        snapshot = service.snapshot("agent-a")
        mood_valence = snapshot["causal"]["affect"]["mood"]["valence"]
        baseline_valence = snapshot["causal"]["affect"]["baselineMood"]["valence"]
        # Without wait the untouched baseline is 12; a 30h unanswered wait shifts
        # the effective baseline by -12, and the mood follows it.
        assert baseline_valence <= 12 - 6
        assert mood_valence <= baseline_valence
        assert snapshot["causal"]["relationshipTone"].startswith("关系")


class TestServiceRelationshipCommandClamp:
    def test_boundary_interaction_keeps_relationship_undropped(self, tmp_path) -> None:
        now = [datetime(2026, 10, 19, 12, 0, tzinfo=UTC)]
        service = _make_service(tmp_path, now[0])
        version = service.snapshot("agent-a")["state"]["stateVersion"]
        result = service.execute_command(
            "agent-a",
            command="recordRelationshipInteraction",
            expected_version=version,
            idempotency_key="boundary-1",
            arguments={
                "targetId": "user",
                "kind": "boundary：用户说先不要打扰",
                "intimacyDelta": -6,
                "trustDelta": -4,
                "sourceTurnId": "turn-boundary",
            },
        )
        relationship = result["result"]["relationship"]
        assert relationship["intimacy"] >= 50
        assert relationship["trust"] >= 50
        events = service.store.read_jsonl("agent-a", "relationships/events.jsonl")
        assert events[-1]["intimacyDelta"] >= 0
        assert events[-1]["trustDelta"] >= 0

    def test_single_misunderstanding_keeps_intimacy(self, tmp_path) -> None:
        now = [datetime(2026, 10, 19, 12, 0, tzinfo=UTC)]
        service = _make_service(tmp_path, now[0])
        version = service.snapshot("agent-a")["state"]["stateVersion"]
        service.execute_command(
            "agent-a",
            command="recordRelationshipInteraction",
            expected_version=version,
            idempotency_key="misunderstand-1",
            arguments={
                "targetId": "user",
                "kind": "误解：会错意了",
                "intimacyDelta": -5,
                "trustDelta": -3,
                "sourceTurnId": "turn-misunderstand",
            },
        )
        events = service.store.read_jsonl("agent-a", "relationships/events.jsonl")
        assert events[-1]["intimacyDelta"] >= 0
        assert events[-1]["trustDelta"] == -3
