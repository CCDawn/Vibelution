from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import git_history_bridge as bridge
from scripts import git_history_closeout as history
from scripts import local_quality_gate as gate
from scripts import reuse_research_contract as reuse
from scripts import task_closeout as closeout


def git(root: Path, *args: str, env=None, input_text=None) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, env=env or gate.git_hook_isolated_environment(),
        input=input_text, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return result.stdout.strip()


def commit(root: Path, name: str, text: str) -> str:
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", name)
    git(root, "commit", "-m", f"Change {name}")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def scenario(tmp_path: Path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Fixture Human")
    git(root, "config", "user.email", "human@example.test")
    git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    (root / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    (root / "common.txt").write_text("base\n", encoding="utf-8")
    git(root, "add", ".")
    env = gate.git_hook_isolated_environment()
    env.update(GIT_AUTHOR_NAME="Old Bot", GIT_AUTHOR_EMAIL="cursoragent@cursor.com")
    git(root, "commit", "-m", "Historical commit", env=env)
    old = git(root, "rev-parse", "HEAD")
    source = root / ".worktrees" / "source"
    git(root, "worktree", "add", "-b", "codex/source", str(source))
    commit(source, "task.txt", "task\n")
    git(root, "update-ref", "refs/history-backup/original-main", old)
    home = root / ".git" / "vibelution-cache" / "history-bridge"
    mapping = bridge.rewrite_commit_dag(
        root, old, author_fixes={old: b"Fixture Human <human@example.test>"},
        backup_zip=home / "backup.zip", receipt_path=home / "mapping.json",
        backup_refs={"refs/history-backup/original-main": old},
    )
    (home / "active.json").write_text(json.dumps({"receipt": str(mapping.receipt_path), "digest": mapping.digest}), encoding="utf-8")
    git(root, "reset", "--hard", mapping.newmain)
    commit(root, "other.txt", "new main\n")
    context = closeout.CloseoutContext(root, source, "codex/source")
    events = []
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *a, **k: events.append("validate-claim"))
    authority = {
        "agents": [{"id": "agent-source", "state": "active", "branch": "codex/source", "worktree": str(source)}],
        "claims": [
            {"id": "claim-source", "agentId": "agent-source", "status": "active", "scopes": ["."]},
            {"id": "integration-id", "agentId": "agent-source", "status": "active", "scopes": ["integration/main"]},
        ],
    }
    monkeypatch.setattr(closeout, "_coordination_call", lambda *a, **k: authority)
    monkeypatch.setattr(closeout, "acquire_integration_claim_with_retry", lambda *a, **k: events.append("lease") or "integration-id")
    def release(*args, **kwargs):
        events.append(f"release:{args[1]}")
        next(item for item in authority["claims"] if item["id"] == args[1])["status"] = kwargs["status"]
    monkeypatch.setattr(closeout, "release_claim", release)
    def complete(*args, **kwargs):
        events.append("complete")
        authority["agents"][0]["state"] = "completed"
    monkeypatch.setattr(closeout, "complete_agent", complete)

    def merge(context, *, integration_claim_id, target_sha=None):
        events.append("merge")
        git(context.main_root, "merge", "--ff-only", target_sha)
        return target_sha

    monkeypatch.setattr(closeout, "merge_ff_only", merge)
    validations = []

    def validate(candidate: Path, base: str, claim_id: str):
        events.append("gate")
        branch = git(candidate, "branch", "--show-current")
        task_id = branch.removeprefix("codex/")
        manifest = home / "test-manifests" / f"{task_id}.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({
            "headSha": git(candidate, "rev-parse", "HEAD"), "branch": branch,
            "worktree": str(candidate), "validatedMainSha": git(root, "rev-parse", "HEAD"),
            "claimId": claim_id,
        }), encoding="utf-8")
        validations.append(candidate)
        return gate.GateResult(outcome="passed", exit_code=0, manifest_path=manifest)

    monkeypatch.setattr(gate, "run_closeout", validate)
    verifications = []

    def verify(path, candidate, base):
        verifications.append(candidate)
        return gate.GateResult(outcome="passed", exit_code=0, manifest_path=path)

    monkeypatch.setattr(gate, "verify_manifest", verify)
    return SimpleNamespace(root=root, source=source, context=context, events=events,
                           mapping=mapping, home=home, validations=validations,
                           verifications=verifications, validate=validate, authority=authority)


def run(s, **kwargs):
    return history.run_if_needed(s.context, claim_id="claim-source", agent_id="agent-source", **kwargs)


