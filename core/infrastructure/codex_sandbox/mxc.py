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
- Sandbox-side TLS is dead on every tier (``import ssl`` DLL init failure,
  ``curl https`` rc=35), so the online tier (``loopback_relay`` network
  profile, basecontainer only) routes traffic as plaintext HTTP to a
  host-side loopback relay (``loopback_relay.py``) whose host process
  terminates upstream TLS. Egress deny stays on for every non-relay target.
  Measured boundary (26200.9711): ``ingress.hostLoopback: allow`` opens the
  whole host address family (the sandbox reaches the host's LAN IP), while
  non-host egress stays denied (external curl refused immediately) — the
  online deny proof therefore targets an external destination where rc==0 is
  the hard failure signal.

All availability answers are fail-closed: any probe/version/verification
failure reports ``ok=False`` with a distinguishable reason code and the
caller must fall back to the pre-MXC chain. Offline and online verdicts are
cached separately (per ``network_profile``) and never cross.
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
from core.infrastructure.codex_sandbox.loopback_relay import (
    RELAY_PROBE_PATH,
    get_or_start_relay,
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

# The full tier is reported by wxc-exec --probe as "base-container" (hyphenated)
# on hosts with the 26200.9278+ servicing stack; early 1.0.x builds and the docs
# also spell it "basecontainer". Accept both spellings and normalize to the
# canonical constant so a probe-naming drift cannot silently disable the backend.
TIER_BASECONTAINER = "basecontainer"
_TIER_BASECONTAINER_PROBE_ALIASES = ("base-container", "basecontainer")
TIER_APPCONTAINER_DACL = "appcontainer-dacl"
_SUPPORTED_TIERS = {*_TIER_BASECONTAINER_PROBE_ALIASES, TIER_APPCONTAINER_DACL}

# Network profiles. "offline" is the historical two-state policy. The online
# profile ("loopback_relay") keeps egress deny but flips ingress hostLoopback
# to allow so the sandbox can reach the host-side plaintext relay (TLS
# terminates in the host process; sandbox TLS is measured-dead: DLL init
# failure on ``import ssl``, curl https rc=35 — basecontainer tier).
NETWORK_PROFILE_OFFLINE = "offline"
NETWORK_PROFILE_LOOPBACK_RELAY = "loopback_relay"
_NETWORK_PROFILES = (NETWORK_PROFILE_OFFLINE, NETWORK_PROFILE_LOOPBACK_RELAY)
RELAY_BASE_ENV_NAME = "VIBELUTION_RELAY_BASE"

VERIFY_TTL_SUCCESS_SECONDS = 300.0
VERIFY_TTL_FAILURE_SECONDS = 30.0
PROBE_TIMEOUT_SECONDS = 15.0
VERIFY_RUN_TIMEOUT_SECONDS = 30.0
VERIFY_MARKER_FILENAME = "mxc-verify-ok.txt"
VERIFY_CURL_CONNECT_TIMEOUT_SECONDS = 2
VERIFY_CURL_MAX_TIME_SECONDS = 8
VERIFY_POLICY_FILENAME = "mxc-verify-policy.json"
COMMAND_POLICY_FILENAME = "policy.json"
# Online-profile deny-proof target: a real external destination. Under egress
# deny the sandbox curl must fail (measured: immediate refusal, rc=7); rc==0
# would mean traffic actually reached the internet and containment is broken.
# A documentation-reserved IP cannot give that positive signal (it would also
# time out on a broken deny), so a stable public name is used — no traffic
# leaves the sandbox while deny is enforced.
VERIFY_ONLINE_DENY_TARGET = "http://example.com/"

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
# Online profile refusals (never silently degrade an online request to the
# offline policy: the caller asked for network and must get a distinguishable
# refusal instead).
REASON_ONLINE_REQUIRES_BASECONTAINER = "online_profile_requires_basecontainer"
REASON_ONLINE_REQUIRES_RELAY_PORT = "online_profile_requires_relay_port"
REASON_NETWORK_PROFILE_UNKNOWN = "mxc_network_profile_unknown"


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
    """One availability verdict for the MXC executor on this host.

    ``network_profile`` is the profile the verdict was proven for ("offline"
    or "loopback_relay"); conclusions never cross profiles. ``relay_port`` is
    the host-side loopback relay port used by the online verification (None
    for offline).
    """

    __slots__ = (
        "ok",
        "code",
        "detail",
        "tier",
        "telemetry_policy",
        "network_profile",
        "relay_port",
        "from_cache",
    )

    def __init__(
        self,
        *,
        ok: bool,
        code: str = "",
        detail: str = "",
        tier: str = "",
        telemetry_policy: str = "",
        network_profile: str = NETWORK_PROFILE_OFFLINE,
        relay_port: int | None = None,
        from_cache: bool = False,
    ) -> None:
        self.ok = bool(ok)
        self.code = str(code)
        self.detail = str(detail)
        self.tier = str(tier)
        self.telemetry_policy = str(telemetry_policy)
        self.network_profile = str(network_profile)
        self.relay_port = int(relay_port) if relay_port is not None else None
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


_VERIFY_STATE: dict[str, _VerifyState] = {}
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
    network_profile: str = NETWORK_PROFILE_OFFLINE,
    relay_port: int | None = None,
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

    ``network_profile="offline"`` (default) keeps the historical network
    block byte-for-byte. ``network_profile="loopback_relay"`` keeps egress
    deny but allows ingress hostLoopback so the sandbox can reach the
    host-side plaintext relay; it is refused on any tier other than
    ``basecontainer`` (measured: the online network JSON shape is
    typed-rejected on ``appcontainer-dacl``) and requires ``relay_port``.
    Unknown profiles and missing online preconditions raise ``MxcPlanRefused``
    — an online request is never silently downgraded to the offline policy.
    """
    if network_profile not in _NETWORK_PROFILES:
        raise MxcPlanRefused(REASON_NETWORK_PROFILE_UNKNOWN, f"profile={network_profile}")
    if network_profile == NETWORK_PROFILE_LOOPBACK_RELAY:
        if tier != TIER_BASECONTAINER:
            raise MxcPlanRefused(
                REASON_ONLINE_REQUIRES_BASECONTAINER, f"tier={tier}"
            )
        if relay_port is None:
            raise MxcPlanRefused(REASON_ONLINE_REQUIRES_RELAY_PORT, "relay_port_missing")
    filesystem: dict = {
        "readwritePaths": [str(workspace), str(child_temp)],
    }
    if tier == TIER_BASECONTAINER and denied_paths:
        filesystem["deniedPaths"] = [str(path) for path in denied_paths]
    if network_profile == NETWORK_PROFILE_LOOPBACK_RELAY:
        network = {
            "egress": {"default": "deny"},
            "ingress": {"default": "allow", "hostLoopback": "allow"},
        }
    else:
        network = {
            "egress": {"default": "deny"},
            "ingress": {"default": "deny", "hostLoopback": "deny"},
        }
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
        "network": network,
    }


def child_env_entries(
    *,
    child_temp: Path,
    base_environment: dict[str, str] | None = None,
    relay_port: int | None = None,
) -> list[str]:
    """Explicit child env list: credential-scrubbed, TEMP inside the grant.

    PoC hard requirement: SystemRoot etc. must be given explicitly. Built from
    the credential-scrubbed environment with host-only Vibelution sandbox
    pointers removed and TMP/TEMP redirected into the granted child temp dir.
    ``relay_port`` (online profile only) adds the ASCII-only
    ``VIBELUTION_RELAY_BASE=http://127.0.0.1:{port}`` pointer to the host-side
    loopback relay.
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
    if relay_port is not None:
        environment[RELAY_BASE_ENV_NAME] = f"http://127.0.0.1:{int(relay_port)}"
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
    # Normalize probe spellings to the canonical constants so downstream
    # ``tier == TIER_BASECONTAINER`` capability checks are spelling-stable.
    if tier in _TIER_BASECONTAINER_PROBE_ALIASES:
        tier = TIER_BASECONTAINER
    return tier, ""


class _LoopbackListener:
    """Host-side loopback listener that proves offline outbound deny.

    Used by the offline profile only: if any sandbox-side connection reaches
    this listener, egress deny is broken and verification must fail. Silence
    plus a participating non-zero curl exit means deny held. (The online
    profile allows the whole host address family by design, so its deny proof
    targets an external destination instead — see ``_self_verify``.)
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
    network_profile: str = NETWORK_PROFILE_OFFLINE,
    relay_port: int | None = None,
) -> tuple[bool, str]:
    """Prove the containment claims at runtime (fail closed).

    Phase W: a minimal sandbox must write the marker file into its granted
    workspace. Phase N: a sandbox curl must NOT reach the deny-proof target.
    Any arrival, a successful request, or an absent curl is a failure — deny
    enforcement must be proven, not assumed.

    Online profile (``loopback_relay``) adds Phase L before the deny proof: a
    sandbox curl to the host relay's ``/__relay_probe`` endpoint MUST
    succeed, proving the ingress hostLoopback grant actually reaches the
    relay. The deny proof then targets an external destination
    (``VERIFY_ONLINE_DENY_TARGET``): the online profile allows the whole host
    address family via ``ingress.hostLoopback`` (measured: the sandbox
    reaches the host's LAN IP), so a host-side listener cannot prove deny.
    Under egress deny the external request must fail (measured: immediate
    refusal); ``rc==0`` — traffic actually reaching the internet — is a
    hard verification failure. On hosts with no internet the request also
    fails, so the positive-signal property (rc==0 breaks verification) holds
    wherever the host has connectivity.
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
            env_entries=child_env_entries(child_temp=child_temp, relay_port=relay_port),
            network_profile=network_profile,
            relay_port=relay_port,
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

        if network_profile == NETWORK_PROFILE_LOOPBACK_RELAY:
            if relay_port is None:  # defensive; builder refuses this earlier
                return False, "verify_online_missing_relay_port"
            probe_argv = [
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
                f"http://127.0.0.1:{int(relay_port)}{RELAY_PROBE_PATH}",
            ]
            try:
                completed = invoke(probe_argv, timeout_s=VERIFY_RUN_TIMEOUT_SECONDS)
                probe_rc = int(completed.returncode)
            except Exception as exc:
                return False, f"verify_probe_spawn_{type(exc).__name__}"
            if probe_rc in {9009, 127}:
                # curl absent: loopback reachability unproven — fail closed.
                return False, f"verify_curl_missing_{probe_rc}"
            if probe_rc != 0:
                return False, f"verify_loopback_probe_rc_{probe_rc}"

        if network_profile == NETWORK_PROFILE_LOOPBACK_RELAY:
            deny_target = VERIFY_ONLINE_DENY_TARGET
            listener = None
        else:
            listener = _LoopbackListener()
            deny_target = f"http://127.0.0.1:{listener.port}/{VERIFY_MARKER_FILENAME}"
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
                deny_target,
            ]
            try:
                completed = invoke(net_argv, timeout_s=VERIFY_RUN_TIMEOUT_SECONDS)
                curl_rc = int(completed.returncode)
            except Exception as exc:
                return False, f"verify_net_spawn_{type(exc).__name__}"
            if listener is not None:
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
            if listener is not None:
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
    network_profile: str = NETWORK_PROFILE_OFFLINE,
    relay_port: int | None = None,
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
            child_temp=child_temp,
            base_environment=base_environment,
            relay_port=relay_port,
        ),
        denied_paths=[workdir / ".git"] if tier == TIER_BASECONTAINER else None,
        network_profile=network_profile,
        relay_port=relay_port,
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
    network_profile: str = NETWORK_PROFILE_OFFLINE,
) -> MxcAvailability:
    """One TTL-cached, fail-closed availability verdict (version+probe+verify).

    The verification spawns a minimal real sandbox (workspace write + egress
    deny, plus the loopback relay probe for the online profile) before any
    agent command may use MXC — declared support is not evidence.
    Degraded-tier hosts (``appcontainer-dacl``) are allowed but restricted to
    the two-state policy; an online-profile request on a degraded tier is
    refused with a distinguishable reason (never downgraded silently).
    Success is cached for ``VERIFY_TTL_SUCCESS_SECONDS``; failure for the
    shorter ``VERIFY_TTL_FAILURE_SECONDS`` so a broken executor is retried
    without hammering it on every command. Cache entries are keyed by
    ``network_profile`` — offline and online conclusions never cross.
    """
    if network_profile not in _NETWORK_PROFILES:
        raise ValueError(f"unknown network profile: {network_profile}")
    source = environ if environ is not None else os.environ
    clock = now if now is not None else time.monotonic
    runner = invoke if invoke is not None else _run_executor
    with _VERIFY_STATE_LOCK:
        state = _VERIFY_STATE.get(network_profile)
        if state is not None and state.expires_at > clock():
            cached = state.availability
            return MxcAvailability(
                ok=cached.ok,
                code=cached.code,
                detail=cached.detail,
                tier=cached.tier,
                telemetry_policy=cached.telemetry_policy,
                network_profile=cached.network_profile,
                relay_port=cached.relay_port,
                from_cache=True,
            )
    availability = _verify_uncached(
        workdir, environ=source, invoke=runner, network_profile=network_profile
    )
    ttl = VERIFY_TTL_SUCCESS_SECONDS if availability.ok else VERIFY_TTL_FAILURE_SECONDS
    with _VERIFY_STATE_LOCK:
        _VERIFY_STATE[network_profile] = _VerifyState(availability, clock() + ttl)
    return availability


