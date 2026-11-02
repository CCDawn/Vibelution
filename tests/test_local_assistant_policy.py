import shutil
import sys

import pytest

from core.web.services.local_assistant import policy
from core.web.services.external_agent.policy import external_runtime_tool_grants
from core.web.services.tool_catalog import TOOL_CATALOG


def test_local_grants_are_registered_workspace_tools_only():
    external_before = external_runtime_tool_grants("workspace_write")
    grants = set(policy.local_runtime_tool_grants("workspace_write"))
    assert {"cli_tool", "exec_command", "write_stdin", "read_file_tool",
            "write_file_tool", "apply_diff_edit_tool", "apply_patch_tool",
            "grep_search_tool", "glob_tool"} == grants
    assert grants <= TOOL_CATALOG.keys()
    assert not grants & {"web_search_tool", "web_fetch_tool", "clean_workspace_debris_tool",
                         "agent_message_tool", "unified_memory_search_tool",
                         "get_session_files_tool", "personal_assistant_manage_tool"}
    read_only = set(policy.local_runtime_tool_grants("read_only"))
    assert read_only == {"grep_search_tool", "glob_tool", "read_file_tool"}
    assert external_runtime_tool_grants("workspace_write") == external_before
    assert not read_only & {"write_file_tool", "apply_diff_edit_tool", "apply_patch_tool"}
    assert policy.LOCAL_RUNTIME_SOURCE_PREFIX == "launcher_assistant_task:"
    with pytest.raises(ValueError):
        policy.local_runtime_tool_grants("full_access")


@pytest.mark.parametrize("command", [
    "python -m pytest tests/test_sample.py -q",
    'python -m pytest -o "addopts=-q" -p pytest_asyncio tests',
    'python -m pytest --override-ini="addopts=-q -s" tests',
    "pytest --override-ini=addopts=-q --confcutdir=. tests",
    "python -m unittest discover -s tests", "python -m unittest test_isolated_demo -v",
    "python -m compileall -q core",
    f'"{sys.executable}" -m pytest -q',
    "npm run test -- --run", "npm run build", "npm run typecheck",
    "npm run lint", "npm run check", "npx --no-install vitest run tests/sample.test.ts",
    "npx --no-install tsc -b --pretty false",
    "node web/node_modules/vitest/vitest.mjs run --root web",
    "node web/node_modules/typescript/bin/tsc -b web/tsconfig.json",
    "git status --short", "git diff --stat", "git log -3 --oneline",
    "git -C . --no-pager diff", "git add core/example.py",
    'git commit -m "Implement ordinary development"',
    "git switch -c codex/example", "git branch codex/example",
    "git merge --ff-only codex/example",
])
def test_ordinary_development_commands_can_continue(tmp_path, command):
    assert policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)
    assert policy.normal_development_call("cli_tool", {"command": command, "cwd": "."}, tmp_path)


@pytest.mark.parametrize("command", [
    "git push origin main", "git reset --hard", "git clean -fd", "git rm core/example.py",
    "git branch -D main", "git switch --discard-changes main", "git config user.email x@y.test",
    "git -c core.hooksPath=outside commit -m test", "git --git-dir=../other status",
    "git diff --output=../outside", "git diff --ext-diff", "git diff --textconv",
    "git grep --open-files-in-pager=python test", "git grep -Opython test",
    "git grep -nOpython test", "git grep --open-files-in-p=python test",
    "git diff --out=../outside", "git log --textc", "git checkout -- .",
    "python scripts/delete_test_data.py", "python -c 'print(1)'", "python -m http.server",
    "node scripts/test_delete.js", "npm run contest", "npm install", "npm publish",
    "npx --yes arbitrary-package test", "npx --no-install vitest --run",
    "npx --no-install vitest run --api", "npx --no-install tsc --watch=true",
    "node evilnode_modules/vitest/vitest.mjs run",
    "pytest -q; git push", "pytest -q && git push", "pytest -q | other",
    "pytest -q > outside", "pytest $(git push)", "pytest `git push`",
    "pytest\ngit push", "pytest\rgit push", "pytest %EVIL%", "pytest !EVIL!", "pytest ^& whoami",
    "powershell -Command pytest", "cmd /c pytest", "sh -c pytest", "Remove-Item file",
])
def test_high_risk_and_uninterpretable_commands_keep_approval(tmp_path, command):
    assert not policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


