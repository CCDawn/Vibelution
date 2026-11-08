"""Execute Agent CLI commands through the automatically selected native sandbox.

The host platform, Codex CLI executable and shell are resolved automatically at
startup/first use; Agent-facing contracts (``exec_command`` / ``cli_tool`` /
``write_stdin``) never select Windows, Linux, Shell or Codex backend.  Public
session/cwd/security/timeout/cancel orchestration stays here; platform-specific
executable/shell/sandbox argv lives in ``core.infrastructure.codex_sandbox``.

MXC (Microsoft Execution Containers) backend — ``workspace_write`` tier only,
Windows only, evaluated before the SANDBOX_UNVERIFIED gate
------------------------------------------------------------------

On Windows the pre-MXC chain is fail-closed: without one-shot user-approval
evidence every sandboxed command is rejected (``SANDBOX_UNVERIFIED``) because
the native Codex offline boundary was never runtime-proven.  When the MXC
executor is installed at ``%LOCALAPPDATA%\\Vibelution\\sandbox\\wxc-exec.exe``
(pinned 1.0.x, version+probe+telemetry checked, and runtime self-verified with
a TTL cache — see ``core.infrastructure.codex_sandbox.mxc``), the
``workspace_write`` tier executes inside MXC instead: workspace readwrite +
redirected TEMP, egress/ingress deny, unique per-run child temp, process-tree
termination on timeout/cancel.  Any MXC failure (probe / version / self-verify
/ spawn) falls back to the pre-MXC chain unchanged (evidence pass or
``SANDBOX_UNVERIFIED`` fail-closed) and emits a structured
``tool.execution.mxc_backend`` event whose ``code`` distinguishes the cause:
``mxc_unavailable`` / ``mxc_version_unsupported`` / ``mxc_probe_failed`` /
``mxc_verify_failed`` / ``mxc_spawn_failed`` / ``mxc_non_ascii_argv``.

Tier matrix (executor ``--probe``, PoC baseline Windows 26200.8875):

- ``basecontainer`` (PSEC; **requires Windows >= 26200.9278**): full policy
  surface — ``deniedPaths`` (workspace ``.git`` protection) and explicit
  egress rules become available.  This tier unlocks the complete MXC
  capability set.
- ``appcontainer-dacl`` (degraded fallback tier): two-state policy only —
  workspace write + network deny are enforced; ``deniedPaths`` and egress
  allow rules are silently unsupported there and are never emitted
  (workspace ``.git`` is NOT protected in this tier).
- ``danger_full_access`` bypasses MXC entirely (direct subprocess, no
  sandbox); the route.blocked content gate and ``_resolve_cwd`` boundary
  semantics keep running before any sandbox selection; ``read_only`` keeps
  the pre-MXC fail-closed behavior (the MXC two-state policy grants
  workspace writes, which would widen read-only).
- git-bash inner payloads never enter MXC (executor refuses: msys binaries
  fail ``STATUS_DLL_INIT_FAILED`` under MXC UI isolation, measured). Those
  commands fall back to the fail-closed chain unchanged; native cmd/powershell
  payloads (including git_bash routes the adapter inlined to cmd) run in MXC,
  with non-ASCII command text relayed through a UTF-8 script file in the
  granted child temp (PoC R5 GBK argv mojibake fix).

Approval integration: ``windows_offline_shell_unverified()`` returns False for
``workspace_write`` when MXC containment is verified, which restores the
auto_review silent auto-approval premise in the approvals service.

Online tier (``workspace_write_online``, programmatic selection only this
round): routed through MXC with the ``loopback_relay`` network profile —
egress deny stays on, ingress hostLoopback allows the sandbox to reach the
in-process plaintext relay (``loopback_relay.py``) whose host side
terminates upstream TLS (sandbox TLS is measured-dead). The online verdict
is verified and cached separately from offline; the online mode refuses with
``SANDBOX_UNVERIFIED`` whenever MXC does not take the command and never
falls back to the Codex chain.
"""

from __future__ import annotations

