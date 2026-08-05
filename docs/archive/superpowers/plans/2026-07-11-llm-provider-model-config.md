# Provider-Scoped LLM Model Configuration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-model inline provider duplication with stable Provider instances, provider-scoped pinned models, derived observed catalogs, canonical `provider_id/model_key` references, and an explicit migration path.

**Architecture:** Operator TOML schema v2 owns Provider instances and pinned models, while a deterministic runtime projection keeps existing LLM consumers working during migration. A provider-scoped catalog persists discovery and capability provenance without making config load perform network I/O; explicit protocol resolution and provider-first APIs/UI consume the new ownership model. The v1 adapter remains read-only until the operator explicitly previews and applies migration.

**Tech Stack:** Python 3.11+, Pydantic v2, TOML via `tomllib` and the existing writer, `httpx`, FastAPI, React 18, TypeScript, HeroUI/VUI primitives, Vitest, Pytest.

## Global Constraints

- Canonical operator config remains `C:\Users\17533\Documents\Vibelution\config\config.toml`; repository `config.toml` and `config.example.toml` are legacy/template inputs only.
- Config loading performs zero network access.
- Operator TOML stores only credential references; secret values never enter TOML, API responses, logs, runtime scenes, fixtures, fingerprints, or exception text.
- Provider business identity is the normalized endpoint plus canonical credential reference; the operator-selected `provider_id` is the stable serialized key.
- Canonical model references use `provider_id/model_key`; `upstream_id` is preserved exactly and local `artifact_path` never becomes a request model ID.
- Discovery writes only `model-catalog-state.json`; it never pins every observed model and never deletes a pinned model after an empty or failed refresh.
- Capability values are exactly `supported`, `unsupported`, or `unknown`, merged independently per field in this order: operator override, runtime probe, provider endpoint metadata, curated snapshot, driver conservative default.
- Schema v2 protocol order is model override, provider default, driver declaration; unresolved v2 routes fail closed with `protocol_unknown`. Legacy heuristics are diagnostic-only for v1.
- The compatibility alias table has one exit condition: remove an alias only after live references to the legacy key reach zero.
- Real operator migration, Launcher refresh, version files, remote push, PR creation, and release publication are outside implementation commits and require their own explicit gate.
- External reuse decision is `REFERENCE_ONLY`: do not copy Hermes/OpenCode code and do not add Models.dev, LiteLLM, or Vercel AI SDK dependencies.
- HTTP discovery limits are fixed for this implementation: redirects disabled, 15-second maximum request timeout, 2 MiB response body, 5,000 models, 512 Unicode code points per upstream ID, and at most 16 non-sensitive custom headers with 64-character names and 512-character values.
- Each task rechecks `agent_work_guard.py check` before writing shared files, stages only listed task files, and uses a scoped commit.

## Dependency Order and File Map

This is one plan rather than separate sub-project plans because every later surface consumes the identity/schema contract established by the previous surface:

```text
Task 1 identity/credentials
  -> Task 2 schema v2 + runtime projection
  -> Task 3 Provider registry + pinning
  -> Task 4 derived catalog + capability provenance
  -> Task 5 discovery adapters
  -> Task 6 explicit runtime protocol resolution
  -> Task 7 Provider APIs and runtime events
  -> Task 8 preview/apply/rollback migration
  -> Task 9 frontend types and provider view model
  -> Task 10 provider-first UI and migration UX
  -> Task 11 integration, templates, build, and rollout evidence
```

New backend files have one responsibility each:

- `config/llm_credentials.py`: canonicalize and resolve credential references without exposing secrets.
- `config/llm_identity.py`: normalize endpoints and create deterministic provider fingerprints, model keys, and model refs.
- `config/llm_projection.py`: convert public schema v2 to the existing effective runtime shape without network access.
- `config/llm_provider_registry.py`: validate Provider uniqueness and mutate provider/pinned-model public config drafts.
- `config/model_catalog.py`: persist derived observed models, availability, capability provenance, TTL, and legacy cache import state.
- `core/llm/provider_discovery/types.py`: discovery request/result contracts.
- `core/llm/provider_discovery/adapters.py`: bounded native/OpenAI-compatible discovery adapters.
- `core/llm/provider_discovery/service.py`: security validation, credential use, adapter selection, catalog reconciliation, and bounded events.
- `config/model_config_migration.py`: deterministic v1 preview, migration manifest, apply, validation, and rollback.
- `core/web/services/provider_config_service.py`: draft orchestration for Provider CRUD, pinning, discovery, and migration APIs.
- `web/src/routes/configProviderLogic.ts`: provider-first view model and wizard state without identity guessing.
- `web/src/routes/ConfigProviderRegistryPanel.tsx`: Provider list/detail/model inventory.
- `web/src/routes/ConfigProviderWizard.tsx`: four-step Provider creation flow.
- `web/src/routes/ConfigModelMigrationPanel.tsx`: v1 preview, conflict display, explicit apply, and alias progress.

Existing files retain these responsibilities:

- `config/models.py`: Pydantic runtime models and compatibility fields.
- `config/settings.py`: public-to-runtime normalization; v1 and v2 route selection only.
- `config/public_config.py`: public draft load/save/hash and compatibility wrappers.
- `core/llm/protocol_resolver.py`: final wire/model protocol selection.
- `core/web/services/config_service.py`: overall config workspace composition and apply transaction; Provider-specific behavior moves out.
- `core/web/services/model_reference_service.py`: scan and stage live-reference rewrites; historical artifacts remain read-only.
- `core/web/routes/config.py`: request validation and HTTP mapping only.
- `web/src/routes/ConfigRoute.tsx`: query/mutation ownership and panel composition only.

Before Task 1 implementation, use `using-git-worktrees`, verify root `main` is clean, and create the exact implementation lane from the then-current local `main`:

```powershell
git -C 'C:\Users\17533\Desktop\Vibelution' status --short --branch
git -C 'C:\Users\17533\Desktop\Vibelution' worktree add 'C:\Users\17533\Desktop\Vibelution-worktrees\llm-provider-model-config' -b 'codex/llm-provider-model-config' main
$guard = 'C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py'
$python = 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe'
$scopes = @(
  'config/llm_credentials.py', 'config/llm_identity.py', 'config/llm_projection.py',
  'config/llm_provider_registry.py', 'config/model_catalog.py', 'config/model_config_migration.py',
  'config/models.py', 'config/settings.py', 'config/public_config.py', 'config/runtime_capabilities.py',
  'config/paths.py', 'config/llm_security.py', 'config/__init__.py',
  'core/llm/provider_discovery', 'core/llm/protocol_resolver.py', 'core/llm/client.py',
  'core/llm/discovery.py', 'core/llm/agent_runtime.py',
  'core/web/services/provider_config_service.py', 'core/web/services/config_service.py',
  'core/web/services/model_reference_service.py', 'core/web/routes/config.py',
  'web/src/api/types/config.ts', 'web/src/routes/ConfigRoute.tsx',
  'web/src/routes/ConfigProviderRegistryPanel.tsx', 'web/src/routes/ConfigProviderWizard.tsx',
  'web/src/routes/ConfigModelMigrationPanel.tsx', 'web/src/routes/ConfigProviderRegistryPanel.styles.ts',
  'web/src/routes/configProviderLogic.ts', 'web/src/routes/configProviderLogic.test.ts',
  'web/src/routes/configRouteLogic.ts', 'web/src/routes/configRouteLogic.test.ts',
  'web/src/routes/ConfigRoute.layout.test.ts', 'web/src/routes/ConfigModelLibraryPanel.tsx',
  'web/src/routes/ConfigModelLibraryPanel.styles.ts',
  'tests/test_llm_identity.py', 'tests/test_llm_config_schema_v2.py',
  'tests/test_llm_provider_registry.py', 'tests/test_model_catalog.py',
  'tests/test_provider_discovery_adapters.py', 'tests/test_llm_protocol_resolver.py',
  'tests/test_agent_llm_runtime.py', 'tests/test_provider_config_service.py',
  'tests/test_model_config_migration.py', 'tests/test_model_reference_service.py',
  'tests/test_public_config_model_refs.py', 'tests/test_runtime_capabilities.py',
  'tests/test_web_config_routes.py', 'tests/test_config_paths.py', 'tests/test_config_redaction.py',
  'tests/test_config_patch_apply.py', 'tests/test_config_panel.py', 'tests/test_config_sync.py',
  'tests/test_llm_config_v2_integration.py', 'tests/fixtures/config', 'tests/select_tests.py', 'tests/README.md'
)
$checkArgs = @('C:\Users\17533\Desktop\Vibelution', 'check', '--lane', 'llm-provider-model-config')
foreach ($scope in $scopes) { $checkArgs += @('--scope', $scope) }
& $python $guard @checkArgs
if ($LASTEXITCODE -ne 0) { throw 'Implementation scope overlaps active or ready work.' }
$claimArgs = @('C:\Users\17533\Desktop\Vibelution', 'claim', '--lane', 'llm-provider-model-config')
foreach ($scope in $scopes) { $claimArgs += @('--scope', $scope) }
$claimArgs += @('--agent', 'codex-llm-provider-model-config', '--task', 'Implement provider-scoped LLM configuration', '--ttl-minutes', '480', '--note', 'Tasks 1-11 only; no real operator migration, Launcher refresh, version edit, push, or PR.')
$claimOutput = & $python $guard @claimArgs
if (($claimOutput -join "`n") -notmatch '(claim-[a-z0-9]+)') { throw 'Failed to capture implementation claim id.' }
$env:VIBELUTION_AGENT_CLAIM_ID = $Matches[1]
```

Expected: root remains on clean `main`; implementation worktree is on `codex/llm-provider-model-config`; the environment variable contains the active implementation claim ID. If the branch/worktree already exists, inspect it instead of deleting or overwriting it.

---

### Task 1: Deterministic Provider, credential, and model identity primitives

**Files:**
- Create: `config/llm_credentials.py`
- Create: `config/llm_identity.py`
- Create: `tests/test_llm_identity.py`

**Interfaces:**
- Produces: `canonicalize_credential_ref(ref: str, *, windows_env: bool | None = None) -> str`
- Produces: `resolve_credential_ref(ref: str, *, env_reader: Callable[[str], str | None] = _read_env_var) -> CredentialResolution`
- Produces: `normalize_provider_endpoint(base_url: str) -> str`
- Produces: `provider_identity_fingerprint(base_url: str, credential_ref: str, *, auth_kind: str, windows_env: bool | None = None) -> str`
- Produces: `make_model_key(upstream_id: str, *, max_length: int = 96) -> str`
- Produces: `make_model_ref(provider_id: str, model_key: str) -> str`
- Produces: `split_model_ref(model_ref: str) -> tuple[str, str]`

- [ ] **Step 1: Write failing identity and credential tests**

```python
from __future__ import annotations

import hashlib

import pytest

from config.llm_credentials import canonicalize_credential_ref, resolve_credential_ref
from config.llm_identity import (
    make_model_key,
    make_model_ref,
    normalize_provider_endpoint,
    provider_identity_fingerprint,
    split_model_ref,
)


def test_provider_endpoint_normalization_preserves_semantic_path() -> None:
    assert normalize_provider_endpoint("HTTPS://Relay.Example:443/v1/") == "https://relay.example/v1"
    assert normalize_provider_endpoint("http://LOCALHOST:80/api") == "http://localhost/api"


@pytest.mark.parametrize(
    "value",
    [
        "https://user:pass@relay.example/v1",
        "https://relay.example/v1?token=secret",
        "https://relay.example/v1#fragment",
    ],
)
def test_provider_endpoint_rejects_embedded_sensitive_or_ambiguous_parts(value: str) -> None:
    with pytest.raises(ValueError, match="provider base_url"):
        normalize_provider_endpoint(value)


def test_env_credential_reference_is_windows_case_insensitive() -> None:
    assert canonicalize_credential_ref("env:Relay_Key", windows_env=True) == "env:RELAY_KEY"
    assert canonicalize_credential_ref("none", windows_env=True) == "none"


def test_credential_resolution_does_not_expose_secret_in_repr() -> None:
    result = resolve_credential_ref("env:RELAY_KEY", env_reader=lambda name: "super-secret" if name == "RELAY_KEY" else None)
    assert result.state == "configured"
    assert result.secret == "super-secret"
    assert "super-secret" not in repr(result)


def test_provider_fingerprint_uses_endpoint_and_reference_not_secret() -> None:
    expected = hashlib.sha256(b"https://relay.example/v1\0env:RELAY_KEY").hexdigest()
    assert (
        provider_identity_fingerprint(
            "https://Relay.Example:443/v1/",
            "env:relay_key",
            auth_kind="api_key",
            windows_env=True,
        )
        == expected
    )


def test_model_key_is_stable_and_order_independent() -> None:
    assert make_model_key("gpt-5.6-luna") == "gpt-5.6-luna"
    assert make_model_key("anthropic/claude-sonnet-4.6") == "anthropic_claude-sonnet-4.6~3e041007"
    assert make_model_key(r"C:\models\Qwen.gguf") == "c_models_qwen.gguf~88f2e351"
    assert make_model_key("Model") != make_model_key("model")


def test_model_ref_round_trip() -> None:
    ref = make_model_ref("pixel_relay", "gpt-5.6-luna")
    assert ref == "pixel_relay/gpt-5.6-luna"
    assert split_model_ref(ref) == ("pixel_relay", "gpt-5.6-luna")
```

- [ ] **Step 2: Run the tests and verify the missing-module failure**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_identity.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'config.llm_credentials'`.

- [ ] **Step 3: Implement credential-reference ownership**

Create `config/llm_credentials.py` with this complete public contract:

```python
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from config.models import _read_env_var


@dataclass(frozen=True)
class CredentialResolution:
    reference: str
    state: str
    source: str
    secret: str = field(default="", repr=False)


def canonicalize_credential_ref(ref: str, *, windows_env: bool | None = None) -> str:
    value = str(ref or "").strip()
    if not value or value == "none":
        return "none"
    scheme, separator, target = value.partition(":")
    if not separator or scheme.lower() != "env" or not target.strip():
        raise ValueError("credential_ref must be `env:VARIABLE_NAME` or `none`")
    variable = target.strip()
    if not variable.replace("_", "A").isalnum() or variable[0].isdigit():
        raise ValueError("credential_ref contains an invalid environment variable name")
    case_insensitive = os.name == "nt" if windows_env is None else windows_env
    return f"env:{variable.upper() if case_insensitive else variable}"


def resolve_credential_ref(
    ref: str,
    *,
    env_reader: Callable[[str], str | None] = _read_env_var,
) -> CredentialResolution:
    canonical = canonicalize_credential_ref(ref)
    if canonical == "none":
        return CredentialResolution(reference="none", state="not_required", source="none")
    variable = canonical.removeprefix("env:")
    secret = str(env_reader(variable) or "")
    return CredentialResolution(
        reference=canonical,
        state="configured" if secret else "missing",
        source=f"env:{variable}",
        secret=secret,
    )


__all__ = ["CredentialResolution", "canonicalize_credential_ref", "resolve_credential_ref"]
```

- [ ] **Step 4: Implement deterministic endpoint/model identity**

Create `config/llm_identity.py` with the following functions and validation:

```python
from __future__ import annotations

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from .llm_credentials import canonicalize_credential_ref


_PROVIDER_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SAFE_MODEL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def normalize_provider_endpoint(base_url: str) -> str:
    value = str(base_url or "").strip()
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("provider base_url must be an absolute http(s) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("provider base_url cannot contain userinfo, query, or fragment")
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower()
    display_host = f"[{host}]" if ":" in host else host
    port = parsed.port
    if port is not None and not ((scheme == "https" and port == 443) or (scheme == "http" and port == 80)):
        display_host = f"{display_host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((scheme, display_host, path, "", ""))


def provider_identity_fingerprint(
    base_url: str,
    credential_ref: str,
    *,
    auth_kind: str,
    windows_env: bool | None = None,
) -> str:
    normalized_auth = str(auth_kind or "").strip().lower()
    canonical_ref = "none" if normalized_auth == "none" else canonicalize_credential_ref(
        credential_ref,
        windows_env=windows_env,
    )
    payload = normalize_provider_endpoint(base_url) + "\0" + canonical_ref
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def validate_provider_id(provider_id: str) -> str:
    value = str(provider_id or "").strip()
    if not _PROVIDER_ID_RE.fullmatch(value):
        raise ValueError("provider_id must match [a-z][a-z0-9_-]{0,63}")
    return value


def make_model_key(upstream_id: str, *, max_length: int = 96) -> str:
    exact = unicodedata.normalize("NFKC", str(upstream_id or "").strip())
    if not exact:
        raise ValueError("upstream_id is required")
    if _SAFE_MODEL_KEY_RE.fullmatch(exact) and len(exact) <= max_length:
        return exact
    digest = hashlib.sha256(exact.encode("utf-8")).hexdigest()[:8]
    slug = re.sub(r"[^a-z0-9._-]+", "_", exact.lower()).strip("_.-") or "model"
    suffix = f"~{digest}"
    return f"{slug[: max_length - len(suffix)]}{suffix}"


def make_model_ref(provider_id: str, model_key: str) -> str:
    provider = validate_provider_id(provider_id)
    key = str(model_key or "").strip()
    if not key or "/" in key or len(key) > 96:
        raise ValueError("model_key must be a non-empty provider-scoped key of at most 96 characters")
    return f"{provider}/{key}"


def split_model_ref(model_ref: str) -> tuple[str, str]:
    provider_id, separator, model_key = str(model_ref or "").strip().partition("/")
    if not separator:
        raise ValueError("model_ref must use provider_id/model_key")
    canonical = make_model_ref(provider_id, model_key)
    return tuple(canonical.split("/", 1))


__all__ = [
    "make_model_key",
    "make_model_ref",
    "normalize_provider_endpoint",
    "provider_identity_fingerprint",
    "split_model_ref",
    "validate_provider_id",
]
```

- [ ] **Step 5: Run identity tests and the existing config path baseline**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_identity.py tests\test_config_paths.py -q
```

Expected: all tests pass, and no test reads or writes the real operator config.

- [ ] **Step 6: Commit Task 1**

```powershell
git add -- config/llm_credentials.py config/llm_identity.py tests/test_llm_identity.py
git commit -m "feat(config): add stable LLM provider identities"
```

---

### Task 2: Schema v2 models, read-only v1 compatibility, and deterministic runtime projection

**Files:**
- Create: `config/llm_projection.py`
- Create: `tests/test_llm_config_schema_v2.py`
- Modify: `config/models.py:184`
- Modify: `config/settings.py:433`
- Modify: `config/public_config.py:870`
- Modify: `config/__init__.py:1`

**Interfaces:**
- Consumes: Task 1 identity and credential helpers.
- Produces: `project_v2_llm_for_runtime(public_config: dict[str, Any]) -> dict[str, Any]`
- Produces: `LLMConfig.schema_version`, `ProviderConfig.models`, `ProviderConfig.protocols`, `ProviderConfig.discovery`, `ProviderConfig.deployment`, and `LLMConfig.model_aliases`.
- Produces: `LLMConfig.resolve_model_ref(model_ref: str) -> str` as the only runtime alias resolver.
- Preserves: existing runtime `providers`, flattened `model_library`, and materialized `LLMProfile` fields for downstream code.

- [ ] **Step 1: Write failing schema/projection tests**

Add `tests/test_llm_config_schema_v2.py`:

```python
from __future__ import annotations

from config.public_config import build_effective_config
from config.settings import normalize_public_config_dict