@pytest.mark.parametrize("command", [
    "pytest --basetemp=C:/outside", "python -m pytest --basetemp ../outside",
    'pytest -o "addopts=--basetemp=C:/outside"',
    "pytest --override-ini=addopts=--basetemp=C:/outside",
    "pytest -oaddopts=--basetemp=C:/outside", "pytest -o cache_dir=../outside",
    'pytest -o "testpaths=../outside"', 'pytest -o "pythonpath=C:/outside"',
    "pytest @../outside/arguments.txt", "pytest -c ../outside/pytest.ini",
    "npm run test --prefix=C:/outside", "npm run test --script-shell=C:/outside/evil.exe",
    "npm run test --workspace=C:/outside", "npm run test -w ../outside", "npm run test -w../outside",
    "npm run test --userconfig=../outside/npmrc", "npm run test --globalconfig=../outside/npmrc",
    "npm run test -- --prefix=C:/outside", "npm run test -- --script-shell=C:/outside/evil.exe",
    "git grep --no-index token C:/outside/file.txt", "git grep -f ../outside/patterns token",
    "python -m unittest discover -s C:/outside", "python -m unittest discover -t ../outside",
    "python -m unittest discover -s../outside", "python -m unittest discover -s=../outside",
    "python -m compileall ../outside", "pytest ../outside/test.py",
    "npx --no-install vitest run --root=C:/outside", "npx --no-install vitest run --dir ../outside",
    "npx --no-install vitest run --config=../outside/vitest.config.ts",
    "npx --no-install vitest run --outputFile=../outside/result.json",
    "npx --no-install vitest run --coverage.reportsDirectory=../outside",
    "npx --no-install tsc --outDir=C:/outside", "npx --no-install tsc --outFile ../outside/out.js",
    "npx --no-install tsc --project=../outside/tsconfig.json", "npx --no-install tsc -p../outside",
    "npx --no-install tsc --declarationDir=../outside", "npx --no-install tsc --tsBuildInfoFile=../outside/build",
    "npx --no-install tsc --typeRoots=types,C:/outside",
    "npx --no-install tsc @../outside/compiler.args", "npx --no-install tsc --clean",
])
def test_explicit_delete_root_switch_and_config_injection_keep_approval(tmp_path, command):
    assert not policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


@pytest.mark.parametrize("command", [
    "pytest --rootdir=. --confcutdir=tests tests/test_sample.py -q",
    "pytest -o cache_dir=.cache/pytest -o testpaths=tests --junitxml=results.xml",
    "python -m unittest discover -s tests -t . -p test_*.py -v",
    "npx --no-install vitest run --root=web --dir=src --config=web/vitest.config.ts",
    "npx --no-install vitest run --outputFile=results.json --coverage.reportsDirectory=coverage",
    "npx --no-install tsc -b web/tsconfig.json --outDir=dist --tsBuildInfoFile=.cache/build --pretty false",
    "node web/node_modules/vitest/vitest.mjs run --config=web/vitest.config.ts",
    "node web/node_modules/typescript/bin/tsc --outDir dist --declarationDir types",
])
def test_explicit_paths_inside_task_can_continue(tmp_path, command):
    assert policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


@pytest.mark.parametrize("tool,entry", [("vitest", "vitest/vitest.mjs"), ("tsc", "typescript/bin/tsc")])
def test_npx_without_no_install_requires_a_local_tool(tmp_path, tool, entry):
    command = "npx vitest run" if tool == "vitest" else "npx tsc -b"
    assert not policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)
    installed = tmp_path / "node_modules" / entry
    installed.parent.mkdir(parents=True)
    installed.write_text("local tool identity fixture", encoding="utf-8")
    assert not policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)
    shim = tmp_path / "node_modules" / ".bin" / tool
    shim.parent.mkdir()
    shim.write_text("local executable fixture", encoding="utf-8")
    assert policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


@pytest.mark.parametrize("executable,arguments", [
    ("pytest.cmd", "-q"), ("git.cmd", "status"), ("python.exe", "-m pytest"),
])
def test_explicit_same_name_local_wrappers_keep_approval(tmp_path, executable, arguments):
    (tmp_path / executable).write_text("untrusted wrapper", encoding="utf-8")
    assert not policy.normal_development_call("exec_command", {"cmd": f'./{executable} {arguments}'}, tmp_path)
    assert not policy.normal_development_call("exec_command", {"cmd": f'"{tmp_path / executable}" {arguments}'}, tmp_path)


