"""MXC (Microsoft Execution Containers) sandbox backend for Windows commands.

Implements the ``wxc-exec.exe`` executor integration verified by the MXC PoC
(``%TEMP%/mxc-poc/REPORT.md``, 2026-11-08): probe precheck, version lock,
telemetry policy observation, fail-closed runtime self-verification with TTL
cache, and the ``workspace_write`` two-state policy (workspace readwrite +
outbound network deny).

Hard facts carried over from the PoC (Windows 11 26200.8875, MXC SDK 1.0.1):

- The executor binary is pinned to 1.0.x. 1.1+ introduces non-opt-out
  telemetry, so any other version is refused (fail closed). 1.0.1 has no
  ``--version`` CLI flag; the PE ``FileVersion`` resource is the shipped
  release authority and is read in-process instead of spawning a probe.
- ``wxc-exec.exe --probe`` (read-only, ~0.2s) reports the containment tier.
  ``basecontainer`` (PSEC, Windows >= 26200.9278) unlocks the full policy
  surface including ``deniedPaths``; ``appcontainer-dacl`` is the degraded
  two-state tier: workspace write + egress deny are enforced, but
  ``deniedPaths`` and explicit egress rules are silently unsupported, so they
  are never emitted there.
- Non-ASCII command arguments are corrupted into GBK mojibake when passed
  through the executor argv (PoC R5). cmd and powershell inner payloads
  therefore relay the command through a UTF-8 script file inside the granted
  child temp directory; direct-executable and git argv shapes have no script
  carrier and are refused (fallback) instead of executing mojibake.
- git-bash inner payloads do not initialize inside the sandbox at all
  (measured on the PoC host: ``STATUS_DLL_INIT_FAILED``, 0xC0000142, because
  MXC UI isolation blocks the win32k calls msys binaries need at startup).
  Bash-shaped commands are refused (``mxc_bash_unavailable``) and keep
  working on the pre-MXC evidence chain; enabling UI access in the policy
  would loosen containment and is not an acceptable trade.
- Every executor spawn uses window-less subprocess kwargs (PoC verified zero
  visible windows for both spawn forms).

All availability answers are fail-closed: any probe/version/verification
failure reports ``ok=False`` with a distinguishable reason code and the
caller must fall back to the pre-MXC chain.
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import socket
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from core.infrastructure.codex_sandbox.environment import (
    sandbox_temp_root as _sandbox_temp_root,
    scrub_credential_environment,
    VIBELUTION_CONFIG_HOME_ENV,
    VIBELUTION_CONFIG_PATH_ENV,
    VIBELUTION_DATA_HOME_ENV,
    VIBELUTION_SANDBOX_TEMP_ENV,
)
from core.infrastructure.codex_sandbox.shell import (
    DANGER_FULL_ACCESS_SANDBOX_MODE,
    WINDOWS_COMMAND_ENV,
    create_shell_adapter,
    powershell_executable as _powershell_executable,
    windows_command_interpreter as _windows_command_interpreter,
)

MXC_POLICY_SCHEMA_VERSION = "1.0.0"
# 1.0.x is the telemetry-safe contract line; 1.1+ ships non-opt-out telemetry.
MXC_ALLOWED_VERSION_PREFIX = "1.0"
MXC_DISABLE_ENV = "VIBELUTION_MXC_SANDBOX_DISABLE"
EXECUTOR_RELATIVE_PARTS = ("Vibelution", "sandbox", "wxc-exec.exe")
TELEMETRY_POLICY_REG_KEY = r"SOFTWARE\Policies\Mxc"
TELEMETRY_POLICY_REG_VALUE = "AllowTelemetry"

TIER_BASECONTAINER = "basecontainer"
TIER_APPCONTAINER_DACL = "appcontainer-dacl"
_SUPPORTED_TIERS = {TIER_BASECONTAINER, TIER_APPCONTAINER_DACL}

VERIFY_TTL_SUCCESS_SECONDS = 300.0
VERIFY_TTL_FAILURE_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 15.0
VERIFY_RUN_TIMEOUT_SECONDS = 30.0
VERIFY_MARKER_FILENAME = "mxc-verify-ok.txt"
VERIFY_CURL_CONNECT_TIMEOUT_SECONDS = 2
VERIFY_CURL_MAX_TIME_SECONDS = 8
VERIFY_POLICY_FILENAME = "mxc-verify-policy.json"
COMMAND_POLICY_FILENAME = "policy.json"

# Reason codes (structured event payload). Any code here means "MXC refused,
# caller must fall back to the pre-MXC chain".
REASON_UNAVAILABLE = "mxc_unavailable"
REASON_VERSION_UNSUPPORTED = "mxc_version_unsupported"
REASON_PROBE_FAILED = "mxc_probe_failed"
REASON_VERIFY_FAILED = "mxc_verify_failed"
REASON_SPAWN_FAILED = "mxc_spawn_failed"
REASON_NON_ASCII_ARGV = "mxc_non_ascii_argv"
# Measured on the PoC host (26200.8875, degraded tier): git bash fails to
# initialize inside the sandbox (STATUS_DLL_INIT_FAILED, 0xC0000142) because
# MXC UI isolation blocks the win32k calls msys needs; enabling UI access
# would loosen containment, so bash-shaped commands are refused and fall back
# to the pre-MXC chain instead.
REASON_BASH_UNAVAILABLE = "mxc_bash_unavailable"


class MxcPlanRefused(Exception):
    """Raised by ``build_command_plan`` when a command cannot be transported.

    ``code`` is one of the ``REASON_*`` codes so the caller can emit a
    distinguishable structured fallback event.
    """

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}")
        self.code = str(code)
        self.detail = str(detail)


class MxcAvailability:
    """One availability verdict for the MXC executor on this host."""

    __slots__ = ("ok", "code", "detail", "tier", "telemetry_policy", "from_cache")

    def __init__(
        self,
        *,
        ok: bool,
        code: str = "",
        detail: str = "",
        tier: str = "",
        telemetry_policy: str = "",
        from_cache: bool = False,
    ) -> None:
        self.ok = bool(ok)
        self.code = str(code)
        self.detail = str(detail)
        self.tier = str(tier)
        self.telemetry_policy = str(telemetry_policy)
        self.from_cache = bool(from_cache)


class MxcCommandPlan:
    """Everything needed to spawn one command inside the MXC sandbox."""

    __slots__ = ("spawn_argv", "policy_path", "child_temp", "relay_path", "tier")

    def __init__(
        self,
        *,
        spawn_argv: list[str],
        policy_path: Path,
        child_temp: Path,
        relay_path: Path | None = None,
        tier: str = "",
    ) -> None:
        self.spawn_argv = list(spawn_argv)
        self.policy_path = Path(policy_path)
        self.child_temp = Path(child_temp)
        self.relay_path = relay_path
        self.tier = str(tier)


class _VerifyState:
    __slots__ = ("availability", "expires_at")

    def __init__(self, availability: MxcAvailability, expires_at: float) -> None:
        self.availability = availability
        self.expires_at = expires_at


_VERIFY_STATE: _VerifyState | None = None
_VERIFY_STATE_LOCK = threading.Lock()

ExecutorInvoker = Callable[..., subprocess.CompletedProcess]


def sandbox_disabled_by_env(environ: dict[str, str] | None = None) -> bool:
    """Operational kill switch: ``VIBELUTION_MXC_SANDBOX_DISABLE=1`` forces off."""
    source = environ if environ is not None else os.environ
    return str(source.get(MXC_DISABLE_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def executor_path(environ: dict[str, str] | None = None) -> Path | None:
    """Fixed product install path of the pinned executor binary (no download)."""
    source = environ if environ is not None else os.environ
    local_app_data = str(source.get("LOCALAPPDATA") or "").strip()
    if not local_app_data:
        return None
    path = Path(local_app_data).joinpath(*EXECUTOR_RELATIVE_PARTS)
    return path if path.is_file() else None


def _read_pe_file_version(path: Path) -> tuple[int, int, int, int] | None:
    """Read the PE ``FileVersion`` resource in-process (Windows only)."""
    if os.name != "nt":
        return None
    try:
        version_api = ctypes.windll.version  # type: ignore[attr-defined]
        size = int(version_api.GetFileVersionInfoSizeW(str(path), None))
        if not size:
            return None
        data = ctypes.create_string_buffer(size)
        if not version_api.GetFileVersionInfoW(str(path), 0, size, data):
            return None
        value = ctypes.c_void_p()
        length = ctypes.c_uint()
        if not version_api.VerQueryValueW(data, "\\", ctypes.byref(value), ctypes.byref(length)):
            return None
        # VS_FIXEDFILEINFO: dwSignature, dwStrucVersion, dwFileVersionMS/LS at +8.
        if length.value < 16:
            return None
        raw = ctypes.cast(value, ctypes.POINTER(ctypes.c_ubyte * length.value)).contents
        signature = int.from_bytes(bytes(raw[0:4]), "little")
        if signature != 0xFEEF04BD:
            return None
        ms = int.from_bytes(bytes(raw[8:12]), "little")
        ls = int.from_bytes(bytes(raw[12:16]), "little")
        return (ms >> 16, ms & 0xFFFF, ls >> 16, ls & 0xFFFF)
    except Exception:
        return None


def executor_version_string(path: Path) -> str:
    """``major.minor.patch.build`` dotted string, or "" when unreadable."""
    parts = _read_pe_file_version(path)
    if parts is None:
        return ""
    return ".".join(str(part) for part in parts)


def _version_is_allowed(version_text: str) -> bool:
    if not version_text:
        return False
    major_minor = ".".join(version_text.split(".")[:2])
    return major_minor == MXC_ALLOWED_VERSION_PREFIX


def read_telemetry_policy() -> str:
    """Read-only HKLM telemetry policy observation (never writes the registry).

    ``blocked``: value present and 0, or unparsable (fail closed). MXC 1.0.x
    additionally ships no forced telemetry (request-level + user consent +
    policy all opt-in), so this is observability, not the enforcement layer.
    """
    if os.name != "nt":
        return "unset"
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, TELEMETRY_POLICY_REG_KEY, 0, winreg.KEY_READ
        ) as key:
            raw_value, value_type = winreg.QueryValueEx(key, TELEMETRY_POLICY_REG_VALUE)
    except FileNotFoundError:
        return "unset"
    except OSError:
        return "blocked"
    try:
        if value_type != winreg.REG_DWORD:
            return "blocked"
        return "blocked" if int(raw_value) == 0 else "allowed"
    except (TypeError, ValueError):
        return "blocked"


def _run_executor(argv: list[str], *, timeout_s: float) -> subprocess.CompletedProcess:
    """Single spawn seam for probe/verify executor calls (window-less)."""
    from scripts.windowless_subprocess import no_window_subprocess_kwargs

    return subprocess.run(
        argv,
        capture_output=True,
        timeout=timeout_s,
        **no_window_subprocess_kwargs(),
    )


def _write_policy_file(policy: dict, target: Path) -> Path:
    """Write the policy JSON (ASCII-escaped) so argv never carries its content."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(policy, ensure_ascii=True, sort_keys=True, indent=2),
        encoding="ascii",
    )
    return target