def _v2_config() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "pixel_relay": {
                    "label": "Pixel Relay",
                    "service_class": "relay",
                    "vendor": "multi_model",
                    "driver": "openai",
                    "base_url": "https://relay.example/v1",
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
                    "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
                    "models": {
                        "gpt-5.6-luna": {
                            "upstream_id": "gpt-5.6-luna",
                            "label": "GPT-5.6 Luna",
                            "enabled": True,
                            "defaults": {"max_output_tokens": 32000, "timeout": 120},
                        }
                    },
                }
            },
            "profiles": {
                "primary": {
                    "model_ref": "pixel_relay/gpt-5.6-luna",
                    "overrides": {"temperature": 0.4},
                }
            },
        }
    }


def test_v2_projection_keeps_one_provider_and_flattens_only_runtime_models() -> None:
    normalized = normalize_public_config_dict(_v2_config())
    assert set(normalized["llm"]["providers"]) == {"pixel_relay"}
    assert set(normalized["llm"]["model_library"]) == {"pixel_relay/gpt-5.6-luna"}
    assert normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]["model"] == "gpt-5.6-luna"
    assert normalized["llm"]["profiles"]["primary"]["provider_id"] == "pixel_relay"
    assert normalized["llm"]["profiles"]["primary"]["temperature"] == 0.4
    assert normalized["llm"]["profiles"]["primary"]["max_output_tokens"] == 32000


def test_v2_effective_config_resolves_provider_credential_without_inline_copies(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY", "secret")
    effective = build_effective_config(_v2_config())
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider(profile.provider_id)
    assert effective.llm.schema_version == 2
    assert profile.model_ref == "pixel_relay/gpt-5.6-luna"
    assert profile.model == "gpt-5.6-luna"
    assert provider.provider_id == "pixel_relay"
    assert provider.resolve_api_key() == "secret"
    assert not any(provider_id.startswith("inline_") for provider_id in effective.llm.providers)


def test_v1_normalization_remains_read_only_and_compatible() -> None:
    legacy = {
        "llm": {
            "model_library": {
                "relay_model": {
                    "provider": {
                        "kind": "relay",
                        "base_url": "https://relay.example/v1",
                        "api_key_env": "RELAY_KEY",
                    },
                    "model": "gpt-5.6-luna",
                }
            },
            "profiles": {"primary": {"model_ref": "relay_model"}},
        }
    }
    normalized = normalize_public_config_dict(legacy)
    assert legacy["llm"]["model_library"]["relay_model"]["provider"]["kind"] == "relay"
    assert normalized["llm"]["profiles"]["primary"]["model"] == "gpt-5.6-luna"
```

- [ ] **Step 2: Run schema tests and verify v2 currently fails**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_config_schema_v2.py -q
```

Expected: v2 assertions fail because nested Provider models are not projected and `schema_version` is absent.

- [ ] **Step 3: Add typed v2 Provider/model structures to `config/models.py`**

Add these models immediately before `ProviderConfig`, then extend `ProviderConfig`, `LLMProfile`, and `LLMConfig` with the listed fields. Keep existing legacy fields during the compatibility window.

```python
class ProviderProtocolsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    default: str = ""
    allowed: List[str] = Field(default_factory=list)
    routes: Dict[str, str] = Field(default_factory=dict)


class ProviderDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "manual"
    adapter: str = "manual"
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)


class ProviderDeploymentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    runtime_framework: str = ""
    artifact_path: str = ""


class PinnedModelDefaults(BaseModel):
    model_config = ConfigDict(extra="allow")

    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=4096, gt=0)
    timeout: int = Field(default=60, gt=0)
    connect_timeout: int = Field(default=30, gt=0)
    streaming: bool = True
    tool_calling_mode: str = "auto"


class PinnedModelConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    upstream_id: str
    label: str = ""
    enabled: bool = True
    wire_protocol: str = ""
    interaction_contract: str = "tool_chat"
    model_protocol: str = ""
    defaults: PinnedModelDefaults = Field(default_factory=PinnedModelDefaults)
    compatibility: Dict[str, Any] = Field(default_factory=dict)
    capabilities: Dict[str, Any] = Field(default_factory=dict)
```

Extend `ProviderConfig` with:

```python
    label: str = ""
    service_class: Literal["official_api", "aggregator", "relay", "self_hosted", "local_runtime"] = "official_api"
    vendor: str = "custom"
    driver: Literal["openai", "anthropic", "gemini"] = "openai"
    auth_kind: Literal["api_key", "oauth", "none"] = "api_key"
    credential_ref: str = ""
    requires_credential: bool = True
    protocols: ProviderProtocolsConfig = Field(default_factory=ProviderProtocolsConfig)
    discovery: ProviderDiscoverySettings = Field(default_factory=ProviderDiscoverySettings)
    deployment: ProviderDeploymentConfig = Field(default_factory=ProviderDeploymentConfig)
    models: Dict[str, PinnedModelConfig] = Field(default_factory=dict)
    legacy_inference_allowed: bool = Field(default=True, exclude=True)
```

Add `Literal` to the existing `typing` imports. Add this v2 consistency validator to `ProviderConfig`; it is inert for legacy providers that have no `credential_ref`, `service_class`, or pinned `models`:

```python
    @model_validator(mode="after")
    def validate_v2_provider_contract(self) -> "ProviderConfig":
        if not self.credential_ref and not self.models:
            return self
        from .llm_credentials import canonicalize_credential_ref
        from .llm_identity import make_model_ref, normalize_provider_endpoint

        normalize_provider_endpoint(self.base_url)
        canonical_ref = canonicalize_credential_ref(self.credential_ref or "none")
        if self.auth_kind == "none" and canonical_ref != "none":
            raise ValueError("auth_kind none requires credential_ref none")
        if self.auth_kind != "none" and canonical_ref == "none" and self.requires_credential:
            raise ValueError("credential_ref is required when provider requires a credential")
        if self.protocols.default and self.protocols.allowed and self.protocols.default not in self.protocols.allowed:
            raise ValueError("provider default protocol must be present in protocols.allowed")
        if self.service_class != "local_runtime" and self.deployment.runtime_framework:
            raise ValueError("runtime_framework is only valid for local_runtime providers")
        for model_key, model in self.models.items():
            make_model_ref(self.provider_id or "provider", model_key)
            if not model.upstream_id.strip():
                raise ValueError(f"pinned model {model_key} requires upstream_id")
        return self
```

Extend `LLMProfile` with `model_ref: str = ""` and extend `LLMConfig` with:

```python
    schema_version: int = Field(default=1, ge=1, le=2)
    model_aliases: Dict[str, str] = Field(default_factory=dict)
```

Add a cycle-safe alias resolver to `LLMConfig` and use it before every `model_library` lookup in this class:

```python
    def resolve_model_ref(self, model_ref: str) -> str:
        requested = str(model_ref or "").strip()
        current = requested
        visited: set[str] = set()
        while current in self.model_aliases:
            if current in visited:
                raise ValueError(f"cyclic model alias: {requested}")
            visited.add(current)
            current = str(self.model_aliases[current] or "").strip()
        return current
```

`get_model_library_entry_for_profile()` must prefer `profile.model_ref`, call `resolve_model_ref()`, and perform direct canonical lookup before retaining the v1 provider/model identity scan as a legacy fallback.

Change `ProviderConfig.resolve_api_key()` so v2 resolves `credential_ref` first and legacy providers keep the existing environment fallback:

```python
    def resolve_api_key(self) -> Optional[str]:
        if self.credential_ref:
            from .llm_credentials import resolve_credential_ref

            resolution = resolve_credential_ref(self.credential_ref)
            return resolution.secret or None
        env_candidates: List[str] = []
        if self.api_key_env:
            env_candidates.append(self.api_key_env)
        canonical_env = get_provider_api_key_env(self.kind)
        if canonical_env and canonical_env not in env_candidates:
            env_candidates.append(canonical_env)
        for env_var in env_candidates:
            value = _read_env_var(env_var)
            if value:
                return value
        for alias in PROVIDER_API_KEY_ENV_ALIASES.get((self.kind or "").strip().lower(), []):
            value = _read_env_var(alias)
            if value:
                return value
        return self.api_key or None
```

- [ ] **Step 4: Implement the network-free v2 runtime projection**

Create `config/llm_projection.py`. The complete projection must deep-copy input, validate every model key/ref, derive only compatibility fields, and never call discovery:

```python
from __future__ import annotations

import copy
from typing import Any

from .llm_credentials import canonicalize_credential_ref
from .llm_identity import make_model_ref, split_model_ref, validate_provider_id


def _credential_env(credential_ref: str) -> str:
    canonical = canonicalize_credential_ref(credential_ref)
    return canonical.removeprefix("env:") if canonical.startswith("env:") else ""


def _runtime_provider(provider_id: str, provider: dict[str, Any]) -> dict[str, Any]:
    default_wire = str(provider.get("protocols", {}).get("default") or "").strip()
    vendor = str(provider.get("vendor") or "custom").strip().lower()
    framework = str(provider.get("deployment", {}).get("runtime_framework") or "").strip().lower()
    driver = str(provider.get("driver") or "openai").strip().lower()
    legacy_kind = framework or (vendor if vendor not in {"custom", "multi_model"} else driver)
    credential_ref = str(provider.get("credential_ref") or "none").strip()
    return {
        **copy.deepcopy(provider),
        "provider_id": provider_id,
        "kind": legacy_kind,
        "api": default_wire.replace("_", "-"),
        "api_key_env": _credential_env(credential_ref),
        "requires_api_key": bool(provider.get("requires_credential", provider.get("auth_kind") != "none")),
        "compat_mode": "openai" if driver == "openai" else "native",
        "legacy_inference_allowed": False,
    }


def project_v2_llm_for_runtime(public_config: dict[str, Any]) -> dict[str, Any]:
    projected = copy.deepcopy(public_config)
    llm = projected.setdefault("llm", {})
    if int(llm.get("schema_version") or 1) != 2:
        return projected
    providers = llm.get("providers")
    profiles = llm.get("profiles")
    if not isinstance(providers, dict) or not isinstance(profiles, dict):
        raise ValueError("llm.providers and llm.profiles must be objects in schema v2")
    runtime_providers: dict[str, dict[str, Any]] = {}
    runtime_models: dict[str, dict[str, Any]] = {}
    for provider_id, raw_provider in providers.items():
        validate_provider_id(str(provider_id))
        if not isinstance(raw_provider, dict):
            raise ValueError(f"llm.providers.{provider_id} must be an object")
        runtime_providers[str(provider_id)] = _runtime_provider(str(provider_id), raw_provider)
        raw_models = raw_provider.get("models", {})
        if not isinstance(raw_models, dict):
            raise ValueError(f"llm.providers.{provider_id}.models must be an object")
        for model_key, raw_model in raw_models.items():
            model_ref = make_model_ref(str(provider_id), str(model_key))
            if not isinstance(raw_model, dict):
                raise ValueError(f"pinned model {model_ref} must be an object")
            upstream_id = str(raw_model.get("upstream_id") or "").strip()
            if not upstream_id:
                raise ValueError(f"pinned model {model_ref} requires upstream_id")
            defaults = raw_model.get("defaults", {}) if isinstance(raw_model.get("defaults"), dict) else {}
            runtime_models[model_ref] = {
                **copy.deepcopy(raw_model),
                **copy.deepcopy(defaults),
                "provider_id": str(provider_id),
                "model": upstream_id,
                "label": str(raw_model.get("label") or upstream_id),
                "transport": str(raw_model.get("wire_protocol") or raw_provider.get("protocols", {}).get("default") or ""),
                "contract": str(raw_model.get("interaction_contract") or "tool_chat"),
                "protocol": str(raw_model.get("model_protocol") or ""),
                "compat": copy.deepcopy(raw_model.get("compatibility", {})),
                "model_ref": model_ref,
            }
    runtime_profiles: dict[str, dict[str, Any]] = {}
    aliases = llm.get("model_aliases", {}) if isinstance(llm.get("model_aliases"), dict) else {}
    for profile_id, raw_profile in profiles.items():
        if not isinstance(raw_profile, dict):
            raise ValueError(f"llm.profiles.{profile_id} must be an object")
        requested_ref = str(raw_profile.get("model_ref") or "").strip()
        model_ref = str(aliases.get(requested_ref) or requested_ref)
        provider_id, model_key = split_model_ref(model_ref)
        canonical_ref = make_model_ref(provider_id, model_key)
        model = runtime_models.get(canonical_ref)
        if model is None:
            raise ValueError(f"unknown profile model_ref: {requested_ref}")
        overrides = raw_profile.get("overrides", {}) if isinstance(raw_profile.get("overrides"), dict) else {}
        runtime_profiles[str(profile_id)] = {
            **copy.deepcopy(model),
            **copy.deepcopy(overrides),
            "profile_id": str(profile_id),
            "provider_id": provider_id,
            "model_ref": canonical_ref,
        }
    llm["providers"] = runtime_providers
    llm["profiles"] = runtime_profiles
    llm["model_library"] = runtime_models
    return projected


__all__ = ["project_v2_llm_for_runtime"]
```

- [ ] **Step 5: Route schema versions in `config/settings.py` without mutating caller data**

Replace `_canonicalize_runtime_public_config()` with:

```python
def _canonicalize_runtime_public_config(public_config: Dict[str, Any]) -> Dict[str, Any]:
    candidate = copy.deepcopy(public_config)
    llm = candidate.get("llm", {})
    schema_version = int(llm.get("schema_version") or 1) if isinstance(llm, dict) else 1
    if schema_version == 2:
        from .llm_projection import project_v2_llm_for_runtime

        return project_v2_llm_for_runtime(candidate)
    repaired = _repair_legacy_model_library_shape(candidate)
    with_profile_models = _ensure_profile_model_library_entries(repaired)
    return _ensure_model_library_prompt_cache_defaults(with_profile_models)
```

In `normalize_public_config_dict()`, keep `_materialize_inline_llm_providers()` only for `schema_version == 1`. For v2, call `_materialize_model_ref_profiles()` against the already-projected library and never create `inline_model_*` or `inline_profile_*` providers.

- [ ] **Step 6: Preserve public v2 shape in `config/public_config.py`**

Change `_canonicalize_public_config()` so schema v2 validates and returns the nested provider structure instead of running v1 model-library repair:

```python
def _canonicalize_public_config(public_config: dict) -> dict:
    candidate = copy.deepcopy(public_config) if isinstance(public_config, dict) else {}
    llm = candidate.get("llm", {})
    schema_version = int(llm.get("schema_version") or 1) if isinstance(llm, dict) else 1
    if schema_version == 2:
        build_effective_config_for_validation = normalize_public_config_dict(candidate)
        AppConfig.model_validate(build_effective_config_for_validation)
        return candidate
    repaired = _repair_legacy_model_library_shape(candidate)
    with_profile_models = _ensure_profile_model_library_entries(repaired)
    canonical = _canonicalize_model_library_api_key_envs(with_profile_models)
    return _ensure_model_library_prompt_cache_defaults(canonical)
```

Avoid recursive `build_effective_config()` calls in this function; the local variable name makes it clear the result is validation input only.

- [ ] **Step 7: Run v2, public config, and settings compatibility tests**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_config_schema_v2.py tests\test_public_config_model_refs.py tests\test_config_sync.py tests\test_config_redaction.py -q
```

Expected: all tests pass; existing v1 fixtures still materialize compatible runtime providers, while v2 produces exactly one runtime Provider per public Provider.

- [ ] **Step 8: Commit Task 2**

```powershell
git add -- config/models.py config/settings.py config/public_config.py config/__init__.py config/llm_projection.py tests/test_llm_config_schema_v2.py
git commit -m "feat(config): add provider-scoped schema v2 projection"
```

---

### Task 3: Provider registry, uniqueness, route impact, and pinned-model operations

**Files:**
- Create: `config/llm_provider_registry.py`
- Create: `tests/test_llm_provider_registry.py`
- Modify: `config/public_config.py:1283`
- Modify: `config/__init__.py:1`

**Interfaces:**
- Consumes: Task 1 identity helpers and Task 2 public schema.
- Produces: `validate_provider_registry(public_config) -> None`
- Produces: `list_llm_provider_options(public_config) -> list[dict[str, Any]]`
- Produces: `add_llm_provider(public_config: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> dict[str, Any]`
- Produces: `update_llm_provider(public_config: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> dict[str, Any]`
- Produces: `delete_llm_provider(public_config: dict[str, Any], provider_id: str) -> dict[str, Any]`
- Produces: `pin_llm_model(public_config: dict[str, Any], provider_id: str, *, upstream_id: str, label: str = "", model_key: str = "", overrides: dict[str, Any] | None = None) -> dict[str, Any]`
- Produces: `unpin_llm_model(public_config: dict[str, Any], model_ref: str) -> dict[str, Any]`
- Produces: `preview_provider_route_replacement(public_config: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> dict[str, Any]`
- Produces: `suggest_provider_id(provider: dict[str, Any], existing_ids: Iterable[str]) -> str` for pre-save UI suggestions only.

- [ ] **Step 1: Write failing Provider registry tests**

Create `tests/test_llm_provider_registry.py` with these behavior anchors:

```python
from __future__ import annotations

import pytest

from config.llm_provider_registry import (
    add_llm_provider,
    pin_llm_model,
    preview_provider_route_replacement,
    suggest_provider_id,
    validate_provider_registry,
)


def _empty_v2() -> dict:
    return {"llm": {"schema_version": 2, "providers": {}, "profiles": {}, "model_aliases": {}}}


def _provider(credential_ref: str = "env:RELAY_KEY") -> dict:
    return {
        "label": "Relay",
        "service_class": "relay",
        "vendor": "multi_model",
        "driver": "openai",
        "base_url": "https://relay.example/v1",
        "auth_kind": "api_key",
        "credential_ref": credential_ref,
        "requires_credential": True,
        "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
        "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
        "models": {},
    }


def test_duplicate_endpoint_and_credential_is_rejected() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    with pytest.raises(ValueError, match="duplicates active provider relay_a"):
        add_llm_provider(config, "relay_b", _provider())


def test_same_endpoint_with_different_credential_is_distinct() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider("env:RELAY_A_KEY"))
    config = add_llm_provider(config, "relay_b", _provider("env:RELAY_B_KEY"))
    validate_provider_registry(config)
    assert set(config["llm"]["providers"]) == {"relay_a", "relay_b"}


def test_pin_uses_upstream_id_and_stable_provider_scoped_key() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    updated = pin_llm_model(config, "relay_a", upstream_id="anthropic/claude-sonnet-4.6", label="Claude")
    models = updated["llm"]["providers"]["relay_a"]["models"]
    assert set(models) == {"anthropic_claude-sonnet-4.6~3e041007"}
    assert models["anthropic_claude-sonnet-4.6~3e041007"]["upstream_id"] == "anthropic/claude-sonnet-4.6"


def test_route_replacement_preview_reports_all_provider_models() -> None:
    config = add_llm_provider(_empty_v2(), "relay_a", _provider())
    config = pin_llm_model(config, "relay_a", upstream_id="gpt-5.6-luna", label="GPT")
    preview = preview_provider_route_replacement(
        config,
        "relay_a",
        {**_provider("env:NEW_ACCOUNT_KEY"), "models": config["llm"]["providers"]["relay_a"]["models"]},
    )
    assert preview["routeChanged"] is True
    assert preview["modelRefs"] == ["relay_a/gpt-5.6-luna"]
    assert preview["oldFingerprint"] != preview["newFingerprint"]


def test_provider_id_suggestion_is_readable_and_collision_deterministic() -> None:
    provider = _provider("env:VIBELUTION_LLM_PROVIDER_RELAY_A_API_KEY")
    assert suggest_provider_id(provider, []) == "relay"
    suggested = suggest_provider_id(provider, ["relay"])
    assert suggested.startswith("relay_")
    assert len(suggested.rsplit("_", 1)[1]) == 8
```

- [ ] **Step 2: Run the registry tests and verify missing API failures**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_provider_registry.py -q
```

Expected: collection fails because `config.llm_provider_registry` does not exist.

- [ ] **Step 3: Implement Provider registry validation and route preview**

Create `config/llm_provider_registry.py` with immutable draft operations. Use `copy.deepcopy()` at every public mutation boundary. The key implementation is:

```python
from __future__ import annotations

import copy
import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlsplit

from .llm_identity import make_model_key, make_model_ref, provider_identity_fingerprint, validate_provider_id


def _providers(public_config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    if int(llm.get("schema_version") or 1) != 2:
        raise ValueError("Provider registry mutations require llm.schema_version = 2")
    providers = llm.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("llm.providers must be an object")
    return providers


def _fingerprint(provider: dict[str, Any]) -> str:
    return provider_identity_fingerprint(
        str(provider.get("base_url") or ""),
        str(provider.get("credential_ref") or "none"),
        auth_kind=str(provider.get("auth_kind") or "api_key"),
    )


def suggest_provider_id(provider: dict[str, Any], existing_ids: Iterable[str]) -> str:
    label = str(provider.get("label") or "").strip().lower()
    host = urlsplit(str(provider.get("base_url") or "")).hostname or ""
    service_class = str(provider.get("service_class") or "provider").strip().lower()
    source = label or host.split(".")[0] or service_class
    base = re.sub(r"[^a-z0-9_-]+", "_", source).strip("_") or "provider"
    if not base[0].isalpha():
        base = f"provider_{base}"
    existing = {str(item) for item in existing_ids}
    if base not in existing:
        return validate_provider_id(base[:64])
    return validate_provider_id(f"{base[:55]}_{_fingerprint(provider)[:8]}")


def validate_provider_registry(public_config: dict[str, Any]) -> None:
    fingerprints: dict[str, str] = {}
    for provider_id, provider in _providers(public_config).items():
        validate_provider_id(str(provider_id))
        if not isinstance(provider, dict):
            raise ValueError(f"provider {provider_id} must be an object")
        fingerprint = _fingerprint(provider)
        duplicate = fingerprints.get(fingerprint)
        if duplicate:
            raise ValueError(f"provider {provider_id} duplicates active provider {duplicate}")
        fingerprints[fingerprint] = str(provider_id)


def add_llm_provider(public_config: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    canonical_id = validate_provider_id(provider_id)
    if canonical_id in providers:
        raise ValueError(f"LLM provider already exists: {canonical_id}")
    providers[canonical_id] = copy.deepcopy(provider)
    providers[canonical_id].setdefault("models", {})
    validate_provider_registry(updated)
    return updated


def update_llm_provider(public_config: dict[str, Any], provider_id: str, provider: dict[str, Any]) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    if provider_id not in providers:
        raise ValueError(f"unknown LLM provider: {provider_id}")
    existing_models = copy.deepcopy(providers[provider_id].get("models", {}))
    providers[provider_id] = copy.deepcopy(provider)
    providers[provider_id]["models"] = copy.deepcopy(provider.get("models", existing_models))
    validate_provider_registry(updated)
    return updated


def preview_provider_route_replacement(
    public_config: dict[str, Any],
    provider_id: str,
    provider: dict[str, Any],
) -> dict[str, Any]:
    existing = _providers(public_config).get(provider_id)
    if not isinstance(existing, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    old_fingerprint = _fingerprint(existing)
    new_fingerprint = _fingerprint(provider)
    model_refs = sorted(make_model_ref(provider_id, key) for key in existing.get("models", {}))
    return {
        "providerId": provider_id,
        "routeChanged": old_fingerprint != new_fingerprint,
        "oldFingerprint": old_fingerprint,
        "newFingerprint": new_fingerprint,
        "modelRefs": model_refs,
    }


def pin_llm_model(
    public_config: dict[str, Any],
    provider_id: str,
    *,
    upstream_id: str,
    label: str = "",
    model_key: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    provider = _providers(updated).get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    key = str(model_key or make_model_key(upstream_id)).strip()
    make_model_ref(provider_id, key)
    models = provider.setdefault("models", {})
    if key in models:
        raise ValueError(f"pinned model already exists: {provider_id}/{key}")
    models[key] = {
        "upstream_id": str(upstream_id),
        "label": str(label or upstream_id),
        "enabled": True,
        **copy.deepcopy(overrides or {}),
    }
    return updated


def unpin_llm_model(public_config: dict[str, Any], model_ref: str) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    provider_id, model_key = model_ref.split("/", 1)
    provider = _providers(updated).get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    provider.get("models", {}).pop(model_key, None)
    return updated


def delete_llm_provider(public_config: dict[str, Any], provider_id: str) -> dict[str, Any]:
    updated = copy.deepcopy(public_config)
    providers = _providers(updated)
    provider = providers.get(provider_id)
    if not isinstance(provider, dict):
        raise ValueError(f"unknown LLM provider: {provider_id}")
    if provider.get("models"):
        raise ValueError("provider must have no pinned models before deletion")
    providers.pop(provider_id)
    return updated
```

- [ ] **Step 4: Add public list/wrapper functions without duplicating identity logic**

In `config/public_config.py`, add `list_llm_provider_options()` that returns stable IDs and credential state but never secret values:

Add `from .llm_credentials import resolve_credential_ref` to the module imports, then add:

```python
def list_llm_provider_options(public_config: dict) -> list[dict[str, object]]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    providers = llm.get("providers", {}) if isinstance(llm, dict) else {}
    if int(llm.get("schema_version") or 1) != 2 or not isinstance(providers, dict):
        return []
    options: list[dict[str, object]] = []
    for provider_id, provider in sorted(providers.items()):
        if not isinstance(provider, dict):
            continue
        credential_ref = str(provider.get("credential_ref") or "none")
        resolution = resolve_credential_ref(credential_ref)
        options.append(
            {
                "provider_id": str(provider_id),
                "label": str(provider.get("label") or provider_id),
                "service_class": str(provider.get("service_class") or ""),
                "vendor": str(provider.get("vendor") or "custom"),
                "driver": str(provider.get("driver") or "openai"),
                "runtime_framework": str(provider.get("deployment", {}).get("runtime_framework") or ""),
                "artifact_path": str(provider.get("deployment", {}).get("artifact_path") or ""),
                "base_url": str(provider.get("base_url") or ""),
                "credential_state": resolution.state,
                "default_protocol": str(provider.get("protocols", {}).get("default") or ""),
                "pinned_count": len(provider.get("models", {})) if isinstance(provider.get("models"), dict) else 0,
            }
        )
    return options
```

Import and re-export Task 3 public helpers from `config/__init__.py`; keep old model mutation functions as v1 compatibility wrappers until Task 11 removes them from new-write paths.

- [ ] **Step 5: Run Provider registry and public config regression tests**

Run:

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_provider_registry.py tests\test_public_config_model_refs.py tests\test_config_panel.py -q
```

Expected: Provider registry tests and existing config panel tests pass; no wrapper persists secrets.

- [ ] **Step 6: Commit Task 3**

```powershell
git add -- config/llm_provider_registry.py config/public_config.py config/__init__.py tests/test_llm_provider_registry.py
git commit -m "feat(config): add LLM provider registry operations"
```

---

### Task 4: Derived model catalog, stale reconciliation, and field-level capability provenance

**Files:**
- Create: `config/model_catalog.py`
- Create: `tests/test_model_catalog.py`
- Modify: `config/paths.py:18`
- Modify: `config/runtime_capabilities.py:12`

**Interfaces:**
- Consumes: canonical model refs from Tasks 1-3.
- Produces: `load_model_catalog_state()`, `save_model_catalog_state()`, `record_discovery_success()`, `record_discovery_failure()`.
- Produces: `merge_capability_observations(observations: list[dict[str, Any]]) -> dict[str, Any]`.
- Produces: `resolve_model_capabilities(*, operator, runtime_probe, provider_metadata, curated_snapshot, driver_default) -> dict[str, Any]` using the same field-level merger.
- Produces: one-time `import_legacy_capability_cache(state, legacy_payload, legacy_to_ref)`.
- Produces: `provider_catalog_refresh_due(state, provider_id, *, ttl_seconds, now) -> bool`.

- [ ] **Step 1: Write failing catalog and capability provenance tests**

Create `tests/test_model_catalog.py`:

```python
from __future__ import annotations

from config.model_catalog import (
    empty_model_catalog_state,
    import_legacy_capability_cache,
    load_model_catalog_state,
    merge_capability_observations,
    provider_catalog_refresh_due,
    record_discovery_failure,
    record_discovery_success,
    save_model_catalog_state,
)


def test_discovery_success_reconciles_observed_and_missing_pinned(tmp_path) -> None:
    state = empty_model_catalog_state()
    state = record_discovery_success(
        state,
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={"gpt-a": {"upstream_id": "gpt-a"}, "gpt-b": {"upstream_id": "gpt-b"}},
    )
    models = state["providers"]["relay"]["models"]
    assert models["gpt-a"]["availability"] == "pinned"
    assert models["gpt-b"]["availability"] == "missing_remote"
    save_model_catalog_state(state, tmp_path / "model-catalog-state.json")
    assert load_model_catalog_state(tmp_path / "model-catalog-state.json") == state


def test_failure_keeps_last_success_and_marks_provider_stale() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={},
    )
    failed = record_discovery_failure(
        state,
        provider_id="relay",
        attempted_at="2026-07-11T13:00:00Z",
        error_type="timeout",
    )
    assert failed["providers"]["relay"]["status"] == "stale"
    assert failed["providers"]["relay"]["lastSuccessAt"] == "2026-07-11T12:00:00Z"
    assert "gpt-a" in failed["providers"]["relay"]["models"]


def test_auth_failure_keeps_models_but_reports_auth_state() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[{"upstream_id": "gpt-a", "label": "GPT A", "capabilities": {}}],
        pinned={},
    )
    failed = record_discovery_failure(
        state,
        provider_id="relay",
        attempted_at="2026-07-11T13:00:00Z",
        error_type="HTTPStatusError",
        status="auth_failed",
    )
    assert failed["providers"]["relay"]["status"] == "auth_failed"
    assert failed["providers"]["relay"]["catalogStale"] is True
    assert "gpt-a" in failed["providers"]["relay"]["models"]


def test_capabilities_merge_per_field_by_source_priority() -> None:
    merged = merge_capability_observations(
        [
            {"field": "image_input", "value": "unsupported", "source": "provider_endpoint", "checked_at": "a"},
            {"field": "image_input", "value": "supported", "source": "operator_override", "checked_at": "b"},
            {"field": "tool_calling", "value": "supported", "source": "runtime_probe", "checked_at": "c"},
        ]
    )
    assert merged["image_input"]["value"] == "supported"
    assert merged["image_input"]["source"] == "operator_override"
    assert merged["tool_calling"]["value"] == "supported"


def test_catalog_refresh_due_uses_last_attempt_and_ttl() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[],
        pinned={},
    )
    assert provider_catalog_refresh_due(state, "relay", ttl_seconds=3600, now="2026-07-11T13:00:01Z") is True
    assert provider_catalog_refresh_due(state, "relay", ttl_seconds=3600, now="2026-07-11T12:59:59Z") is False