def test_explicit_outside_python_wrapper_is_not_the_trusted_interpreter(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    wrapper = tmp_path / "python.exe"
    wrapper.write_text("untrusted wrapper", encoding="utf-8")
    assert not policy.normal_development_call("exec_command", {"cmd": f'"{wrapper}" -m pytest'}, workspace)


@pytest.mark.parametrize("filename,command", [
    ("python.cmd", "python -m unittest discover"), ("python.EXE", "python -m pytest"),
    ("pytest.bat", "pytest -q"), ("git.com", "git status"),
    ("npm.ps1", "npm run build"), ("npx.cmd", "npx vitest run"),
    ("node.exe", "node web/node_modules/vitest/vitest.mjs run"),
])
def test_bare_tool_name_cannot_hide_a_working_directory_shadow(tmp_path, filename, command):
    (tmp_path / filename).write_text("untrusted wrapper", encoding="utf-8")
    assert not policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


def test_trusted_python_absolute_path_is_independent_of_cwd_shadows(tmp_path):
    (tmp_path / "python.cmd").write_text("untrusted wrapper", encoding="utf-8")
    assert policy.normal_development_call("exec_command", {"cmd": f'"{sys.executable}" -m unittest discover'}, tmp_path)


def test_explicit_tool_must_match_its_canonical_system_lookup(tmp_path, monkeypatch):
    workspace = tmp_path / "task"
    workspace.mkdir()
    installed = tmp_path / "system" / "git.exe"
    installed.parent.mkdir()
    installed.write_text("trusted identity fixture", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: str(installed) if name == "git" else None)
    assert policy.normal_development_call("exec_command", {"cmd": f'"{installed}" status'}, workspace)
    (workspace / "git.cmd").write_text("untrusted wrapper", encoding="utf-8")
    assert policy.normal_development_call("exec_command", {"cmd": f'"{installed}" status'}, workspace)


def test_task_local_path_lookup_does_not_establish_a_trusted_tool(tmp_path, monkeypatch):
    wrapper = tmp_path / "pytest.exe"
    wrapper.write_text("untrusted wrapper", encoding="utf-8")
    monkeypatch.setattr(shutil, "which", lambda name: str(wrapper))
    assert not policy.normal_development_call("exec_command", {"cmd": "pytest -q"}, tmp_path)
    assert not policy.normal_development_call("exec_command", {"cmd": f'"{wrapper}" -q'}, tmp_path)


def test_missing_path_tool_keeps_approval_but_the_server_python_still_works(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    assert not policy.normal_development_call("exec_command", {"cmd": "pytest -q"}, tmp_path)
    assert policy.normal_development_call("exec_command", {"cmd": f'"{sys.executable}" -m unittest discover'}, tmp_path)


def test_non_executable_directory_does_not_shadow_the_python_command(tmp_path):
    (tmp_path / "python").mkdir()
    assert policy.normal_development_call("exec_command", {"cmd": "python -m unittest discover"}, tmp_path)


@pytest.mark.parametrize("command", [
    "git status --short --branch", "git diff --stat --name-only", "git log -3 --oneline",
    "git grep -n test", "git grep -Fi test", "git grep -nFi test", "git grep --fixed-strings test",
    "git grep -n -e test -- core", "git grep --regexp=test", "git rev-parse --show-toplevel",
])
def test_explicit_read_only_git_option_sets_still_continue(tmp_path, command):
    assert policy.normal_development_call("exec_command", {"cmd": command}, tmp_path)


def test_command_cwd_and_git_directory_must_stay_inside_real_workspace(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    assert policy.normal_development_call("exec_command", {"cmd": "pytest", "cwd": str(workspace)}, workspace)
    for arguments in ({"cmd": "pytest", "cwd": ".."},
                      {"cmd": "pytest", "cwd": str(tmp_path)},
                      {"cmd": "git -C .. status"},
                      {"cmd": "git -C . -C .. status"}):
        assert not policy.normal_development_call("exec_command", arguments, workspace)


@pytest.mark.parametrize("name,args", [
    ("write_file_tool", {"file_path": "core/new.py", "content": "print(1)"}),
    ("apply_diff_edit_tool", {"file_path": "core/new.py", "diff_text": "example"}),
    ("read_file_tool", {"file_path": "core/new.py"}),
    ("apply_patch_tool", {"patch_text": "*** Begin Patch\n*** Add File: core/new.py\n+pass\n*** End Patch"}),
])
def test_file_calls_are_limited_to_task_workspace(tmp_path, name, args):
    assert policy.normal_development_call(name, args, tmp_path)
    if name != "apply_patch_tool":
        assert policy.normal_development_call(name, {**args, "file_path": str(tmp_path / "new.py")}, tmp_path)
        assert not policy.normal_development_call(name, {**args, "file_path": "../outside.py"}, tmp_path)


@pytest.mark.parametrize("patch", [
    "*** Begin Patch\n*** Add File: ../outside.py\n+pass\n*** End Patch",
    "*** Begin Patch\n*** Delete File: core/old.py\n*** End Patch",
    "*** Begin Patch\n*** Update File: core/old.py\n*** Move to: ../outside.py\n@@\n-old\n+new\n*** End Patch",
    "*** Begin Patch\n*** Add File: core/new.py\n+pass\n*** Delete File: core/old.py\n*** End Patch",
    "not a patch",
])
def test_patch_delete_and_escape_keep_approval(tmp_path, patch):
    assert not policy.normal_development_call("apply_patch_tool", {"patch_text": patch}, tmp_path)


def test_write_tool_prefix_normalization_and_git_authority_keep_approval(tmp_path):
    assert policy.normal_development_call("write_file_tool", {"file_path": "workspace/core/new.py"}, tmp_path)
    for target in ("workspace/../outside.py", ".git", ".GIT", ".git/config"):
        assert not policy.normal_development_call("write_file_tool", {"file_path": target}, tmp_path)


def test_unknown_workspace_is_not_inferred_from_process_cwd():
    assert not policy.normal_development_call("exec_command", {"cmd": "pytest"}, "")


def test_symlink_path_escape_keeps_approval(tmp_path):
    workspace = tmp_path / "task"
    workspace.mkdir()
    try:
        (workspace / "link").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    assert not policy.normal_development_call("write_file_tool", {"file_path": "link/out.py"}, workspace)
    assert not policy.normal_development_call("exec_command", {"cmd": "pytest", "cwd": "link"}, workspace)


def test_stdin_only_polling_and_no_other_tool_can_auto_approve(tmp_path):
    assert policy.normal_development_call("write_stdin", {"session_id": "terminal-a", "chars": ""}, tmp_path)
    assert policy.normal_development_call("write_stdin", {"session_id": "terminal-a"}, tmp_path)
    assert not policy.normal_development_call("write_stdin", {"session_id": "terminal-a", "chars": "y\n"}, tmp_path)
    for name in ("web_fetch_tool", "clean_workspace_debris_tool", "personal_assistant_manage_tool", "unknown"):
        assert not policy.normal_development_call(name, {"cmd": "pytest"}, tmp_path)


@pytest.mark.parametrize("action,args", [
    ("dispatch_write", {"project_id": "project", "agent_id": "coder", "dispatch_id": "task-a", "task": "Run tests"}),
    ("dispatch_derived", {"project_id": "project", "agent_id": "coder", "dispatch_id": "task-a", "task": "Run tests", "goal_id": "goal-a", "permission_profile": "workspace_write"}),
    ("delegation_goal_create", {"goal_id": "goal-a", "targets": [{"project_id": "project", "agent_id": "coder"}], "permission_profile": "workspace_write"}),
    ("delegation_goal_get", {"goal_id": "goal-a"}),
    ("delegation_goal_revoke", {"goal_id": "goal-a"}),
    ("dispatch_cancel", {"project_id": "project", "dispatch_id": "task-a", "native_task_id": "native-a"}),
])
def test_only_normal_management_actions_and_valid_arguments_continue(action, args):
    assert policy.normal_assistant_manage_call(action, args)
    assert not policy.normal_assistant_manage_call(action, {**args, "unexpected": True})
    assert not policy.normal_assistant_manage_call(action, {})


def test_management_privilege_increases_and_destructive_actions_keep_approval():
    args = {"goal_id": "goal-a", "targets": [{"project_id": "project", "agent_id": "coder"}], "permission_profile": "full_access"}
    assert not policy.normal_assistant_manage_call("delegation_goal_create", args)
    for action in ("restart", "agent_purge", "session_delete", "authorization_upgrade",
                   "knowledge_acl_grant", "config_update", "runtime_command", "publish", "dispatch"):
        assert not policy.normal_assistant_manage_call(action, {})


def test_descriptor_network_or_delete_metadata_cannot_use_command_auto_approval(tmp_path, monkeypatch):
    for risk in ("network_access", "delete_or_cleanup"):
        monkeypatch.setitem(TOOL_CATALOG, "exec_command", {**TOOL_CATALOG["exec_command"], "riskTags": [risk]})
        assert not policy.normal_development_call("exec_command", {"cmd": "pytest"}, tmp_path)


@pytest.mark.parametrize("args", [None, [], {"cmd": 4}, {"cmd": "pytest", "cwd": []}])
def test_malformed_development_arguments_keep_approval(tmp_path, args):
    assert not policy.normal_development_call("exec_command", args, tmp_path)
