"""Assistant branch cleanup plan/execute gates, wiring and approval semantics."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from core.assistant_runtime import local_actions as local
from core.web.services.local_assistant import branch_cleanup_actions as actions
from core.web.services.local_assistant.management_approval import approval_requirement, _risk
from core.web.services.session.tool_approvals import _assistant_management_summary


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {args} failed: {result.stderr or result.stdout}")
    return result.stdout.strip()


@pytest.fixture(autouse=True)
def _isolated_instance_registry(tmp_path, monkeypatch):
    """Cleanup fences never touch the real %LOCALAPPDATA% instances registry."""
    from core.runtime_manager import instances_registry as registry

    registry_path = tmp_path / "Vibelution" / "instances.json"
    monkeypatch.setattr(registry, "instances_registry_path", lambda: registry_path)
    monkeypatch.setattr(registry, "_port_is_free", lambda _port, host=None: True)


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True)
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "cleanup@example.local")
    _git(root, "config", "user.name", "Cleanup Test")
    (root / "README.md").write_text("base\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "base")
    return root


def _worktree(root: Path, name: str, branch: str, *, commit: bool = False) -> Path:
    path = root / ".worktrees" / name
    _git(root, "worktree", "add", "-b", branch, str(path))
    if commit:
        (path / "README.md").write_text("ahead\n", encoding="utf-8")
        _git(path, "add", ".")
        _git(path, "commit", "-m", "ahead")
    return path


def _dirty(path: Path) -> bool:
    return bool(_git(path, "status", "--porcelain"))


def _item(instance_id: str, path: Path, branch: str, *, merged: bool, **overrides):
    item = {
        "id": instance_id,
        "kind": "worktree",
        "branch": branch,
        "shortName": branch.rsplit("/", 1)[-1],
        "path": str(path),
        "displayPath": str(path),
        "head": _git(path, "rev-parse", "HEAD"),
        "current": False,
        "legacy": False,
        "dirty": _dirty(path),
        "checkedOut": True,
        "alive": False,
        "mergedToMain": merged,
        "cleanupEligible": True,
        "cleanupRisks": [],
    }
    item.update(overrides)
    return item


def _payload(root: Path, items: list[dict]) -> dict:
    return {"integrationRoot": str(root), "items": items}


def _patch_payload(monkeypatch, payload: dict) -> None:
    from core.launcher import service as launcher_service

    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances",
                        lambda **kwargs: payload)


def _no_claims(monkeypatch, payload: dict | None = {"agents": [], "claims": []}) -> None:
    monkeypatch.setattr(actions, "_coordination_status", lambda root: payload)


def _with_root(monkeypatch, *roots: Path) -> None:
    """Pretend the host dispatch registry authorized exactly these roots."""
    monkeypatch.setattr(actions, "_dispatch_registered_roots", lambda: tuple(roots))


def _scanned_repo(tmp_path: Path) -> tuple[Path, dict[str, dict]]:
    """Temp repo with merged+clean, unmerged and dirty worktrees."""
    root = _init_repo(tmp_path / "repo")
    clean = _worktree(root, "clean", "codex/clean")
    unmerged = _worktree(root, "unmerged", "codex/unmerged", commit=True)
    dirty = _worktree(root, "dirty", "codex/dirty")
    (dirty / "notes.txt").write_text("scratch\n", encoding="utf-8")
    items = {
        "clean": _item("worktree:clean", clean, "codex/clean", merged=True),
        "unmerged": _item("worktree:unmerged", unmerged, "codex/unmerged", merged=False),
        "dirty": _item("worktree:dirty", dirty, "codex/dirty", merged=True),
    }
    return root, items


def _branch_exists(root: Path, branch: str) -> bool:
    return subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(root), capture_output=True, check=False,
    ).returncode == 0


def test_plan_lists_full_ids_reasons_and_active_claim(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    items["main"] = {"id": "main", "kind": "main", "branch": "main", "shortName": "main",
                     "path": str(root), "current": True, "dirty": False, "mergedToMain": True,
                     "checkedOut": True, "alive": False}
    _no_claims(monkeypatch, {"agents": [
        {"id": "agent-1", "state": "active", "branch": "codex/unmerged",
         "stage": "implement", "worktree": ""},
    ], "claims": []})

    result = actions._plan_view(_payload(root, list(items.values())))

    assert result["total"] == len(items)
    rows = {row["instanceId"]: row for row in result["instances"]}
    assert rows["worktree:clean"]["eligible"] is True
    assert rows["worktree:clean"]["reasons"] == []
    assert rows["worktree:unmerged"]["eligible"] is False
    assert rows["worktree:unmerged"]["reasons"] == ["CLAIM_ACTIVE", "UNMERGED"]
    assert rows["worktree:dirty"]["reasons"] == ["DIRTY"]
    assert rows["main"]["eligible"] is False
    assert rows["main"]["reasons"] == ["PROTECTED_BRANCH"]
    claim_row = rows["worktree:unmerged"]
    assert claim_row["activeClaim"] == {"agentId": "agent-1", "stage": "implement"}
    clean_row = rows["worktree:clean"]
    assert clean_row["activeClaim"] is None
    assert clean_row["mergedToMain"] is True and clean_row["dirty"] is False
    assert clean_row["registeredStatus"] == "" and clean_row["backendAlive"] is False
    assert rows["worktree:dirty"]["dirty"] is True


def test_plan_current_workspace_and_in_flight_reasons(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    items["clean"]["current"] = True
    items["unmerged"]["status"] = "starting"
    _no_claims(monkeypatch)

    rows = {row["instanceId"]: row
            for row in actions._plan_view(_payload(root, list(items.values())))["instances"]}

    assert rows["worktree:clean"]["reasons"] == ["CURRENT_WORKSPACE"]
    assert rows["worktree:unmerged"]["reasons"] == ["INSTANCE_IN_FLIGHT", "UNMERGED"]


def test_plan_marks_every_row_unprovable_when_coordination_unavailable(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    _no_claims(monkeypatch, None)

    rows = {row["instanceId"]: row
            for row in actions._plan_view(_payload(root, list(items.values())))["instances"]}

    assert all(row["reasons"][0] == "CLAIM_UNPROVABLE" for row in rows.values())
    assert all(row["eligible"] is False for row in rows.values())


def test_worktree_claim_binding_resolves_active_registry_claim(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    clean_path = Path(items["clean"]["path"])
    git_dir = Path(_git(clean_path, "rev-parse", "--absolute-git-dir"))
    binding = {"claim_id": "claim-7", "agent_id": "agent-9", "branch": "codex/clean",
               "worktree": str(clean_path), "scopes": ["integration/codex/clean"]}
    (git_dir / "vibelution-claim.json").write_text(json.dumps(binding), encoding="utf-8")
    payload = _payload(root, list(items.values()))

    # The bound claim is active in the registry -> blocked with the binding owner.
    _no_claims(monkeypatch, {"agents": [], "claims": [{"id": "claim-7", "status": "active"}]})
    rows = {row["instanceId"]: row for row in actions._plan_view(payload)["instances"]}
    assert rows["worktree:clean"]["reasons"] == ["CLAIM_ACTIVE"]
    assert rows["worktree:clean"]["activeClaim"] == {"agentId": "agent-9", "stage": ""}

    # A completed/expired bound claim no longer blocks.
    _no_claims(monkeypatch, {"agents": [], "claims": [{"id": "claim-7", "status": "completed"}]})
    rows = {row["instanceId"]: row for row in actions._plan_view(payload)["instances"]}
    assert rows["worktree:clean"]["reasons"] == []


def test_execute_without_governed_returns_native_approval_guidance(tmp_path, monkeypatch):
    from core.launcher import service as launcher_service

    def fail(**kwargs):
        raise AssertionError("execute must not scan before approval")

    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances", fail)
    assert actions.execute("branch_cleanup_execute", {"instance_ids": ["worktree:clean"]},
                           {}, governed=False) == {
        "ok": False, "status": "approval_required", "action": "branch_cleanup_execute",
        "tool": "personal_assistant_manage_tool",
        "message": "使用 manage，action 保持不变，arguments_json 为这些参数的JSON；等待原生审批后执行。",
    }


def test_execute_gates_unmerged_and_dirty_then_flags_allow_deletion(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    payload = _payload(root, list(items.values()))
    _patch_payload(monkeypatch, payload)
    _with_root(monkeypatch, root)
    _no_claims(monkeypatch)

    rejected = actions.execute_cleanup({"instance_ids": ["worktree:unmerged", "worktree:dirty"]})
    assert rejected["ok"] is False and rejected["status"] == "rejected"
    by_id = {row["instanceId"]: row for row in rejected["rejected"]}
    assert by_id["worktree:unmerged"]["reasons"] == ["UNMERGED"]
    assert by_id["worktree:dirty"]["reasons"] == ["DIRTY"]
    assert not rejected["cleaned"] and not rejected["failed"] and not rejected["skipped"]
    assert Path(items["unmerged"]["path"]).exists() and Path(items["dirty"]["path"]).exists()
    assert _branch_exists(root, "codex/unmerged") and _branch_exists(root, "codex/dirty")

    applied = actions.execute_cleanup({"instance_ids": ["worktree:unmerged", "worktree:dirty"],
                                       "allow_unmerged": True, "allow_dirty": True})
    assert applied["ok"] is True and applied["status"] == "applied"
    assert [row["id"] for row in applied["cleaned"]] == ["worktree:unmerged", "worktree:dirty"]
    assert set(applied["cleaned"][0]["actions"]) >= {"worktree_removed", "branch_deleted"}
    assert not Path(items["unmerged"]["path"]).exists()
    assert not Path(items["dirty"]["path"]).exists()
    assert not _branch_exists(root, "codex/unmerged")
    assert not _branch_exists(root, "codex/dirty")


def test_execute_never_deletes_claimed_or_unprovable_instances(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    payload = _payload(root, list(items.values()))
    _patch_payload(monkeypatch, payload)
    _with_root(monkeypatch, root)
    _no_claims(monkeypatch, {"agents": [
        {"id": "agent-1", "state": "paused", "branch": "codex/unmerged",
         "stage": "review", "worktree": str(items["unmerged"]["path"])},
    ], "claims": []})

    rejected = actions.execute_cleanup({"instance_ids": ["worktree:unmerged", "worktree:dirty"],
                                        "allow_unmerged": True, "allow_dirty": True})
    by_id = {row["instanceId"]: row for row in rejected["rejected"]}
    # The allow_unmerged flag suppresses the unmerged reason; the claim gate stays absolute.
    assert by_id["worktree:unmerged"]["reasons"] == ["CLAIM_ACTIVE"]
    assert by_id["worktree:unmerged"]["branch"] == "codex/unmerged"
    assert Path(items["unmerged"]["path"]).exists()
    assert _branch_exists(root, "codex/unmerged")

    _no_claims(monkeypatch, None)
    rejected = actions.execute_cleanup({"instance_ids": ["worktree:clean"],
                                        "allow_unmerged": True, "allow_dirty": True})
    assert rejected["rejected"] == [{"instanceId": "worktree:clean", "branch": "codex/clean",
                                     "shortName": "clean", "reasons": ["CLAIM_UNPROVABLE"]}]
    assert Path(items["clean"]["path"]).exists()
    assert _branch_exists(root, "codex/clean")


def test_execute_rejects_protected_current_and_unknown_instances(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    items["main"] = {"id": "main", "kind": "main", "branch": "main", "shortName": "main",
                     "path": str(root), "current": True, "dirty": False, "mergedToMain": True,
                     "checkedOut": True, "alive": False}
    items["clean"]["current"] = True
    payload = _payload(root, list(items.values()))
    _patch_payload(monkeypatch, payload)
    _with_root(monkeypatch, root)
    _no_claims(monkeypatch)

    result = actions.execute_cleanup({"instance_ids": ["main", "worktree:clean", "worktree:ghost"]})
    by_id = {row["instanceId"]: row for row in result["rejected"]}
    assert by_id["main"]["reasons"] == ["PROTECTED_BRANCH"]
    assert by_id["worktree:clean"]["reasons"] == ["CURRENT_WORKSPACE"]
    assert by_id["worktree:ghost"]["reason"] == "INSTANCE_NOT_FOUND"
    assert result["ok"] is False and result["status"] == "rejected"
    assert not result["cleaned"]
    assert Path(items["clean"]["path"]).exists()
    root_readme = root / "README.md"
    assert root_readme.read_text(encoding="utf-8") == "base\n"


def test_execute_validates_instance_ids_strictly():
    result = actions.execute_cleanup({"instance_ids": []})
    assert result["ok"] is False and result["error"] == "invalid_input"
    result = actions.execute_cleanup({"instance_ids": ["   "]})
    assert result["ok"] is False and result["error"] == "invalid_input"
    result = actions.execute_cleanup({"instance_ids": ["worktree:one"], "extra": True})
    assert result["ok"] is False and result["error"] == "invalid_input"


def test_contract_and_allowlist_wiring():
    contracts = local.contracts()
    assert contracts["branch_cleanup_plan"]["governed"] is False
    assert contracts["branch_cleanup_execute"]["governed"] is True
    assert "把结果给用户看" in contracts["branch_cleanup_plan"]["description"]
    assert "branch_cleanup_plan" in contracts["branch_cleanup_execute"]["description"]
    assert "活跃 claim" in contracts["branch_cleanup_execute"]["description"]
    for name in ("branch_cleanup_plan", "branch_cleanup_execute"):
        assert contracts[name]["parameters"]["additionalProperties"] is False
        assert contracts[name]["action"] == name
    assert contracts["branch_cleanup_execute"]["parameters"]["required"] == ["instance_ids"]


@pytest.mark.parametrize("action,governed", [
    ("branch_cleanup_plan", False),
    ("branch_cleanup_execute", True),
])
def test_local_allowlist_dispatch_reaches_module(monkeypatch, action, governed):
    calls = []

    def stubbed_execute(name, parameters, runtime, *, governed=False):
        calls.append((name, governed))
        return {"ok": True, "action": name}

    monkeypatch.setattr(actions, "execute", stubbed_execute)
    assert local.execute(action, {}, {"agentId": "a"}, governed=governed) == {
        "ok": True, "action": action}
    assert calls == [(action, governed)]


def test_management_approval_semantics_read_plan_destructive_execute():
    assert _risk("branch_cleanup_plan", {}) == "read"
    parameters = {"instance_ids": ["worktree:clean"], "allow_unmerged": False, "allow_dirty": False}
    assert _risk("branch_cleanup_execute", parameters) == "destructive"
    assert approval_requirement({"agentId": "assistant"}, {
        "action": "branch_cleanup_plan", "arguments_json": "{}"}) is None
    assert approval_requirement({"agentId": "assistant"}, {
        "action": "branch_cleanup_execute", "arguments_json": json.dumps(parameters),
    }) == ("always", "destructive")
    # Unknown actions stay fail-closed destructive.
    assert approval_requirement({"agentId": "assistant"}, {
        "action": "branch_cleanup_invade", "arguments_json": "{}"}) == ("always", "destructive")


def test_execute_approval_summary_projects_instance_list(monkeypatch):
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process",
                        lambda: True)
    parameters = {"instance_ids": ["worktree:clean", "worktree:dirty"],
                  "allow_unmerged": True, "allow_dirty": False}
    summary = _assistant_management_summary({
        "action": "branch_cleanup_execute", "arguments_json": json.dumps(parameters)})
    assert summary["assistantAction"] == "branch_cleanup_execute"
    assert summary["assistantTargets"] == {"instanceIds": ["worktree:clean", "worktree:dirty"],
                                           "allowUnmerged": True, "allowDirty": False}
    assert "branch_cleanup_plan" in summary["assistantOperationDescription"]
    invalid = _assistant_management_summary({
        "action": "branch_cleanup_execute", "arguments_json": json.dumps({"instance_ids": []})})
    assert invalid["assistantArgumentsInvalid"] is True
    monkeypatch.setattr("core.infrastructure.native_runtime.is_launcher_assistant_process",
                        lambda: False)
    assert _assistant_management_summary({
        "action": "branch_cleanup_execute", "arguments_json": "{}"})["assistantArgumentsInvalid"] is True


class _StubHostService:
    """Minimal stand-in for the bound DispatchService facade."""

    def __init__(self, *roots: Path):
        self._roots = roots

    def registered_project_roots(self):
        return self._roots


def _redirect_host_project_root(monkeypatch, tmp_path):
    """Simulate the assistant host: module PROJECT_ROOT is a non-Git profile."""
    profile = tmp_path / "DesktopShell" / "assistant" / "profile"
    profile.mkdir(parents=True, exist_ok=True)
    assert not (profile / ".git").exists()
    from core.launcher import branch_instance_cleanup, branch_instance_lifecycle
    from core.launcher import service as launcher_service

    for module in (branch_instance_lifecycle, branch_instance_cleanup, launcher_service):
        monkeypatch.setattr(module, "PROJECT_ROOT", profile)


def test_plan_and_execute_run_real_chain_under_redirected_host_project_root(tmp_path, monkeypatch):
    root, items = _scanned_repo(tmp_path)
    _redirect_host_project_root(monkeypatch, tmp_path)
    monkeypatch.setattr("core.assistant_runtime.actions._binding",
                        (_StubHostService(root), object(), None))
    _no_claims(monkeypatch)
    unmerged_path = Path(items["unmerged"]["path"])

    plan = actions.plan({"agentId": "assistant", "sessionId": "s"})

    assert plan["ok"] is True and plan["status"] == "observed"
    rows = {row["instanceId"]: row for row in plan["instances"]}
    assert {"worktree:clean", "worktree:unmerged", "worktree:dirty"} <= set(rows)
    assert rows["worktree:unmerged"]["worktreeRoot"] == str(unmerged_path)
    assert rows["worktree:clean"]["eligible"] is True
    assert rows["worktree:unmerged"]["reasons"] == ["UNMERGED"]

    applied = actions.execute("branch_cleanup_execute",
                              {"instance_ids": ["worktree:unmerged"], "allow_unmerged": True},
                              {"agentId": "assistant", "sessionId": "s"}, governed=True)

    assert applied["ok"] is True and applied["status"] == "applied"
    assert [row["id"] for row in applied["cleaned"]] == ["worktree:unmerged"]
    assert not unmerged_path.exists()
    assert not _branch_exists(root, "codex/unmerged")
    assert Path(items["clean"]["path"]).exists()


def test_plan_fails_closed_without_resolvable_root(tmp_path, monkeypatch):
    from core.launcher import service as launcher_service

    root, items = _scanned_repo(tmp_path)
    _redirect_host_project_root(monkeypatch, tmp_path)
    monkeypatch.setattr("core.assistant_runtime.actions._binding", None)
    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("no root, no scan")))

    result = actions.plan({"agentId": "assistant"})

    assert result["ok"] is False
    assert result["status"] == "unavailable"
    assert result["error"] == "project_root_unavailable"
    assert "项目根" in result["message"]
    assert Path(items["clean"]["path"]).exists()


def test_plan_fails_closed_when_registered_roots_are_ambiguous(tmp_path, monkeypatch):
    from core.launcher import service as launcher_service

    root, items = _scanned_repo(tmp_path)
    other = _init_repo(tmp_path / "other-repo")
    monkeypatch.setattr("core.assistant_runtime.actions._binding",
                        (_StubHostService(root, other), object(), None))
    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("ambiguous root must not scan")))

    result = actions.plan({})

    assert result["ok"] is False
    assert result["error"] == "project_root_ambiguous"
    assert Path(items["clean"]["path"]).exists()


def test_instances_registry_fallback_resolves_single_git_root(tmp_path, monkeypatch):
    from core.runtime_manager import instances_registry as registry

    root, items = _scanned_repo(tmp_path)
    _redirect_host_project_root(monkeypatch, tmp_path)
    monkeypatch.setattr("core.assistant_runtime.actions._binding", None)
    _no_claims(monkeypatch)
    registry_path = registry.instances_registry_path()
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps({"schemaVersion": 3, "instances": {
        "worktree:elsewhere": {"projectRoot": str(tmp_path / "not-a-repo"), "status": "closed"},
        "worktree:main": {"status": "closed"},
        "worktree:managed": {"projectRoot": str(root), "status": "closed"},
    }}, ensure_ascii=False), encoding="utf-8")

    plan = actions.plan({})

    assert plan["ok"] is True
    rows = {row["instanceId"]: row for row in plan["instances"]}
    assert rows["worktree:clean"]["eligible"] is True


def test_execute_fails_closed_without_root_and_never_scans(tmp_path, monkeypatch):
    from core.launcher import service as launcher_service

    root, items = _scanned_repo(tmp_path)
    monkeypatch.setattr("core.assistant_runtime.actions._binding", None)
    monkeypatch.setattr(launcher_service, "list_launcher_branch_instances",
                        lambda **kwargs: (_ for _ in ()).throw(AssertionError("no root, no scan")))

    result = actions.execute_cleanup({"instance_ids": ["worktree:clean"]}, {"agentId": "assistant"})

    assert result["ok"] is False
    assert result["action"] == "branch_cleanup_execute"
    assert result["error"] == "project_root_unavailable"
    assert Path(items["clean"]["path"]).exists()
    assert _branch_exists(root, "codex/clean")


def test_dispatch_registry_exposes_distinct_physical_roots(tmp_path):
    from core.assistant_runtime.dispatch import DispatchService

    first = tmp_path / "repo-one"
    second = tmp_path / "repo-two"
    first.mkdir()
    second.mkdir()
    service = DispatchService(tmp_path / "profile", {"registered:1": first, "registered:2": second,
                                                     "registered:aliased": first})
    assert service.registered_project_roots() == (first.resolve(), second.resolve())
