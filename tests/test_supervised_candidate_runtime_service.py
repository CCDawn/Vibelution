from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from core.web.services import supervised_candidate_runtime_service as service
from scripts.evolution_harness import HarnessResult


def _harness_result(candidate: Path) -> HarnessResult:
    return HarnessResult(
        harness_id="conversation-rerun",
        status="success",
        reason="rerun completed",
        started_at="2026-07-30T00:00:00Z",
        ended_at="2026-07-30T00:00:05Z",
        repo_root=str(candidate),
        worktree_path="",
        base_head="",
        checkpoint_commit="",
        checkpoint_ref=None,
        tracked_dirty=False,
        untracked_files=[],
        command=["session_service.submit_session_message", "session-rerun"],
        returncode=0,
        timeout_seconds=60,
        restarts_observed=0,
        normalized_restarts_observed=0,
        restart_expected=False,
        restart_reentered=False,
        process_history=[],
        process_summary={"session_id": "session-rerun"},
        new_conversation_files=["session:session-rerun"],
        new_debug_files=[],
        stdout_tail=["rerun answer"],
        stderr_tail=[],
        agent_realtime_tail=[],
        last_observation={},
        post_restart_observation={},
        evolution_summary={
            "tool_trace": [
                {
                    "toolName": "python_lint_tool",
                    "status": "success",
                    "timestamp": "2026-07-30T00:00:02Z",
                    "arguments": {"source_path": "scripts/evolution_harness.py"},
                    "result": {"status": "success"},
                }
            ]
        },
        agent_binding={"agentId": "baseline-agent", "role": "baseline"},
    )


def _candidate(tmp_path: Path) -> tuple[Path, dict[str, object], str]:
    candidate = tmp_path / "candidate"
    module_path = candidate / "scripts" / "evolution_harness.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# candidate harness\n", encoding="utf-8")
    module_sha = hashlib.sha256(module_path.read_bytes()).hexdigest()
    variant = {
        "variantId": "swte-variant-test",
        "patchSha256": "a" * 64,
        "checkpointCommit": "base",
        "bindingStatus": "verified",
        "changedFileCount": 1,
    }
    return candidate, variant, module_sha


def test_candidate_runtime_executes_candidate_harness_contract_in_isolated_process(tmp_path):
    candidate, variant, module_sha = _candidate(tmp_path)
    captured: dict[str, object] = {}

    def fake_sandbox(command, timeout, cwd, _cancel_checker=None, _environment_policy="default"):
        captured.update(
            {
                "command": command,
                "timeout": timeout,
                "cwd": cwd,
                "environmentPolicy": _environment_policy,
            }
        )
        inputs = list((candidate / ".runtime" / "supervised-candidate-runtime").glob("*.json"))
        assert len(inputs) == 1
        payload = json.loads(inputs[0].read_text(encoding="utf-8"))
        assert payload["candidateVariant"]["variantId"] == variant["variantId"]
        assert payload["events"][0]["tool_name"] == "python_lint_tool"
        result = {
            "protocolVersion": 1,
            "status": "success",
            "executionBackend": "isolated_candidate_subprocess",
            "candidateVariantId": variant["variantId"],
            "candidatePatchSha256": variant["patchSha256"],
            "moduleSha256": module_sha,
            "processId": os.getpid() + 100,
            "evolutionSummary": {"validation": {"passed": 1, "failed": 0}},
            "workspaceEvidence": {"repo_root": str(candidate), "head": "base"},
            "extensionEvidence": {
                "workspaceSnapshotCaptured": True,
                "api_key": "must-not-escape",
                "note": "token=must-not-escape",
            },
        }
        return f"noise\n{service.CANDIDATE_RUNTIME_RESULT_PREFIX}{json.dumps(result)}\n"

    evidence = service.run_candidate_runtime_evidence(
        candidate_path=candidate,
        candidate_variant=variant,
        harness_result=_harness_result(candidate),
        sandbox_runner=fake_sandbox,
    )

    assert evidence["status"] == "verified"
    assert evidence["runtimeEffect"] == "candidate_harness_executed"
    assert evidence["candidateVariantId"] == variant["variantId"]
    assert evidence["moduleSha256"] == module_sha
    assert evidence["worktreePath"] == str(candidate.resolve())
    assert evidence["extensionEvidence"]["workspaceSnapshotCaptured"] is True
    assert evidence["extensionEvidence"]["api_key"] == "[redacted]"
    assert evidence["extensionEvidence"]["note"] == "token=[redacted]"
    assert captured["environmentPolicy"] == "candidate_runtime"
    assert not (candidate / ".runtime" / "supervised-candidate-runtime").exists()


def test_candidate_runtime_fails_closed_when_subprocess_module_hash_does_not_match(tmp_path):
    candidate, variant, _ = _candidate(tmp_path)

    def fake_sandbox(*args, **kwargs):
        result = {
            "protocolVersion": 1,
            "status": "success",
            "executionBackend": "isolated_candidate_subprocess",
            "candidateVariantId": variant["variantId"],
            "candidatePatchSha256": variant["patchSha256"],
            "moduleSha256": "b" * 64,
            "processId": os.getpid() + 1,
            "evolutionSummary": {},
            "workspaceEvidence": {},
            "extensionEvidence": {},
        }
        return f"{service.CANDIDATE_RUNTIME_RESULT_PREFIX}{json.dumps(result)}"

    with pytest.raises(service.CandidateRuntimeExecutionError, match="module hash"):
        service.run_candidate_runtime_evidence(
            candidate_path=candidate,
            candidate_variant=variant,
            harness_result=_harness_result(candidate),
            sandbox_runner=fake_sandbox,
        )