def test_case_distinct_upstream_ids_remain_distinct_and_emit_warning() -> None:
    state = record_discovery_success(
        empty_model_catalog_state(),
        provider_id="relay",
        provider_fingerprint="fp",
        discovered_at="2026-07-11T12:00:00Z",
        observed=[
            {"upstream_id": "Model-A", "label": "Model A upper", "capabilities": {}},
            {"upstream_id": "model-a", "label": "Model A lower", "capabilities": {}},
        ],
        pinned={},
    )
    provider = state["providers"]["relay"]
    assert len(provider["models"]) == 2
    assert provider["warnings"][0]["code"] == "upstream_id_case_collision"


def test_legacy_capability_import_runs_once() -> None:
    legacy = {
        "schemaVersion": 1,
        "models": {
            "old_model": {
                "capabilities": {
                    "image_input": {
                        "supports_image_input": True,
                        "capability_status": "supported",
                        "capability_source": "runtime_probe",
                        "capability_checked_at": "2026-07-10",
                    }
                }
            }
        },
    }
    imported = import_legacy_capability_cache(empty_model_catalog_state(), legacy, {"old_model": "relay/gpt-a"})
    assert imported["providers"]["relay"]["models"]["gpt-a"]["capabilities"]["image_input"]["value"] == "supported"
    changed_legacy = {
        "schemaVersion": 1,
        "models": {
            "old_model": {
                "capabilities": {
                    "image_input": {"supports_image_input": False, "capability_status": "unsupported"}
                }
            }
        },
    }
    second = import_legacy_capability_cache(imported, changed_legacy, {"old_model": "relay/gpt-a"})
    assert second == imported
```

- [ ] **Step 2: Run the catalog tests and verify missing-module failure**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_model_catalog.py -q
```

Expected: collection fails because `config.model_catalog` does not exist.

- [ ] **Step 3: Add the catalog path beside operator config**

In `config/paths.py`, add:

```python
MODEL_CATALOG_STATE_FILENAME = "model-catalog-state.json"


def resolve_model_catalog_state_path(config_path: str | os.PathLike[str] | None = None) -> Path:
    return resolve_config_path(config_path).with_name(MODEL_CATALOG_STATE_FILENAME)
```

Export both names in `__all__`. Do not derive this path from the repository root.

- [ ] **Step 4: Implement catalog persistence and reconciliation**

Create `config/model_catalog.py` using `core.infrastructure.atomic_io.atomic_write_json` for writes. Lock the serialized envelope to:

```python
def empty_model_catalog_state() -> dict[str, Any]:
    return {
        "schemaVersion": 2,
        "providers": {},
        "metadata": {"legacyCapabilityImportCompleted": False},
    }
```

Implement success reconciliation with deterministic model keys and no deletion on failures:

```python
def _capability_observations(capabilities: Any, *, default_source: str) -> list[dict[str, Any]]:
    if not isinstance(capabilities, dict):
        return []
    observations: list[dict[str, Any]] = []
    for field, raw in capabilities.items():
        if isinstance(raw, dict):
            observations.append(
                {
                    "field": str(field),
                    "value": str(raw.get("value") or raw.get("capability_status") or "unknown"),
                    "source": str(raw.get("source") or raw.get("capability_source") or default_source),
                    "confidence": str(raw.get("confidence") or ""),
                    "checked_at": str(raw.get("checked_at") or raw.get("capability_checked_at") or ""),
                    "error": str(raw.get("error") or raw.get("capability_error") or ""),
                }
            )
        elif isinstance(raw, bool):
            observations.append(
                {
                    "field": str(field),
                    "value": "supported" if raw else "unsupported",
                    "source": default_source,
                    "confidence": "",
                    "checked_at": "",
                    "error": "",
                }
            )
    return observations


def record_discovery_success(
    state: dict[str, Any],
    *,
    provider_id: str,
    provider_fingerprint: str,
    discovered_at: str,
    observed: list[dict[str, Any]],
    pinned: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    updated = copy.deepcopy(state)
    previous = updated.setdefault("providers", {}).get(provider_id, {})
    previous_models = previous.get("models", {}) if isinstance(previous, dict) else {}
    models: dict[str, dict[str, Any]] = {}
    observed_upstream_ids: set[str] = set()
    for raw in observed:
        upstream_id = str(raw.get("upstream_id") or "").strip()
        if not upstream_id:
            continue
        observed_upstream_ids.add(upstream_id)
        model_key = make_model_key(upstream_id)
        is_pinned = model_key in pinned and str(pinned[model_key].get("upstream_id")) == upstream_id
        prior = previous_models.get(model_key, {}) if isinstance(previous_models, dict) else {}
        operator_capabilities = pinned.get(model_key, {}).get("capabilities", {}) if is_pinned else {}
        capability_observations = [
            *_capability_observations(prior.get("capabilities", {}), default_source="driver_default"),
            *_capability_observations(raw.get("capabilities", {}), default_source="provider_endpoint"),
            *_capability_observations(operator_capabilities, default_source="operator_override"),
        ]
        models[model_key] = {
            "upstreamId": upstream_id,
            "label": str(raw.get("label") or upstream_id),
            "availability": "pinned" if is_pinned else "observed",
            "capabilities": merge_capability_observations(capability_observations),
            "limits": copy.deepcopy(raw.get("limits", {})),
            "metadataSource": str(raw.get("metadata_source") or "provider_endpoint"),
        }
    for model_key, pinned_model in pinned.items():
        upstream_id = str(pinned_model.get("upstream_id") or "").strip()
        if upstream_id in observed_upstream_ids:
            continue
        prior = copy.deepcopy(previous_models.get(model_key, {})) if isinstance(previous_models, dict) else {}
        models[model_key] = {
            **prior,
            "upstreamId": upstream_id,
            "label": str(pinned_model.get("label") or prior.get("label") or upstream_id),
            "availability": "missing_remote",
        }
    updated["providers"][provider_id] = {
        "providerFingerprint": provider_fingerprint,
        "status": "reachable",
        "lastAttemptAt": discovered_at,
        "lastSuccessAt": discovered_at,
        "lastErrorType": "",
        "models": models,
    }
    return updated
```

`record_discovery_failure()` must deep-copy state, retain `models` and `lastSuccessAt`, set `lastAttemptAt`, `catalogStale`, and bounded `lastErrorType`. It accepts only `auth_failed`, `discovery_failed`, `stale`, `protocol_mismatch`, or `blocked`; ordinary refresh failures choose `stale` when a previous success exists and `discovery_failed` otherwise, while a classified 401/403 remains `auth_failed` and preserves the previous models with `catalogStale=true`. `load_model_catalog_state()` returns the empty envelope for a missing file, rejects schema versions other than `2`, and never reads `model-capabilities.json` itself.

`provider_catalog_refresh_due()` parses UTC timestamps, returns true when no successful/attempt timestamp exists, compares `now - lastAttemptAt` against the Provider's `cache_ttl_seconds`, and returns false for `ttl_seconds == 0` so manual-only providers never auto-refresh.

During successful reconciliation, group observed IDs by Unicode-NFKC `casefold()` only for diagnostics. Keep every exact upstream ID and deterministic model key; when a group contains more than one exact value, add a bounded `upstream_id_case_collision` warning listing only their model keys.

- [ ] **Step 5: Implement field-level capability precedence and one-time import**

Use the exact priority table and a per-field record:

```python
CAPABILITY_SOURCE_PRIORITY = {
    "driver_default": 10,
    "curated_snapshot": 20,
    "provider_endpoint": 30,
    "runtime_probe": 40,
    "operator_override": 50,
}
CAPABILITY_VALUES = {"supported", "unsupported", "unknown"}


def merge_capability_observations(observations: list[dict[str, Any]]) -> dict[str, Any]:
    merged: dict[str, dict[str, Any]] = {}
    for observation in observations:
        field = str(observation.get("field") or "").strip()
        value = str(observation.get("value") or "unknown").strip().lower()
        source = str(observation.get("source") or "driver_default").strip()
        if not field or value not in CAPABILITY_VALUES or source not in CAPABILITY_SOURCE_PRIORITY:
            raise ValueError("invalid capability observation")
        current = merged.get(field)
        if current is None or CAPABILITY_SOURCE_PRIORITY[source] >= CAPABILITY_SOURCE_PRIORITY[current["source"]]:
            merged[field] = {
                "value": value,
                "source": source,
                "confidence": str(observation.get("confidence") or ""),
                "checked_at": str(observation.get("checked_at") or ""),
                "error": str(observation.get("error") or "")[:240],
            }
    return merged
```

Implement `resolve_model_capabilities()` as a thin ordered collector that labels the five input dictionaries with `operator_override`, `runtime_probe`, `provider_endpoint`, `curated_snapshot`, and `driver_default`, then calls `merge_capability_observations()`. `core/llm/discovery.py` will pass current model preset metadata as the curated snapshot and `capabilities_for_adapter()` results as conservative driver defaults in Task 6.