def source_state(s):
    return (git(s.source, "rev-parse", "HEAD"), git(s.source, "symbolic-ref", "HEAD"),
            (s.source / "task.txt").read_bytes(), git(s.source, "status", "--porcelain"),
            (Path(git(s.source, "rev-parse", "--absolute-git-dir")) / "index").read_bytes())


def test_independent_candidate_preserves_source_and_main_changes_and_exact_retry(scenario):
    s = scenario
    before = source_state(s)
    main = git(s.root, "rev-parse", "HEAD")
    result = run(s)
    assert result.merged and result.exit_code == 0
    assert result.status == "merged_cleanup_pending"
    assert result.next_action == "retain_original_worktree_and_branch"
    assert source_state(s) == before
    assert (s.root / "task.txt").read_text() == "task\n"
    assert (s.root / "other.txt").read_text() == "new main\n"
    assert git(s.root, "rev-parse", "HEAD^1") == main
    assert len(git(s.root, "rev-list", "--parents", "-n", "1", "HEAD").split()) == 3
    assert len(s.validations) == 1 and s.validations[0] != s.source
    assert s.verifications == [s.validations[0], s.validations[0]]
    assert not s.validations[0].exists()
    assert "codex/history-" not in git(s.root, "branch", "--list")
    receipts = list((s.home / "closeouts").glob("*.json"))
    receipt = json.loads(receipts[0].read_text())
    assert receipt["sourceHead"] == before[0]
    assert receipt["candidateHead"] == result.merge_sha
    assert receipt["mainSha"] == main
    assert receipt["mapDigest"] == s.mapping.digest
    assert receipt["ownerCompleted"] is True
    calls = list(s.events)
    assert run(s).merge_sha == result.merge_sha
    assert s.events == calls


@pytest.mark.parametrize("dirty", ["staged", "unstaged", "untracked"])
def test_dirty_source_rejected_without_mutation(scenario, dirty):
    s = scenario
    if dirty == "untracked":
        (s.source / "new.txt").write_text("untracked")
    else:
        (s.source / "task.txt").write_text("changed")
        if dirty == "staged":
            git(s.source, "add", "task.txt")
    before = source_state(s)
    main = git(s.root, "rev-parse", "HEAD")
    result = run(s)
    assert result.errors == ["history_source_dirty"]
    assert source_state(s) == before
    assert git(s.root, "rev-parse", "HEAD") == main
    assert not s.validations and "complete" not in s.events


def test_merge_conflict_leaves_source_and_main_untouched(scenario):
    s = scenario
    commit(s.source, "common.txt", "source collision\n")
    commit(s.root, "common.txt", "main collision\n")
    before = source_state(s)
    main = git(s.root, "rev-parse", "HEAD")
    result = run(s)
    assert result.errors == ["history_merge_conflict"]
    assert source_state(s) == before
    assert git(s.root, "rev-parse", "HEAD") == main
    assert "complete" not in s.events and not s.validations


def test_translation_preserves_task_merge_parents(scenario):
    s = scenario
    git(s.source, "checkout", "-b", "codex/fixture-side")
    commit(s.source, "side.txt", "side\n")
    git(s.source, "checkout", "codex/source")
    commit(s.source, "top.txt", "top\n")
    git(s.source, "merge", "--no-ff", "codex/fixture-side", "-m", "Join task work")
    before = source_state(s)
    result = run(s)
    assert result.merged and source_state(s) == before
    translated = git(s.root, "rev-parse", "HEAD^2")
    assert len(git(s.root, "rev-list", "--parents", "-n", "1", translated).split()) == 3
    assert (s.root / "side.txt").exists() and (s.root / "top.txt").exists()


@pytest.mark.parametrize("mutation,expected", [
    ("source", "history_source_changed"), ("main", "history_main_changed"),
    ("map", "history_mapping_changed"),
])
@pytest.mark.parametrize("when", ["gate", "lease"])
def test_source_main_and_mapping_races_refuse_integration(scenario, monkeypatch, mutation, expected, when):
    s = scenario

    def mutate():
        if mutation == "source":
            commit(s.source, "raced.txt", "source race\n")
        elif mutation == "main":
            commit(s.root, "raced.txt", "main race\n")
        else:
            monkeypatch.setattr(bridge, "load_active_mapping", lambda *a: SimpleNamespace(digest="changed"))

    if when == "gate":
        def validate(*args):
            result = s.validate(*args)
            mutate()
            return result
        monkeypatch.setattr(gate, "run_closeout", validate)
    else:
        def lease(*args, **kwargs):
            mutate()
            return "integration-id"
        monkeypatch.setattr(closeout, "acquire_integration_claim_with_retry", lease)
    result = run(s)
    assert result.errors[0] == expected
    assert not result.merged and "merge" not in s.events and "complete" not in s.events
    if when == "lease":
        assert "release:integration-id" in s.events


