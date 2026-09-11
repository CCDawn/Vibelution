"""Structured heartbeat + RetryPolicy contract tests for the citation recheck.

SCI-049 follow-up: covers the heartbeat payload/counting contract, the
interrupted-run resume semantics (per-URL persistence), the Temporal-style
RetryPolicy parameters (env overrides, backoff curve, max-interval cap) and
the non-retryable short-circuit.  Every DOI lookup is an injected fake —
no real network.
"""

from __future__ import annotations

import pytest

from core.web.services.team_workflow import citation_recheck
from core.web.services.team_workflow.citation_recheck import (
    HEARTBEAT_CONTRACT,
    HEARTBEAT_STAGE,
    KIND_ATTEMPT,
    KIND_HEARTBEAT,
    KIND_URL_RESULT,
    RECORD_KIND,
    NonRetryableReceiptError,
    RetryPolicy,
    load_retry_policy_from_env,
    progress_report,
    read_resume_verified,
    verify_receipts_with_heartbeat,
)
from core.web.services.team_workflow.doi_metadata_verification import (
    DefinitiveDoiRejection,
)

TEAM_ID = "research-team"
QUESTION_ID = "SCI-096"
RUN_ID = "run-sci-096"


def _check(source_url: str, *, status: str = "failed", doi: str = "") -> dict:
    return {"sourceUrl": source_url, "status": status, "doi": doi}


def _metadata(doi: str) -> dict:
    return {"DOI": doi, "title": ["Real paper"]}


def _run(
    tmp_path,
    checks,
    verifier,
    *,
    ledger_name: str = "run.citation-recheck.jsonl",
    retry_policy: RetryPolicy | None = None,
    sleeper=None,
    monotonic=None,
    **kwargs,
):
    ledger = tmp_path / ledger_name
    report = verify_receipts_with_heartbeat(
        checks,
        team_id=TEAM_ID,
        question_id=QUESTION_ID,
        run_id=RUN_ID,
        ledger_path=ledger,
        verifier=verifier,
        retry_policy=retry_policy if retry_policy is not None else RetryPolicy(maximum_attempts=1),
        sleeper=sleeper if sleeper is not None else (lambda _seconds: None),
        monotonic=monotonic if monotonic is not None else (lambda: 0.0),
        **kwargs,
    )
    return ledger, report


def _records_of_kind(ledger, kind: str) -> list[dict]:
    return [
        record
        for record in citation_recheck.read_recheck_events(ledger)
        if record.get("kind") == kind
    ]


def test_heartbeat_payload_structure_and_counting(tmp_path):
    checks = [
        _check("https://doi.org/10.1103/a", doi="10.1103/a"),
        _check("https://example.org/already-passed", status="passed"),
        _check("https://doi.org/10.1103/c", doi="10.1103/c"),
        _check("https://example.org/no-doi"),
    ]
    calls: list[str] = []

    def verifier(doi: str):
        calls.append(doi)
        return _metadata(doi)

    ledger, report = _run(tmp_path, checks, verifier)

    heartbeats = _records_of_kind(ledger, KIND_HEARTBEAT)
    # One heartbeat per evidence row: the progress covers the whole set.
    assert [record["done"] for record in heartbeats] == [1, 2, 3, 4]
    assert all(record["total"] == 4 for record in heartbeats)
    assert all(record["stage"] == HEARTBEAT_STAGE for record in heartbeats)
    assert all(record["recordKind"] == RECORD_KIND for record in heartbeats)
    assert all(record["etaSeconds"] >= 0.0 for record in heartbeats)
    assert all(record["at"] and record["atMs"] > 0 for record in heartbeats)
    # One attemptId per invocation, shared by attempt + heartbeat records.
    attempt_ids = {record["attemptId"] for record in heartbeats}
    assert len(attempt_ids) == 1

    attempts = _records_of_kind(ledger, KIND_ATTEMPT)
    assert attempts[0]["status"] == "running"
    assert attempts[0]["total"] == 4
    assert attempts[-1]["status"] == "finished"
    assert attempts[-1]["outcome"] == "completed"

    url_results = _records_of_kind(ledger, KIND_URL_RESULT)
    assert {record["sourceUrl"] for record in url_results} == {
        "https://doi.org/10.1103/a",
        "https://doi.org/10.1103/c",
        "https://example.org/no-doi",
    }
    verified_results = [r for r in url_results if r["outcome"] == "verified"]
    assert len(verified_results) == 2
    assert all(record["attempts"] == 1 for record in verified_results)

    # Report keys of the pre-existing verifier contract keep their semantics.
    assert report["attemptedCount"] == 2  # only DOI-bearing URLs hit the network
    assert report["verifiedCount"] == 2
    assert set(report["verifiedSourceUrls"]) == {
        "https://doi.org/10.1103/a",
        "https://doi.org/10.1103/c",
    }
    assert report["unresolvedSourceUrls"] == []
    assert report["resumedSourceUrls"] == []
    assert report["failedSourceUrls"] == [
        {"sourceUrl": "https://example.org/no-doi", "reason": "no_doi_authority", "attempts": 0}
    ]
    assert report["ledgerWriteFailures"] == 0
    assert calls == ["10.1103/a", "10.1103/c"]