`import_legacy_capability_cache()` must set `metadata.legacyCapabilityImportCompleted = True` even when there are no mappable entries, so future loads never re-read or dual-write the old file.

- [ ] **Step 6: Turn `runtime_capabilities.py` into a compatibility adapter**

Keep its public functions for current callers, but make `record_model_image_input_capability()` split canonical `model_ref` and update `model-catalog-state.json` under `providers[provider_id].models[model_key].capabilities.image_input`. `apply_model_capability_overrides()` reads the same Provider-scoped catalog record and never writes runtime fields into public TOML. Retain the legacy loader only inside the one-time import path; do not add a second flat catalog index.

- [ ] **Step 7: Run catalog, legacy cache, and path tests**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_model_catalog.py tests\test_runtime_capabilities.py tests\test_config_paths.py -q
```

Expected: all tests pass; modifying the legacy cache after the import marker does not alter catalog state.

- [ ] **Step 8: Commit Task 4**

```powershell
git add -- config/model_catalog.py config/paths.py config/runtime_capabilities.py tests/test_model_catalog.py tests/test_runtime_capabilities.py tests/test_config_paths.py
git commit -m "feat(config): persist provider-scoped model catalog"
```

---

### Task 5: Bounded Provider discovery adapters and catalog reconciliation service

**Files:**
- Create: `core/llm/provider_discovery/__init__.py`
- Create: `core/llm/provider_discovery/types.py`
- Create: `core/llm/provider_discovery/adapters.py`
- Create: `core/llm/provider_discovery/service.py`
- Create: `tests/test_provider_discovery_adapters.py`
- Modify: `config/llm_security.py:187`
- Modify: `core/web/services/config_service.py:1854`
- Modify: `tests/test_config_panel.py:1`
- Modify: `tests/test_web_config_routes.py:2102`

**Interfaces:**
- Consumes: Provider schema, credentials, identity fingerprint, target validation, and Task 4 catalog functions.
- Produces: `ProviderDiscoveryRequest`, `DiscoveredProviderModel`, and `ProviderDiscoveryResult`.
- Produces: `get_provider_discovery_adapter(adapter_id: str) -> ProviderDiscoveryAdapter`.
- Produces: `discover_provider_models(public_config, provider_id, *, credential_override="", catalog_path=None, transport=None) -> ProviderDiscoveryResult`.
- Replaces: `_discover_openai_compatible_model_list()` as the primary discovery owner; the old function remains a v1 route wrapper only until Task 11.

- [ ] **Step 1: Write failing adapter and service tests**

Create `tests/test_provider_discovery_adapters.py` with fixtures for OpenAI-compatible, Ollama, native auth, empty responses, limits, and stale preservation:

```python
from __future__ import annotations

import json

import httpx
import pytest

from config.model_catalog import load_model_catalog_state
from core.llm.provider_discovery.service import discover_provider_models


def _config(adapter: str, *, driver: str = "openai", base_url: str = "https://models.example/v1") -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "lab": {
                    "label": "Lab",
                    "service_class": "self_hosted",
                    "vendor": "custom",
                    "driver": driver,
                    "base_url": base_url,
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_PROVIDER_LAB_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "chat_completions", "allowed": ["chat_completions"]},
                    "discovery": {"mode": "auto", "adapter": adapter, "cache_ttl_seconds": 60},
                    "models": {"pinned-gone": {"upstream_id": "pinned-gone", "label": "Pinned Gone"}},
                }
            },
            "profiles": {},
        }
    }


def test_openai_compatible_adapter_normalizes_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer secret"
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "gpt-a", "context_window": 128000}]})

    result = discover_provider_models(
        _config("openai_compatible"),
        "lab",
        catalog_path=tmp_path / "model-catalog-state.json",
        transport=httpx.MockTransport(handler),
    )
    assert result.models[0].upstream_id == "gpt-a"
    assert result.models[0].limits == {"context_window": 128000}
    state = load_model_catalog_state(tmp_path / "model-catalog-state.json")
    assert state["providers"]["lab"]["models"]["pinned-gone"]["availability"] == "missing_remote"


def test_ollama_adapter_uses_native_tags_surface(tmp_path) -> None:
    config = _config("ollama", base_url="http://127.0.0.1:11434")
    config["llm"]["providers"]["lab"].update(
        {"service_class": "local_runtime", "auth_kind": "none", "credential_ref": "none", "requires_credential": False}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "details": {"family": "qwen3"}}]})

    result = discover_provider_models(
        config,
        "lab",
        catalog_path=tmp_path / "model-catalog-state.json",
        transport=httpx.MockTransport(handler),
    )
    assert [model.upstream_id for model in result.models] == ["qwen3:8b"]


def test_empty_refresh_marks_stale_and_preserves_previous_catalog(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    path = tmp_path / "model-catalog-state.json"
    success_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "gpt-a"}]}))
    discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=success_transport)
    empty_transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": []}))
    with pytest.raises(ValueError, match="no usable models"):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=empty_transport)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["status"] == "stale"
    assert "gpt-a" in state["providers"]["lab"]["models"]


def test_discovery_rejects_oversized_response(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    payload = {"data": [{"id": "x" * 513}]}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=json.dumps(payload).encode("utf-8")))
    with pytest.raises(ValueError, match="model id exceeds 512"):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=tmp_path / "state.json", transport=transport)


def test_auth_failure_is_classified_without_losing_previous_models(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    path = tmp_path / "model-catalog-state.json"
    success = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "gpt-a"}]}))
    discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=success)
    unauthorized = httpx.MockTransport(lambda request: httpx.Response(401, json={"error": "unauthorized"}))
    with pytest.raises(httpx.HTTPStatusError):
        discover_provider_models(_config("openai_compatible"), "lab", catalog_path=path, transport=unauthorized)
    state = load_model_catalog_state(path)
    assert state["providers"]["lab"]["status"] == "auth_failed"
    assert "gpt-a" in state["providers"]["lab"]["models"]


def test_discovery_include_and_exclude_filters_are_provider_scoped(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_LAB_API_KEY", "secret")
    config = _config("openai_compatible")
    config["llm"]["providers"]["lab"]["discovery"].update(
        {"include": ["gpt-*"], "exclude": ["*-preview"]}
    )
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            json={"data": [{"id": "gpt-a"}, {"id": "gpt-a-preview"}, {"id": "claude-a"}]},
        )
    )
    result = discover_provider_models(
        config,
        "lab",
        catalog_path=tmp_path / "state.json",
        transport=transport,
    )
    assert [model.upstream_id for model in result.models] == ["gpt-a"]
```

- [ ] **Step 2: Run adapter tests and verify the missing-package failure**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_discovery_adapters.py -q
```

Expected: collection fails with `ModuleNotFoundError: No module named 'core.llm.provider_discovery'`.

- [ ] **Step 3: Define discovery contracts with secret-safe representations**

Create `core/llm/provider_discovery/types.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import httpx


@dataclass(frozen=True)
class ProviderDiscoveryRequest:
    provider_id: str
    provider: dict[str, Any]
    credential: str = field(default="", repr=False)
    timeout_seconds: float = 15.0
    transport: httpx.BaseTransport | None = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class DiscoveredProviderModel:
    upstream_id: str
    label: str
    capabilities: dict[str, Any] = field(default_factory=dict)
    limits: dict[str, Any] = field(default_factory=dict)
    metadata_source: str = "provider_endpoint"


@dataclass(frozen=True)
class ProviderDiscoveryResult:
    provider_id: str
    adapter_id: str
    attempted_endpoints: tuple[str, ...]
    discovered_at: str
    models: tuple[DiscoveredProviderModel, ...]


class ProviderDiscoveryAdapter(Protocol):
    adapter_id: str

    def discover(self, request: ProviderDiscoveryRequest) -> ProviderDiscoveryResult:
        raise NotImplementedError
```

- [ ] **Step 4: Implement bounded HTTP adapters and explicit registry**

In `core/llm/provider_discovery/adapters.py`, use one bounded JSON requester and adapter-specific endpoint/normalization functions. The requester must disable redirects and enforce body/model/ID limits before catalog writes:

```python
MAX_DISCOVERY_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_DISCOVERED_MODELS = 5000
MAX_UPSTREAM_ID_LENGTH = 512


def _bounded_json_get(
    url: str,
    *,
    headers: dict[str, str],
    params: dict[str, str] | None,
    request: ProviderDiscoveryRequest,
) -> Any:
    timeout = min(max(float(request.timeout_seconds), 0.5), 15.0)
    with httpx.Client(
        timeout=timeout,
        headers=headers,
        follow_redirects=False,
        transport=request.transport,
    ) as client:
        with client.stream("GET", url, params=params) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > MAX_DISCOVERY_RESPONSE_BYTES:
                    raise ValueError("model discovery response exceeds 2 MiB")
                chunks.append(chunk)
    body = b"".join(chunks)
    return json.loads(body)


def _validate_models(models: list[DiscoveredProviderModel]) -> tuple[DiscoveredProviderModel, ...]:
    if len(models) > MAX_DISCOVERED_MODELS:
        raise ValueError("model discovery returned more than 5000 models")
    seen: set[str] = set()
    normalized: list[DiscoveredProviderModel] = []
    for model in models:
        if len(model.upstream_id) > MAX_UPSTREAM_ID_LENGTH:
            raise ValueError("model id exceeds 512 Unicode code points")
        if model.upstream_id and model.upstream_id not in seen:
            seen.add(model.upstream_id)
            normalized.append(model)
    return tuple(normalized)
```

Implement adapter IDs and endpoint rules exactly as follows:

```python
ADAPTERS: dict[str, ProviderDiscoveryAdapter] = {
    "openai": OpenAICompatibleDiscoveryAdapter("openai"),
    "openai_compatible": OpenAICompatibleDiscoveryAdapter("openai_compatible"),
    "ollama": OllamaDiscoveryAdapter(),
    "llamacpp": OpenAICompatibleDiscoveryAdapter("llamacpp"),
    "lmstudio": OpenAICompatibleDiscoveryAdapter("lmstudio"),
    "vllm": OpenAICompatibleDiscoveryAdapter("vllm"),
    "sglang": OpenAICompatibleDiscoveryAdapter("sglang"),
    "anthropic": AnthropicDiscoveryAdapter(),
    "gemini": GeminiDiscoveryAdapter(),
    "manual": ManualDiscoveryAdapter(),
}
```

- OpenAI-compatible adapters use `<base>/models` when base ends in `/v1`, otherwise try `<base>/v1/models` then `<base>/models`, in that order.
- Ollama uses `<service-root>/api/tags` and reads `models[].name`.
- Anthropic uses `<service-root>/v1/models`, `x-api-key`, and `anthropic-version: 2023-06-01`.
- Gemini uses `<service-root>/v1beta/models` with the credential in `params={"key": credential}`; safe endpoint summaries omit query parameters.
- Manual performs no HTTP call and returns a result with an empty model tuple; the service returns this as `manual` rather than treating it as a failed refresh.

- [ ] **Step 5: Implement discovery orchestration and catalog reconciliation**

Create `core/llm/provider_discovery/service.py` with this order:

```python
def discover_provider_models(
    public_config: dict[str, Any],
    provider_id: str,
    *,
    credential_override: str = "",
    catalog_path: Path | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ProviderDiscoveryResult:
    llm = public_config.get("llm", {})
    provider = llm.get("providers", {}).get(provider_id)
    if int(llm.get("schema_version") or 1) != 2 or not isinstance(provider, dict):
        raise ValueError(f"unknown schema v2 provider: {provider_id}")
    validate_llm_provider_target(provider, context="llm.provider.discovery", resolve_dns=True)
    resolution = resolve_credential_ref(str(provider.get("credential_ref") or "none"))
    credential = str(credential_override or resolution.secret)
    if provider.get("requires_credential", True) and not credential:
        raise ValueError("provider credential is missing")
    adapter_id = str(provider.get("discovery", {}).get("adapter") or "manual")
    adapter = get_provider_discovery_adapter(adapter_id)
    request = ProviderDiscoveryRequest(
        provider_id=provider_id,
        provider=copy.deepcopy(provider),
        credential=credential,
        timeout_seconds=15.0,
        transport=transport,
    )
    path = catalog_path or resolve_model_catalog_state_path()
    state = load_model_catalog_state(path)
    attempted_at = utcnow_iso()
    try:
        result = adapter.discover(request)
        if adapter_id == "manual":
            return result
        if not result.models:
            raise ValueError("model discovery returned no usable models")
        updated = record_discovery_success(
            state,
            provider_id=provider_id,
            provider_fingerprint=provider_identity_fingerprint(
                str(provider.get("base_url") or ""),
                str(provider.get("credential_ref") or "none"),
                auth_kind=str(provider.get("auth_kind") or "api_key"),
            ),
            discovered_at=result.discovered_at,
            observed=[dataclasses.asdict(model) for model in result.models],
            pinned=copy.deepcopy(provider.get("models", {})),
        )
        save_model_catalog_state(updated, path)
        return result
    except Exception as exc:
        status = "auth_failed" if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403} else ""
        failed = record_discovery_failure(
            state,
            provider_id=provider_id,
            attempted_at=attempted_at,
            error_type=type(exc).__name__,
            status=status,
        )
        save_model_catalog_state(failed, path)
        raise
```

Do not store `credential_override`, response bodies, authorization headers, or full exception text in catalog state.

Before success reconciliation, apply `discovery.include` and `discovery.exclude` with Python `fnmatch.fnmatchcase()` against exact `upstream_id`. An empty include list means all IDs; exclude always wins. Preserve adapter order after filtering, and treat a non-manual result filtered to zero as the same explicit empty-discovery failure that preserves stale catalog state.

- [ ] **Step 6: Expand target validation for schema v2 classifications and credential references**

In `config/llm_security.py`, derive policy from `service_class` when it exists:

```python
def _provider_security_kind(provider: Any) -> str:
    service_class = str(_read_field(provider, "service_class", "") or "").strip().lower()
    if not service_class:
        return str(_read_field(provider, "kind", "") or "").strip().lower()
    if service_class == "local_runtime":
        return "local"
    if service_class in {"relay", "aggregator", "self_hosted"}:
        return "relay"
    return str(_read_field(provider, "vendor", "custom") or "custom").strip().lower()
```

Use this helper in `validate_llm_provider_target()` and `coerce_llm_runtime_probe_timeout()`. For schema v2:

- reject public Provider objects containing `api_key` or `api_key_env`;
- canonicalize `credential_ref` and validate the extracted `env:` name with `validate_llm_api_key_env()`;
- reject more than 16 `extra_headers`, invalid header-token names, names longer than 64, values longer than 512, and credential-bearing names such as `authorization`, `proxy-authorization`, `x-api-key`, or `api-key`;
- allow localhost/private LAN only for `service_class=local_runtime`;
- allow arbitrary public HTTPS hosts for `relay`, `aggregator`, and `self_hosted` after DNS resolution proves all returned addresses public;
- keep official vendor host allowlists;
- reject query, fragment, userinfo, redirects, link-local, metadata, loopback, and private addresses for remote classes.

Add direct tests in `tests/test_config_panel.py` for local runtime LAN allowed, self-hosted LAN rejected, public relay allowed, v2 inline secret rejected, invalid credential env prefix rejected, sensitive custom header rejected, and header count/name/value limits.

- [ ] **Step 7: Restrict old config discovery to the v1 compatibility route**

In `core/web/services/config_service.py`, make `discover_config_models()` branch on `llm.schema_version`:

- v2 requires `provider_id` and delegates to `discover_provider_models()`.
- v1 retains `_discover_openai_compatible_model_list()` unchanged for read-only compatibility.
- no config load, workspace read, or `build_effective_config()` call invokes either branch.

Update the existing v1 route tests to assert the compatibility branch still works and add an assertion that `get_config_workspace()` performs zero `httpx.Client.get` calls.

- [ ] **Step 8: Run discovery and security regression tests**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_discovery_adapters.py tests\test_config_panel.py tests\test_web_config_routes.py -k "discover or security or provider_target or workspace" -q
```

Expected: adapters, stale preservation, SSRF/localhost rules, and the zero-network workspace test pass.

- [ ] **Step 9: Commit Task 5**

```powershell
git add -- config/llm_security.py core/llm/provider_discovery/__init__.py core/llm/provider_discovery/types.py core/llm/provider_discovery/adapters.py core/llm/provider_discovery/service.py core/web/services/config_service.py tests/test_provider_discovery_adapters.py tests/test_config_panel.py tests/test_web_config_routes.py
git commit -m "feat(llm): discover provider-scoped model catalogs"
```

---

### Task 6: Explicit schema v2 protocol resolution and canonical runtime refs

**Files:**
- Modify: `core/llm/protocol_resolver.py:23`
- Modify: `core/llm/client.py:1217`
- Modify: `core/llm/discovery.py:170`
- Modify: `core/llm/agent_runtime.py:167`
- Modify: `tests/test_llm_protocol_resolver.py:12`
- Modify: `tests/test_agent_llm_runtime.py:1`

**Interfaces:**
- Consumes: projected `ProviderConfig.protocols`, `ProviderConfig.driver`, `ProviderConfig.legacy_inference_allowed`, and model entries containing `model_ref`/`wire_protocol`.
- Produces: `ProtocolResolutionError(code: str, message: str, *, provider_id: str, model_ref: str)`; strict unknown routes use code `protocol_unknown`.
- Preserves: all existing v1 inference behavior and existing `ResolvedProtocolRoute` fields.
- Emits: bounded `llm.protocol.resolved` and `llm.protocol.blocked` events from the runtime owner.

- [ ] **Step 1: Add failing v2 protocol-priority and fail-closed tests**

Append to `tests/test_llm_protocol_resolver.py`:

```python
def _v2_provider(**overrides):
    payload = {
        "provider_id": "relay",
        "kind": "openai",
        "driver": "openai",
        "service_class": "relay",
        "base_url": "https://relay.example/v1",
        "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
        "legacy_inference_allowed": False,
    }
    payload.update(overrides)
    return ProviderConfig(**payload)


def test_v2_model_wire_override_beats_provider_default() -> None:
    provider = _v2_provider()
    profile = LLMProfile(profile_id="primary", provider_id="relay", model="gpt-a")
    route = resolve_model_protocol(
        profile,
        provider,
        model_entry={"model_ref": "relay/gpt-a", "model": "gpt-a", "wire_protocol": "chat_completions"},
    )
    assert route.wire_protocol == WireProtocol.CHAT_COMPLETIONS
    assert route.wire_source == "explicit_model_wire"


def test_v2_provider_default_beats_driver_default() -> None:
    provider = _v2_provider(driver="anthropic")
    profile = LLMProfile(profile_id="primary", provider_id="relay", model="gpt-a")
    route = resolve_model_protocol(profile, provider, model_entry={"model_ref": "relay/gpt-a", "model": "gpt-a"})
    assert route.wire_protocol == WireProtocol.RESPONSES
    assert route.wire_source == "provider_default"


def test_v2_unknown_protocol_fails_closed_without_endpoint_or_model_heuristics() -> None:
    provider = _v2_provider(driver="custom", protocols={"default": "", "allowed": []})
    profile = LLMProfile(profile_id="primary", provider_id="relay", model="qwen-local")
    with pytest.raises(ProtocolResolutionError) as error:
        resolve_model_protocol(profile, provider, model_entry={"model_ref": "relay/qwen-local", "model": "qwen-local"})
    assert error.value.code == "protocol_unknown"


