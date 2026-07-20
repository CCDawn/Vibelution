"""Focused tests for session list cache slice."""

from __future__ import annotations

from core.web.services.session import list_cache


def test_session_list_cache_roundtrip_and_invalidate() -> None:
    signature = ("test-signature", True)
    list_cache.invalidate_session_list_cache()
    assert (
        list_cache.get_session_list_cache(now=100.0, signature=signature) is None
    )

    sessions = [
        {
            "id": "s1",
            "title": "alpha",
            "childSessionIds": ["c1"],
            "resultCard": {"changedFiles": ["a.py"], "validations": ["ok"]},
        }
    ]
    list_cache.set_session_list_cache(
        sessions,
        now=100.0,
        signature=signature,
        conversation_count=1,
        agent_count=2,
    )
    cached = list_cache.get_session_list_cache(now=101.0, signature=signature)
    assert cached is not None
    snapshot, age_ms, conversation_count, agent_count = cached
    assert conversation_count == 1
    assert agent_count == 2
    assert age_ms >= 0
    assert snapshot[0]["id"] == "s1"
    # defensive copy
    snapshot[0]["childSessionIds"].append("mutated")
    cached_again = list_cache.get_session_list_cache(now=101.0, signature=signature)
    assert cached_again is not None
    assert cached_again[0][0]["childSessionIds"] == ["c1"]

    list_cache.invalidate_session_list_cache()
    assert list_cache.get_session_list_cache(now=102.0, signature=signature) is None


def test_session_list_cache_single_flight_begin_finish() -> None:
    signature = ("inflight-signature", False)
    list_cache.invalidate_session_list_cache()
    cached, should_build, waited = list_cache.begin_session_list_cache_build(
        now=200.0,
        signature=signature,
    )
    assert cached is None
    assert should_build is True
    assert waited is False
    list_cache.finish_session_list_cache_build(
        signature=signature,
        sessions=[{"id": "built", "title": "t"}],
        started_at=200.0,
        conversation_count=3,
        agent_count=1,
    )
    hit = list_cache.get_session_list_cache(now=200.5, signature=signature)
    assert hit is not None
    assert hit[0][0]["id"] == "built"
    list_cache.invalidate_session_list_cache()