def _verify_uncached(
    workdir: Path | None,
    *,
    environ: dict[str, str],
    invoke: ExecutorInvoker,
    network_profile: str = NETWORK_PROFILE_OFFLINE,
) -> MxcAvailability:
    telemetry_policy = read_telemetry_policy()
    executor = executor_path(environ)
    if executor is None:
        # Follow the cua-driver convention (human installs, product only
        # discovers and locks versions): never auto-download here. Point the
        # operator at the pinned provisioning CLI instead of leaving the
        # sandbox silently unavailable.
        return MxcAvailability(
            ok=False,
            code=REASON_UNAVAILABLE,
            detail=(
                "executor_binary_missing; install via: "
                "python -m core.infrastructure.codex_sandbox.executor_provision --install"
            ),
            telemetry_policy=telemetry_policy,
            network_profile=network_profile,
        )
    version_text = executor_version_string(executor)
    if not _version_is_allowed(version_text):
        return MxcAvailability(
            ok=False,
            code=REASON_VERSION_UNSUPPORTED,
            detail=f"version={version_text or 'unreadable'}; allowed=1.0.x",
            telemetry_policy=telemetry_policy,
            network_profile=network_profile,
        )
    tier, probe_detail = _probe_tier(executor, invoke)
    if not tier:
        return MxcAvailability(
            ok=False,
            code=REASON_PROBE_FAILED,
            detail=probe_detail,
            telemetry_policy=telemetry_policy,
            network_profile=network_profile,
        )
    relay_port: int | None = None
    if network_profile == NETWORK_PROFILE_LOOPBACK_RELAY:
        if tier != TIER_BASECONTAINER:
            # Online needs the typed network shape (ingress hostLoopback
            # allow) that only the basecontainer tier accepts; the degraded
            # tier typed-rejects it. Refuse with a distinguishable reason
            # instead of silently degrading to the offline policy.
            return MxcAvailability(
                ok=False,
                code=REASON_ONLINE_REQUIRES_BASECONTAINER,
                detail=f"tier={tier}",
                tier=tier,
                telemetry_policy=telemetry_policy,
                network_profile=network_profile,
            )
        try:
            # Empty service map is enough for verification: only the probe
            # endpoint is exercised; execution entries merge their services
            # into the same singleton afterwards.
            handle = get_or_start_relay({})
            relay_port = int(handle.port)
        except Exception as exc:
            return MxcAvailability(
                ok=False,
                code=REASON_UNAVAILABLE,
                detail=f"relay_start_{type(exc).__name__}",
                tier=tier,
                telemetry_policy=telemetry_policy,
                network_profile=network_profile,
            )
    verify_workdir = Path(workdir).resolve() if workdir else _default_verify_workdir()
    verify_ok, verify_detail = _self_verify(
        executor,
        workdir=verify_workdir,
        tier=tier,
        invoke=invoke,
        network_profile=network_profile,
        relay_port=relay_port,
    )
    if not verify_ok:
        return MxcAvailability(
            ok=False,
            code=REASON_VERIFY_FAILED,
            detail=verify_detail,
            tier=tier,
            telemetry_policy=telemetry_policy,
            network_profile=network_profile,
            relay_port=relay_port,
        )
    return MxcAvailability(
        ok=True,
        tier=tier,
        telemetry_policy=telemetry_policy,
        detail=f"version={version_text}",
        network_profile=network_profile,
        relay_port=relay_port,
    )


def _default_verify_workdir() -> Path:
    try:
        from core.infrastructure.codex_cli_sandbox import PROJECT_ROOT

        return Path(PROJECT_ROOT)
    except Exception:
        return Path(os.path.expanduser("~"))


def reset_verification_cache() -> None:
    """Test/ops seam: drop the cached availability verdicts (all profiles)."""
    with _VERIFY_STATE_LOCK:
        _VERIFY_STATE.clear()


def cached_availability(
    network_profile: str = NETWORK_PROFILE_OFFLINE,
) -> MxcAvailability | None:
    """Current cached verdict for a profile, without fresh verification."""
    with _VERIFY_STATE_LOCK:
        state = _VERIFY_STATE.get(network_profile)
        if state is None:
            return None
        cached = state.availability
        return MxcAvailability(
            ok=cached.ok,
            code=cached.code,
            detail=cached.detail,
            tier=cached.tier,
            telemetry_policy=cached.telemetry_policy,
            network_profile=cached.network_profile,
            relay_port=cached.relay_port,
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