def test_v2_relative_protocol_route_builds_final_runtime_endpoint() -> None:
    provider = _v2_provider(
        protocols={
            "default": "responses",
            "allowed": ["responses"],
            "routes": {"responses": "custom/responses"},
        }
    )
    profile = LLMProfile(profile_id="primary", provider_id="relay", model="gpt-a")
    route = resolve_model_protocol(profile, provider, model_entry={"model_ref": "relay/gpt-a", "model": "gpt-a"})
    assert route.configured_endpoint == "https://relay.example/v1"
    assert route.runtime_endpoint == "https://relay.example/v1/custom/responses"


def test_v2_protocol_route_rejects_absolute_or_query_override() -> None:
    provider = _v2_provider(
        protocols={
            "default": "responses",
            "allowed": ["responses"],
            "routes": {"responses": "https://evil.example/responses?key=secret"},
        }
    )
    profile = LLMProfile(profile_id="primary", provider_id="relay", model="gpt-a")
    with pytest.raises(ProtocolResolutionError) as error:
        resolve_model_protocol(profile, provider, model_entry={"model_ref": "relay/gpt-a", "model": "gpt-a"})
    assert error.value.code == "protocol_mismatch"


def test_v1_keeps_diagnostic_inference() -> None:
    provider = ProviderConfig(provider_id="legacy", kind="llamacpp", base_url="http://127.0.0.1:8080/v1")
    profile = LLMProfile(profile_id="primary", provider_id="legacy", model="qwen-local", thinking_type="adaptive")
    route = resolve_model_protocol(profile, provider)
    assert route.source == "inferred"
    assert "model_protocol.missing_explicit_protocol" in route.warnings
```

- [ ] **Step 2: Run resolver tests and verify the new precedence fails**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_protocol_resolver.py -q
```

Expected: new tests fail because Provider default/driver layers and `ProtocolResolutionError` are absent.

- [ ] **Step 3: Add a typed fail-closed error and explicit resolver layers**

In `core/llm/protocol_resolver.py`, add:

```python
class ProtocolResolutionError(ValueError):
    def __init__(self, code: str, message: str, *, provider_id: str, model_ref: str) -> None:
        super().__init__(message)
        self.code = code
        self.provider_id = provider_id
        self.model_ref = model_ref


def _provider_default_wire(provider: ProviderConfig) -> WireProtocol | None:
    protocols = getattr(provider, "protocols", None)
    raw = str(getattr(protocols, "default", "") or "")
    return _normalize_wire_protocol(raw) if raw else None


def _driver_default_wire(provider: ProviderConfig) -> WireProtocol | None:
    driver = _read_optional_string(provider, "driver").lower()
    return {
        "openai": WireProtocol.CHAT_COMPLETIONS,
        "anthropic": WireProtocol.ANTHROPIC_MESSAGES,
        "gemini": WireProtocol.GEMINI_GENERATE_CONTENT,
    }.get(driver)
```

Replace `_resolve_wire_protocol()` with the precedence below. Validate a model override against `provider.protocols.allowed` before returning it:

```python
    explicit_wire = _wire_protocol_from_model_entry(model_entry)
    allowed = tuple(getattr(getattr(provider, "protocols", None), "allowed", ()) or ())
    if explicit_wire is not None:
        if allowed and explicit_wire.value not in allowed:
            raise ProtocolResolutionError(
                "protocol_mismatch",
                "model wire protocol is not allowed by provider",
                provider_id=_read_optional_string(provider, "provider_id"),
                model_ref=_read_optional_string(model_entry, "model_ref"),
            )
        return explicit_wire, "explicit_model_wire", "model"
    provider_default = _provider_default_wire(provider)
    if provider_default is not None:
        return provider_default, "provider_default", "provider"
    driver_default = _driver_default_wire(provider)
    if driver_default is not None:
        return driver_default, "driver_default", "driver"
    if not bool(getattr(provider, "legacy_inference_allowed", True)):
        raise ProtocolResolutionError(
            "protocol_unknown",
            "schema v2 requires an explicit model, provider, or driver wire protocol",
            provider_id=_read_optional_string(provider, "provider_id"),
            model_ref=_read_optional_string(model_entry, "model_ref"),
        )
```

After this block, retain the existing provider-model/API/kind/profile/endpoint heuristics only for legacy providers and add `wire_protocol.legacy_inference` to warnings whenever one wins.

Replace `_runtime_endpoint()` so v2 protocol routes are relative to the normalized service root:

```python
def _runtime_endpoint(provider: ProviderConfig, configured_endpoint: str, wire_protocol: WireProtocol) -> str:
    endpoint = str(configured_endpoint or "").strip().rstrip("/")
    if bool(getattr(provider, "legacy_inference_allowed", True)):
        return _legacy_runtime_endpoint(provider, endpoint, wire_protocol)
    routes = getattr(getattr(provider, "protocols", None), "routes", {}) or {}
    relative = str(routes.get(wire_protocol.value) or "").strip()
    if not relative:
        relative = {
            WireProtocol.CHAT_COMPLETIONS: "chat/completions",
            WireProtocol.RESPONSES: "responses",
            WireProtocol.ANTHROPIC_MESSAGES: "v1/messages",
            WireProtocol.GEMINI_GENERATE_CONTENT: "v1beta/models:generateContent",
        }[wire_protocol]
    parsed = urlparse(relative)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or relative.startswith(("/", "\\")):
        raise ProtocolResolutionError(
            "protocol_mismatch",
            "provider protocol route must be a relative path without query or fragment",
            provider_id=_read_optional_string(provider, "provider_id"),
            model_ref="",
        )
    return f"{endpoint}/{relative.lstrip('/')}"
```

Rename the current function body to `_legacy_runtime_endpoint()` unchanged. A Gemini adapter may replace the `:generateContent` model placeholder when that wire adapter is implemented; this plan must not enable an uninstalled wire adapter.

- [ ] **Step 4: Make runtime model selection canonical-ref aware**

In `core/llm/agent_runtime.py::config_for_agent_llm_model()`, resolve `LLMConfig.model_aliases` before looking up `model_library`:

```python
    requested_model_ref = str(model_id or "").strip()
    normalized_model_id = runtime_config.llm.resolve_model_ref(requested_model_ref)
```

Return both requested and canonical refs in `ResolvedAgentLlm.log_fields()` as `requestedModelRef` and `modelRef`. New writes use only the canonical value; aliases are read compatibility only.

In `core/llm/discovery.py`, expose `model_ref`, `provider_id`, `upstream_id`, capability provenance, and catalog availability in `provider_details`. Do not load the catalog during config normalization; load it when resolving the selected runtime model.

Replace the current boolean-only capability layering in `discover_model()` with `resolve_model_capabilities()`: pinned model declarations are `operator_override`, current runtime probe catalog records are `runtime_probe`, discovery metadata is `provider_endpoint`, matching `LLM_MODEL_PRESETS` capability metadata is `curated_snapshot`, and `capabilities_for_adapter()` supplies `driver_default`. Convert the resolved tri-state values back to `LLMCapabilities` booleans conservatively (`supported=True`; `unsupported=False`; `unknown=False`) while retaining the complete provenance map in `provider_details["capabilities"]`.

- [ ] **Step 5: Emit bounded protocol resolution/blocked evidence at the runtime owner**

Wrap `resolve_model_protocol()` in `LLMClient.__init__`:

```python
        try:
            self.protocol_route = resolve_model_protocol(
                self.profile,
                self.provider,
                model_entry=model_entry if isinstance(model_entry, dict) else None,
            )
        except ProtocolResolutionError as exc:
            _record_llm_scene_event(
                "llm.protocol.blocked",
                outcome="blocked",
                fields={"providerId": exc.provider_id, "modelRef": exc.model_ref, "errorType": exc.code},
            )
            raise LLMError(
                "provider_protocol_error",
                str(exc),
                retryable=False,
                provider=self.provider.provider_id,
                model=self.profile.model,
            ) from exc
        _record_llm_scene_event(
            "llm.protocol.resolved",
            outcome="succeeded",
            fields=self.protocol_route.log_summary(),
        )
```

Call the existing `_record_llm_scene_event()` owner so its current field-count/text-length bounds remain authoritative; add negative test assertions that the emitted event contains no prompts, headers, credentials, catalog payloads, or full artifact paths.

- [ ] **Step 6: Run resolver, runtime, payload, and client tests**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_protocol_resolver.py tests\test_agent_llm_runtime.py tests\test_llm_payload_builder.py tests\test_llm_client.py -q
```

Expected: all v1 routes remain green, v2 precedence is explicit, and unknown v2 protocols raise a non-retryable provider protocol error before sending a request.

- [ ] **Step 7: Commit Task 6**

```powershell
git add -- core/llm/protocol_resolver.py core/llm/client.py core/llm/discovery.py core/llm/agent_runtime.py tests/test_llm_protocol_resolver.py tests/test_agent_llm_runtime.py
git commit -m "feat(llm): resolve schema v2 protocols explicitly"
```

---

### Task 7: Provider draft APIs, discovery orchestration, and bounded config events

**Files:**
- Create: `core/web/services/provider_config_service.py`
- Create: `tests/test_provider_config_service.py`
- Modify: `core/web/services/config_service.py:1190`
- Modify: `core/web/routes/config.py:46`
- Modify: `tests/test_web_config_routes.py:86`

**Interfaces:**
- Consumes: Provider registry, catalog discovery, reference scan, existing draft hash/secret-token helpers, and `_build_workspace()`.
- Produces draft services: `suggest_draft_provider_id`, `draft_add_provider`, `draft_update_provider`, `draft_delete_provider`, `draft_pin_provider_model`, `draft_unpin_provider_model`, `discover_draft_provider`.
- Produces HTTP routes under `/api/config/draft/providers`.
- Returns stable provider IDs, catalog summaries, impacted refs, and credential state; never returns secrets.

- [ ] **Step 1: Write failing service and route tests**

Create `tests/test_provider_config_service.py` with direct service coverage, then add route assertions to `tests/test_web_config_routes.py`:

```python
from __future__ import annotations

import json

import pytest

from config.public_config import public_config_hash
from core.web.services import config_service, provider_config_service


def _provider(credential_ref: str) -> dict:
    return {
        "label": "Relay",
        "service_class": "relay",
        "vendor": "multi_model",
        "driver": "openai",
        "base_url": "https://relay.example/v1",
        "auth_kind": "api_key",
        "credential_ref": credential_ref,
        "requires_credential": True,
        "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
        "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
        "models": {},
    }


def _v2_config() -> dict:
    return {"llm": {"schema_version": 2, "providers": {}, "profiles": {}, "model_aliases": {}}}


def _v2_with_provider() -> dict:
    config = _v2_config()
    config["llm"]["providers"]["relay_a"] = _provider("env:VIBELUTION_LLM_PROVIDER_RELAY_A_API_KEY")
    return config


def _v2_with_provider_and_model() -> dict:
    config = _v2_with_provider()
    config["llm"]["providers"]["relay_a"]["models"]["gpt-a"] = {
        "upstream_id": "gpt-a",
        "label": "GPT A",
        "enabled": True,
    }
    return config


def test_provider_draft_add_returns_stable_provider_without_secret(monkeypatch) -> None:
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: _v2_config())
    workspace = provider_config_service.draft_add_provider(
        _v2_config(),
        draft_meta={},
        base_hash=public_config_hash(_v2_config()),
        provider_id="relay_b",
        provider=_provider("env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY"),
        credential_value="secret-value",
    )
    assert workspace["providerOptions"][-1]["provider_id"] == "relay_b"
    assert "secret-value" not in json.dumps(workspace)
    assert workspace["draftMeta"]["pending_api_keys"]


def test_provider_route_update_requires_preview_token(monkeypatch) -> None:
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: _v2_with_provider())
    with pytest.raises(ValueError, match="route replacement preview"):
        provider_config_service.draft_update_provider(
            _v2_with_provider(),
            draft_meta={},
            base_hash=public_config_hash(_v2_with_provider()),
            provider_id="relay_a",
            provider=_provider("env:VIBELUTION_LLM_PROVIDER_OTHER_ACCOUNT_API_KEY"),
            route_preview_token="",
        )


def test_provider_delete_blocks_pinned_models_and_live_refs(monkeypatch) -> None:
    config = _v2_with_provider_and_model()
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: config)
    with pytest.raises(ValueError, match="pinned models"):
        provider_config_service.draft_delete_provider(
            config,
            draft_meta={},
            base_hash=public_config_hash(config),
            provider_id="relay_a",
        )


def test_profile_binding_to_observed_model_pins_only_that_model(monkeypatch) -> None:
    config = _v2_with_provider()
    config["llm"]["profiles"]["primary"] = {"model_ref": "relay_a/observed-a", "overrides": {}}
    monkeypatch.setattr(config_service, "load_model_catalog_state", lambda: {
        "schemaVersion": 2,
        "providers": {
            "relay_a": {
                "models": {
                    "observed-a": {"upstreamId": "observed-a", "label": "Observed A", "availability": "observed"},
                    "observed-b": {"upstreamId": "observed-b", "label": "Observed B", "availability": "observed"},
                }
            }
        },
    })
    materialized = config_service.materialize_observed_binding_pins(config)
    models = materialized["llm"]["providers"]["relay_a"]["models"]
    assert set(models) == {"observed-a"}
    assert models["observed-a"]["upstream_id"] == "observed-a"
```

Add this route test to `tests/test_web_config_routes.py`, using that module's existing global `client`:

```python
def test_provider_routes_never_return_submitted_secret(monkeypatch) -> None:
    submitted = {"llm": {"schema_version": 2, "providers": {}, "profiles": {}, "model_aliases": {}}}
    provider = {
        "label": "Relay B",
        "service_class": "relay",
        "vendor": "multi_model",
        "driver": "openai",
        "base_url": "https://relay.example/v1",
        "auth_kind": "api_key",
        "credential_ref": "env:VIBELUTION_LLM_PROVIDER_RELAY_B_API_KEY",
        "requires_credential": True,
        "protocols": {"default": "responses", "allowed": ["responses"]},
        "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
        "models": {},
    }
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: copy.deepcopy(submitted))
    response = client.post(
        "/api/config/draft/providers",
        json={
            "publicConfig": submitted,
            "baseHash": public_config_hash(submitted),
            "providerId": "relay_b",
            "provider": provider,
            "credentialValue": "secret-value",
        },
    )
    assert response.status_code == 200
    assert "secret-value" not in response.text
```

Add `provider_config_service` to that test module's existing `core.web.services` import list.

- [ ] **Step 2: Run the focused tests and verify service/route failures**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_config_service.py tests\test_web_config_routes.py -k "provider" -q
```

Expected: missing service module and missing routes fail.

- [ ] **Step 3: Implement Provider draft orchestration in a narrow service**

Create `core/web/services/provider_config_service.py`. Each public function must:

1. load saved config only for base-hash comparison;
2. normalize a deep-copied submitted draft;
3. call Task 3 pure mutations;
4. register a pending secret token against the environment variable derived from `credential_ref`;
5. validate with `build_effective_config()`;
6. return `_build_workspace()` without saving.

The add function signature and result flow are:

```python
def draft_add_provider(
    public_config: dict[str, Any],
    *,
    draft_meta: dict[str, Any] | None,
    base_hash: str,
    provider_id: str,
    provider: dict[str, Any],
    credential_value: str = "",
) -> dict[str, Any]:
    saved = load_public_config()
    _assert_base_hash_matches(base_hash, saved, _resolve_workspace_language(saved))
    current = copy.deepcopy(public_config)
    updated = add_llm_provider(current, provider_id, provider)
    meta = _normalize_draft_meta(draft_meta)
    credential_ref = canonicalize_credential_ref(str(provider.get("credential_ref") or "none"))
    if credential_value and credential_ref.startswith("env:"):
        meta = _with_pending_api_key(meta, credential_ref.removeprefix("env:"), credential_value)
    build_effective_config(updated)
    _record_provider_event(
        "config.provider.created",
        provider_id=provider_id,
        outcome="drafted",
        fields={"serviceClass": str(provider.get("service_class") or ""), "modelCount": 0},
    )
    return _build_workspace(updated, draft_meta=meta, base_hash=base_hash)
```

`draft_update_provider()` must call `preview_provider_route_replacement()`. If `routeChanged` is true, require an HMAC-backed, five-minute route preview token generated over `baseHash + providerId + oldFingerprint + newFingerprint`; never accept a boolean acknowledgement.

Implement preview tokens as process-local, single-use capabilities so no signing key enters config:

```python
_ROUTE_PREVIEW_SECRET = secrets.token_bytes(32)
_ROUTE_PREVIEW_TTL_SECONDS = 300.0
_ROUTE_PREVIEW_EXPIRY: dict[str, float] = {}


def _compute_route_preview_token(*, base_hash: str, provider_id: str, old_fingerprint: str, new_fingerprint: str) -> str:
    message = "\0".join((base_hash, provider_id, old_fingerprint, new_fingerprint)).encode("utf-8")
    return hmac.new(_ROUTE_PREVIEW_SECRET, message, hashlib.sha256).hexdigest()


def _issue_route_preview_token(*, base_hash: str, provider_id: str, old_fingerprint: str, new_fingerprint: str) -> str:
    digest = _compute_route_preview_token(
        base_hash=base_hash,
        provider_id=provider_id,
        old_fingerprint=old_fingerprint,
        new_fingerprint=new_fingerprint,
    )
    _ROUTE_PREVIEW_EXPIRY[digest] = time.monotonic() + _ROUTE_PREVIEW_TTL_SECONDS
    return digest


def _consume_route_preview_token(token: str, *, expected: str) -> None:
    expires_at = _ROUTE_PREVIEW_EXPIRY.pop(str(token or ""), 0.0)
    if not hmac.compare_digest(str(token or ""), expected) or expires_at < time.monotonic():
        raise ValueError("route replacement preview is required or expired")
```

The preview endpoint returns the token but not fingerprints; the update service recomputes fingerprints from the current saved/draft routes, recreates the expected HMAC without registering a second expiry, and consumes the submitted token once.

`draft_unpin_provider_model()` and `draft_delete_provider()` must call `scan_model_references()` and return `ModelReferenceConflictError` for live refs. Provider deletion additionally requires zero pinned models.

- [ ] **Step 4: Pin an observed model only when a same-config binding actually uses it**

Add `materialize_observed_binding_pins(public_config)` to `config_service.py`. It scans only model-ref fields owned by the submitted operator config (`llm.profiles.*.model_ref`, `tools.image2.default_model_ref`, and `git.commit_message_model_ref`). For each canonical ref absent from pinned Provider models but present as `availability=observed` in the catalog, it calls `pin_llm_model()` with the catalog's exact upstream ID and label. It does not pin every observed model, and external Agent/Team/ChatRoom selectors continue listing pinned models only.

Call this helper inside `apply_config_workspace()` after stale-hash/patch merge and before `validate_llm_public_config()`. Because the binding and pin are in the same submitted TOML transaction, a failed validation/save writes neither. Add `observedPinCount` and canonical refs, bounded to 50 items, to `config.workspace.applied`.

- [ ] **Step 5: Add stable Provider/catalog data to the config workspace**

Add this helper beside `_build_workspace()`:

```python
def _provider_workspace_fields(public_config: dict[str, Any]) -> dict[str, Any]:
    llm = public_config.get("llm", {}) if isinstance(public_config, dict) else {}
    return {
        "schemaVersion": int(llm.get("schema_version") or 1) if isinstance(llm, dict) else 1,
        "providerOptions": list_llm_provider_options(public_config),
        "modelCatalog": summarize_model_catalog(load_model_catalog_state(), public_config=public_config),
    }
```

Spread `_provider_workspace_fields(public_config)` into the single dictionary returned by `_build_workspace()` immediately before `modelPresetOptions`; do not create a second workspace response path.