def test_source_manifest_is_never_accepted_as_candidate_manifest(scenario, monkeypatch):
    s = scenario
    def validate(*args):
        result = s.validate(*args)
        payload = json.loads(result.manifest_path.read_text())
        payload.update(headSha=git(s.source, "rev-parse", "HEAD"), branch="codex/source", worktree=str(s.source))
        result.manifest_path.write_text(json.dumps(payload))
        return result
    monkeypatch.setattr(gate, "run_closeout", validate)
    result = run(s)
    assert result.errors == ["history_manifest_candidate_mismatch"]
    assert "merge" not in s.events and "complete" not in s.events


def test_candidate_copies_only_validated_original_reuse_decision(scenario):
    s = scenario
    commit(s.source, "owned.py", "value = 1\n")
    evidence = reuse.record_evidence(
        s.source, feature="Fixture owner", decision="BUILD_IN_HOUSE", local_reuse_decision="ADAPT",
        local_owner_paths=["owned.py"], candidate_ids=[], borrowed_slices=[], rejected_alternatives=[],
        reason="Reuse the task implementation", implementation_boundary="Task owner only",
        verification_strategy="Focused real Git tests", risk_notes=[], source_refs=[], research_mode="LOCAL_ONLY",
    )
    result = run(s)
    assert result.merged
    receipt = json.loads(next((s.home / "closeouts").glob("*.json")).read_text())
    copied = json.loads(reuse.evidence_path(s.source, receipt["candidateBranch"].removeprefix("codex/")).read_text())
    assert copied["decision"] == evidence["decision"]
    assert copied["localReuseDecision"] == evidence["localReuseDecision"]
    assert copied["historyBridgeSource"] == receipt["sourceReuseEvidence"]
    assert copied["taskId"] != evidence["taskId"]


def test_source_owner_must_match_original_branch_and_worktree(scenario, monkeypatch):
    s = scenario
    monkeypatch.setattr(closeout, "_coordination_call", lambda *a, **k: {
        "agents": [{"id": "agent-source", "branch": "codex/unrelated", "worktree": str(s.source)}]})
    result = run(s)
    assert result.errors == ["history_source_owner_mismatch"]
    assert not s.validations and "complete" not in s.events


def test_old_nodes_trigger_translation_even_when_source_contains_current_main(scenario):
    s = scenario
    git(s.source, "merge", "--no-ff", "--allow-unrelated-histories", "main", "-m", "Old task absorbed clean main")
    before = source_state(s)
    result = run(s)
    assert result.merged and source_state(s) == before
    reachable = set(git(s.root, "rev-list", "HEAD").splitlines())
    assert not reachable.intersection({old for old, new in s.mapping.mapping.items() if old != new})


def test_entry_routes_history_before_expired_claim_validation(scenario, monkeypatch):
    s = scenario
    result = run(s)
    monkeypatch.setattr(closeout, "validate_development_claim", lambda *a, **k: pytest.fail("exact retry revalidated completed claim"))
    retried = closeout.run_managed_closeout(s.source, claim_id="claim-source", agent_id="agent-source")
    assert retried.merged and retried.merge_sha == result.merge_sha


@pytest.mark.parametrize("dirty", [False, True])
def test_source_continuing_after_merge_keeps_development_claim_and_owner(scenario, monkeypatch, dirty):
    s = scenario
    original_merge = closeout.merge_ff_only
    def merge(*args, **kwargs):
        head = original_merge(*args, **kwargs)
        if dirty:
            (s.source / "task.txt").write_text("unfinished new work")
        else:
            commit(s.source, "continued.txt", "new work\n")
        return head
    monkeypatch.setattr(closeout, "merge_ff_only", merge)
    result = run(s)
    assert result.merged and result.errors == ["history_source_changed_after_merge"]
    assert "release:claim-source" not in s.events and "complete" not in s.events
    assert "release:integration-id" in s.events
    assert s.authority["claims"][0]["status"] == "active"
    assert s.authority["agents"][0]["state"] == "active"