def test_heartbeat_eta_uses_injected_monotonic_clock(tmp_path):
    checks = [
        _check("https://doi.org/10.1103/a", doi="10.1103/a"),
        _check("https://doi.org/10.1103/b", doi="10.1103/b"),
        _check("https://doi.org/10.1103/c", doi="10.1103/c"),
        _check("https://doi.org/10.1103/d", doi="10.1103/d"),
    ]
    ticks = iter([0.0, 5.0, 10.0, 15.0, 20.0])

    ledger, _report = _run(tmp_path, checks, _metadata, monotonic=lambda: next(ticks))

    etas = [record["etaSeconds"] for record in _records_of_kind(ledger, KIND_HEARTBEAT)]
    assert etas == [15.0, 10.0, 5.0, 0.0]


def test_resume_skips_verified_and_retries_failed(tmp_path):
    checks = [
        _check("https://doi.org/10.1103/a", doi="10.1103/a"),
        _check("https://doi.org/10.1103/b", doi="10.1103/b"),
    ]
    def first_pass(doi: str):
        if doi == "10.1103/a":
            return _metadata(doi)  # A verifies on the first pass
        return None  # B keeps failing

    ledger, first = _run(tmp_path, checks, first_pass, ledger_name="resume.jsonl")
    assert first["verifiedSourceUrls"] == {"https://doi.org/10.1103/a": True}
    assert read_resume_verified(ledger) == {"https://doi.org/10.1103/a": True}

    calls: list[str] = []

    def verifier(doi: str):
        calls.append(doi)
        return _metadata(doi)

    _ledger, second = _run(tmp_path, checks, verifier, ledger_name="resume.jsonl")

    # Already-verified URLs are never re-attempted after an interruption.
    assert calls == ["10.1103/b"]
    assert second["resumedSourceUrls"] == ["https://doi.org/10.1103/a"]
    assert set(second["verifiedSourceUrls"]) == {
        "https://doi.org/10.1103/a",
        "https://doi.org/10.1103/b",
    }
    assert second["attemptedCount"] == 1
    resumed_heartbeats = [
        record
        for record in _records_of_kind(ledger, KIND_HEARTBEAT)
        if record.get("resumed")
    ]
    assert len(resumed_heartbeats) == 1
    assert resumed_heartbeats[0]["done"] == 1


def test_interrupted_run_resumes_from_persisted_prefix(tmp_path):
    checks = [
        _check("https://doi.org/10.1103/a", doi="10.1103/a"),
        _check("https://doi.org/10.1103/b", doi="10.1103/b"),
    ]

    def crashing_verifier(doi: str):
        if doi == "10.1103/b":
            raise KeyboardInterrupt  # abrupt death mid-recheck
        return _metadata(doi)

    ledger = tmp_path / "interrupted.jsonl"
    with pytest.raises(KeyboardInterrupt):
        verify_receipts_with_heartbeat(
            checks,
            team_id=TEAM_ID,
            question_id=QUESTION_ID,
            run_id=RUN_ID,
            ledger_path=ledger,
            verifier=crashing_verifier,
            retry_policy=RetryPolicy(maximum_attempts=1),
            sleeper=lambda _seconds: None,
        )

    # The prefix verified before the crash is durable, and the attempt is
    # fenced as finished/interrupted instead of looking still-running.
    assert read_resume_verified(ledger) == {"https://doi.org/10.1103/a": True}
    finished = _records_of_kind(ledger, KIND_ATTEMPT)[-1]
    assert finished["status"] == "finished"
    assert finished["outcome"] == "interrupted"

    calls: list[str] = []

    def verifier(doi: str):
        calls.append(doi)
        return _metadata(doi)

    _ledger, report = _run(tmp_path, checks, verifier, ledger_name="interrupted.jsonl")

    assert calls == ["10.1103/b"]
    assert set(report["verifiedSourceUrls"]) == {
        "https://doi.org/10.1103/a",
        "https://doi.org/10.1103/b",
    }
    assert report["resumedSourceUrls"] == ["https://doi.org/10.1103/a"]