`summarize_model_catalog()` must include provider/model statuses, counts, last attempt/success timestamps, and bounded errors only. It computes and exposes `refreshDue` per Provider from its configured `cache_ttl_seconds`. Before returning, run explicit protocol validation for each pinned model: a disallowed override yields Provider `protocol_mismatch`; an unresolved strict route yields model `protocol_unknown` and Provider `blocked`. These are derived diagnostics, not catalog writes. The projection must omit fingerprints, credential references, full metadata, and response data.

- [ ] **Step 6: Add explicit request models and routes**

In `core/web/routes/config.py`, add typed payloads:

```python
class ConfigProviderDraftPayload(ConfigDraftPayload):
    providerId: str
    provider: dict[str, Any] = Field(default_factory=dict)
    credentialValue: str = ""
    routePreviewToken: str = ""


class ConfigProviderModelPayload(ConfigDraftPayload):
    providerId: str
    upstreamId: str
    modelKey: str = ""
    label: str = ""
    overrides: dict[str, Any] = Field(default_factory=dict)


class ConfigProviderDiscoveryPayload(ConfigDraftPayload):
    providerId: str
    credentialValue: str = ""


class ConfigProviderSuggestionPayload(ConfigDraftPayload):
    provider: dict[str, Any] = Field(default_factory=dict)
```

Add these routes with `_raise_config_http_error()` mapping `ModelReferenceConflictError` and stale base hashes to HTTP 409:

```text
POST   /config/draft/providers/id-suggestion
POST   /config/draft/providers
PUT    /config/draft/providers/{provider_id}
DELETE /config/draft/providers/{provider_id}
POST   /config/draft/providers/{provider_id}/route-preview
POST   /config/draft/providers/{provider_id}/discover
POST   /config/draft/providers/{provider_id}/models
DELETE /config/draft/providers/{provider_id}/models/{model_key}
```

Register the static `id-suggestion` route before any `/{provider_id}` route. It calls `suggest_provider_id(payload.provider, current_provider_ids)` and returns only `{suggestedProviderId}`. The wizard may accept or edit this suggestion before first save; later edits never rename an existing Provider key.

- [ ] **Step 7: Assert bounded runtime events**

Tests must inspect runtime-scene calls for:

```text
config.provider.created
config.provider.updated
config.provider.route_replacement_previewed
config.provider.discovery_succeeded
config.provider.discovery_failed
config.model.pinned
config.model.unpinned
```

Allowed fields are stable IDs, category/status, counts, elapsed milliseconds, error type, and a bounded repair summary. Add negative assertions for `credentialValue`, `Authorization`, `api_key`, response bodies, and local `artifact_path`.

- [ ] **Step 8: Run service, route, config apply, and redaction tests**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_config_service.py tests\test_web_config_routes.py tests\test_config_redaction.py tests\test_config_patch_apply.py -q
```

Expected: all tests pass; Provider operations remain draft-only until the existing `/config/apply` transaction runs.

- [ ] **Step 9: Commit Task 7**

```powershell
git add -- core/web/services/provider_config_service.py core/web/services/config_service.py core/web/routes/config.py tests/test_provider_config_service.py tests/test_web_config_routes.py
git commit -m "feat(web): add provider-scoped config APIs"
```

---

### Task 8: Deterministic v1 migration preview, reference rewrite manifest, apply, and rollback

**Files:**
- Create: `config/model_config_migration.py`
- Create: `tests/test_model_config_migration.py`
- Modify: `core/web/services/model_reference_service.py:422`
- Modify: `core/web/services/provider_config_service.py:1`
- Modify: `core/web/services/config_service.py:1190`
- Modify: `core/web/routes/config.py:46`
- Modify: `tests/test_model_reference_service.py:86`
- Modify: `tests/test_web_config_routes.py:2493`

**Interfaces:**
- Consumes: v1 effective credential sources, Task 1 identity, Task 3 registry validation, existing base hash/save lock, and live reference scanning.
- Produces: `preview_v1_to_v2(public_config, *, project_root) -> ModelConfigMigrationPreview`.
- Produces: `apply_v1_to_v2(preview_id, *, expected_base_hash, config_path, project_root) -> dict[str, Any]`.
- Produces: `rollback_v1_to_v2(migration_id, *, config_path, project_root) -> dict[str, Any]`.
- Produces: `build_model_reference_rewrite_plan(mapping: dict[str, str], *, public_config: dict[str, Any], project_root: Path | str) -> ModelReferenceRewritePlan`.
- Produces: `apply_model_reference_rewrite_plan(plan: ModelReferenceRewritePlan) -> dict[str, Any]`.
- Produces: `rewrite_model_reference_payload(owner_kind: str, payload: dict[str, Any], mapping: dict[str, str]) -> tuple[dict[str, Any], tuple[dict[str, Any], ...]]`.
- Produces: `scan_model_alias_usage(public_config, *, project_root) -> dict[str, Any]` with a zero-usage exit signal.

- [ ] **Step 1: Write failing preview, conflict, alias, and rollback tests**

Create `tests/test_model_config_migration.py` with exact failure/success behaviors:

```python
from __future__ import annotations

import json

import pytest

from config.model_config_migration import apply_v1_to_v2, preview_v1_to_v2
from config.public_config import public_config_hash
from config.toml_writer import dumps_public_config
from core.web.services.model_reference_service import rewrite_model_reference_payload


def legacy_config_with_models(*rows: tuple[str, str, str, str]) -> dict:
    model_library: dict[str, dict] = {}
    profiles: dict[str, dict] = {}
    for index, (model_id, base_url, api_key_env, upstream_id) in enumerate(rows):
        model_library[model_id] = {
            "provider": {
                "kind": "relay" if model_id.startswith("relay") else "openai_compatible",
                "base_url": base_url,
                "api_key_env": api_key_env,
                "compat_mode": "openai",
                "requires_api_key": bool(api_key_env),
            },
            "model": upstream_id,
            "label": upstream_id,
            "transport": "chat_completions",
            "contract": "tool_chat",
            "timeout": 60,
        }
        profiles["primary" if index == 0 else f"profile_{index}"] = {"model_ref": model_id}
    first_model_id = rows[0][0] if rows else ""
    return {
        "llm": {"model_library": model_library, "profiles": profiles},
        "tools": {"image2": {"default_model_ref": first_model_id}},
        "git": {"commit_message_model_ref": first_model_id},
    }


def write_migration_fixture(tmp_path) -> tuple:
    project_root = tmp_path / "repo"
    project_root.mkdir()
    config_path = tmp_path / "operator" / "config.toml"
    config_path.parent.mkdir()
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "VIBELUTION_LLM_MODEL_RELAY_A_API_KEY", "gpt-a"),
    )
    config_path.write_text(dumps_public_config(legacy), encoding="utf-8")
    return config_path, project_root, legacy