def build_workspace_write_policy(
    *,
    workspace: Path,
    child_temp: Path,
    timeout_ms: int,
    tier: str,
    env_entries: list[str],
    denied_paths: list[Path] | None = None,
) -> dict:
    """Build the MXC 1.0.0 ``workspace_write`` policy document.

    Two-state degraded tier (``appcontainer-dacl``): workspace/child-temp
    readwrite + egress/ingress deny, never ``deniedPaths`` (silently
    unsupported there — PoC R1) and never egress allow rules. The PSEC tier
    (``basecontainer``) additionally emits ``deniedPaths`` (used for the
    workspace ``.git`` directory); that guarantee requires
    Windows >= 26200.9278. ``env`` is explicit (``inheritDefaultEnv: false``)
    so the child cannot inherit credential-ish entries even if the executor
    process environment changes.
    """
    filesystem: dict = {
        "readwritePaths": [str(workspace), str(child_temp)],
    }
    if tier == TIER_BASECONTAINER and denied_paths:
        filesystem["deniedPaths"] = [str(path) for path in denied_paths]
    return {
        "version": MXC_POLICY_SCHEMA_VERSION,
        "containment": "processcontainer",
        "lifecycle": {"destroyOnExit": True},
        "process": {
            "cwd": str(workspace),
            "timeout": int(timeout_ms),
            "inheritDefaultEnv": False,
            "env": list(env_entries),
        },
        "filesystem": filesystem,
        "network": {
            "egress": {"default": "deny"},
            "ingress": {"default": "deny", "hostLoopback": "deny"},
        },
    }