def test_retry_policy_parameters_drive_backoff_and_attempts(tmp_path):
    sleeps: list[float] = []
    policy = RetryPolicy(
        initial_interval_seconds=2.0,
        backoff_coefficient=2.0,
        maximum_interval_seconds=60.0,
        maximum_attempts=3,
    )
    checks = [_check("https://doi.org/10.1103/a", doi="10.1103/a")]

    _ledger, report = _run(
        tmp_path,
        checks,
        lambda _doi: None,  # persistent transient failure
        retry_policy=policy,
        sleeper=sleeps.append,
    )

    assert sleeps == [2.0, 4.0]  # initial 2s, backoff x2.0
    url_result = _records_of_kind(tmp_path / "run.citation-recheck.jsonl", KIND_URL_RESULT)[0]
    assert url_result["attempts"] == 3  # maximum_attempts respected
    assert url_result["outcome"] == "failed"
    assert url_result["reason"] == "attempts_exhausted"
    assert report["unresolvedSourceUrls"] == ["https://doi.org/10.1103/a"]
    assert report["attemptedCount"] == 1  # retries do not inflate the URL count


def test_retry_policy_max_interval_cap(tmp_path):
    sleeps: list[float] = []
    policy = RetryPolicy(
        initial_interval_seconds=40.0,
        backoff_coefficient=2.0,
        maximum_interval_seconds=60.0,
        maximum_attempts=3,
    )

    _run(
        tmp_path,
        [_check("https://doi.org/10.1103/a", doi="10.1103/a")],
        lambda _doi: None,
        retry_policy=policy,
        sleeper=sleeps.append,
    )

    assert sleeps == [40.0, 60.0]  # capped at maximum_interval_seconds


def test_non_retryable_errors_short_circuit_retries(tmp_path):
    sleeps: list[float] = []
    policy = RetryPolicy(maximum_attempts=5)
    checks = [_check("https://doi.org/10.1103/a", doi="10.1103/a")]

    def refusing(_doi: str):
        raise NonRetryableReceiptError("registry refused", reason="invalid_doi")

    ledger, report = _run(
        tmp_path, checks, refusing, retry_policy=policy, sleeper=sleeps.append
    )

    assert sleeps == []  # no backoff burned on a validation-class failure
    url_result = _records_of_kind(ledger, KIND_URL_RESULT)[0]
    assert url_result["attempts"] == 1
    assert url_result["outcome"] == "failed"
    assert url_result["reason"] == "invalid_doi"
    assert report["failedSourceUrls"] == [
        {"sourceUrl": "https://doi.org/10.1103/a", "reason": "invalid_doi", "attempts": 1}
    ]


def test_definitive_doi_rejection_short_circuits_retries(tmp_path):
    sleeps: list[float] = []

    def rejecting(_doi: str):
        raise DefinitiveDoiRejection("10.1103/a", 404)

    ledger, _report = _run(
        tmp_path,
        [_check("https://doi.org/10.1103/a", doi="10.1103/a")],
        rejecting,
        sleeper=sleeps.append,
    )

    assert sleeps == []
    url_result = _records_of_kind(ledger, KIND_URL_RESULT)[0]
    assert url_result["reason"] == "doi_definitive_rejection:404"
    assert url_result["attempts"] == 1


def test_force_full_reverifies_cached_urls(tmp_path):
    checks = [_check("https://doi.org/10.1103/a", doi="10.1103/a")]
    ledger, _first = _run(tmp_path, checks, _metadata, ledger_name="force.jsonl")
    assert read_resume_verified(ledger) == {"https://doi.org/10.1103/a": True}

    calls: list[str] = []

    def verifier(doi: str):
        calls.append(doi)
        return _metadata(doi)

    _ledger, second = _run(
        tmp_path, checks, verifier, ledger_name="force.jsonl", force_full=True
    )

    assert calls == ["10.1103/a"]  # explicit full pass re-verifies
    assert second["resumedSourceUrls"] == []
    assert second["attemptedCount"] == 1