def test_preview_groups_same_endpoint_and_credential_without_writing(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[llm]\n", encoding="utf-8")
    legacy = legacy_config_with_models(
        ("relay_text", "https://relay.example/v1", "RELAY_KEY", "gpt-a"),
        ("relay_image", "https://relay.example/v1", "RELAY_KEY", "image-a"),
    )
    before = config_path.read_text(encoding="utf-8")
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert len(preview.providers) == 1
    assert set(preview.model_ref_map) == {"relay_text", "relay_image"}
    assert config_path.read_text(encoding="utf-8") == before


def test_preview_splits_same_endpoint_with_different_credentials(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1", "RELAY_A_KEY", "gpt-a"),
        ("relay_b", "https://relay.example/v1", "RELAY_B_KEY", "gpt-a"),
    )
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert len(preview.providers) == 2


def test_missing_credential_source_requires_review(tmp_path) -> None:
    legacy = legacy_config_with_models(("relay_a", "https://relay.example/v1", "", "gpt-a"))
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.status == "NEEDS_REVIEW"
    assert preview.conflicts[0]["code"] == "credential_source_missing"


def test_preview_strips_only_adapter_confirmed_protocol_route(tmp_path) -> None:
    legacy = legacy_config_with_models(
        ("relay_a", "https://relay.example/v1/responses", "RELAY_A_KEY", "gpt-a"),
    )
    legacy["llm"]["model_library"]["relay_a"]["transport"] = "responses"
    preview = preview_v1_to_v2(legacy, project_root=tmp_path)
    assert preview.providers[0]["base_url"] == "https://relay.example/v1"
    custom = legacy_config_with_models(
        ("custom_a", "https://custom.example/gateway/responses", "CUSTOM_KEY", "gpt-a"),
    )
    custom["llm"]["model_library"]["custom_a"]["provider"]["compat_mode"] = "custom"
    custom_preview = preview_v1_to_v2(custom, project_root=tmp_path)
    assert custom_preview.providers[0]["base_url"] == "https://custom.example/gateway/responses"


def test_apply_rejects_stale_hash_without_writes(tmp_path) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    with pytest.raises(ValueError, match="stale config hash"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash="stale",
            config_path=config_path,
            project_root=project_root,
        )
    assert "schema_version = 2" not in config_path.read_text(encoding="utf-8")


def test_apply_writes_aliases_and_rolls_back_all_staged_files_on_failure(tmp_path, monkeypatch) -> None:
    config_path, project_root, legacy = write_migration_fixture(tmp_path)
    preview = preview_v1_to_v2(legacy, project_root=project_root)
    monkeypatch.setattr("config.model_config_migration.reload_config", lambda path: (_ for _ in ()).throw(RuntimeError("reload failed")))
    with pytest.raises(RuntimeError, match="reload failed"):
        apply_v1_to_v2(
            preview.preview_id,
            expected_base_hash=public_config_hash(legacy),
            config_path=config_path,
            project_root=project_root,
        )
    assert "schema_version = 2" not in config_path.read_text(encoding="utf-8")
    manifests = list((config_path.parent / "backups").glob("llm-config-migration-*.json"))
    assert manifests
    assert json.loads(manifests[0].read_text(encoding="utf-8"))["status"] == "rolled_back"


@pytest.mark.parametrize(
    ("owner_kind", "payload", "expected_count"),
    [
        (
            "public_config",
            {
                "llm": {"profiles": {"primary": {"model_ref": "legacy_model"}}},
                "tools": {"image2": {"default_model_ref": "legacy_model"}},
                "git": {"commit_message_model_ref": "legacy_model"},
            },
            3,
        ),
        (
            "agent_registry",
            {"agents": [{"dialogueModelId": "legacy_model", "llmBindings": {"dialogue": {"modelId": "legacy_model"}}}]},
            2,
        ),
        (
            "chat_room_registry",
            {"rooms": [{"participants": [{"dialogueModelId": "legacy_model", "llmBindings": {"vision": {"modelId": "legacy_model"}}}]}]},
            2,
        ),
        (
            "active_supervised_run",
            {"status": "running", "currentAgentBinding": {"modelId": "legacy_model"}, "agentBindings": {"baseline": {"modelId": "legacy_model"}}},
            2,
        ),
        (
            "team_live_prompt_cache_policy",
            {"promptCachePolicy": {"modelId": "legacy_model"}},
            1,
        ),
    ],
)
def test_known_live_reference_payloads_rewrite_only_owned_model_fields(owner_kind, payload, expected_count) -> None:
    updated, references = rewrite_model_reference_payload(
        owner_kind,
        payload,
        {"legacy_model": "relay/gpt-a"},
    )
    assert json.dumps(updated).count("relay/gpt-a") == expected_count
    assert len(references) == expected_count


def test_historical_payload_is_never_rewritten() -> None:
    payload = {"decision": {"modelId": "legacy_model"}}
    updated, references = rewrite_model_reference_payload(
        "historical_supervised_artifact",
        payload,
        {"legacy_model": "relay/gpt-a"},
    )
    assert updated == payload
    assert references == ()
```

The helpers above write only under `tmp_path`. Put the parameterized payload-rewrite tests in `tests/test_model_reference_service.py`; keep preview/apply tests in `tests/test_model_config_migration.py`.

- [ ] **Step 2: Run migration tests and verify missing engine failures**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_model_config_migration.py tests\test_model_reference_service.py -q
```

Expected: missing migration module and mapping-aware reference APIs fail.

- [ ] **Step 3: Separate reference planning from writes**

In `model_reference_service.py`, introduce immutable rewrite records:

```python
@dataclass(frozen=True)
class ModelReferenceFileRewrite:
    path: Path
    before_bytes: bytes
    after_bytes: bytes
    references: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class ModelReferenceRewritePlan:
    mapping: dict[str, str]
    public_config: dict[str, Any]
    file_rewrites: tuple[ModelReferenceFileRewrite, ...]
    historical_references: tuple[dict[str, Any], ...]
```

Add `build_model_reference_rewrite_plan(mapping, public_config, project_root)` that loads each live owning file once, applies all replacements in memory, and never rewrites historical supervised artifacts. Add `apply_model_reference_rewrite_plan(plan)` that uses `atomic_write_text()` for staged files and returns changed paths/references. Existing `rebind_model_references()` becomes a one-entry wrapper.

Add `scan_model_alias_usage()` that iterates `llm.model_aliases`, calls the same exact live scanners for each legacy key, and returns per-alias/live totals plus `canRemoveAliases = totalLiveReferenceCount == 0`. Historical references remain reported but do not block alias removal. Expose this bounded summary as `modelAliasUsage` from `_build_workspace()` after Task 8; never remove aliases automatically.

Extend scan coverage only to the exact live owners listed in Step 1, including Team live prompt-cache policy `modelId`; do not replace arbitrary strings or completed workflow artifacts.

- [ ] **Step 4: Implement deterministic preview grouping and Provider ID suggestions**

In `config/model_config_migration.py`, define serialized preview and conflict records. Preview grouping key is exactly `(normalize_provider_endpoint(base_url), canonicalize_credential_ref(effective_credential_ref))`.

Provider ID suggestions must be deterministic from service class/vendor/host and resolve collisions with the first eight fingerprint characters, never `_2`/`_3`. Model keys use `make_model_key(upstream_id)`. A model field ending in `.gguf`, `.safetensors`, or `.bin`, or matching a Windows absolute path, produces `artifact_path_suspected` and `NEEDS_REVIEW`; it is never silently used as `upstream_id` in an applicable preview.

Normalize legacy endpoint suffixes only when the selected adapter and old protocol field prove the final path is a wire route:

```python
def normalize_legacy_service_root(base_url: str, *, adapter: str, wire_protocol: str) -> str:
    normalized = normalize_provider_endpoint(base_url)
    suffixes = {
        ("openai_compatible", "responses"): "/responses",
        ("openai_compatible", "chat_completions"): "/chat/completions",
        ("openai", "responses"): "/responses",
        ("openai", "chat_completions"): "/chat/completions",
        ("anthropic", "messages"): "/v1/messages",
    }
    suffix = suffixes.get((adapter, wire_protocol))
    if not suffix or not normalized.lower().endswith(suffix):
        return normalized
    return normalized[: -len(suffix)].rstrip("/")
```

Do not strip a final `responses`, `messages`, or `chat/completions` token for a custom adapter/compat mode, and do not guess a Gemini deployment route.

Map every v1 model field explicitly:

```text
transport             -> pinned model wire_protocol
contract              -> pinned model interaction_contract
protocol              -> pinned model model_protocol
compat                -> pinned model compatibility
temperature           -> pinned model defaults.temperature
max_output_tokens     -> pinned model defaults.max_output_tokens
timeout               -> pinned model defaults.timeout
connect_timeout       -> pinned model defaults.connect_timeout
streaming             -> pinned model defaults.streaming
tool_calling_mode     -> pinned model defaults.tool_calling_mode
prompt_cache          -> pinned model prompt_cache
thinking_type         -> pinned model thinking_type
thinking_display      -> pinned model thinking_display
reasoning_effort      -> pinned model reasoning_effort
supports_image_input  -> pinned model capabilities.image_input operator override
profile overrides     -> llm.profiles.<id>.overrides
```

If the same Provider/upstream pair has conflicting model defaults across old profile copies, preview marks `model_defaults_conflict` as `NEEDS_REVIEW` and reports field names without secret values.

When two legacy credential references at the same normalized endpoint resolve to configured values, compare only a process-keyed HMAC-SHA256 of those values in memory. Equal HMACs add a `same_secret_different_reference` merge suggestion containing the two reference labels and proposed Provider ID; they do not auto-merge because the approved stable boundary remains credential reference. Do not serialize, log, cache, or return the HMAC/secret, and discard the local comparison values when preview construction returns.

The preview envelope is:

```python
@dataclass(frozen=True)
class ModelConfigMigrationPreview:
    preview_id: str
    base_hash: str
    status: str
    providers: tuple[dict[str, Any], ...]
    model_ref_map: dict[str, str]
    reference_impact: dict[str, Any]
    conflicts: tuple[dict[str, Any], ...]
    proposed_public_config: dict[str, Any] = field(repr=False)
```

Store preview envelopes only in a bounded in-memory registry for 15 minutes; never write the proposed TOML during preview.

- [ ] **Step 5: Implement manifest-backed apply and automatic rollback**

Before writes, `apply_v1_to_v2()` must:

1. reload operator config and compare `public_config_hash()` with both the preview base hash and request hash;
2. reject preview status other than `READY`;
3. build the reference rewrite plan;
4. write a manifest under `resolve_config_backup_dir(config_path) / f"llm-config-migration-{migration_id}.json"` with `status="prepared"` and SHA-256 hashes of each before/after byte payload;
5. write versioned backup bytes for config and each mutable live reference file;
6. atomically write v2 config and reference files;
7. run `load_public_config()`, `build_effective_config()`, `validate_llm_public_config()`, `reload_config()`, and a final live-ref scan;
8. mark manifest `applied` only after all checks pass.

On any exception after the prepared manifest, restore every file from its before bytes, validate the restored v1 config, mark `rolled_back`, record only the exception type and bounded phase name, and re-raise.

The proposed v2 config must include:

```toml
[llm]
schema_version = 2

[llm.model_aliases]
legacy_model_id = "provider_id/model_key"
```

All migrated live references are canonical; aliases remain only for missed/external readers and report usage until zero.

- [ ] **Step 6: Add migration preview/apply/rollback service and HTTP routes**

Add these routes:

```text
POST /config/migration/llm-v2/preview
POST /config/migration/llm-v2/apply
POST /config/migration/llm-v2/{migration_id}/rollback
```

Apply payload requires `previewId` and `baseHash`. Rollback payload requires `migrationId` and the hash of the currently applied v2 config. HTTP 409 covers stale hashes/live-ref conflicts; HTTP 422 covers unresolved preview conflicts.

The preview route projects internal provider proposals to `{providerId, label, serviceClass, vendor, driver, baseUrl, credentialState, modelRefs}`. It never returns `credential_ref`, fingerprints, proposed TOML, HMAC material, secret comparisons, or full local artifact paths.

Emit:

```text
config.schema.migration_previewed
config.schema.migration_applied
config.schema.migration_rolled_back
config.model_reference.migrated
```

Events contain migration ID, provider/model/reference counts, phase, outcome, elapsed time, and bounded error type only.

- [ ] **Step 7: Run migration, reference, route, and config-lock tests**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_model_config_migration.py tests\test_model_reference_service.py tests\test_web_config_routes.py tests\test_config_panel.py -k "migration or reference or stale or backup or lock" -q
```

Expected: preview is read-only, stale writes are rejected, live refs are fully enumerated, apply is atomic, and injected failure restores every staged file.

- [ ] **Step 8: Commit Task 8**

```powershell
git add -- config/model_config_migration.py core/web/services/model_reference_service.py core/web/services/provider_config_service.py core/web/services/config_service.py core/web/routes/config.py tests/test_model_config_migration.py tests/test_model_reference_service.py tests/test_web_config_routes.py
git commit -m "feat(config): migrate model refs with rollback manifests"
```

---

### Task 9: Frontend Provider/catalog contracts and identity-safe view models

**Files:**
- Create: `web/src/routes/configProviderLogic.ts`
- Create: `web/src/routes/configProviderLogic.test.ts`
- Modify: `web/src/api/types/config.ts:25`
- Modify: `web/src/routes/configRouteLogic.ts:572`
- Modify: `web/src/routes/configRouteLogic.test.ts:425`

**Interfaces:**
- Consumes: Task 7 workspace `schemaVersion`, `providerOptions`, `modelCatalog`, and Task 8 migration responses.
- Produces: `ConfigProviderOption`, `ConfigModelCatalog`, `ConfigMigrationPreview`, and typed Provider mutation payloads.
- Produces: `deriveProviderRegistryRows()`, `initialProviderWizardState()`, `providerWizardReducer()`, and `canAdvanceProviderWizard()`.
- Removes from v2 ownership: `accountIdForModelOption()` and UI-generated `modelLibraryIdFromParts()`.

- [ ] **Step 1: Add failing provider view-model and wizard-state tests**

Create `web/src/routes/configProviderLogic.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import type { ConfigModelCatalog, ConfigProviderOption } from "../api/types";
import {
  canAdvanceProviderWizard,
  deriveProviderRegistryRows,
  initialProviderWizardState,
  providerWizardReducer,
} from "./configProviderLogic";

const providers: ConfigProviderOption[] = [
  {
    provider_id: "relay_a",
    label: "Relay A",
    service_class: "relay",
    vendor: "multi_model",
    driver: "openai",
    runtime_framework: "",
    artifact_path: "",
    base_url: "https://relay.example/v1",
    credential_state: "configured",
    default_protocol: "responses",
    pinned_count: 1,
  },
  {
    provider_id: "relay_b",
    label: "Relay B",
    service_class: "relay",
    vendor: "multi_model",
    driver: "openai",
    runtime_framework: "",
    artifact_path: "",
    base_url: "https://relay.example/v1",
    credential_state: "missing",
    default_protocol: "responses",
    pinned_count: 1,
  },
];

const catalog: ConfigModelCatalog = {
  providers: {
    relay_a: {
      status: "reachable",
      lastAttemptAt: "2026-07-11T12:00:00Z",
      lastSuccessAt: "2026-07-11T12:00:00Z",
      refreshDue: false,
      models: {
        "gpt-a": { modelRef: "relay_a/gpt-a", upstreamId: "gpt-a", label: "GPT A", availability: "pinned", capabilities: {} },
      },
    },
    relay_b: {
      status: "auth_failed",
      lastAttemptAt: "2026-07-11T12:01:00Z",
      lastSuccessAt: "",
      refreshDue: true,
      models: {
        "gpt-a": { modelRef: "relay_b/gpt-a", upstreamId: "gpt-a", label: "GPT A", availability: "pinned", capabilities: {} },
      },
    },
  },
};

describe("configProviderLogic", () => {
  it("uses backend provider ids and keeps same-name models distinct", () => {
    const rows = deriveProviderRegistryRows(providers, catalog);
    expect(rows.map((row) => row.providerId)).toEqual(["relay_a", "relay_b"]);
    expect(rows.flatMap((row) => row.models.map((model) => model.modelRef))).toEqual([
      "relay_a/gpt-a",
      "relay_b/gpt-a",
    ]);
    expect(rows[1].credentialState).toBe("missing");
    expect(rows[1].status).toBe("auth_failed");
  });

  it("advances the wizard only after the current step contract is satisfied", () => {
    let state = initialProviderWizardState();
    expect(canAdvanceProviderWizard(state)).toBe(false);
    state = providerWizardReducer(state, { type: "choose_template", templateId: "relay_openai", serviceClass: "relay" });
    expect(canAdvanceProviderWizard(state)).toBe(true);
    state = providerWizardReducer(state, { type: "next" });
    expect(state.step).toBe("connection");
    expect(canAdvanceProviderWizard(state)).toBe(false);
    state = providerWizardReducer(state, {
      type: "set_connection",
      providerId: "relay_a",
      label: "Relay A",
      baseUrl: "https://relay.example/v1",
      credentialRef: "env:RELAY_A_KEY",
    });
    expect(canAdvanceProviderWizard(state)).toBe(true);
  });

  it("never generates provider or model identity from labels", () => {
    const state = providerWizardReducer(initialProviderWizardState(), {
      type: "set_connection",
      providerId: "stable_provider",
      label: "Label Can Change",
      baseUrl: "https://relay.example/v1",
      credentialRef: "env:RELAY_KEY",
    });
    expect(state.providerId).toBe("stable_provider");
  });
});
```

- [ ] **Step 2: Run the frontend logic test and verify missing module/types**

```powershell
npm --prefix web test -- src/routes/configProviderLogic.test.ts
```

Expected: TypeScript/Vitest fails because the provider logic module and workspace types do not exist.

- [ ] **Step 3: Add exact API contracts to `web/src/api/types/config.ts`**

Add:

```typescript
export type ConfigProviderStatus =
  | "configured"
  | "reachable"
  | "auth_failed"
  | "discovery_failed"
  | "stale"
  | "protocol_mismatch"
  | "blocked";

export type ConfigModelAvailability =
  | "observed"
  | "pinned"
  | "missing_remote"
  | "capability_unknown"
  | "protocol_unknown"
  | "disabled";

export type ConfigCapabilityObservation = {
  value: "supported" | "unsupported" | "unknown";
  source: "operator_override" | "runtime_probe" | "provider_endpoint" | "curated_snapshot" | "driver_default";
  confidence: string;
  checked_at: string;
  error: string;
};

export type ConfigProviderOption = {
  provider_id: string;
  label: string;
  service_class: "official_api" | "aggregator" | "relay" | "self_hosted" | "local_runtime" | string;
  vendor: string;
  driver: "openai" | "anthropic" | "gemini" | string;
  runtime_framework: string;
  artifact_path: string;
  base_url: string;
  credential_state: "configured" | "missing" | "not_required" | string;
  default_protocol: string;
  pinned_count: number;
};

export type ConfigCatalogModel = {
  modelRef: string;
  upstreamId: string;
  label: string;
  availability: ConfigModelAvailability;
  capabilities: Record<string, ConfigCapabilityObservation>;
};

export type ConfigCatalogProvider = {
  status: ConfigProviderStatus;
  lastAttemptAt: string;
  lastSuccessAt: string;
  refreshDue: boolean;
  models: Record<string, ConfigCatalogModel>;
};

export type ConfigModelCatalog = {
  providers: Record<string, ConfigCatalogProvider>;
};

export type ConfigMigrationConflict = {
  code: string;
  modelId: string;
  message: string;
};

export type ConfigMigrationProviderPreview = {
  providerId: string;
  label: string;
  serviceClass: string;
  vendor: string;
  driver: string;
  baseUrl: string;
  credentialState: "configured" | "missing" | "not_required" | "conflict" | string;
  modelRefs: string[];
};

export type ConfigMigrationPreview = {
  previewId: string;
  baseHash: string;
  status: "READY" | "NEEDS_REVIEW";
  providers: ConfigMigrationProviderPreview[];
  modelRefMap: Record<string, string>;
  referenceImpact: Record<string, unknown>;
  conflicts: ConfigMigrationConflict[];
};

export type ConfigModelAliasUsage = {
  aliases: Record<string, { canonicalModelRef: string; liveReferenceCount: number; historicalReferenceCount: number }>;
  totalLiveReferenceCount: number;
  totalHistoricalReferenceCount: number;
  canRemoveAliases: boolean;
};
```

Add this composed field type:

```typescript
export type ConfigProviderWorkspaceFields = {
  schemaVersion: 1 | 2;
  providerOptions: ConfigProviderOption[];
  modelCatalog: ConfigModelCatalog;
  modelAliasUsage: ConfigModelAliasUsage;
};
```

In the existing `ConfigWorkspace` declaration, insert `ConfigProviderWorkspaceFields &` between `ConfigSummary &` and the opening object type; do not duplicate its current fields or introduce a second response type.

Extend `ConfigModelOption` with required `model_ref`, `provider_id`, and `upstream_id` fields once backend v2 is active; keep old fields optional for a v1 compatibility row.

- [ ] **Step 4: Implement provider-first row derivation and wizard reducer**

Create `configProviderLogic.ts` with no endpoint/key fingerprinting:

```typescript
import type {
  ConfigCatalogModel,
  ConfigModelCatalog,
  ConfigProviderOption,
  ConfigProviderStatus,
} from "../api/types";

export type ProviderRegistryRow = {
  providerId: string;
  label: string;
  serviceClass: string;
  vendor: string;
  driver: string;
  runtimeFramework: string;
  artifactPath: string;
  baseUrl: string;
  credentialState: string;
  defaultProtocol: string;
  status: ConfigProviderStatus | "configured";
  lastAttemptAt: string;
  lastSuccessAt: string;
  refreshDue: boolean;
  models: ConfigCatalogModel[];
};

export function deriveProviderRegistryRows(
  providers: ConfigProviderOption[],
  catalog: ConfigModelCatalog,
): ProviderRegistryRow[] {
  return providers
    .map((provider) => {
      const observed = catalog.providers[provider.provider_id];
      return {
        providerId: provider.provider_id,
        label: provider.label,
        serviceClass: provider.service_class,
        vendor: provider.vendor,
        driver: provider.driver,
        runtimeFramework: provider.runtime_framework,
        artifactPath: provider.artifact_path,
        baseUrl: provider.base_url,
        credentialState: provider.credential_state,
        defaultProtocol: provider.default_protocol,
        status: observed?.status ?? "configured",
        lastAttemptAt: observed?.lastAttemptAt ?? "",
        lastSuccessAt: observed?.lastSuccessAt ?? "",
        refreshDue: observed?.refreshDue ?? false,
        models: Object.values(observed?.models ?? {}).sort((left, right) => left.modelRef.localeCompare(right.modelRef)),
      };
    })
    .sort((left, right) => left.providerId.localeCompare(right.providerId));
}

export type ProviderWizardStep = "template" | "connection" | "discovery" | "pin";
export type ProviderWizardState = {
  step: ProviderWizardStep;
  templateId: string;
  serviceClass: string;
  providerId: string;
  label: string;
  baseUrl: string;
  credentialRef: string;
  discoveredModels: ConfigCatalogModel[];
  pinnedModelRefs: string[];
};

export type ProviderWizardAction =
  | { type: "choose_template"; templateId: string; serviceClass: string }
  | { type: "set_connection"; providerId: string; label: string; baseUrl: string; credentialRef: string }
  | { type: "set_discovery"; models: ConfigCatalogModel[] }
  | { type: "toggle_pin"; modelRef: string }
  | { type: "next" }
  | { type: "back" }
  | { type: "reset" };

const STEPS: ProviderWizardStep[] = ["template", "connection", "discovery", "pin"];

export function initialProviderWizardState(): ProviderWizardState {
  return {
    step: "template",
    templateId: "",
    serviceClass: "",
    providerId: "",
    label: "",
    baseUrl: "",
    credentialRef: "",
    discoveredModels: [],
    pinnedModelRefs: [],
  };
}

export function canAdvanceProviderWizard(state: ProviderWizardState): boolean {
  if (state.step === "template") return Boolean(state.templateId && state.serviceClass);
  if (state.step === "connection") return Boolean(state.providerId && state.label && state.baseUrl && state.credentialRef);
  if (state.step === "discovery") return state.discoveredModels.length > 0;
  return state.pinnedModelRefs.length > 0;
}

export function providerWizardReducer(state: ProviderWizardState, action: ProviderWizardAction): ProviderWizardState {
  if (action.type === "reset") return initialProviderWizardState();
  if (action.type === "choose_template") return { ...state, templateId: action.templateId, serviceClass: action.serviceClass };
  if (action.type === "set_connection") {
    return {
      ...state,
      providerId: action.providerId,
      label: action.label,
      baseUrl: action.baseUrl,
      credentialRef: action.credentialRef,
    };
  }
  if (action.type === "set_discovery") return { ...state, discoveredModels: action.models };
  if (action.type === "toggle_pin") {
    const selected = new Set(state.pinnedModelRefs);
    selected.has(action.modelRef) ? selected.delete(action.modelRef) : selected.add(action.modelRef);
    return { ...state, pinnedModelRefs: Array.from(selected).sort() };
  }
  const index = STEPS.indexOf(state.step);
  if (action.type === "back") return { ...state, step: STEPS[Math.max(0, index - 1)] };
  if (!canAdvanceProviderWizard(state)) return state;
  return { ...state, step: STEPS[Math.min(STEPS.length - 1, index + 1)] };
}
```

- [ ] **Step 5: Retire frontend identity heuristics from v2 write paths**

In `configRouteLogic.ts`:

- remove `accountIdForModelOption()` from `deriveModelCenterSummary()` and derive account rows only from backend `provider_id`;
- rename legacy `modelLibraryIdFromParts()` to `legacyModelLibraryIdFromParts()` and use it only when `workspace.schemaVersion === 1`;
- remove `uniqueModelLibraryId()` from Provider wizard and discovery handlers;
- keep provider template categorization, visible copy helpers, capability labels, and old v1 compatibility tests.

Add negative tests asserting v2 row derivation does not read `provider.base_url`, `provider.api_key_env`, or labels to create identity.

- [ ] **Step 6: Run frontend provider/config logic tests**

```powershell
npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/configRouteLogic.test.ts
```

Expected: all tests pass; same upstream model IDs under two Providers remain two rows with different canonical refs.

- [ ] **Step 7: Commit Task 9**

```powershell
git add -- web/src/api/types/config.ts web/src/routes/configProviderLogic.ts web/src/routes/configProviderLogic.test.ts web/src/routes/configRouteLogic.ts web/src/routes/configRouteLogic.test.ts
git commit -m "feat(web): model provider-scoped config state"
```

---

### Task 10: Provider-first settings UI, four-step wizard, status diagnostics, and migration UX

**Files:**
- Create: `web/src/routes/ConfigProviderRegistryPanel.tsx`
- Create: `web/src/routes/ConfigProviderWizard.tsx`
- Create: `web/src/routes/ConfigModelMigrationPanel.tsx`
- Create: `web/src/routes/ConfigProviderRegistryPanel.styles.ts`
- Modify: `web/src/routes/ConfigRoute.tsx:2031`
- Modify: `web/src/routes/ConfigRoute.layout.test.ts:101`
- Modify: `web/src/routes/ConfigModelLibraryPanel.tsx:42`

**Interfaces:**
- Consumes: Task 9 typed workspace, rows, wizard reducer, and migration preview.
- Produces visible Provider list/detail tabs for connection, models, protocols/capabilities, and diagnostics.
- Produces explicit v1 migration preview/apply UI and route replacement preview.
- Preserves: `ConfigRoute` as query/mutation owner and VUI primitives as controls.

- [ ] **Step 1: Add failing structural and interaction contract tests**

Extend `ConfigRoute.layout.test.ts` and add source assertions for the three narrow components:

```typescript
it("renders provider-first configuration without endpoint fingerprint identity", () => {
  expect(routeSource).toContain("ConfigProviderRegistryPanel");
  expect(routeSource).toContain("ConfigProviderWizard");
  expect(routeSource).toContain("ConfigModelMigrationPanel");
  expect(providerPanelSource).toContain("provider.providerId");
  expect(providerPanelSource).toContain("model.modelRef");
  expect(providerPanelSource).toContain("connection");
  expect(providerPanelSource).toContain("models");
  expect(providerPanelSource).toContain("protocols");
  expect(providerPanelSource).toContain("diagnostics");
  expect(providerPanelSource).not.toContain("api_key");
});

it("keeps v1 migration preview explicit and apply disabled on unresolved conflicts", () => {
  expect(migrationPanelSource).toContain("preview.status !== \"READY\"");
  expect(migrationPanelSource).toContain("preview.conflicts");
  expect(migrationPanelSource).toContain("onApply(preview.previewId, preview.baseHash)");
});

it("implements the four provider wizard steps", () => {
  expect(wizardSource).toContain('"template"');
  expect(wizardSource).toContain('"connection"');
  expect(wizardSource).toContain('"discovery"');
  expect(wizardSource).toContain('"pin"');
  expect(wizardSource).toContain("canAdvanceProviderWizard");
});

it("refreshes only ttl-expired providers when the model surface opens", () => {
  expect(routeSource).toContain("row.refreshDue");
  expect(routeSource).toContain("autoRefreshAttemptedProviderIds");
  expect(routeSource).not.toContain("load_public_config");
});
```

- [ ] **Step 2: Run layout and logic tests and verify missing components**

```powershell
npm --prefix web test -- src/routes/ConfigRoute.layout.test.ts src/routes/configProviderLogic.test.ts
```

Expected: tests fail because the Provider-first components and route composition are absent.

- [ ] **Step 3: Implement the Provider registry panel**

Create `ConfigProviderRegistryPanel.tsx` around this explicit prop contract:

```typescript
export type ConfigProviderRegistryPanelProps = {
  rows: ProviderRegistryRow[];
  selectedProviderId: string;
  selectedTab: "connection" | "models" | "protocols" | "diagnostics";
  disabled: boolean;
  onSelectProvider: (providerId: string) => void;
  onSelectTab: (tab: "connection" | "models" | "protocols" | "diagnostics") => void;
  onDiscover: (providerId: string) => void;
  onEditRoute: (providerId: string) => void;
  onUnpin: (modelRef: string) => void;
  onDeleteProvider: (providerId: string) => void;
};
```

Render the left Provider list using `row.providerId` as React key and the right detail surface using the selected row. The model table uses `model.modelRef` as key/value, shows `upstreamId` separately, and renders capability `unknown` separately from `unsupported`. The connection tab displays endpoint and credential state but never the credential reference target or secret; for `local_runtime`, it displays `runtimeFramework` and `artifactPath` in a deployment subsection, visually separate from every model's `upstreamId`. The diagnostics tab displays last attempt/success, stale/auth/protocol state, and a discovery action.

Use the existing VUI controls and Tailwind-first style strings. Do not add a new styling dependency or raw color literal.

- [ ] **Step 4: Implement the four-step Provider wizard**

Create `ConfigProviderWizard.tsx` with this mutation boundary:

```typescript
export type ConfigProviderWizardProps = {
  state: ProviderWizardState;
  templates: ConfigProviderPresetOption[];
  disabled: boolean;
  busyLabel: string;
  onChange: (action: ProviderWizardAction) => void;
  onSuggestProviderId: (provider: Record<string, unknown>) => Promise<string>;
  onCreateProvider: (state: ProviderWizardState, credentialValue: string) => Promise<void>;
  onDiscover: (providerId: string, credentialValue: string) => Promise<ConfigCatalogModel[]>;
  onPin: (providerId: string, models: ConfigCatalogModel[]) => Promise<void>;
};
```

Behavior is exact:

1. `template`: grouped official API, aggregator, relay, remote self-hosted, local framework, and custom templates; model families are badges, never Provider categories.
2. `connection`: request the backend Provider ID suggestion after template/label/endpoint/credential-reference changes; keep `providerId` editable only before first save, alongside label, service root, credential reference, secret input, auth kind, driver, and default/allowed wire protocols.
3. `discovery`: create/test the Provider draft, call discovery, show attempted outcome without raw response, and keep the last catalog on failure.
4. `pin`: select observed models by canonical `modelRef`; submit only selected models.

Use an `<input type="password" autoComplete="new-password">` local state for `credentialValue`, clear it after create/discover, and never copy it into `ProviderWizardState`, query cache, URL, or browser storage.

- [ ] **Step 5: Implement the migration panel and route replacement impact dialog**

Create `ConfigModelMigrationPanel.tsx` with:

```typescript
export type ConfigModelMigrationPanelProps = {
  schemaVersion: 1 | 2;
  preview: ConfigMigrationPreview | null;
  aliasUsageCount: number;
  busy: boolean;
  onPreview: () => void;
  onApply: (previewId: string, baseHash: string) => void;
};
```

For schema v1, render the migration reason, Provider grouping, old-to-new model ref table, live reference counts, artifact-path warnings, credential conflicts, backup/rollback promise, and a preview button. Enable Apply only when `preview.status === "READY"`; use `onApply(preview.previewId, preview.baseHash)` and show that it modifies the external operator config. For schema v2, show alias usage and the exit condition; do not offer alias deletion while usage is nonzero.

The route replacement dialog must list affected canonical model refs and live-reference counts from the backend preview and submit the returned preview token. A checkbox or local boolean is not valid authorization.

- [ ] **Step 6: Recompose `ConfigRoute.tsx` as mutation owner**

Add state for selected Provider/tab, wizard reducer, migration preview, and bounded errors. Add request functions for Task 7/8 routes using existing `requestJson()` and query invalidation:

```typescript
const buildProviderDraftRequest = (extra: Record<string, unknown>) => ({
  publicConfig: requireDraft(),
  draftMeta,
  baseHash,
  ...extra,
});

const handleDiscoverProvider = async (providerId: string, credentialValue = "") => {
  const response = await requestJson<ConfigWorkspace>(
    `/api/config/draft/providers/${encodeURIComponent(providerId)}/discover`,
    buildProviderDraftRequest({ providerId, credentialValue }),
  );
  syncWorkspace(response, "success", { resetBase: false });
};

const handlePreviewMigration = async () => {
  const response = await requestJson<ConfigMigrationPreview>(
    "/api/config/migration/llm-v2/preview",
    buildProviderDraftRequest({}),
  );
  setMigrationPreview(response);
};
```

Add a guarded TTL refresh effect. It runs only while the model settings surface is active, only once per Provider ID per workspace load, skips manual adapters, and invokes providers sequentially to avoid a burst:

```typescript
const autoRefreshAttemptedProviderIds = useRef(new Set<string>());

useEffect(() => {
  if (activeSectionId !== "models" || workspace?.schemaVersion !== 2) return;
  let cancelled = false;
  const refreshDueProviders = async () => {
    for (const row of providerRows.filter((item) => item.refreshDue)) {
      if (cancelled || autoRefreshAttemptedProviderIds.current.has(row.providerId)) continue;
      autoRefreshAttemptedProviderIds.current.add(row.providerId);
      await handleDiscoverProvider(row.providerId);
    }
  };
  void refreshDueProviders();
  return () => {
    cancelled = true;
  };
}, [activeSectionId, providerRows, workspace?.schemaVersion]);
```

Memoize `providerRows` and keep `handleDiscoverProvider` callback-stable so the effect does not loop after each workspace response. Discovery failure remains a visible Provider state and does not clear the catalog.

The actual migration apply handler must display a final destructive-impact confirmation using the preview data before calling the apply endpoint. It must not automatically apply after preview.

For schema v2, replace the existing all-in-one `ConfigModelLibraryPanel` with the new Provider panel and wizard. For schema v1, keep legacy inventory read-only and render the migration panel; disable legacy add/update/delete writes.

- [ ] **Step 7: Add responsive styles and screenshot-ready state selectors**

`ConfigProviderRegistryPanel.styles.ts` must use a two-column registry/detail grid above 960 px and one column below it. Add stable `data-provider-status`, `data-model-availability`, `data-wizard-step`, and `data-migration-status` attributes for visual QA. Long endpoints/model refs use ellipsis plus `title`; tables scroll horizontally rather than stretching the route.

- [ ] **Step 8: Run UI logic, layout, and production build**

```powershell
npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
```

Expected: Vitest passes and Vite production build exits 0 with no TypeScript errors.

- [ ] **Step 9: Commit Task 10**

```powershell
git add -- web/src/routes/ConfigProviderRegistryPanel.tsx web/src/routes/ConfigProviderWizard.tsx web/src/routes/ConfigModelMigrationPanel.tsx web/src/routes/ConfigProviderRegistryPanel.styles.ts web/src/routes/ConfigRoute.tsx web/src/routes/ConfigRoute.layout.test.ts web/src/routes/ConfigModelLibraryPanel.tsx
git commit -m "feat(web): add provider-first model settings"
```

---

### Task 11: Compatibility convergence, starter config, full validation, and controlled rollout evidence

**Files:**
- Modify: `config/paths.py:20`
- Modify: `config/settings.py:589`
- Modify: `config/public_config.py:1359`
- Modify: `core/web/services/config_service.py:2329`
- Modify: `web/src/routes/configRouteLogic.ts:572`
- Delete after zero references: `web/src/routes/ConfigModelLibraryPanel.tsx`
- Delete after zero references: `web/src/routes/ConfigModelLibraryPanel.styles.ts`
- Create: `tests/fixtures/config/llm_schema_v1_inline.toml`
- Create: `tests/fixtures/config/llm_schema_v2_provider.toml`
- Create: `tests/test_llm_config_v2_integration.py`
- Modify: `tests/select_tests.py:1`
- Modify: `tests/README.md:1`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: one normal schema v2 write path, one bounded v1 read/preview path, fresh-install v2 starter config, and an evidence matrix ready for local-main integration.
- Does not perform: real operator migration, Launcher refresh, version bump, push, or PR.

- [ ] **Step 1: Add end-to-end fixture tests before removing compatibility write paths**

Create `tests/test_llm_config_v2_integration.py` with these scenarios:

```python
from __future__ import annotations

import tomllib
from pathlib import Path

from config.public_config import build_effective_config, load_public_config
from config.toml_writer import dumps_public_config


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "config"


def test_v2_toml_round_trip_preserves_provider_scoped_models(tmp_path) -> None:
    source = tomllib.loads((FIXTURE_ROOT / "llm_schema_v2_provider.toml").read_text(encoding="utf-8"))
    path = tmp_path / "config.toml"
    path.write_text(dumps_public_config(source), encoding="utf-8")
    loaded = load_public_config(path)
    assert loaded == source
    effective = build_effective_config(loaded)
    assert set(effective.llm.providers) == {"pixel_relay", "lab_llamacpp_a"}
    assert "pixel_relay/gpt-5.6-luna" in effective.llm.model_library
    assert effective.llm.model_library["lab_llamacpp_a/qwen3.6-35b-a3b"]["model"] == "qwen3.6-35b-a3b"


def test_config_load_never_calls_discovery(monkeypatch, tmp_path) -> None:
    source = tomllib.loads((FIXTURE_ROOT / "llm_schema_v2_provider.toml").read_text(encoding="utf-8"))
    path = tmp_path / "config.toml"
    path.write_text(dumps_public_config(source), encoding="utf-8")
    monkeypatch.setattr("core.llm.provider_discovery.service.discover_provider_models", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("network discovery called")))
    build_effective_config(load_public_config(path))