def child_env_entries(
    *,
    child_temp: Path,
    base_environment: dict[str, str] | None = None,
) -> list[str]:
    """Explicit child env list: credential-scrubbed, TEMP inside the grant.

    PoC hard requirement: SystemRoot etc. must be given explicitly. Built from
    the credential-scrubbed environment with host-only Vibelution sandbox
    pointers removed and TMP/TEMP redirected into the granted child temp dir.
    """
    source = dict(base_environment) if base_environment is not None else dict(os.environ)
    environment = scrub_credential_environment(source)
    for name in (
        VIBELUTION_SANDBOX_TEMP_ENV,
        VIBELUTION_DATA_HOME_ENV,
        VIBELUTION_CONFIG_HOME_ENV,
        VIBELUTION_CONFIG_PATH_ENV,
        "PYTEST_ADDOPTS",
    ):
        environment.pop(name, None)
    child_temp_text = str(child_temp)
    for name in ("TMP", "TEMP", "TMPDIR"):
        environment[name] = child_temp_text
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    return [f"{name}={value}" for name, value in sorted(environment.items())]


def _probe_tier(executor: Path, invoke: ExecutorInvoker) -> tuple[str, str]:
    """Run the read-only ``--probe`` detector; return ``(tier, detail)``."""
    try:
        completed = invoke([str(executor), "--probe"], timeout_s=PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        return "", f"probe_spawn_{type(exc).__name__}"
    try:
        payload = json.loads(completed.stdout.decode("utf-8", "replace"))
    except Exception:
        return "", "probe_output_unparsable"
    tier = str(payload.get("tier") or "").strip()
    if tier not in _SUPPORTED_TIERS:
        return "", f"probe_tier_unknown:{tier or 'empty'}"
    return tier, ""


class _LoopbackListener:
    """Host-side loopback listener that proves outbound deny is enforced.

    If any sandbox-side connection reaches this listener, egress deny is
    broken and verification must fail. Silence plus a participating non-zero
    curl exit means deny held.
    """

    def __init__(self) -> None:
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(0.2)
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(4)
        self.port = int(self._socket.getsockname()[1])
        self.received = False

    def poll_pending(self) -> None:
        """Accept any connection that queued while the sandbox was running."""
        while True:
            try:
                connection, _ = self._socket.accept()
            except (TimeoutError, socket.timeout):
                return
            except OSError:
                return
            self.received = True
            try:
                connection.close()
            except OSError:
                pass

    def close(self) -> None:
        try:
            self._socket.close()
        except OSError:
            pass


def _self_verify(
    executor: Path,
    *,
    workdir: Path,
    tier: str,
    invoke: ExecutorInvoker,
) -> tuple[bool, str]:
    """Prove the two-state containment at runtime (fail closed).

    Phase W: a minimal sandbox must write the marker file into its granted
    workspace. Phase N: a sandbox curl must NOT reach a host loopback
    listener. Any arrival, a successful request, or an absent curl is a
    failure — deny enforcement must be proven, not assumed.
    """
    verify_root = (
        _sandbox_temp_root(workdir) / f"mxc-verify-{uuid.uuid4().hex[:12]}"
    ).resolve()
    child_temp = (verify_root / "tmp").resolve()
    try:
        child_temp.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        return False, f"verify_workspace_{type(exc).__name__}"
    try:
        policy = build_workspace_write_policy(
            workspace=verify_root,
            child_temp=child_temp,
            timeout_ms=int(VERIFY_RUN_TIMEOUT_SECONDS * 1000),
            tier=tier,
            env_entries=child_env_entries(child_temp=child_temp),
        )
        policy_path = _write_policy_file(policy, child_temp / VERIFY_POLICY_FILENAME)
        marker = verify_root / VERIFY_MARKER_FILENAME

        write_argv = [
            str(executor),
            str(policy_path),
            "--",
            "cmd.exe",
            "/d",
            "/s",
            "/c",
            f"echo verify-ok>{VERIFY_MARKER_FILENAME}",
        ]
        try:
            completed = invoke(write_argv, timeout_s=VERIFY_RUN_TIMEOUT_SECONDS)
        except Exception as exc:
            return False, f"verify_write_spawn_{type(exc).__name__}"
        if completed.returncode != 0:
            return False, f"verify_write_rc_{completed.returncode}"
        if (
            not marker.is_file()
            or marker.read_text(encoding="utf-8", errors="replace").strip() != "verify-ok"
        ):
            return False, "verify_write_marker_missing"

        listener = _LoopbackListener()
        try:
            net_argv = [
                str(executor),
                str(policy_path),
                "--",
                "curl.exe",
                "-s",
                "-o",
                "NUL",
                "--connect-timeout",
                str(VERIFY_CURL_CONNECT_TIMEOUT_SECONDS),
                "--max-time",
                str(VERIFY_CURL_MAX_TIME_SECONDS),
                f"http://127.0.0.1:{listener.port}/{VERIFY_MARKER_FILENAME}",
            ]
            try:
                completed = invoke(net_argv, timeout_s=VERIFY_RUN_TIMEOUT_SECONDS)
                curl_rc = int(completed.returncode)
            except Exception as exc:
                return False, f"verify_net_spawn_{type(exc).__name__}"
            listener.poll_pending()
            if listener.received:
                return False, "verify_egress_not_denied"
            if curl_rc == 0:
                return False, "verify_egress_request_succeeded"
            if curl_rc in {9009, 127}:
                # Shell-level "program not found": curl never participated, so
                # deny enforcement is unproven — fail closed.
                return False, f"verify_curl_missing_{curl_rc}"
        finally:
            listener.close()
        return True, ""
    finally:
        shutil.rmtree(verify_root, ignore_errors=True)


def build_command_plan(
    executor: Path,
    route: Any,
    *,
    workdir: Path,
    child_temp: Path,
    timeout_ms: int,
    tier: str,
    base_environment: dict[str, str] | None = None,
    git_bash_executable: str = "",
) -> MxcCommandPlan | None:
    """Build the full spawn plan for one command; ``None`` = refuse (fallback).

    The inner argv reuses the existing shell adapter in passthrough mode so
    MXC routing matches the pre-MXC argv semantics exactly. Refusal covers
    argv that cannot be transported safely through the executor: non-ASCII
    argv would mojibake (PoC R5) — interpreted routes relay the command text
    through a UTF-8 script file inside the granted child temp, while
    direct-executable and git argv shapes are refused instead.
    """
    inner_argv = create_shell_adapter(
        platform="windows",
        windows_command_interpreter_fn=_windows_command_interpreter,
        powershell_executable_fn=_powershell_executable,
        which=_command_exists,
    ).sandbox_argv(
        "",
        route,
        git_bash_executable=git_bash_executable,
        sandbox_mode=DANGER_FULL_ACCESS_SANDBOX_MODE,
    )
    # Inline the env-var indirection: the adapter encodes native Windows
    # commands behind %VIBELUTION_CODEX_SANDBOX_COMMAND%; inside MXC the
    # command text goes directly into the inner argv instead of a child env
    # var (policy env stays free of command payloads).
    env_var_token = f"%{WINDOWS_COMMAND_ENV}%"
    if env_var_token in inner_argv:
        command_text = str(getattr(route, "command", "") or "")
        if not command_text:
            raise MxcPlanRefused(REASON_NON_ASCII_ARGV, "native_command_text_missing")
        inner_argv = [command_text if item == env_var_token else item for item in inner_argv]

    if not inner_argv:
        raise MxcPlanRefused(REASON_NON_ASCII_ARGV, "empty_inner_argv")
    interpreter = _inner_interpreter(inner_argv)
    if interpreter == "bash":
        # Measured failure (STATUS_DLL_INIT_FAILED) — refuse; the caller falls
        # back so bash commands keep working on the evidence chain.
        raise MxcPlanRefused(REASON_BASH_UNAVAILABLE, str(inner_argv[0]))
    relay_path: Path | None = None
    if not all(str(item).isascii() for item in inner_argv):
        relayed = _relay_non_ascii_command(
            str(getattr(route, "command", "") or ""),
            interpreter,
            inner_argv,
            child_temp=child_temp,
        )
        if relayed is None:
            raise MxcPlanRefused(REASON_NON_ASCII_ARGV, "no_relay_carrier")
        inner_argv, relay_path = relayed
    if not all(str(item).isascii() for item in inner_argv):
        # e.g. workspace/script path itself non-ASCII — cannot transport.
        raise MxcPlanRefused(REASON_NON_ASCII_ARGV, "argv_non_ascii_after_relay")

    policy = build_workspace_write_policy(
        workspace=workdir,
        child_temp=child_temp,
        timeout_ms=timeout_ms,
        tier=tier,
        env_entries=child_env_entries(
            child_temp=child_temp, base_environment=base_environment
        ),
        denied_paths=[workdir / ".git"] if tier == TIER_BASECONTAINER else None,
    )
    policy_path = _write_policy_file(policy, child_temp / COMMAND_POLICY_FILENAME)
    return MxcCommandPlan(
        spawn_argv=[str(executor), str(policy_path), "--", *inner_argv],
        policy_path=policy_path,
        child_temp=child_temp,
        relay_path=relay_path,
        tier=tier,
    )


def _command_exists(name: str) -> str | None:
    from shutil import which

    return which(name)


def _inner_interpreter(inner_argv: list[str]) -> str:
    """Classify the inner payload by its leading interpreter executable."""
    first = str(inner_argv[0]).strip().strip('"').lower() if inner_argv else ""
    if first.endswith("bash.exe") or first in {"bash", "sh"}:
        return "bash"
    if first.endswith("cmd.exe") or first == "cmd":
        return "cmd"
    if first.endswith("powershell.exe") or first in {"powershell", "pwsh", "pwsh.exe"}:
        return "powershell"
    return "other"


def _relay_non_ascii_command(
    command_text: str,
    interpreter: str,
    inner_argv: list[str],
    *,
    child_temp: Path,
) -> tuple[list[str], Path] | None:
    """Relay a non-ASCII command through a UTF-8 script file (PoC R5 fix).

    cmd parses the batch after an in-file ``chcp 65001`` (UTF-8, no BOM);
    PowerShell 5.1 requires a UTF-8 BOM. Direct executable and git argv
    shapes have no script carrier and are refused. Bash never reaches here
    (refused earlier — measured STATUS_DLL_INIT_FAILED under MXC).
    """
    if not command_text:
        return None
    if interpreter == "powershell":
        script_path = (child_temp / "mxc-relay.ps1").resolve()
        script_path.write_text(command_text, encoding="utf-8-sig")
        argv = [
            _powershell_executable(),
            "-NoProfile",
            "-WindowStyle",
            "Hidden",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
        ]
        return argv, script_path
    if interpreter == "cmd":
        script_path = (child_temp / "mxc-relay.cmd").resolve()
        script_path.write_bytes(
            ("@echo off\r\n@chcp 65001 >nul\r\n" + command_text + "\r\n").encode("utf-8")
        )
        # ``call`` is required: cmd opens batch files launched directly with an
        # execute-mode access that the sandbox grant denies (measured:
        # 拒绝访问; the existing adapter's native chain form also uses ``call``).
        return [
            _windows_command_interpreter(),
            "/d",
            "/s",
            "/c",
            "call",
            str(script_path),
        ], script_path
    return None


def ensure_verified(
    workdir: Path | None = None,
    *,
    environ: dict[str, str] | None = None,
    invoke: ExecutorInvoker | None = None,
    now: Callable[[], float] | None = None,
) -> MxcAvailability:
    """One TTL-cached, fail-closed availability verdict (version+probe+verify).

    The verification spawns a minimal real sandbox (workspace write + loopback
    egress deny) before any agent command may use MXC — declared support is
    not evidence. Degraded-tier hosts (``appcontainer-dacl``) are allowed but
    restricted to the two-state policy. Success is cached for
    ``VERIFY_TTL_SUCCESS_SECONDS``; failure for the shorter
    ``VERIFY_TTL_FAILURE_SECONDS`` so a broken executor is retried without
    hammering it on every command.
    """
    global _VERIFY_STATE
    source = environ if environ is not None else os.environ
    clock = now if now is not None else time.monotonic
    runner = invoke if invoke is not None else _run_executor
    with _VERIFY_STATE_LOCK:
        state = _VERIFY_STATE
        if state is not None and state.expires_at > clock():
            cached = state.availability
            return MxcAvailability(
                ok=cached.ok,
                code=cached.code,
                detail=cached.detail,
                tier=cached.tier,
                telemetry_policy=cached.telemetry_policy,
                from_cache=True,
            )
    availability = _verify_uncached(workdir, environ=source, invoke=runner)
    ttl = VERIFY_TTL_SUCCESS_SECONDS if availability.ok else VERIFY_TTL_FAILURE_SECONDS
    with _VERIFY_STATE_LOCK:
        _VERIFY_STATE = _VerifyState(availability, clock() + ttl)
    return availability


def _verify_uncached(
    workdir: Path | None,
    *,
    environ: dict[str, str],
    invoke: ExecutorInvoker,
) -> MxcAvailability:
    telemetry_policy = read_telemetry_policy()
    executor = executor_path(environ)
    if executor is None:
        return MxcAvailability(
            ok=False,
            code=REASON_UNAVAILABLE,
            detail="executor_binary_missing",
            telemetry_policy=telemetry_policy,
        )
    version_text = executor_version_string(executor)
    if not _version_is_allowed(version_text):
        return MxcAvailability(
            ok=False,
            code=REASON_VERSION_UNSUPPORTED,
            detail=f"version={version_text or 'unreadable'}; allowed=1.0.x",
            telemetry_policy=telemetry_policy,
        )
    tier, probe_detail = _probe_tier(executor, invoke)
    if not tier:
        return MxcAvailability(
            ok=False,
            code=REASON_PROBE_FAILED,
            detail=probe_detail,
            telemetry_policy=telemetry_policy,
        )
    verify_workdir = Path(workdir).resolve() if workdir else _default_verify_workdir()
    verify_ok, verify_detail = _self_verify(
        executor, workdir=verify_workdir, tier=tier, invoke=invoke
    )
    if not verify_ok:
        return MxcAvailability(
            ok=False,
            code=REASON_VERIFY_FAILED,
            detail=verify_detail,
            tier=tier,
            telemetry_policy=telemetry_policy,
        )
    return MxcAvailability(
        ok=True,
        tier=tier,
        telemetry_policy=telemetry_policy,
        detail=f"version={version_text}",
    )


def _default_verify_workdir() -> Path:
    try:
        from core.infrastructure.codex_cli_sandbox import PROJECT_ROOT

        return Path(PROJECT_ROOT)
    except Exception:
        return Path(os.path.expanduser("~"))


def reset_verification_cache() -> None:
    """Test/ops seam: drop the cached availability verdict."""
    global _VERIFY_STATE
    with _VERIFY_STATE_LOCK:
        _VERIFY_STATE = None


def cached_availability() -> MxcAvailability | None:
    """Current cached verdict without triggering a fresh verification."""
    with _VERIFY_STATE_LOCK:
        state = _VERIFY_STATE
        if state is None:
            return None
        cached = state.availability
        return MxcAvailability(
            ok=cached.ok,
            code=cached.code,
            detail=cached.detail,
            tier=cached.tier,
            telemetry_policy=cached.telemetry_policy,
            from_cache=True,
        )


def cleanup_child_temp(child_temp: Path, *, keep_parents: bool = True) -> None:
    """Remove one command's child temp dir (policy + relay + scratch)."""
    shutil.rmtree(child_temp, ignore_errors=True)
    if keep_parents:
        for parent in child_temp.parents:
            if parent.name == "mxc":
                try:
                    parent.rmdir()
                except OSError:
                    pass
                return