import hashlib
import locale
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.logging import debug as _debug_logger
from core.infrastructure.tool_execution_trace import record_tool_process_event
from core.infrastructure.codex_sandbox.environment import (
    sandbox_process_environment as _adapter_sandbox_process_environment,
    sandbox_temp_root as _adapter_sandbox_temp_root,
    scrub_credential_environment as _adapter_scrub_credential_environment,
)
from core.infrastructure.codex_sandbox import mxc as _mxc_backend
from core.infrastructure.codex_sandbox.loopback_relay import (
    get_or_start_relay as _get_or_start_relay,
)
from core.infrastructure.codex_sandbox.platform import host_platform as _host_platform
from core.infrastructure.codex_sandbox.process import (
    sandbox_popen_command as _sandbox_popen_command,
    sandbox_popen_kwargs as _sandbox_popen_kwargs,
    terminate_process_tree as _adapter_terminate_process_tree,
)
from core.infrastructure.codex_sandbox.resolver import (
    resolve_codex_executable as _resolve_codex_executable_impl,
)
from core.infrastructure.codex_sandbox.shell import (
    create_shell_adapter,
    powershell_executable as _powershell_executable,
    unix_shell_executable as _unix_shell_executable,
    windows_command_interpreter as _windows_command_interpreter,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_POLL_INTERVAL_SECONDS = 0.2
_TERMINAL_SESSION_MAX_OUTPUT_CHARS = 120_000
_TERMINAL_SESSION_TTL_SECONDS = 15 * 60
_TERMINAL_SESSION_MAX_LIFETIME_SECONDS = 15 * 60
_READ_ONLY_SANDBOX_MODE = "read_only"
_WORKSPACE_WRITE_SANDBOX_MODE = "workspace_write"
_WORKSPACE_WRITE_ONLINE_SANDBOX_MODE = "workspace_write_online"
_DANGER_FULL_ACCESS_SANDBOX_MODE = "danger_full_access"
_CODEX_SANDBOX_MODES = {
    _READ_ONLY_SANDBOX_MODE,
    _WORKSPACE_WRITE_SANDBOX_MODE,
    _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE,
}
# MXC online tier: the relay service map is a product-level default here (the
# relay module itself hard-codes no site); only programmatic callers select
# the online mode — preset mapping stays untouched this round.
_MXC_RELAY_SERVICES = {"pypi": "pypi.org", "npm": "registry.npmjs.org"}
_WINDOWS_OFFLINE_SHELL_BLOCK_CODE = "SANDBOX_UNVERIFIED"
# Public alias: tool layers (e.g. shell 失败冷却) need to recognize the
# environment-level rejection without importing private names.
SANDBOX_UNVERIFIED_BLOCK_CODE = _WINDOWS_OFFLINE_SHELL_BLOCK_CODE
_WINDOWS_OFFLINE_SHELL_BLOCK_MESSAGE = (
    "Windows 原生 Codex 离线 shell 隔离未通过运行时验证；"
    "为避免命令在可访问外网的错误边界中执行，只有携带用户显式批准一次性执行凭据的命令才会放行。"
    "本次调用没有有效凭据（审批即证据）：请在审批卡片显式批准该命令后重试，"
    "或由显式 danger_full_access 权限执行。命令未执行。"
)
_MXC_ONLINE_UNHANDLED_BLOCK_MESSAGE = (
    "在线档（workspace_write_online）只能在已通过运行时验证的 MXC 沙盒边界内执行；"
    "本次 MXC 未接管（不可用、被禁用或运行时验证未通过），"
    "命令未执行，也未回退到其他沙盒链路（不静默降级）。"
)


def _current_agent_sandbox_mode() -> str:
    """Read the immutable turn permission snapshot; default to sandboxed."""
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        runtime = {}
    permissions = (
        runtime.get("runtimePermissions")
        if isinstance(runtime, dict)
        and isinstance(runtime.get("runtimePermissions"), dict)
        else {}
    )
    sandbox_mode = str(permissions.get("sandboxMode") or "").strip().lower()
    if sandbox_mode in _CODEX_SANDBOX_MODES | {_DANGER_FULL_ACCESS_SANDBOX_MODE}:
        return sandbox_mode
    return _READ_ONLY_SANDBOX_MODE


def _sandbox_requires_codex(sandbox_mode: str) -> bool:
    return sandbox_mode != _DANGER_FULL_ACCESS_SANDBOX_MODE


def windows_mxc_containment_verified(sandbox_mode: str = _WORKSPACE_WRITE_SANDBOX_MODE) -> bool:
    """True when the MXC backend proves real containment for the given mode.

    审批层的沙箱包含前提：executor 二进制在位（固定安装路径）、版本锁
    1.0.x、probe 通过、且运行时自验证（workspace 写 + 出站必拒；在线档另
    加回环中继正向探测）通过。任何一环失败都返回 False —— 沙箱包含前提
    不成立，宁可多问一次。online 档按 ``loopback_relay`` profile 验证，
    与 offline 结论分开缓存、互不借用。
    """
    if _host_platform() != "windows" or _mxc_backend.sandbox_disabled_by_env():
        return False
    return _mxc_availability_with_events(
        "approval_premise", network_profile=_mxc_profile_for_mode(sandbox_mode)
    ).ok


def _mxc_profile_for_mode(sandbox_mode: str) -> str:
    """Map a sandbox mode to its MXC network profile (default offline)."""
    if sandbox_mode == _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE:
        return _mxc_backend.NETWORK_PROFILE_LOOPBACK_RELAY
    return _mxc_backend.NETWORK_PROFILE_OFFLINE


def _mxc_availability_with_events(
    context: str, *, network_profile: str = _mxc_backend.NETWORK_PROFILE_OFFLINE
) -> "_mxc_backend.MxcAvailability":
    """Availability verdict plus one structured event per fresh verification."""
    availability = _mxc_backend.ensure_verified(network_profile=network_profile)
    if availability.from_cache:
        return availability
    record_tool_process_event(
        "tool.execution.mxc_backend",
        commandHash="",
        code="mxc_verified" if availability.ok else (availability.code or "mxc_refused"),
        context=context,
        tier=availability.tier,
        telemetryPolicy=availability.telemetry_policy,
        networkProfile=availability.network_profile,
        relayPort=availability.relay_port,
        detail=availability.detail,
        processStatus="verified" if availability.ok else "refused",
    )
    if availability.ok:
        _debug_logger.info(
            f"[Codex CLI 沙盒] MXC 后端自验证通过 tier={availability.tier} "
            f"telemetryPolicy={availability.telemetry_policy} {availability.detail}"
        )
    else:
        _debug_logger.warning(
            f"[Codex CLI 沙盒] MXC 后端不可用 code={availability.code or 'mxc_refused'} "
            f"detail={availability.detail} telemetryPolicy={availability.telemetry_policy}；"
            "回退既有链路。"
        )
    return availability


def _mxc_network_policy_label(sandbox_mode: str) -> str:
    return "loopback_relay" if sandbox_mode == _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE else "deny"


def _block_online_mode_unhandled(command_hash: str) -> dict:
    """Fail-closed refusal for online mode whenever MXC did not take the command.

    在线档唯一执行边界是 MXC：任何「MXC 未接管」（不可用、被禁用、验证未
    通过、拒绝或 spawn 失败）都直接拒绝，绝不回退 Codex 链，绝不静默降级
    成 workspace_write 或更宽的边界放网络。
    """
    _log_outcome(command_hash, "blocked", reason="mxc_online_unhandled")
    return _terminal_error_payload(
        _WINDOWS_OFFLINE_SHELL_BLOCK_CODE,
        _MXC_ONLINE_UNHANDLED_BLOCK_MESSAGE,
    )


def _mxc_route_candidate(sandbox_mode: str) -> bool:
    """MXC handles Windows ``workspace_write`` / online commands, when enabled."""
    return (
        _host_platform() == "windows"
        and sandbox_mode
        in {_WORKSPACE_WRITE_SANDBOX_MODE, _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE}
        and not _mxc_backend.sandbox_disabled_by_env()
    )


def _record_mxc_event(command_hash: str, code: str, *, detail: str = "") -> None:
    record_tool_process_event(
        "tool.execution.mxc_backend",
        commandHash=command_hash,
        code=code,
        detail=detail,
        processStatus="fallback",
    )
    _debug_logger.warning(
        f"[Codex CLI 沙盒] MXC 后端回退 code={code} detail={detail} commandHash={command_hash}"
    )


def _mxc_build_gate_plan(
    *,
    sandbox_mode: str,
    route: Any,
    workdir: Path,
    command_hash: str,
    timeout_seconds: int,
    git_bash_executable: str,
) -> "_mxc_backend.MxcCommandPlan | None":
    """Build the MXC spawn plan for one command; ``None`` = fall back.

    Failure reasons are recorded as structured events (probe/version/verify
    failures come through the cached availability verdict; argv transport and
    policy preparation failures are recorded here).
    """
    if not _mxc_route_candidate(sandbox_mode):
        return None
    network_profile = _mxc_profile_for_mode(sandbox_mode)
    availability = _mxc_availability_with_events("gate", network_profile=network_profile)
    if not availability.ok:
        return None
    relay_port: int | None = None
    if network_profile == _mxc_backend.NETWORK_PROFILE_LOOPBACK_RELAY:
        try:
            relay_port = int(_get_or_start_relay(_MXC_RELAY_SERVICES).port)
        except Exception as exc:
            _record_mxc_event(
                command_hash,
                _mxc_backend.REASON_SPAWN_FAILED,
                detail=f"relay_start_{type(exc).__name__}",
            )
            return None
    executor = _mxc_backend.executor_path()
    if executor is None:
        _record_mxc_event(command_hash, _mxc_backend.REASON_UNAVAILABLE, detail="executor_binary_missing")
        return None
    child_temp = (
        workdir / ".tmp" / "mxc" / f"{command_hash[:8]}-{uuid.uuid4().hex[:6]}"
    ).resolve()
    try:
        child_temp.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        _record_mxc_event(
            command_hash, _mxc_backend.REASON_SPAWN_FAILED, detail=f"child_temp_{type(exc).__name__}"
        )
        return None
    try:
        plan = _mxc_backend.build_command_plan(
            executor,
            route,
            workdir=workdir,
            child_temp=child_temp,
            # External deadline enforcement stays authoritative; the in-policy
            # timeout is the last-resort backstop (PoC: 双保险).
            timeout_ms=(int(timeout_seconds) + 5) * 1000,
            tier=availability.tier,
            git_bash_executable=git_bash_executable,
            network_profile=network_profile,
            relay_port=relay_port,
        )
    except _mxc_backend.MxcPlanRefused as exc:
        _record_mxc_event(command_hash, exc.code, detail=exc.detail)
        _mxc_backend.cleanup_child_temp(child_temp)
        return None
    except Exception as exc:
        _record_mxc_event(
            command_hash, _mxc_backend.REASON_SPAWN_FAILED, detail=f"plan_{type(exc).__name__}"
        )
        _mxc_backend.cleanup_child_temp(child_temp)
        return None
    return plan


def _mxc_spawn_process(
    plan: "_mxc_backend.MxcCommandPlan",
    *,
    workdir: Path,
    stdin: int | None,
) -> subprocess.Popen[str]:
    """Spawn ``wxc-exec.exe`` window-less with the UTF-8 pipeline contract."""
    environment = _adapter_scrub_credential_environment(os.environ)
    environment.setdefault("PYTHONIOENCODING", "utf-8")
    environment.setdefault("PYTHONUTF8", "1")
    popen_kwargs: dict[str, Any] = dict(_sandbox_popen_kwargs(platform=_host_platform()))
    if stdin is not None:
        popen_kwargs["stdin"] = stdin
    process = subprocess.Popen(
        _sandbox_popen_command(plan.spawn_argv, platform=_host_platform()),
        shell=False,
        cwd=str(workdir),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="surrogateescape",
        **popen_kwargs,
    )
    return process


def _windows_offline_shell_is_unverified(sandbox_mode: str) -> bool:
    """Fail closed until native Windows offline containment is runtime-proven.

    A configured policy or an ``CodexSandboxOffline`` identity alone is not
    sufficient evidence: the direct shell boundary must also block outbound
    traffic. Networked work therefore stays on governed tools instead of an
    arbitrary local shell while the native boundary is unverifiable.

    MXC exception: when the MXC backend proves real containment (executor
    1.0.x in place + runtime self-verification passed), the
    ``workspace_write`` premise holds and this gate no longer claims
    otherwise. ``workspace_write_online`` needs its own ``loopback_relay``
    profile verification (loopback relay probe + external-target egress
    deny); an offline-only verdict never opens the online mode. ``read_only`` keeps
    fail-closed behavior (the MXC two-state policy grants workspace writes,
    which would widen read-only).
    """
    if not (_host_platform() == "windows" and _sandbox_requires_codex(sandbox_mode)):
        return False
    if (
        sandbox_mode in {_WORKSPACE_WRITE_SANDBOX_MODE, _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE}
        and windows_mxc_containment_verified(sandbox_mode)
    ):
        return False
    return True


def windows_offline_shell_unverified() -> bool:
    """Whether the live host+runtime shell boundary is an unverified Windows sandbox.

    Shared with the approval service: silent auto-approval of sandbox-contained
    tools is only valid where containment is actually proven.  With the MXC
    backend verified, ``workspace_write`` containment is real and this returns
    False; without MXC the Windows fail-closed answer is unchanged.
    """
    return _windows_offline_shell_is_unverified(_current_agent_sandbox_mode())


def is_sandbox_unverified_block(result_text: str) -> bool:
    """True when a tool result is this module's sandbox-unverified rejection.

    环境拒绝（无凭据）不是命令本身的失败：shell 失败冷却等机制应据此豁免，
    避免模型因环境拦截被计入失败意图而劝退。
    """
    return SANDBOX_UNVERIFIED_BLOCK_CODE in str(result_text or "")


def _approved_execution_evidence_allows(command_text: str) -> tuple[bool, str]:
    """Validate (and consume) one-shot user-approval evidence for this command.

    「审批即证据」：沙箱门只在 Windows 未验证场景生效。证据由审批服务在用户
    显式批准时签发（服务端内存态，模型不可见、不可构造），绑定 session +
    turn + 命令哈希且短 TTL。验证成功即消费（一次性）；查无证据、过期、
    会话/回合不一致一律拒绝并维持 SANDBOX_UNVERIFIED。
    """
    try:
        from core.web.services.agent_directory_service import current_agent_runtime

        runtime = current_agent_runtime()
    except Exception:
        runtime = {}
    session_id = str((runtime or {}).get("sessionId") or "").strip()
    turn_id = str((runtime or {}).get("turnId") or (runtime or {}).get("runId") or "").strip()
    if not session_id or not turn_id:
        return False, "no_runtime_identity"
    try:
        from core.web.services.session.execution_evidence import (
            command_execution_hash,
            verify_and_consume_execution_evidence,
        )

        return verify_and_consume_execution_evidence(
            session_id=session_id,
            turn_id=turn_id,
            command_hash=command_execution_hash(command_text),
        )
    except Exception:
        # 证据探测失败绝不放行；维持 fail-closed。
        return False, "evidence_probe_failed"


def _log_outcome(
    command_hash: str,
    status: str,
    *,
    reason: str,
    started_at: float | None = None,
    exit_code: int | None = None,
) -> None:
    record_tool_process_event(
        "tool.execution.process_outcome", commandHash=command_hash,
        processStatus=status, reason=reason, exitCode=exit_code,
        durationMs=(max(0, int((time.monotonic() - started_at) * 1000))
                    if started_at is not None else None),
    )
    fields = [
        f"commandHash={command_hash}",
        f"status={status}",
        f"reason={reason}",
    ]
    if exit_code is not None:
        fields.append(f"exitCode={exit_code}")
    if started_at is not None:
        fields.append(f"durationMs={int((time.monotonic() - started_at) * 1000)}")
    message = f"[Codex CLI 沙盒] 结果 {' '.join(fields)}"
    if status in {"completed", "started"}:
        _debug_logger.info(message)
    else:
        _debug_logger.warning(message)


def _resolve_codex_executable() -> str:
    """Resolve the native Codex executable for the live host (fail closed)."""
    return _resolve_codex_executable_impl(
        platform=_host_platform(),
        environ=os.environ,
        which=shutil.which,
    )


def _resolve_cwd(cwd: str | None) -> Path:
    from tools.shell_tools import _get_workspace_root, get_workspace_root_override

    active_workspace = _get_workspace_root().resolve()
    workspace_root = active_workspace if (active_workspace / ".git").exists() else PROJECT_ROOT
    raw = Path(str(cwd or "").strip()) if str(cwd or "").strip() else workspace_root
    if not raw.is_absolute():
        raw = workspace_root / raw
    resolved = raw.resolve()
    if (
        get_workspace_root_override() is not None
        and _current_agent_sandbox_mode() != _DANGER_FULL_ACCESS_SANDBOX_MODE
        and resolved != workspace_root
        and not resolved.is_relative_to(workspace_root)
    ):
        raise PermissionError(
            f"工作目录超出 Agent 工作区边界: {resolved}; allowed={workspace_root}"
        )
    return resolved


def _sandbox_process_environment(
    workdir: Path,
    command_hash: str,
    *,
    environment_policy: str = "default",
) -> tuple[dict[str, str], Path]:
    """Build the sandbox child environment for the live host platform."""
    return _adapter_sandbox_process_environment(
        workdir,
        command_hash,
        environment_policy=environment_policy,
        platform=_host_platform(),
    )


def _cleanup_sandbox_temp(workdir: Path, sandbox_temp: Path | None) -> None:
    if sandbox_temp is None:
        return
    temp_root = _adapter_sandbox_temp_root(workdir)
    resolved = sandbox_temp.resolve()
    if resolved == temp_root or not resolved.is_relative_to(temp_root):
        return
    shutil.rmtree(resolved, ignore_errors=True)


def _sandbox_argv(
    executable: str,
    route: Any,
    *,
    git_bash_executable: str = "",
    sandbox_mode: str = _WORKSPACE_WRITE_SANDBOX_MODE,
) -> list[str]:
    """Build the sandbox argv for the live host platform (auto-selected)."""
    return create_shell_adapter(
        platform=_host_platform(),
        windows_command_interpreter_fn=_windows_command_interpreter,
        powershell_executable_fn=_powershell_executable,
        unix_shell_executable_fn=_unix_shell_executable,
        which=shutil.which,
    ).sandbox_argv(
        executable,
        route,
        git_bash_executable=git_bash_executable,
        sandbox_mode=sandbox_mode,
    )


def _describe_sandbox_route(route: Any) -> tuple[bool, str, str]:
    """Return ``(is_native_windows_command, command_env_var, route_label)``."""
    return create_shell_adapter(
        platform=_host_platform(),
        windows_command_interpreter_fn=_windows_command_interpreter,
        powershell_executable_fn=_powershell_executable,
        unix_shell_executable_fn=_unix_shell_executable,
        which=shutil.which,
    ).describe_route(route)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    """Terminate the sandbox process tree for the live host platform."""
    _adapter_terminate_process_tree(process, platform=_host_platform())


def _collect_output(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=2)
    except Exception:
        stdout, stderr = "", ""
    return str(stdout or ""), str(stderr or "")


def _recover_terminal_text(text: str) -> str:
    """Recover native Windows ANSI/OEM bytes that UTF-8 decoding left as surrogates."""

    if not text or not any("\udc80" <= character <= "\udcff" for character in text):
        return text
    try:
        raw = text.encode("utf-8", "surrogateescape")
    except UnicodeEncodeError:
        return text
    fallbacks = [encoding for encoding in ("mbcs", locale.getpreferredencoding(False)) if encoding]
    recovered: list[str] = []
    for line in raw.splitlines(keepends=True):
        try:
            recovered.append(line.decode("utf-8"))
            continue
        except UnicodeDecodeError:
            pass
        decoded = ""
        for fallback in fallbacks:
            try:
                decoded = line.decode(fallback)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        recovered.append(decoded or line.decode("utf-8", errors="replace"))
    return "".join(recovered)


def _format_output(stdout: str, stderr: str, returncode: int | None) -> str:
    stdout = _recover_terminal_text(stdout)
    stderr = _recover_terminal_text(stderr)
    parts = []
    if stdout:
        parts.append(stdout.strip())
    if stderr:
        parts.append(f"[STDERR]\n{stderr.strip()}")
    if not parts:
        parts.append("[命令执行完成，无输出]")
    output = "\n\n".join(parts)
    code = int(returncode or 0)
    if code == 0:
        return output
    has_error_keywords = any(
        keyword in output.lower()
        for keyword in (
            "error",
            "exception",
            "failed",
            "fail",
            "traceback",
            "syntaxerror",
            "indentationerror",
        )
    )
    prefix = "EXEC FAILURE" if has_error_keywords else "WARNING"
    return f"[{prefix} | Exit Code: {code}]\n{output}"


def _clamp_terminal_timeout(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        normalized = default
    return max(minimum, min(normalized, maximum))


class _SandboxTerminalSession:
    """One sandboxed process with bounded, pollable output and stdin support.

    The session is intentionally in-memory.  A backend restart makes a live child
    process unavailable rather than attempting to reattach to an unsafe shell.
    """

    def __init__(
        self,
        *,
        session_id: str,
        process: Any,
        command_hash: str,
        workdir: Path,
        sandbox_temp: Path | None,
        timeout_seconds: int,
        extra_cleanup: Callable[[], None] | None = None,
    ) -> None:
        self.session_id = session_id
        self.process = process
        self.command_hash = command_hash
        self.workdir = workdir
        self.sandbox_temp = sandbox_temp
        self.timeout_seconds = timeout_seconds
        self.extra_cleanup = extra_cleanup
        self.started_at = time.monotonic()
        self.idle_timeout_seconds = timeout_seconds
        self.hard_deadline = self.started_at + _TERMINAL_SESSION_MAX_LIFETIME_SECONDS
        self.deadline = min(
            self.started_at + self.idle_timeout_seconds,
            self.hard_deadline,
        )
        self.last_accessed_at = self.started_at
        self._status = "running"
        self._lock = threading.RLock()
        self._output_ready = threading.Event()
        self._stdout_pending = ""
        self._stderr_pending = ""
        self._total_output_chars = 0
        self._output_truncated = False
        self._outcome_logged = False
        self._final_snapshot: dict[str, Any] | None = None
        self._reader_threads = [
            threading.Thread(target=self._reader_loop, args=("stdout",), daemon=True, name=f"codex-sandbox-out-{session_id}"),
            threading.Thread(target=self._reader_loop, args=("stderr",), daemon=True, name=f"codex-sandbox-err-{session_id}"),
        ]

    def start(self) -> None:
        for reader in self._reader_threads:
            reader.start()

    def _reader_loop(self, stream_name: str) -> None:
        stream = getattr(self.process, stream_name, None)
        if stream is None:
            return
        while True:
            try:
                chunk = str(stream.read(1) or "")
            except Exception:
                return
            if not chunk:
                return
            with self._lock:
                self._total_output_chars += len(chunk)
                attribute = "_stdout_pending" if stream_name == "stdout" else "_stderr_pending"
                existing = str(getattr(self, attribute) or "")
                combined = existing + chunk
                if len(combined) > _TERMINAL_SESSION_MAX_OUTPUT_CHARS:
                    combined = combined[-_TERMINAL_SESSION_MAX_OUTPUT_CHARS :]
                    self._output_truncated = True
                setattr(self, attribute, combined)
                self._output_ready.set()

    def _is_alive(self) -> bool:
        try:
            return self.process.poll() is None
        except Exception:
            return False

    def _expire_if_needed(self) -> None:
        if self._status != "running" or time.monotonic() < self.deadline:
            return
        self._status = "timeout"
        _terminate_process_tree(self.process)

    def refresh_client_lease(self) -> None:
        """Keep a live process available across model and approval round trips."""

        now = time.monotonic()
        with self._lock:
            self.last_accessed_at = now
            if (
                self._status == "running"
                and now < self.hard_deadline
                and self._is_alive()
            ):
                self.deadline = min(
                    now + self.idle_timeout_seconds,
                    self.hard_deadline,
                )

    def _terminal_status(self) -> str:
        self._expire_if_needed()
        if self._status != "running":
            return self._status
        if self._is_alive():
            return "running"
        return "completed"

    def _drain_output(self, *, max_output_chars: int) -> tuple[str, str, bool, int]:
        with self._lock:
            stdout = _recover_terminal_text(self._stdout_pending)
            stderr = _recover_terminal_text(self._stderr_pending)
            self._stdout_pending = ""
            self._stderr_pending = ""
            self._output_ready.clear()
            total = self._total_output_chars
            truncated = self._output_truncated
        limit = _clamp_terminal_timeout(max_output_chars, default=12000, minimum=256, maximum=60000)
        combined_length = len(stdout) + len(stderr)
        if combined_length > limit:
            keep_stdout = min(len(stdout), max(0, limit // 2))
            keep_stderr = max(0, limit - keep_stdout)
            stdout = stdout[:keep_stdout]
            stderr = stderr[-keep_stderr:] if keep_stderr else ""
            truncated = True
        return stdout, stderr, truncated, total

    def _log_terminal_outcome_once(self, status: str, exit_code: int | None) -> None:
        if status == "running" or self._outcome_logged:
            return
        self._outcome_logged = True
        _log_outcome(
            self.command_hash,
            status,
            reason="terminal_session_exit",
            started_at=self.started_at,
            exit_code=exit_code,
        )
        _cleanup_sandbox_temp(self.workdir, self.sandbox_temp)
        if callable(self.extra_cleanup):
            try:
                self.extra_cleanup()
            except Exception:
                pass

    def snapshot(self, *, max_output_chars: int) -> dict[str, Any]:
        self.last_accessed_at = time.monotonic()
        status = self._terminal_status()
        if status != "running" and self._final_snapshot is not None:
            return dict(self._final_snapshot)
        if status != "running":
            for reader in self._reader_threads:
                if reader.ident is not None and reader.is_alive():
                    reader.join(timeout=1.0)
        stdout, stderr, truncated, original_length = self._drain_output(max_output_chars=max_output_chars)
        try:
            exit_code = self.process.returncode if not self._is_alive() else None
        except Exception:
            exit_code = None
        self._log_terminal_outcome_once(status, exit_code)
        formatted_output = _format_output(stdout, stderr, exit_code) if (stdout or stderr or status != "running") else ""
        outcome_status = "running"
        if status == "completed":
            outcome_status = "success" if exit_code in (None, 0) else "nonzero_exit"
        elif status in {"timeout", "cancelled", "failed"}:
            outcome_status = status
        payload: dict[str, Any] = {
            "status": status,
            "terminalSessionId": self.session_id,
            "sessionOpen": status == "running",
            "exitCode": exit_code,
            "outcomeStatus": outcome_status,
            "stdout": stdout,
            "stderr": stderr,
            "formattedOutput": formatted_output,
            "durationMs": int((time.monotonic() - self.started_at) * 1000),
            "timedOut": status == "timeout",
            "truncated": bool(truncated),
            "originalLength": original_length,
        }
        if status in {"failed", "timeout", "cancelled"} or outcome_status == "nonzero_exit":
            payload["failureClass"] = "timeout" if status == "timeout" else "process_exit"
        result = {key: value for key, value in payload.items() if value not in {None, ""}}
        if status != "running":
            self._final_snapshot = dict(result)
        return result

    def wait_for_update(
        self,
        *,
        yield_time_ms: int,
        max_output_chars: int,
        cancel_checker: Callable[[], str] | None = None,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + _clamp_terminal_timeout(
            yield_time_ms,
            default=10_000,
            minimum=0,
            maximum=30_000,
        ) / 1000.0
        while True:
            cancellation_reason = ""
            if callable(cancel_checker):
                try:
                    cancellation_reason = str(cancel_checker() or "").strip()
                except Exception:
                    cancellation_reason = ""
            if cancellation_reason:
                self._status = "cancelled"
                _terminate_process_tree(self.process)
                payload = self.snapshot(max_output_chars=max_output_chars)
                payload["cancelReason"] = cancellation_reason
                return payload
            if self._terminal_status() != "running" or self._output_ready.is_set() or time.monotonic() >= deadline:
                return self.snapshot(max_output_chars=max_output_chars)
            self._output_ready.wait(timeout=min(0.1, max(0.0, deadline - time.monotonic())))

    def send_input(self, chars: str) -> str:
        if self._terminal_status() != "running":
            return "terminal_not_running"
        if not chars:
            return ""
        stdin = getattr(self.process, "stdin", None)
        if stdin is None:
            return "stdin_unavailable"
        try:
            stdin.write(chars)
            stdin.flush()
        except Exception:
            return "stdin_write_failed"
        return ""


_SANDBOX_TERMINAL_SESSIONS: dict[str, _SandboxTerminalSession] = {}
_SANDBOX_TERMINAL_SESSIONS_LOCK = threading.RLock()


def _prune_sandbox_terminal_sessions() -> None:
    now = time.monotonic()
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        stale_ids: list[str] = []
        for session_id, session in _SANDBOX_TERMINAL_SESSIONS.items():
            status = session._terminal_status()
            if status == "running":
                continue
            try:
                exit_code = session.process.returncode
            except Exception:
                exit_code = None
            session._log_terminal_outcome_once(status, exit_code)
            if now - session.last_accessed_at > _TERMINAL_SESSION_TTL_SECONDS:
                stale_ids.append(session_id)
        for session_id in stale_ids:
            _SANDBOX_TERMINAL_SESSIONS.pop(session_id, None)


def _terminal_error_payload(code: str, message: str, *, session_id: str = "") -> dict[str, Any]:
    payload = {
        "status": "failed",
        "code": code,
        "message": message,
        "failureClass": code.lower(),
    }
    if session_id:
        payload["terminalSessionId"] = session_id
    return payload


def _try_start_mxc_terminal_session(
    *,
    sandbox_mode: str,
    route: Any,
    workdir: Path,
    command_hash: str,
    timeout_seconds: int,
    yield_time_ms: int,
    max_output_chars: int,
    _cancel_checker: Callable[[], str] | None,
) -> tuple[dict[str, Any] | None, bool]:
    """Start one MXC terminal session.

    Returns ``(snapshot, mxc_not_handled)``; ``snapshot is None`` = fall back
    to the pre-MXC chain. ``mxc_not_handled`` forces the fail-closed evidence
    gate at the caller (same contract as ``_try_execute_via_mxc``).
    stdin piping depends on the executor forwarding its own stdin to the
    sandbox child; when it does not, the existing terminal_not_running /
    stdin guidance applies unchanged (one-shot ``cli_tool`` remains the
    reliable path).
    """
    if not _mxc_route_candidate(sandbox_mode):
        return None, False
    plan = _mxc_build_gate_plan(
        sandbox_mode=sandbox_mode,
        route=route,
        workdir=workdir,
        command_hash=command_hash,
        timeout_seconds=timeout_seconds,
        git_bash_executable=_mxc_git_bash_for_route(route),
    )
    if plan is None:
        return None, True
    try:
        process = _mxc_spawn_process(plan, workdir=workdir, stdin=subprocess.PIPE)
    except Exception as exc:
        _record_mxc_event(
            command_hash,
            _mxc_backend.REASON_SPAWN_FAILED,
            detail=f"popen_{type(exc).__name__}",
        )
        _mxc_backend.cleanup_child_temp(plan.child_temp)
        return None, True
    _prune_sandbox_terminal_sessions()
    session_id = f"sandbox-{uuid.uuid4().hex[:16]}"
    session = _SandboxTerminalSession(
        session_id=session_id,
        process=process,
        command_hash=command_hash,
        workdir=workdir,
        sandbox_temp=None,
        timeout_seconds=timeout_seconds,
        extra_cleanup=lambda: _mxc_backend.cleanup_child_temp(plan.child_temp),
    )
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        _SANDBOX_TERMINAL_SESSIONS[session_id] = session
    session.start()
    tier = plan.tier
    _debug_logger.info(
        f"[Codex CLI 沙盒] MXC 后端终端会话 terminalSessionId={session_id} "
        f"commandHash={command_hash} route={getattr(route, 'route', '')} tier={tier} "
        f"networkPolicy={_mxc_network_policy_label(sandbox_mode)} "
        f"cwd={workdir} timeout={timeout_seconds}s"
    )
    _log_outcome(command_hash, "started", reason="mxc_terminal_session_started", started_at=session.started_at)
    return (
        session.wait_for_update(
            yield_time_ms=yield_time_ms,
            max_output_chars=max_output_chars,
            cancel_checker=_cancel_checker,
        ),
        False,
    )


def start_codex_sandbox_terminal_session(
    command: str = "",
    *,
    timeout: int = 60,
    cwd: str | None = None,
    yield_time_ms: int = 10_000,
    max_output_chars: int = 12_000,
    _cancel_checker: Callable[[], str] | None = None,
    _environment_policy: str = "default",
) -> dict[str, Any]:
    """Start one sandboxed command and return a bounded Codex-style process snapshot."""

    normalized_command = str(command or "").strip()
    if not normalized_command:
        return _terminal_error_payload("MISSING_COMMAND", "exec_command 需要提供 cmd 参数。")
    command_hash = hashlib.sha256(normalized_command.encode("utf-8")).hexdigest()[:12]
    from tools.shell_tools import _find_git_bash, _is_command_dangerous, classify_shell_command

    sandbox_mode = _current_agent_sandbox_mode()
    is_dangerous, message = _is_command_dangerous(normalized_command)
    if is_dangerous and sandbox_mode != _DANGER_FULL_ACCESS_SANDBOX_MODE:
        _log_outcome(command_hash, "blocked", reason="dangerous_command")
        return _terminal_error_payload("DANGEROUS_COMMAND", message)
    try:
        workdir = _resolve_cwd(cwd)
    except PermissionError as exc:
        _log_outcome(command_hash, "blocked", reason="cwd_outside_sandbox")
        return _terminal_error_payload("CWD_OUTSIDE_SANDBOX", str(exc))
    if not workdir.is_dir():
        _log_outcome(command_hash, "unavailable", reason="invalid_cwd")
        return _terminal_error_payload("INVALID_CWD", f"工作目录不存在: {workdir}")
    route = classify_shell_command(normalized_command)
    if route.blocked:
        _log_outcome(command_hash, "blocked", reason=route.reason or "shell_route")
        return _terminal_error_payload("SHELL_ROUTE_BLOCKED", str(route.error or "命令路由被拦截。"))
    timeout_seconds = _clamp_terminal_timeout(timeout, default=60, minimum=1, maximum=_TERMINAL_SESSION_MAX_LIFETIME_SECONDS)

    # MXC backend (Windows workspace_write): content gates above already ran;
    # any MXC non-handling falls through and keeps the fail-closed evidence
    # gate on (same contract as the one-shot execution path).
    mxc_result, mxc_not_handled = _try_start_mxc_terminal_session(
        sandbox_mode=sandbox_mode,
        route=route,
        workdir=workdir,
        command_hash=command_hash,
        timeout_seconds=timeout_seconds,
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
        _cancel_checker=_cancel_checker,
    )
    if mxc_result is not None:
        return mxc_result

    if mxc_not_handled or _windows_offline_shell_is_unverified(sandbox_mode):
        evidence_ok, evidence_reason = _approved_execution_evidence_allows(normalized_command)
        if not evidence_ok:
            _log_outcome(
                command_hash,
                "blocked",
                reason=f"windows_offline_shell_unverified:{evidence_reason}",
            )
            return _terminal_error_payload(
                _WINDOWS_OFFLINE_SHELL_BLOCK_CODE,
                _WINDOWS_OFFLINE_SHELL_BLOCK_MESSAGE,
            )
    if sandbox_mode == _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE:
        # MXC handled online commands earlier (we would have returned); any
        # arrival here means MXC did not take it — refuse, never fall through
        # to the Codex chain (that would silently downgrade the online grant).
        return _block_online_mode_unhandled(command_hash)
    executable = _resolve_codex_executable() if _sandbox_requires_codex(sandbox_mode) else ""
    if _sandbox_requires_codex(sandbox_mode) and not executable:
        _log_outcome(command_hash, "unavailable", reason="codex_executable_missing")
        return _terminal_error_payload("CODEX_SANDBOX_UNAVAILABLE", "未找到原生 Codex CLI 可执行文件（codex.exe / codex）；命令未执行。")
    is_native_windows_command, command_env_name, _route_label = _describe_sandbox_route(
        route
    )
    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
        sandbox_mode=sandbox_mode,
    )
    sandbox_temp: Path | None = None
    try:
        # Prefer UTF-8 so agent-facing tool text is stable; native Windows tools
        # may still emit ANSI/OEM bytes — surrogateescape keeps them recoverable.
        encoding = "utf-8"
        environment, sandbox_temp = _sandbox_process_environment(
            workdir,
            command_hash,
            environment_policy=_environment_policy,
        )
        environment.pop(command_env_name, None)
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        environment.setdefault("PYTHONUTF8", "1")
        if is_native_windows_command:
            environment[command_env_name] = route.command
        if str(getattr(route, "route", "") or "") == "no_console_git":
            try:
                from core.infrastructure.no_console_git import (
                    apply_no_console_git_env,
                    resolve_git_executable,
                )

                environment = apply_no_console_git_env(
                    environment,
                    git_exe=resolve_git_executable(),
                )
            except Exception:
                pass
        process = subprocess.Popen(
            _sandbox_popen_command(argv, platform=_host_platform()),
            shell=False,
            cwd=str(workdir),
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="surrogateescape",
            **_sandbox_popen_kwargs(platform=_host_platform()),
        )
    except (FileNotFoundError, PermissionError) as exc:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
        _log_outcome(command_hash, "unavailable", reason=type(exc).__name__)
        return _terminal_error_payload("SANDBOX_START_FAILED", "Codex CLI 沙盒启动失败；命令未回退到非沙盒模式。")
    except Exception as exc:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
        _log_outcome(command_hash, "failed", reason=type(exc).__name__)
        return _terminal_error_payload("SANDBOX_START_FAILED", f"Codex CLI 沙盒启动失败: {type(exc).__name__}")
    if sandbox_temp is None:
        _terminate_process_tree(process)
        return _terminal_error_payload("SANDBOX_TEMP_UNAVAILABLE", "沙盒临时目录不可用。")
    _prune_sandbox_terminal_sessions()
    session_id = f"sandbox-{uuid.uuid4().hex[:16]}"
    session = _SandboxTerminalSession(
        session_id=session_id,
        process=process,
        command_hash=command_hash,
        workdir=workdir,
        sandbox_temp=sandbox_temp,
        timeout_seconds=timeout_seconds,
    )
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        _SANDBOX_TERMINAL_SESSIONS[session_id] = session
    session.start()
    _log_outcome(command_hash, "started", reason="terminal_session_started", started_at=session.started_at)
    return session.wait_for_update(
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
        cancel_checker=_cancel_checker,
    )


def write_codex_sandbox_terminal_stdin(
    terminal_session_id: str = "",
    chars: str = "",
    *,
    yield_time_ms: int = 1_000,
    max_output_chars: int = 12_000,
    _cancel_checker: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Send stdin to a live sandbox command or poll its bounded output."""

    session_id = str(terminal_session_id or "").strip()
    if not session_id:
        return _terminal_error_payload("MISSING_SESSION_ID", "write_stdin 需要提供 session_id 参数。")
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        session = _SANDBOX_TERMINAL_SESSIONS.get(session_id)
    if session is not None:
        session.refresh_client_lease()
    _prune_sandbox_terminal_sessions()
    with _SANDBOX_TERMINAL_SESSIONS_LOCK:
        session = _SANDBOX_TERMINAL_SESSIONS.get(session_id)
    if session is None:
        return _terminal_error_payload("TERMINAL_SESSION_NOT_FOUND", "终端会话不存在、已过期或后端已重启。", session_id=session_id)
    normalized_chars = str(chars or "")
    if not normalized_chars:
        return session.wait_for_update(
            yield_time_ms=yield_time_ms,
            max_output_chars=max_output_chars,
            cancel_checker=_cancel_checker,
        )
    input_error = session.send_input(normalized_chars)
    if input_error:
        # Distinguish process exit from true stdin pipe absence — agents often
        # write_stdin after a non-interactive command already completed.
        error_by_kind = {
            "terminal_not_running": (
                "TERMINAL_SESSION_CLOSED",
                "终端进程已结束，无法写入 stdin。"
                "非交互命令（powershell/cmd 单次执行）结束后会话即关闭；"
                "请用 cli_tool 一次性执行完整命令，不要依赖 write_stdin 续跑。",
            ),
            "stdin_unavailable": (
                "TERMINAL_STDIN_UNAVAILABLE",
                "终端会话不支持标准输入（stdin 管道不可用）。",
            ),
            "stdin_write_failed": (
                "TERMINAL_STDIN_WRITE_FAILED",
                "写入终端标准输入失败（管道已关闭或进程退出）。",
            ),
        }
        code, message = error_by_kind.get(
            input_error,
            ("TERMINAL_STDIN_UNAVAILABLE", "终端输入不可用。"),
        )
        payload = session.snapshot(max_output_chars=max_output_chars)
        payload.update(_terminal_error_payload(code, message, session_id=session_id))
        return payload
    return session.wait_for_update(
        yield_time_ms=yield_time_ms,
        max_output_chars=max_output_chars,
        cancel_checker=_cancel_checker,
    )


def _run_process_loop(
    process: subprocess.Popen[str],
    *,
    command_hash: str,
    started_at: float,
    timeout_seconds: int,
    cancel_checker: Callable[[], str] | None,
) -> str:
    """Shared poll loop: cancel + deadline + exit semantics for all backends."""
    deadline = started_at + timeout_seconds
    while True:
        cancellation_reason = ""
        if callable(cancel_checker):
            try:
                cancellation_reason = str(cancel_checker() or "").strip()
            except Exception:
                cancellation_reason = ""
        if cancellation_reason:
            _terminate_process_tree(process)
            stdout, stderr = _collect_output(process)
            preview = _format_output(stdout, stderr, process.returncode)
            suffix = "" if preview == "[命令执行完成，无输出]" else f"\n\n{preview}"
            elapsed_ms = int((time.monotonic() - started_at) * 1000)
            _log_outcome(
                command_hash,
                "cancelled",
                reason="stop_requested",
                started_at=started_at,
                exit_code=process.returncode,
            )
            return (
                f"[取消] 命令已因停止请求终止：{cancellation_reason} "
                f"({elapsed_ms}ms){suffix}"
            )

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _terminate_process_tree(process)
            _collect_output(process)
            _log_outcome(
                command_hash,
                "timeout",
                reason="deadline_exceeded",
                started_at=started_at,
                exit_code=process.returncode,
            )
            return (
                f"[超时] 命令执行超过 {timeout_seconds} 秒被强制终止。\n"
                "请检查命令是否陷入死循环。"
            )
        try:
            stdout, stderr = process.communicate(
                timeout=min(_POLL_INTERVAL_SECONDS, remaining)
            )
            record_tool_process_event(
                "tool.execution.process_exit_observed", commandHash=command_hash,
                processId=getattr(process, "pid", None), exitCode=process.returncode,
            )
            result = _format_output(
                str(stdout or ""),
                str(stderr or ""),
                process.returncode,
            )
            _log_outcome(
                command_hash,
                "completed",
                reason="process_exit",
                started_at=started_at,
                exit_code=process.returncode,
            )
            return result
        except subprocess.TimeoutExpired:
            continue


def _mxc_git_bash_for_route(route: Any) -> str:
    if str(getattr(route, "route", "") or "") != "git_bash":
        return ""
    try:
        from tools.shell_tools import _find_git_bash

        return _find_git_bash()
    except Exception:
        return ""


def _try_execute_via_mxc(
    *,
    sandbox_mode: str,
    route: Any,
    workdir: Path,
    command_hash: str,
    timeout_seconds: int,
    cancel_checker: Callable[[], str] | None,
) -> tuple[str | None, bool]:
    """Run one command through MXC.

    Returns ``(output, mxc_not_handled)``. ``output is None`` means fall back
    to the pre-MXC chain; ``mxc_not_handled`` is True whenever MXC was the
    selected backend candidate but the command did not go through it
    (availability refusal, argv transport refusal, or spawn failure). The
    caller applies the fail-closed evidence gate in that case even though MXC
    containment may be cached as verified — the fallback would otherwise
    execute in the never-proven Windows Codex sandbox with the gate open.
    """
    if not _mxc_route_candidate(sandbox_mode):
        return None, False
    plan = _mxc_build_gate_plan(
        sandbox_mode=sandbox_mode,
        route=route,
        workdir=workdir,
        command_hash=command_hash,
        timeout_seconds=timeout_seconds,
        git_bash_executable=_mxc_git_bash_for_route(route),
    )
    if plan is None:
        return None, True
    started_at = time.monotonic()
    try:
        process = _mxc_spawn_process(plan, workdir=workdir, stdin=None)
    except Exception as exc:
        _record_mxc_event(
            command_hash,
            _mxc_backend.REASON_SPAWN_FAILED,
            detail=f"popen_{type(exc).__name__}",
        )
        _mxc_backend.cleanup_child_temp(plan.child_temp)
        return None, True
    tier = plan.tier
    _debug_logger.info(
        f"[Codex CLI 沙盒] MXC 后端执行 commandHash={command_hash} "
        f"route={getattr(route, 'route', '')} tier={tier} "
        f"networkPolicy={_mxc_network_policy_label(sandbox_mode)} "
        f"cwd={workdir} timeout={timeout_seconds}s"
    )
    record_tool_process_event(
        "tool.execution.process_started", commandHash=command_hash,
        processId=getattr(process, "pid", None),
        route=f"mxc:{tier}" if tier else "mxc", timeoutSeconds=timeout_seconds,
    )
    try:
        return (
            _run_process_loop(
                process,
                command_hash=command_hash,
                started_at=started_at,
                timeout_seconds=timeout_seconds,
                cancel_checker=cancel_checker,
            ),
            False,
        )
    finally:
        _mxc_backend.cleanup_child_temp(plan.child_temp)


def execute_codex_sandbox_command(
    command: str = "",
    timeout: int = 60,
    cwd: str | None = None,
    _cancel_checker: Callable[[], str] | None = None,
    _environment_policy: str = "default",
) -> str:
    """Run one shell command in the automatically selected native sandbox."""

    normalized_command = str(command or "").strip()
    if not normalized_command:
        return "[错误] 命令不能为空"
    command_hash = hashlib.sha256(normalized_command.encode("utf-8")).hexdigest()[:12]

    from tools.shell_tools import _is_command_dangerous
    from tools.shell_tools import _find_git_bash
    from tools.shell_tools import classify_shell_command

    sandbox_mode = _current_agent_sandbox_mode()
    is_dangerous, message = _is_command_dangerous(normalized_command)
    if is_dangerous and sandbox_mode != _DANGER_FULL_ACCESS_SANDBOX_MODE:
        _log_outcome(command_hash, "blocked", reason="dangerous_command")
        return f"[安全拦截] {message}\n该危险命令已被系统安全策略禁止执行。"

    try:
        workdir = _resolve_cwd(cwd)
    except PermissionError as exc:
        _log_outcome(command_hash, "blocked", reason="cwd_outside_sandbox")
        return f"[安全拦截] {exc}"
    if not workdir.is_dir():
        _log_outcome(command_hash, "unavailable", reason="invalid_cwd")
        return f"[错误] 工作目录不存在: {workdir}"

    route = classify_shell_command(normalized_command)
    if route.blocked:
        _log_outcome(command_hash, "blocked", reason=route.reason or "shell_route")
        return route.error

    try:
        timeout_seconds = max(int(timeout), 1)
    except (TypeError, ValueError):
        timeout_seconds = 60

    # MXC backend (Windows workspace_write): content gates above already ran;
    # containment is runtime-proven before any command may enter MXC. Any MXC
    # non-handling (refusal or spawn failure) falls through and keeps the
    # fail-closed evidence gate on — the fallback Codex path is never trusted
    # on the strength of MXC's containment.
    mxc_result, mxc_not_handled = _try_execute_via_mxc(
        sandbox_mode=sandbox_mode,
        route=route,
        workdir=workdir,
        command_hash=command_hash,
        timeout_seconds=timeout_seconds,
        cancel_checker=_cancel_checker,
    )
    if mxc_result is not None:
        return mxc_result

    if mxc_not_handled or _windows_offline_shell_is_unverified(sandbox_mode):
        evidence_ok, evidence_reason = _approved_execution_evidence_allows(normalized_command)
        if not evidence_ok:
            _log_outcome(
                command_hash,
                "blocked",
                reason=f"windows_offline_shell_unverified:{evidence_reason}",
            )
            return (
                f"[安全拦截 | {_WINDOWS_OFFLINE_SHELL_BLOCK_CODE}] "
                f"{_WINDOWS_OFFLINE_SHELL_BLOCK_MESSAGE}\n也未回退到非沙盒模式。"
            )
    if sandbox_mode == _WORKSPACE_WRITE_ONLINE_SANDBOX_MODE:
        # MXC handled online commands earlier (we would have returned); any
        # arrival here means MXC did not take it — refuse, never fall through
        # to the Codex chain (that would silently downgrade the online grant).
        return (
            f"[安全拦截 | {_WINDOWS_OFFLINE_SHELL_BLOCK_CODE}] "
            f"{_MXC_ONLINE_UNHANDLED_BLOCK_MESSAGE}"
        )

    executable = _resolve_codex_executable() if _sandbox_requires_codex(sandbox_mode) else ""
    if _sandbox_requires_codex(sandbox_mode) and not executable:
        _log_outcome(command_hash, "unavailable", reason="codex_executable_missing")
        return (
            "[错误] Codex CLI 沙盒不可用：未找到原生 Codex CLI（codex.exe / codex）。"
            "命令未执行，也未回退到非沙盒模式。"
        )

    is_native_windows_command, command_env_name, route_label = _describe_sandbox_route(
        route
    )
    argv = _sandbox_argv(
        executable,
        route,
        git_bash_executable=_find_git_bash() if route.route == "git_bash" else "",
        sandbox_mode=sandbox_mode,
    )
    _debug_logger.info(
        f"[Codex CLI 沙盒] 启动 commandHash={command_hash} "
        f"route={route_label} sandboxMode={sandbox_mode} "
        f"networkPolicy={'host' if sandbox_mode == _DANGER_FULL_ACCESS_SANDBOX_MODE else 'disabled'} "
        f"cwd={workdir} timeout={timeout_seconds}s"
    )
    started_at = time.monotonic()
    process: subprocess.Popen[str] | None = None
    sandbox_temp: Path | None = None
    try:
        encoding = "utf-8"
        environment, sandbox_temp = _sandbox_process_environment(
            workdir,
            command_hash,
            environment_policy=_environment_policy,
        )
        environment.pop(command_env_name, None)
        environment.setdefault("PYTHONIOENCODING", "utf-8")
        environment.setdefault("PYTHONUTF8", "1")
        if is_native_windows_command:
            environment[command_env_name] = route.command
        if str(getattr(route, "route", "") or "") == "no_console_git":
            try:
                from core.infrastructure.no_console_git import (
                    apply_no_console_git_env,
                    resolve_git_executable,
                )

                environment = apply_no_console_git_env(
                    environment,
                    git_exe=resolve_git_executable(),
                )
            except Exception:
                pass
        process = subprocess.Popen(
            _sandbox_popen_command(argv, platform=_host_platform()),
            shell=False,
            cwd=str(workdir),
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=encoding,
            errors="surrogateescape",
            **_sandbox_popen_kwargs(platform=_host_platform()),
        )
        record_tool_process_event(
            "tool.execution.process_started", commandHash=command_hash,
            processId=getattr(process, "pid", None), route=route_label, timeoutSeconds=timeout_seconds,
        )
        return _run_process_loop(
            process,
            command_hash=command_hash,
            started_at=started_at,
            timeout_seconds=timeout_seconds,
            cancel_checker=_cancel_checker,
        )
    except FileNotFoundError:
        _log_outcome(
            command_hash,
            "unavailable",
            reason="sandbox_process_missing",
            started_at=started_at,
        )
        return (
            "[错误] Codex CLI 沙盒启动失败：Codex CLI 或命令解释器不存在。"
            "命令未执行，也未回退到非沙盒模式。"
        )
    except PermissionError:
        _log_outcome(
            command_hash,
            "unavailable",
            reason="sandbox_process_permission_denied",
            started_at=started_at,
        )
        return (
            "[权限错误] 无法启动 Codex CLI 沙盒。"
            "命令未执行，也未回退到非沙盒模式。"
        )
    except Exception as exc:
        _log_outcome(
            command_hash,
            "failed",
            reason=type(exc).__name__,
            started_at=started_at,
        )
        if process is not None:
            _terminate_process_tree(process)
        return (
            f"[执行错误] Codex CLI 沙盒启动失败: {type(exc).__name__}: {exc}\n"
            "命令未执行，也未回退到非沙盒模式。"
        )
    finally:
        _cleanup_sandbox_temp(workdir, sandbox_temp)