def test_alias_is_read_only_and_new_writes_are_canonical() -> None:
    source = tomllib.loads((FIXTURE_ROOT / "llm_schema_v2_provider.toml").read_text(encoding="utf-8"))
    source["llm"]["model_aliases"] = {"legacy_gpt": "pixel_relay/gpt-5.6-luna"}
    effective = build_effective_config(source)
    assert effective.llm.model_aliases["legacy_gpt"] == "pixel_relay/gpt-5.6-luna"
    assert set(effective.llm.model_library) == {
        "pixel_relay/gpt-5.6-luna",
        "lab_llamacpp_a/qwen3.6-35b-a3b",
    }
```

The v2 fixture must include one relay with two protocols, one local llama.cpp Provider with separate `deployment.artifact_path`, two canonical profiles, and no secret value. The v1 fixture must exercise the read-only adapter and migration preview.

- [ ] **Step 2: Run integration fixtures and verify all paths before cleanup**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_config_v2_integration.py tests\test_llm_config_schema_v2.py tests\test_model_config_migration.py -q
```

Expected: round-trip, zero-network load, aliases, local artifact separation, and preview behavior pass.

- [ ] **Step 3: Make fresh installs schema v2 and remove v2 legacy write paths**

Replace `CONFIG_STARTER_TEXT` and `EXAMPLE_CONFIG_STARTER_TEXT` in `config/paths.py` with a minimal valid provider-scoped config:

```toml
# Vibelution operator config
[llm]
schema_version = 2

[llm.providers.local_openai]
label = "Local OpenAI-compatible service"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.local_openai.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.local_openai.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.local_openai.models.local-model]
upstream_id = "local-model"
label = "Local model"
enabled = true

[llm.profiles.primary]
model_ref = "local_openai/local-model"
```

Then enforce convergence:

- schema v2 never calls `_materialize_inline_llm_providers()`;
- Provider/model CRUD routes are the only v2 structured write path;
- old per-model add/update/delete/discover routes reject schema v2 with a migration-safe message;
- `_discover_openai_compatible_model_list()` remains reachable only through the v1 route;
- runtime capability writes target catalog only;
- frontend v2 code has no imports of `legacyModelLibraryIdFromParts()`;
- legacy aliases resolve reads but are never emitted by new selection controls.

- [ ] **Step 4: Remove the obsolete all-in-one model panel after zero-reference proof**

Run:

```powershell
rg -n "ConfigModelLibraryPanel|ConfigModelLibraryPanel\.styles" web\src -g "*.ts" -g "*.tsx"
```

Expected before deletion: only the component/style files themselves remain. Delete both files, then rerun the search and expect no output. If any live import remains, update that owner in Task 10 scope before deleting; do not leave a second v2 UI path.

- [ ] **Step 5: Add selector coverage and test documentation**

Update `tests/select_tests.py` so changes under these paths select the focused config/model/protocol suite:

```text
config/llm_*.py
config/model_catalog.py
config/model_config_migration.py
core/llm/provider_discovery/**
core/web/services/provider_config_service.py
web/src/routes/ConfigProvider*.tsx
web/src/routes/configProviderLogic.ts
```

Update `tests/README.md` with exact focused commands from this plan and state that real operator migration is not part of automated tests.

- [ ] **Step 6: Run the complete backend configuration/protocol/reference matrix**

```powershell
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_llm_identity.py tests\test_llm_config_schema_v2.py tests\test_llm_provider_registry.py tests\test_model_catalog.py tests\test_provider_discovery_adapters.py tests\test_llm_protocol_resolver.py tests\test_agent_llm_runtime.py tests\test_provider_config_service.py tests\test_model_config_migration.py tests\test_model_reference_service.py tests\test_public_config_model_refs.py tests\test_runtime_capabilities.py tests\test_web_config_routes.py tests\test_config_paths.py tests\test_config_redaction.py tests\test_config_patch_apply.py tests\test_config_panel.py -q
```

Expected: all selected tests pass with no access to the real operator config path.

- [ ] **Step 7: Run complete frontend logic/layout and production build**

```powershell
npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/configRouteLogic.test.ts src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
```

Expected: Vitest passes; Vite build exits 0; there are no TypeScript errors or references to the removed panel.

- [ ] **Step 8: Verify diff, redaction, runtime-event names, and clean task worktree**

```powershell
git diff --check
rg -n "config\.provider\.(created|updated|route_replacement_previewed|discovery_succeeded|discovery_failed)|config\.model\.(pinned|unpinned)|config\.schema\.migration_(previewed|applied|rolled_back)|config\.model_reference\.migrated|llm\.protocol\.(resolved|blocked)" config core tests -g "*.py"
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' -m pytest tests\test_provider_config_service.py tests\test_provider_discovery_adapters.py tests\test_model_config_migration.py tests\test_config_redaction.py -q
git status --short --branch
```

Expected: `git diff --check` is silent; all required event names have implementation/tests; fixture-backed event/redaction tests prove secrets, headers, responses, and sensitive artifact paths are absent without scanning or printing real runtime logs; only Task 11 files are staged for its commit.

- [ ] **Step 9: Commit Task 11**

```powershell
git add -- config/paths.py config/settings.py config/public_config.py core/web/services/config_service.py web/src/routes/configRouteLogic.ts tests/fixtures/config/llm_schema_v1_inline.toml tests/fixtures/config/llm_schema_v2_provider.toml tests/test_llm_config_v2_integration.py tests/select_tests.py tests/README.md
git add -u -- web/src/routes/ConfigModelLibraryPanel.tsx web/src/routes/ConfigModelLibraryPanel.styles.ts
git commit -m "feat(config): converge on provider-scoped model configuration"
```

- [ ] **Step 10: Run the project local quality closeout without merging or refreshing**

```powershell
if (-not $env:VIBELUTION_AGENT_CLAIM_ID) { throw 'VIBELUTION_AGENT_CLAIM_ID is required for closeout.' }
& 'C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe' scripts\local_quality_gate.py closeout --base main --claim-id $env:VIBELUTION_AGENT_CLAIM_ID
```

Expected: closeout manifest status is `passed` and binds the current claim, local `main` base, task HEAD, selector commands, and merge preflight. This produces integration evidence only; it does not merge, release claims, remove the worktree, refresh Launcher, migrate operator config, or modify version files.

---

## Controlled Operator Rollout Gate

This gate is deliberately outside the implementation commits. Do not execute it merely because Tasks 1-11 pass.

1. Load the real operator config only through the existing config workspace and generate `/api/config/migration/llm-v2/preview`.
2. Report the proposed Provider groups, canonical model refs, credential conflicts, suspected artifact paths, live reference counts, alias count, backup path, and rollback availability without exposing secrets.
3. Stop for explicit operator approval of that concrete preview.
4. After approval, apply using the preview ID and matching base hash; verify manifest `applied`, config reload, zero unresolved live legacy refs or an explicitly bounded alias remainder, and catalog state beside the real config.
5. Before Launcher refresh, check active work. If blocked, report exactly: `有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。`
6. After a permitted Launcher refresh, verify the config workspace loads, one official/relay model and one local-runtime model resolve canonical refs, discovery failure preserves stale catalog, unknown v2 protocol blocks before request, and runtime scenes contain bounded event evidence.
7. Using the browser visual-QA workflow, capture the Provider list/detail, four-step wizard, stale/auth/protocol diagnostics, and migration/alias panel at 1440×900 and 390×844. Verify no clipped actions, horizontal page overflow, merged same-name model rows, exposed credential target/secret, or artifact/upstream identity confusion.
8. Report version impact as `minor`; do not edit `VERSION`, `CHANGELOG.md`, `web/package.json`, or `web/package-lock.json` outside the release steward flow.

## Plan Review Loop

| Perspective | Challenge | Evidence in this plan | Result |
| --- | --- | --- | --- |
| User intent | Could the result still duplicate Providers or confuse GPT family with service/protocol? | Tasks 1-3 make endpoint+credential the service identity; Tasks 9-10 consume backend Provider IDs and show service class/vendor/driver/protocol separately. | PASS |
| Existing ownership | Could new code further enlarge `config_service.py`, `public_config.py`, or `ConfigRoute.tsx`? | New registry, catalog, discovery, migration, Provider service, view model, and three UI panels have narrow files; existing large files retain orchestration only. | PASS |
| Migration/data safety | Could preview write, stale state overwrite changes, or partial rewrites corrupt references? | Task 8 is preview-only until apply, checks two hashes, stages all rewrites, writes manifest/backups, validates after atomic writes, and restores every before image on failure. | PASS |
| Security | Could credentials leak through fingerprints, discovery URLs, API DTOs, events, fixtures, or errors? | Tasks 1, 5, 7, 8, and 11 use secret-safe repr, reference-only fingerprints, bounded safe endpoints, negative redaction assertions, and no secret fixtures. | PASS |
| Runtime compatibility | Could schema v2 break all current `model_library` consumers at once? | Task 2 provides a deterministic flattened runtime projection; Task 6 switches identity/protocol consumers before compatibility cleanup in Task 11. | PASS |
| Discovery/cache correctness | Could an outage or empty response erase usable models? | Tasks 4-5 preserve last success, mark stale, distinguish missing pinned models, and never couple discovery to config load. | PASS |
| Protocol correctness | Could URL/model-name heuristics silently select a v2 protocol? | Task 6 allows heuristics only when `legacy_inference_allowed`; v2 uses model/provider/driver precedence and fails closed. | PASS |
| UI correctness | Could two accounts or same-name models merge visually? | Task 9 uses `provider_id` and `modelRef` only; tests include identical endpoint/upstream ID under two Provider IDs. | PASS |
| Test truth | Could implementation claim success from unit tests while the real build/migration path is unverified? | Task 11 requires backend matrix, frontend tests/build, diff/redaction checks, local quality closeout, then a separate real operator/Launcher gate. | PASS |
| Maintainability/reuse | Could this add a parallel external runtime or permanent dual system? | Reuse remains `REFERENCE_ONLY`; Task 11 removes v2 legacy writes and old UI, while v1 remains read/preview only with alias exit criteria. | PASS |

## Spec Coverage Audit

| Approved spec requirement | Implementation task(s) |
| --- | --- |
| Provider instance identity and credential references | Tasks 1-3 |
| Stable provider-scoped model keys/refs and exact upstream IDs | Tasks 1-3 |
| Public TOML schema v2 and profile overrides | Task 2 |
| Local runtime framework and artifact separation | Tasks 2, 10, 11 |
| Config load performs no network | Tasks 2, 5, 11 |
| Observed/pinned catalog, TTL, stale, missing remote | Tasks 4-5 |
| One-time legacy capability cache migration | Task 4 |
| Capability tri-state and field provenance | Tasks 4, 9-10 |
| Explicit protocol precedence and fail closed | Task 6 |
| Provider CRUD, route replacement preview, pin/unpin/delete guards | Task 7 |
| v1 preview, deterministic grouping, aliases, refs, manifest, rollback | Task 8 |
| Profiles, Agent, Tool, Git, Team, ChatRoom, active/durable refs | Task 8 |
| Provider-first list/detail/wizard and error states | Tasks 9-10 |
| Bounded runtime-scene events and secret redaction | Tasks 6-8, 11 |
| Backend/frontend/build/Launcher validation | Task 11 and Controlled Operator Rollout Gate |
| Minor version judgment without branch version edits | Controlled Operator Rollout Gate |

No approved requirement lacks an owning task. No external dependency, OAuth flow, automatic all-model pinning, automatic operator migration, local artifact deletion, request-chain rewrite, version bump, or remote publication has been added.

## Implementation Stop Conditions

Stop the active task and report evidence if any of these occur:

- `agent_work_guard.py check` reports overlap on the task's write scope.
- The current local `main` SHA differs from the implementation worktree base before Task 1 begins, unless the change is reviewed and merged into the task worktree first.
- A v2 implementation step needs to persist a secret value, query/fragment/userinfo URL, raw provider response, or full sensitive local path.
- The migration preview cannot enumerate an owning reference surface or produces `NEEDS_REVIEW` for the real operator config.
- A task would require enabling an uninstalled Anthropic/Gemini wire adapter rather than discovery-only support.
- Backend validation, frontend build, manifest rollback, or stale-catalog preservation fails twice after an in-scope correction.
- Operator migration, Launcher refresh, merge, version edit, push, PR, deletion, or release is reached without its explicit gate.

## Execution Handoff

Plan implementation should begin from a fresh scoped implementation worktree based on the then-current local `main`, not by adding product-code commits to this design-plan branch. Each task uses TDD, a fresh claim check, focused tests, scoped staging, self-review, and its own commit.

Execution options:

1. **Subagent-Driven (recommended by `writing-plans`)** — dispatch a fresh implementation worker per task with review between tasks. This option may be used only when the active collaboration policy/user explicitly allows subagents.
2. **Inline Execution** — execute in the current primary-agent flow using `executing-plans`, in dependency order with review checkpoints and no subagent dispatch.

The current collaboration policy does not authorize subagent dispatch, so the immediately executable route is **Inline Execution** unless the user explicitly requests a multi-agent implementation lane.