@pytest.mark.parametrize("flag,event", [("developmentReleased", "release:claim-source"), ("ownerCompleted", "complete")])
def test_authoritative_readback_recovers_failed_receipt_acknowledgement(scenario, monkeypatch, flag, event):
    s = scenario
    original_atomic = history._atomic
    failed = False
    def atomic(path, payload):
        nonlocal failed
        if payload.get(flag) and not failed:
            failed = True
            raise OSError("receipt acknowledgement unavailable")
        original_atomic(path, payload)
    monkeypatch.setattr(history, "_atomic", atomic)
    first = run(s)
    assert first.merged and failed
    second = run(s)
    assert second.merged and not second.errors
    assert s.events.count(event) == 1
    assert s.events.count("merge") == 1
    assert s.events.count("complete") == 1


def test_replace_ref_cannot_change_native_merge_ancestry(scenario):
    s = scenario
    # A replace overlay can make an unrelated root look like it shares a base.
    git(s.root, "replace", s.mapping.oldmain, s.mapping.newmain)
    before = source_state(s)
    result = run(s)
    assert result.errors == ["history_replace_refs_present"]
    assert source_state(s) == before and not s.validations
    assert git(s.root, "for-each-ref", "--format=%(refname)", "refs/replace")


def test_reuse_evidence_mutation_during_validation_refuses_merge(scenario, monkeypatch):
    s = scenario
    commit(s.source, "owned.py", "value = 1\n")
    reuse.record_evidence(
        s.source, feature="Fixture owner", decision="BUILD_IN_HOUSE", local_reuse_decision="ADAPT",
        local_owner_paths=["owned.py"], candidate_ids=[], borrowed_slices=[], rejected_alternatives=[],
        reason="Original reuse decision", implementation_boundary="Task owner only",
        verification_strategy="Focused real Git tests", risk_notes=[], source_refs=[], research_mode="LOCAL_ONLY",
    )
    def validate(*args):
        result = s.validate(*args)
        path = reuse.evidence_path(s.source, "source")
        payload = json.loads(path.read_text())
        payload["reason"] = "The source assessment changed while validation ran"
        path.write_text(json.dumps(payload))
        return result
    monkeypatch.setattr(gate, "run_closeout", validate)
    result = run(s)
    assert result.errors == ["history_reuse_evidence_changed"]
    assert "merge" not in s.events and "complete" not in s.events


def test_retry_recomputes_translation_instead_of_trusting_receipt(scenario):
    s = scenario
    assert run(s).merged
    path = next((s.home / "closeouts").glob("*.json"))
    receipt = json.loads(path.read_text())
    receipt["translatedHead"] = receipt["mainSha"]
    path.write_text(json.dumps(receipt))
    before = list(s.events)
    result = run(s)
    assert result.errors == ["history_receipt_translation_mismatch"]
    assert s.events == before


def test_failed_lease_release_reports_exact_remaining_lease(scenario, monkeypatch):
    s = scenario
    def lease(*args, **kwargs):
        commit(s.root, "lease-race.txt", "main advanced\n")
        return "integration-id"
    monkeypatch.setattr(closeout, "acquire_integration_claim_with_retry", lease)
    def release(*args, **kwargs):
        raise OSError("coordination temporarily unavailable")
    monkeypatch.setattr(closeout, "release_claim", release)
    result = run(s)
    assert result.errors[0] == "history_main_changed"
    assert result.errors[1].startswith("integration_release_pending: integration-id:")
    assert "complete" not in s.events


def test_reuse_evidence_changed_between_validation_and_copy_is_rejected(scenario, monkeypatch):
    s = scenario
    commit(s.source, "owned.py", "value = 1\n")
    reuse.record_evidence(
        s.source, feature="Fixture owner", decision="BUILD_IN_HOUSE", local_reuse_decision="ADAPT",
        local_owner_paths=["owned.py"], candidate_ids=[], borrowed_slices=[], rejected_alternatives=[],
        reason="Original assessment", implementation_boundary="Task owner only",
        verification_strategy="Focused real Git tests", risk_notes=[], source_refs=[], research_mode="LOCAL_ONLY",
    )
    original = history._read_source_reuse
    def read(*args):
        payload = original(*args)
        path = reuse.evidence_path(s.source, "source")
        changed = dict(payload, reason="Assessment was replaced after it was checked")
        path.write_text(json.dumps(changed))
        return payload
    monkeypatch.setattr(history, "_read_source_reuse", read)
    result = run(s)
    assert result.errors == ["history_reuse_evidence_changed"]
    assert not s.validations and "merge" not in s.events