def test_retry_policy_env_overrides_and_defaults(monkeypatch):
    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_INITIAL_SECONDS", "0.5")
    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_BACKOFF_COEFFICIENT", "3.0")
    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_MAX_INTERVAL_SECONDS", "90")
    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_MAX_ATTEMPTS", "7")
    assert load_retry_policy_from_env() == RetryPolicy(
        initial_interval_seconds=0.5,
        backoff_coefficient=3.0,
        maximum_interval_seconds=90.0,
        maximum_attempts=7,
    )

    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_INITIAL_SECONDS", "bogus")
    monkeypatch.setenv("VIBELUTION_CITATION_RECHECK_RETRY_MAX_ATTEMPTS", "999")
    policy = load_retry_policy_from_env()
    assert policy.initial_interval_seconds == 2.0  # invalid value -> default
    assert policy.maximum_attempts == 20  # clamped to the sane ceiling

    monkeypatch.delenv("VIBELUTION_CITATION_RECHECK_RETRY_INITIAL_SECONDS")
    monkeypatch.delenv("VIBELUTION_CITATION_RECHECK_RETRY_BACKOFF_COEFFICIENT")
    monkeypatch.delenv("VIBELUTION_CITATION_RECHECK_RETRY_MAX_INTERVAL_SECONDS")
    monkeypatch.delenv("VIBELUTION_CITATION_RECHECK_RETRY_MAX_ATTEMPTS")
    assert load_retry_policy_from_env() == RetryPolicy()


def test_progress_report_shape(tmp_path):
    checks = [
        _check("https://doi.org/10.1103/a", doi="10.1103/a"),
        _check("https://doi.org/10.1103/b", doi="10.1103/b"),
    ]
    ledger, _report = _run(
        tmp_path,
        checks,
        lambda _doi: None,  # everything fails
        ledger_name="progress.jsonl",
    )

    progress = progress_report(ledger, team_id=TEAM_ID, question_id=QUESTION_ID, run_id=RUN_ID)
    assert progress["contract"] == HEARTBEAT_CONTRACT
    assert progress["stage"] == HEARTBEAT_STAGE
    assert progress["teamId"] == TEAM_ID
    assert progress["questionId"] == QUESTION_ID
    assert progress["runId"] == RUN_ID
    assert progress["heartbeat"]["done"] == 2
    assert progress["heartbeat"]["total"] == 2
    assert progress["attempt"]["status"] == "finished"
    assert progress["attempt"]["attemptId"] == progress["heartbeat"]["attemptId"]
    assert progress["verifiedSourceUrls"] == []
    assert [entry["sourceUrl"] for entry in progress["failedSourceUrls"]] == [
        "https://doi.org/10.1103/a",
        "https://doi.org/10.1103/b",
    ]
    assert progress["eventCount"] > 0

    empty = progress_report(tmp_path / "missing.jsonl", team_id=TEAM_ID, question_id=QUESTION_ID, run_id=RUN_ID)
    assert empty["heartbeat"] is None
    assert empty["attempt"] is None
    assert empty["eventCount"] == 0


def test_ledger_write_failures_never_break_the_recheck(tmp_path, monkeypatch):
    checks = [_check("https://doi.org/10.1103/a", doi="10.1103/a")]

    def broken_append(path, record):
        raise OSError("disk full")

    monkeypatch.setattr(citation_recheck, "append_recheck_event", broken_append)

    report = verify_receipts_with_heartbeat(
        checks,
        team_id=TEAM_ID,
        question_id=QUESTION_ID,
        run_id=RUN_ID,
        ledger_path=tmp_path / "broken.jsonl",
        verifier=_metadata,
        retry_policy=RetryPolicy(maximum_attempts=1),
        sleeper=lambda _seconds: None,
    )

    # The ledger is progress metadata: its loss must not corrupt the gate.
    # Counted here: attempt start + url_result + heartbeat; the closing
    # attempt-finished write lands after the report is built.
    assert report["verifiedCount"] == 1
    assert report["ledgerWriteFailures"] == 3
