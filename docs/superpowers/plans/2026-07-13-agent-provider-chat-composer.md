# Agent Provider Model and Codex Composer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让一个 Provider 稳定管理多个模型，让每个 Agent 固定一个主模型、每个 Session 只覆盖推理强度，并把主 Chat Composer 收敛为 Codex 风格，同时提供可回滚的 Ai-Pixel Provider 合并。

**Architecture:** 继续以 operator `config.toml`、model catalog、Agent registry、Session conversation record 和 turn snapshot 分别作为唯一事实源。新增模型发现端点解析、统一 Agent candidate projection、保留 TOML 原文的配置事务和 promotion coordinator；前端 Agent 设置负责固定模型，Chat Composer 只展示固定模型并修改当前 Session effort。

**Tech Stack:** Python 3.12、FastAPI、Pydantic v2、httpx、React 19、TypeScript、TanStack Query、HeroUI/VUI、Tailwind CSS、pytest、Vitest。

## Global Constraints

- Operator 配置唯一事实源是 `C:\Users\17533\Documents\Vibelution\config\config.toml`；项目根配置只作模板或兼容输入。
- 不新增 OpenCode、Hermes、CC Switch 或其他第三方运行时依赖；只复用其设计思想。
- 普通 Agent binding、Session effort、catalog refresh、capability probe 不得切换整套配置或重写 operator config。
- Promotion 和 Provider merge 必须校验 `baseHash`、先备份、原子写入、重载验证，并在后续参与者失败时恢复原始字节。
- Source-preserving TOML patch 必须保留未触及字段、注释、空行和用户排序；不得用完整 dump 代替局部变更。
- 动态发现只产生 `observed` 目录；不会自动写入 pinned model，也不会把名称启发式升级为 confirmed capability。
- 一个 Agent 的 `llmBindings.dialogue.modelId` 是固定模型事实；Chat API 不再修改它。
- Agent metadata 中的 `llmReasoningEffort.dialogue` 只是新 Session 默认值；Session record 的 `reasoning_effort` 是当前 Session 值。
- 所有请求必须记录 requested/effective effort、adapter、modelRef 和 providerId 的有界字段；禁止记录凭据、完整请求、完整响应和 prompt。
- `ConversationView` 的 `codex` variant 只由 `ChatConversationComposerBridge` 启用；Evolution/SelfEvolution 保持 `compact`。
- `agent_directory_service.py`、`session_service.py`、`AgentsRoute.tsx`、`ConversationView.tsx` 和共享 DTO 是热文件；实施前必须重新检查 claims 并串行合并。
- 任务 Agent 只提交本任务文件，不修改 `VERSION`、`CHANGELOG.md`、`web/package.json` 或锁文件。
- 前端/API/runtime 变更在用户手工验收前必须通过 Launcher refresh；活动任务存在时不得绕过 guard。

### Reasoning effort / 中转站（2026-07-24 确认增补）

推理强度显示与注入、中转站 per-model 合同、OpenCode variants 映射、D1–D3 / R1–R3，以及实现工单 T1–T9，以确认稿为准：

- `docs/superpowers/specs/2026-07-24-reasoning-effort-protocol-contract-confirmed.md`

执行本 plan 中与 reasoning contract / Composer effort / promotion 相关的步骤时，须同时满足该确认稿（运营声明即可显示、无合同不注入、pin 不猜合同、Agent 选项与合同同源）。调研笔记：`Agent论文/search-results/2026-07-24-opencode-hermes-reasoning-effort-config.md`。

---

## Dependency Order and File Map

| Task | Deliverable | Primary files | Depends on |
| --- | --- | --- | --- |
| 1 | 有界模型端点解析、discovery fingerprint、verification 失效 | `config/models.py`, `config/llm_identity.py`, `core/llm/provider_discovery/*`, `config/model_catalog.py` | none |
| 2 | pinned + observed 统一 Agent candidate projection | new `agent_model_candidate_service.py`, Agent workspace/API types | Task 1 |
| 3 | 保留 TOML 原文的 operator config transaction | new `config/operator_config_transaction.py`, `config/toml_writer.py` | none |
| 4 | discovered -> pinned -> Agent bound promotion coordinator | new promotion service, Agent route/tests | Tasks 2, 3 |
| 5 | Provider 分组 Agent 模型选择器和 promotion UX | new Agent picker, `AgentCoreConfigPanel`, `AgentsRoute` | Task 4 |
| 6 | Session effort 单一所有权和模型级请求适配 | Session route/service, Agent runtime, LLM adapter | Tasks 1, 2 |
| 7 | Codex Composer shell 与只读模型/effort control | conversation components, Chat bridge/route | Task 6 |
| 8 | Ai-Pixel duplicate Provider preview/apply/rollback | provider merge migration + Config UI | Tasks 3, 4, 5 |
| 9 | 集成、Launcher、浏览器、真实模型和迁移门禁 | focused suites + runtime evidence | Tasks 5-8 |

### New files

- `core/web/services/agent_model_candidate_service.py`: 合并 pinned inventory 与 derived catalog，投影 slot compatibility 和 capability provenance。
- `config/operator_config_transaction.py`: source-preserving TOML patch、备份、manifest、原子写入、参与者补偿和 reload gate。
- `core/web/services/agent_model_promotion_service.py`: 首次选择 observed model 时协调 pin + Agent binding。
- `web/src/routes/AgentModelPicker.tsx` / `.styles.ts` / `.test.tsx`: Provider 分组、搜索、状态与 promotion 确认。
- `web/src/routes/configDraftPresence.ts` / `.test.ts`: 跨路由暴露未保存 Config 草稿状态，不保存草稿内容。
- `web/src/components/conversation/ConversationInferenceControl.tsx` / `.styles.ts` / `.test.tsx`: 只读模型标签和当前 Session effort menu。
- `config/provider_merge_migration.py`: duplicate Provider preview、source-preserving apply、reference rewrite、rollback manifest。
- `tests/test_agent_model_candidate_service.py`
- `tests/test_operator_config_transaction.py`
- `tests/test_agent_model_promotion_service.py`
- `tests/test_provider_merge_migration.py`

### Existing files with bounded changes

- `config/models.py`: discovery override 与模型级 reasoning adapter typed fields。
- `config/llm_identity.py`: discovery-specific fingerprint，不改变 Provider identity fingerprint 语义。
- `config/model_catalog.py`: verification fingerprint 和 stale 状态。
- `core/llm/provider_discovery/adapters.py`: endpoint candidates 和明确 fallthrough policy。
- `core/llm/provider_discovery/service.py`: override 安全校验和 discovery fingerprint。
- `core/web/services/agent_config_workspace_service.py`: 改为读取统一 candidate service。
- `core/web/routes/agents.py`: promotion DTO/route。
- `core/web/routes/sessions.py`: effort-only DTO/route。
- `core/web/services/session_service.py`: Session effort 持久化与 runtime resolution。
- `core/llm/agent_runtime.py`, `core/llm/reasoning_effort.py`, `core/llm/adapters.py`: requested/effective effort 和 wire mapping。
- `web/src/api/types/agents.ts`, `web/src/api/types/chat.ts`: candidate 与 effort-only contract。
- `web/src/routes/AgentCoreConfigPanel.tsx`, `web/src/routes/AgentsRoute.tsx`: Agent 固定模型 UI orchestration。
- `web/src/components/conversation/conversationViewTypes.ts`, `ConversationView.tsx`, `ConversationView.styles.ts`: Composer variant。
- `web/src/routes/chat/ChatConversationComposerBridge.tsx`, `web/src/routes/ChatCodingRoute.tsx`: `codex` variant 和 effort mutation。
- `core/web/routes/config.py`, `core/web/services/provider_config_service.py`, `web/src/routes/ConfigProviderRegistryPanel.tsx`, `web/src/routes/ConfigRoute.tsx`: Provider merge API/UI。

---

### Task 1: Resolve model-list endpoints and invalidate stale capability evidence

**Files:**

- Modify: `config/models.py`
- Modify: `config/llm_identity.py`
- Modify: `core/llm/provider_discovery/adapters.py`
- Modify: `core/llm/provider_discovery/service.py`
- Modify: `core/web/services/config_service.py`
- Modify: `config/model_catalog.py`
- Test: `tests/test_llm_identity.py`
- Test: `tests/test_provider_discovery_adapters.py`
- Test: `tests/test_model_catalog.py`

**Interfaces:**

- Produces: `resolve_discovery_endpoints(provider: dict[str, Any], adapter_id: str) -> tuple[str, ...]`.
- Produces: `provider_discovery_fingerprint(provider: Mapping[str, Any]) -> str`.
- Changes: `record_model_verification(state, *, model_ref, provider_fingerprint, checked_at, ok, error_type="", http_status=None)` stores the verification context.
- Consumed by: Tasks 2, 4, 6 and 8.

- [ ] **Step 1: Write endpoint and fingerprint RED tests**

Add parameterized tests that establish exact behavior:

```python
@pytest.mark.parametrize(
    ("base_url", "expected"),
    [
        ("https://relay.example", ("https://relay.example/v1/models",)),
        ("https://relay.example/v1", ("https://relay.example/v1/models",)),
        ("https://relay.example/v2", ("https://relay.example/v2/models", "https://relay.example/v1/models")),
        ("https://relay.example/v1/responses", ("https://relay.example/v1/models",)),
        ("https://relay.example/v1/chat/completions", ("https://relay.example/v1/models",)),
    ],
)
def test_openai_model_endpoint_candidates_are_ordered_and_bounded(base_url, expected):
    provider = {"base_url": base_url, "discovery": {"adapter": "openai_compatible"}}
    assert resolve_discovery_endpoints(provider, "openai_compatible") == expected


def test_explicit_models_url_override_is_the_only_candidate():
    provider = {
        "base_url": "https://relay.example/v1/responses",
        "discovery": {
            "adapter": "openai_compatible",
            "models_url_override": "https://catalog.example/custom/models",
        },
    }
    assert resolve_discovery_endpoints(provider, "openai_compatible") == (
        "https://catalog.example/custom/models",
    )


def test_discovery_fingerprint_changes_for_driver_protocol_and_override():
    base = {
        "base_url": "https://relay.example/v1",
        "credential_ref": "env:RELAY_KEY",
        "auth_kind": "api_key",
        "driver": "openai",
        "protocols": {"default": "responses"},
        "discovery": {"adapter": "openai_compatible"},
    }
    changed = copy.deepcopy(base)
    changed["discovery"]["models_url_override"] = "https://relay.example/models"
    assert provider_discovery_fingerprint(base) != provider_discovery_fingerprint(changed)
```

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_llm_identity.py tests/test_provider_discovery_adapters.py tests/test_model_catalog.py -q
```

Expected: FAIL because `models_url_override`, endpoint resolution and verification fingerprints do not exist.

- [ ] **Step 3: Add the typed override and discovery-specific fingerprint**

In `ProviderDiscoverySettings`, add the project-native snake_case field:

```python
class ProviderDiscoverySettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: str = "manual"
    adapter: str = "manual"
    models_url_override: str = ""
    cache_ttl_seconds: int = Field(default=3600, ge=0, le=86400)
    include: List[str] = Field(default_factory=list)
    exclude: List[str] = Field(default_factory=list)
```

Keep `provider_identity_fingerprint()` unchanged and add a separate discovery fingerprint:

```python
def provider_discovery_fingerprint(provider: Mapping[str, Any]) -> str:
    discovery = provider.get("discovery") if isinstance(provider.get("discovery"), dict) else {}
    protocols = provider.get("protocols") if isinstance(provider.get("protocols"), dict) else {}
    identity = provider_identity_fingerprint(
        str(provider.get("base_url") or ""),
        str(provider.get("credential_ref") or "none"),
        auth_kind=str(provider.get("auth_kind") or "api_key"),
    )
    payload = "\0".join(
        (
            identity,
            str(provider.get("driver") or "").strip().lower(),
            str(discovery.get("adapter") or "manual").strip().lower(),
            str(discovery.get("models_url_override") or "").strip(),
            json.dumps(protocols, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Implement ordered endpoint candidates and stop rules**

Add a pure resolver to `adapters.py` and make OpenAI-compatible discovery call it:

```python
_REQUEST_SUFFIXES = ("/chat/completions", "/responses", "/completions")
_VERSION_SEGMENT = re.compile(r"/v[0-9]+(?:beta)?$")


def resolve_discovery_endpoints(provider: dict[str, Any], adapter_id: str) -> tuple[str, ...]:
    discovery = provider.get("discovery") if isinstance(provider.get("discovery"), dict) else {}
    override = str(discovery.get("models_url_override") or "").strip().rstrip("/")
    if override:
        return (override,)
    base = str(provider.get("base_url") or "").strip().rstrip("/")
    adapter = str(adapter_id or "").strip().lower()
    if adapter == "anthropic":
        return (_join_endpoint(_service_root(base), "v1/models"),)
    if adapter == "gemini":
        return (_join_endpoint(_service_root(base), "v1beta/models"),)
    for suffix in _REQUEST_SUFFIXES:
        if base.lower().endswith(suffix):
            base = base[: -len(suffix)]
            break
    candidates: list[str]
    if _VERSION_SEGMENT.search(urlsplit(base).path.rstrip("/")):
        candidates = [_join_endpoint(base, "models")]
        if not base.lower().endswith("/v1"):
            candidates.append(_join_endpoint(_service_root(base), "v1/models"))
    else:
        candidates = [_join_endpoint(base, "v1/models")]
    return tuple(dict.fromkeys(candidate for candidate in candidates if candidate))[:4]
```

Change fallback handling so only route mismatch proceeds by default:

```python
def _candidate_can_fall_through(exc: Exception) -> bool:
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {404, 405}


except Exception as exc:
    last_error = exc
    if _candidate_can_fall_through(exc):
        continue
    raise
```

Before requesting an explicit override, call `validate_llm_provider_target()` with a copied Provider whose `base_url` is the override. This preserves the existing DNS/SSRF policy.

- [ ] **Step 5: Bind verification to the current discovery fingerprint**

Use `provider_discovery_fingerprint(provider)` in `discover_provider_models()`. Store the fingerprint on successful verification and mark old evidence stale after a fingerprint change:

```python
def record_model_verification(
    state: dict[str, Any],
    *,
    model_ref: str,
    provider_fingerprint: str,
    checked_at: str,
    ok: bool,
    error_type: str = "",
    http_status: int | None = None,
) -> dict[str, Any]:
    provider_id, model_key = split_model_ref(model_ref)
    _parse_utc(checked_at)
    normalized_error = "" if ok else str(error_type or "failed").strip().lower()[:64]
    normalized_status = None
    if http_status is not None:
        try:
            normalized_status = int(http_status)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid model verification HTTP status") from exc
        if normalized_status < 100 or normalized_status > 599:
            raise ValueError("invalid model verification HTTP status")

    updated = copy.deepcopy(state)
    providers = updated.setdefault("providers", {})
    provider = providers.setdefault(
        provider_id,
        {
            "status": "not_discovered",
            "catalogStale": False,
            "lastAttemptAt": "",
            "lastSuccessAt": "",
            "lastErrorType": "",
            "models": {},
            "warnings": [],
        },
    )
    models = provider.setdefault("models", {})
    model = models.setdefault(
        model_key,
        {
            "upstreamId": model_key,
            "label": model_key,
            "availability": "pinned",
            "capabilities": {},
        },
    )
    verification = {
        "status": "verified" if ok else "failed",
        "checkedAt": str(checked_at),
        "errorType": normalized_error,
        "httpStatus": normalized_status,
        "providerFingerprint": str(provider_fingerprint),
    }
    model["verification"] = verification
    return updated
```

In `record_discovery_success()`, preserve verification only when its fingerprint matches; otherwise project it as `stale` without deleting the prior diagnostic:

```python
verification = copy.deepcopy(prior.get("verification", {})) if isinstance(prior.get("verification"), dict) else {}
if verification and verification.get("providerFingerprint") != provider_fingerprint:
    verification["status"] = "stale"
models[model_key]["verification"] = verification
reasoning_contract = copy.deepcopy(prior.get("reasoningContract", {})) if isinstance(prior.get("reasoningContract"), dict) else {}
if reasoning_contract and reasoning_contract.get("providerFingerprint") != provider_fingerprint:
    reasoning_contract["verificationStatus"] = "stale"
models[model_key]["reasoningContract"] = reasoning_contract
```

Update the saved-model probe caller so the required fingerprint is derived from the same submitted/saved Provider, never from a model name:

```python
provider_id, _model_key = split_model_ref(model_ref)
provider = public_config.get("llm", {}).get("providers", {}).get(provider_id, {})
updated = record_model_verification(
    state,
    model_ref=model_ref,
    provider_fingerprint=provider_discovery_fingerprint(provider),
    checked_at=str(verification["checked_at"]),
    ok=verification["status"] == "verified",
    error_type=str(verification["error_type"]),
    http_status=verification["http_status"],
)
```

- [ ] **Step 6: Run GREEN and commit Task 1**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_llm_identity.py tests/test_provider_discovery_adapters.py tests/test_model_catalog.py tests/test_web_config_routes.py -q
git add config/models.py config/llm_identity.py config/model_catalog.py core/llm/provider_discovery/adapters.py core/llm/provider_discovery/service.py core/web/services/config_service.py tests/test_llm_identity.py tests/test_provider_discovery_adapters.py tests/test_model_catalog.py tests/test_web_config_routes.py
git commit -m "feat(llm): harden provider model discovery"
```

Expected: PASS; 401/403/429/timeout/network/5xx retain their original category, 404/405 may advance, and no secret appears in attempted endpoint diagnostics.

**Review Gate:** Reject any implementation that writes a guessed models URL back to `base_url`, continues after auth failure, or changes `provider_identity_fingerprint()` semantics.

---

### Task 2: Project pinned and observed models into one Agent candidate list

**Files:**

- Create: `core/web/services/agent_model_candidate_service.py`
- Modify: `core/web/services/agent_config_workspace_service.py`
- Modify: `web/src/api/types/agents.ts`
- Test: `tests/test_agent_model_candidate_service.py`
- Test: `tests/test_agent_config_workspace_service.py`
- Test: `tests/test_agent_config_workspace_routes.py`

**Interfaces:**

- Produces: `project_agent_model_candidates(public_config, catalog_state) -> list[dict[str, Any]]`.
- Produces: `list_agent_model_candidates() -> dict` with `operatorConfigHash` and `candidates`.
- Candidate identity remains `modelRef = providerId/modelKey`; observed items are not runtime-selectable until promoted.
- Consumed by: Tasks 4-7.

- [ ] **Step 1: Write candidate projection RED tests**

Create fixtures with one pinned model and three observed models under one Provider:

```python
def test_projection_unions_pinned_and_observed_without_duplicate_model_refs():
    payload = project_agent_model_candidates(_public_config(), _catalog_state())
    by_ref = {item["modelRef"]: item for item in payload}

    assert sorted(by_ref) == [
        "ai-pixel/gpt-5.6-luna",
        "ai-pixel/gpt-5.6-sol",
        "ai-pixel/gpt-5.6-terra",
        "ai-pixel/image2",
    ]
    assert by_ref["ai-pixel/image2"]["source"] == "both"
    assert by_ref["ai-pixel/gpt-5.6-luna"]["source"] == "discovered"
    assert by_ref["ai-pixel/gpt-5.6-luna"]["runtimeSelectable"] is False
    assert by_ref["ai-pixel/gpt-5.6-luna"]["slotCompatibility"]["dialogue"]["allowed"] is True


def test_image_and_audio_candidates_remain_visible_with_disabled_reason():
    payload = project_agent_model_candidates(_public_config(), _catalog_with_special_models())
    by_upstream = {item["upstreamId"]: item for item in payload}
    assert by_upstream["gpt-image-1"]["slotCompatibility"]["dialogue"] == {
        "allowed": False,
        "reasonCode": "non_dialogue_model",
    }
```

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_agent_model_candidate_service.py tests/test_agent_config_workspace_service.py tests/test_agent_config_workspace_routes.py -q
```

Expected: FAIL because the workspace currently reads only `list_llm_model_options()` pinned entries.

- [ ] **Step 3: Implement the pure projection service**

Use a stable DTO with explicit provenance:

```python
def _provider_credential_compatibility(provider: dict[str, Any]) -> dict[str, Any]:
    credential_ref = str(provider.get("credential_ref") or "none").strip()
    resolution = resolve_credential_ref(credential_ref)
    requires = bool(provider.get("requires_credential", True)) and str(provider.get("auth_kind") or "api_key") != "none"
    configured = not requires or bool(resolution.secret)
    return {
        "apiKeyEnv": credential_ref[4:] if credential_ref.startswith("env:") else "",
        "apiKeyConfigured": configured,
        "apiKeyState": str(resolution.state or "unknown"),
        "requiresApiKey": requires,
        "missingApiKey": requires and not configured,
    }


def _candidate(
    *,
    provider_id: str,
    provider: dict[str, Any],
    model_key: str,
    pinned: dict[str, Any],
    observed: dict[str, Any],
    provider_catalog: dict[str, Any],
    credential_compatibility: dict[str, Any],
    current_provider_fingerprint: str,
) -> dict[str, Any]:
    model_ref = make_model_ref(provider_id, model_key)
    has_pinned = bool(pinned)
    has_observed = bool(observed)
    upstream_id = str(pinned.get("upstream_id") or observed.get("upstreamId") or model_key)
    capabilities = resolve_model_capabilities(
        operator=pinned.get("capabilities", {}),
        runtime_probe={},
        provider_metadata=observed.get("capabilities", {}),
        curated_snapshot={},
        driver_default={},
    )
    image_input = capabilities.get("image_input") if isinstance(capabilities.get("image_input"), dict) else {}
    verification = observed.get("verification") if isinstance(observed.get("verification"), dict) else {}
    fingerprint_stale = bool(
        verification
        and str(verification.get("providerFingerprint") or "") != current_provider_fingerprint
    )
    catalog_fingerprint = str(provider_catalog.get("providerFingerprint") or "")
    catalog_stale = bool(
        provider_catalog.get("catalogStale")
        or (catalog_fingerprint and catalog_fingerprint != current_provider_fingerprint)
    )
    reasoning = project_reasoning_contract(
        pinned,
        observed,
        current_provider_fingerprint=current_provider_fingerprint,
    )
    return {
        "modelId": model_ref,
        "modelRef": model_ref,
        "modelKey": model_key,
        "upstreamId": upstream_id,
        "label": str(pinned.get("label") or observed.get("label") or upstream_id),
        "model": upstream_id,
        "contextWindow": int(pinned.get("context_window") or observed.get("contextWindow") or provider.get("context_window") or 0),
        "providerId": provider_id,
        "providerLabel": str(provider.get("label") or provider_id),
        "providerKind": str(provider.get("driver") or ""),
        "providerBaseUrl": str(provider.get("base_url") or ""),
        "transport": str(pinned.get("wire_protocol") or provider.get("protocols", {}).get("default") or ""),
        "source": "both" if has_pinned and has_observed else "pinned" if has_pinned else "discovered",
        "runtimeSelectable": has_pinned and pinned.get("enabled", True) is not False,
        "availability": str(observed.get("availability") or ("pinned" if has_pinned else "unknown")),
        "catalogStale": catalog_stale,
        "verificationStatus": "stale" if fingerprint_stale else str(verification.get("status") or "unverified"),
        "capabilities": capabilities,
        "supportsImageInput": True if image_input.get("value") == "supported" else False if image_input.get("value") == "unsupported" else None,
        "slotCompatibility": project_slot_compatibility(upstream_id, pinned, observed),
        **credential_compatibility,
        **reasoning,
    }
```

`project_agent_model_candidates()` must iterate configured Providers, compute credential compatibility and `provider_discovery_fingerprint(provider)` once per Provider, union `provider.models` and `catalog.providers.<id>.models`, deduplicate by canonical modelRef, and sort by `(providerLabel, label, modelRef)`. The helper may inspect whether a credential resolves, but its returned DTO never contains the secret or credential value.

- [ ] **Step 4: Project model-specific reasoning contracts without name promotion**

Add one helper that reads only confirmed layers and keeps source/status:

```python
def project_reasoning_contract(
    pinned: dict[str, Any],
    observed: dict[str, Any],
    *,
    current_provider_fingerprint: str,
) -> dict[str, Any]:
    defaults = pinned.get("defaults") if isinstance(pinned.get("defaults"), dict) else {}
    capabilities = pinned.get("capabilities") if isinstance(pinned.get("capabilities"), dict) else {}
    observed_contract = observed.get("reasoningContract") if isinstance(observed.get("reasoningContract"), dict) else {}
    observed_verified = (
        observed_contract.get("verificationStatus") == "verified"
        and str(observed_contract.get("providerFingerprint") or "") == current_provider_fingerprint
    )
    values = list(
        defaults.get("reasoning_effort_values")
        or capabilities.get("reasoning_effort_values")
        or (observed_contract.get("effortValues") if observed_verified else [])
        or []
    )
    values = list(dict.fromkeys(normalize_reasoning_effort(value) for value in values if normalize_reasoning_effort(value)))
    source = "operator_override" if defaults.get("reasoning_effort_values") or capabilities.get("reasoning_effort_values") else str(observed_contract.get("source") or "unknown") if observed_verified else "unknown"
    requested_default = normalize_reasoning_effort(
        defaults.get("default_reasoning_effort")
        or (observed_contract.get("default") if observed_verified else "")
    )
    adapter = str(
        defaults.get("reasoning_effort_adapter")
        or (observed_contract.get("adapter") if observed_verified else "")
        or "none"
    )
    mapping = dict(
        defaults.get("reasoning_effort_map")
        or (observed_contract.get("map") if observed_verified else {})
        or {}
    )
    return {
        "supportsReasoningEffort": bool(values),
        "reasoningEffortValues": values,
        "reasoningEffortOptions": reasoning_effort_options(values),
        "defaultReasoningEffort": requested_default if requested_default in values else (values[0] if values else ""),
        "reasoningAdapter": adapter if values else "none",
        "reasoningEffortMap": mapping if values else {},
        "reasoningDefaultSource": source,
        "capabilityStatus": "confirmed" if source == "operator_override" and values else "verified" if observed_verified and values else "unknown",
        "capabilitySource": source,
    }
```

Catalog heuristics may populate `suggestedCapabilities`, but must not populate `reasoningContract` or the confirmed fields above. A catalog reasoning contract is accepted only when its own verification status/fingerprint matches the current Provider discovery fingerprint.

- [ ] **Step 5: Replace the Agent workspace input and extend the API type**

In `_build_agent_config_workspace()`, replace the pinned-only source:

```python
candidate_payload = _timed_stage(timings, "agent_model_candidates", list_agent_model_candidates)
agent_model_choices = list(candidate_payload.get("candidates") or [])
model_refs = {
    str(item.get("modelRef") or item.get("modelId") or ""): item
    for item in agent_model_choices
    if str(item.get("modelRef") or item.get("modelId") or "")
}
```

Add `operatorConfigHash` to the workspace response and extend `AgentModelChoice`:

```typescript
export type AgentModelChoice = {
  modelId: string;
  modelRef: string;
  modelKey: string;
  upstreamId: string;
  label: string;
  model: string;
  contextWindow?: number;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  providerBaseUrl: string;
  transport: string;
  source: "pinned" | "discovered" | "both";
  runtimeSelectable: boolean;
  availability: string;
  verificationStatus: string;
  catalogStale: boolean;
  slotCompatibility: Record<string, { allowed: boolean; reasonCode: string }>;
  capabilities: Record<string, unknown>;
  apiKeyEnv: string;
  apiKeyConfigured: boolean;
  apiKeyState: string;
  requiresApiKey: boolean;
  missingApiKey: boolean;
  supportsImageInput?: boolean | null;
  supportsReasoningEffort?: boolean;
  reasoningAdapter?: string;
  reasoningEffortMap?: Record<string, string>;
  reasoningDefaultSource?: string;
  reasoningEffortValues?: string[];
  reasoningEffortOptions?: Array<{ value: string; label: string; description: string }>;
  defaultReasoningEffort?: string;
  capabilityStatus: string;
  capabilitySource: string;
};
```

- [ ] **Step 6: Run GREEN and commit Task 2**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_agent_model_candidate_service.py tests/test_agent_config_workspace_service.py tests/test_agent_config_workspace_routes.py tests/test_session_llm_selection.py -q
git add core/web/services/agent_model_candidate_service.py core/web/services/agent_config_workspace_service.py web/src/api/types/agents.ts tests/test_agent_model_candidate_service.py tests/test_agent_config_workspace_service.py tests/test_agent_config_workspace_routes.py tests/test_session_llm_selection.py
git commit -m "feat(agent): expose provider model candidates"
```

Expected: PASS; Luna/Sol/Terra appear under one Provider, image/audio remain visible but disabled for dialogue, and no observed candidate becomes pinned as a side effect.

**Review Gate:** Reject projection code that reads the external config more than once per request, mutates catalog/config, or infers confirmed capability from a model name.

---

### Task 3: Add source-preserving operator config transactions

**Files:**

- Modify: `config/toml_writer.py`
- Create: `config/operator_config_transaction.py`
- Test: `tests/test_operator_config_transaction.py`
- Test: `tests/test_config_panel.py`

**Interfaces:**

- Produces: `append_toml_table(text, table_path, values) -> str`.
- Produces: `remove_toml_table_tree(text, table_path) -> str`.
- Produces: `replace_toml_scalar(text, table_path, key, expected, replacement) -> str`.
- Produces: `prepare_operator_config_transaction(operation_kind, expected_base_hash, mutate_text, config_path=CONFIG_PATH)`.
- Produces: `apply_operator_config_transaction(prepared, participants=()) -> dict[str, Any]`.
- Consumed by: Tasks 4 and 8.

- [ ] **Step 1: Write source-preservation and rollback RED tests**

```python
def test_append_model_preserves_comments_unknown_fields_and_order(tmp_path):
    original = """# operator note
[custom]
unknown = "keep-me" # inline note

[llm]
schema_version = 2

[llm.providers.ai-pixel]
base_url = "https://relay.example/v1"
"""
    patched = append_toml_table(
        original,
        ("llm", "providers", "ai-pixel", "models", "gpt-5.6-luna"),
        {"upstream_id": "gpt-5.6-luna", "label": "Luna", "enabled": True},
    )
    assert "# operator note" in patched
    assert 'unknown = "keep-me" # inline note' in patched
    assert tomllib.loads(patched)["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"]["enabled"] is True


def test_participant_failure_restores_exact_config_bytes(tmp_path):
    before = b"# exact bytes\n[llm]\nschema_version = 2\n"
    config_path = tmp_path / "config.toml"
    config_path.write_bytes(before)
    prepared = prepare_operator_config_transaction(
        operation_kind="test",
        expected_base_hash=public_config_hash(tomllib.loads(before.decode())),
        mutate_text=lambda text: text + "\n[extra]\nvalue = true\n",
        config_path=config_path,
    )
    with pytest.raises(RuntimeError, match="participant failed"):
        apply_operator_config_transaction(prepared, participants=[_failing_participant()])
    assert config_path.read_bytes() == before
```

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_operator_config_transaction.py tests/test_config_panel.py -q
```

Expected: FAIL because source-preserving table patches and multi-participant transactions do not exist.

- [ ] **Step 3: Expose bounded TOML fragment formatting**

Keep the existing full writer and add two public helpers:

```python
def format_toml_scalar(value: Any) -> str:
    return _format_scalar(value)


def dumps_toml_table(table_path: Iterable[str], data: Dict[str, Any]) -> str:
    parts = [str(part) for part in table_path]
    if not parts:
        raise ValueError("table_path is required")
    lines: List[str] = []
    _write_table(lines, parts, data)
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Implement exact table span operations**

Parse table headers without implementing a second TOML parser:

```python
_TABLE_HEADER = re.compile(r"^\s*\[(?!\[)(.+)]\s*(?:#.*)?$")


def _table_path_from_line(line: str) -> tuple[str, ...] | None:
    match = _TABLE_HEADER.match(line)
    if not match:
        return None
    marker = "__vibelution_table_marker__"
    payload = tomllib.loads(f"[{match.group(1)}]\n{marker} = true\n")

    def find(node: dict[str, Any], prefix: tuple[str, ...]) -> tuple[str, ...]:
        if node.get(marker) is True:
            return prefix
        for key, value in node.items():
            if isinstance(value, dict):
                found = find(value, (*prefix, str(key)))
                if found:
                    return found
        return ()

    resolved = find(payload, ())
    return resolved or None
```

Use header indices to append, remove a table subtree, or replace one scalar inside an exact table. Every operation must parse the result with `tomllib.loads()` before returning:

```python
def append_toml_table(text: str, table_path: tuple[str, ...], values: dict[str, Any]) -> str:
    if table_path in _table_paths(text):
        raise ValueError("TOML table already exists")
    suffix = "" if not text or text.endswith("\n\n") else "\n" if text.endswith("\n") else "\n\n"
    candidate = text + suffix + dumps_toml_table(table_path, values)
    tomllib.loads(candidate)
    return candidate


def remove_toml_table_tree(text: str, table_path: tuple[str, ...]) -> str:
    lines = text.splitlines(keepends=True)
    spans = _table_spans(lines)
    removed = [span for span in spans if span.path[: len(table_path)] == table_path]
    if not removed:
        raise ValueError("TOML table tree not found")
    indexes = {index for span in removed for index in range(span.start, span.end)}
    candidate = "".join(line for index, line in enumerate(lines) if index not in indexes)
    tomllib.loads(candidate)
    return candidate


_SCALAR_ASSIGNMENT = re.compile(
    r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)(?P<separator>\s*=\s*)(?P<payload>.*)$"
)


def _split_toml_value_suffix(payload: str) -> tuple[str, str]:
    quote = ""
    escaped = False
    for index, char in enumerate(payload):
        if quote == '"':
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = ""
        elif quote == "'":
            if char == quote:
                quote = ""
        elif char in {'"', "'"}:
            quote = char
        elif char == "#":
            value = payload[:index].rstrip()
            return value, payload[len(value):]
    value = payload.rstrip()
    return value, payload[len(value):]


def replace_toml_scalar(
    text: str,
    table_path: tuple[str, ...],
    key: str,
    expected: Any,
    replacement: Any,
) -> str:
    lines = text.splitlines(keepends=True)
    matches: list[tuple[int, re.Match[str], str, str]] = []
    for span in _table_spans(lines):
        if span.path != table_path:
            continue
        for index in range(span.start + 1, span.end):
            newline = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
            body = lines[index][:-len(newline)] if newline else lines[index]
            match = _SCALAR_ASSIGNMENT.fullmatch(body)
            if match and match.group("key") == key:
                value_text, suffix = _split_toml_value_suffix(match.group("payload"))
                matches.append((index, match, value_text, suffix + newline))
    if len(matches) != 1:
        raise ValueError(f"expected one scalar {'.'.join((*table_path, key))}, found {len(matches)}")
    index, match, value_text, suffix = matches[0]
    current = tomllib.loads(f"value = {value_text}\n")["value"]
    if current != expected:
        raise ValueError(f"unexpected current value for {'.'.join((*table_path, key))}")
    lines[index] = (
        match.group("indent")
        + match.group("key")
        + match.group("separator")
        + format_toml_scalar(replacement)
        + suffix
    )
    candidate = "".join(lines)
    tomllib.loads(candidate)
    return candidate
```

The helper intentionally accepts direct bare scalar keys only; nested paths are selected by `table_path`. Tests cover missing/duplicate keys, unexpected current values, basic/literal quoted strings, escaped `#` characters, CRLF and inline comments.

- [ ] **Step 5: Implement transaction prepare/apply/rollback**

Use typed participants so promotion and merge share one rollback engine:

```python
@dataclass(frozen=True)
class TransactionParticipant:
    name: str
    apply: Callable[[], None]
    verify: Callable[[], None]
    rollback: Callable[[], None]


@dataclass(frozen=True)
class PreparedOperatorConfigTransaction:
    operation_id: str
    operation_kind: str
    config_path: Path
    before_bytes: bytes
    after_bytes: bytes
    base_hash: str
    candidate_hash: str
    manifest_path: Path


def prepare_operator_config_transaction(*, operation_kind, expected_base_hash, mutate_text, config_path=CONFIG_PATH):
    path = Path(config_path).resolve()
    before = path.read_bytes()
    current = tomllib.loads(before.decode("utf-8"))
    if public_config_hash(current) != str(expected_base_hash):
        raise ValueError("stale config hash")
    after_text = mutate_text(before.decode("utf-8"))
    after = after_text.encode("utf-8")
    candidate = tomllib.loads(after_text)
    validate_llm_public_config(candidate)
    build_effective_config(candidate)
    return _prepared_transaction(operation_kind, path, before, after, expected_base_hash)
```

Implement the apply path with one explicit compensation stack:

```python
def apply_operator_config_transaction(
    prepared: PreparedOperatorConfigTransaction,
    *,
    participants: Sequence[TransactionParticipant] = (),
) -> dict[str, Any]:
    applied: list[TransactionParticipant] = []
    rollback_errors: list[str] = []
    with _config_edit_lock(prepared.config_path):
        current_bytes = prepared.config_path.read_bytes()
        current_public = tomllib.loads(current_bytes.decode("utf-8"))
        if current_bytes != prepared.before_bytes or public_config_hash(current_public) != prepared.base_hash:
            raise ValueError("operator config changed after transaction preparation")
        artifacts = _write_transaction_artifacts(prepared, status="prepared")
        try:
            _strict_atomic_write(prepared.config_path, prepared.after_bytes)
            persisted = load_public_config(prepared.config_path)
            validate_llm_public_config(persisted)
            build_effective_config(persisted)
            reload_config(str(prepared.config_path))
            _update_transaction_manifest(artifacts, status="reloaded")
            for participant in participants:
                applied.append(participant)
                participant.apply()
                participant.verify()
            _update_transaction_manifest(artifacts, status="completed")
            return {
                "status": "completed",
                "operationId": prepared.operation_id,
                "hash": public_config_hash(persisted),
                "manifestPath": str(prepared.manifest_path),
            }
        except Exception as exc:
            for participant in reversed(applied):
                try:
                    participant.rollback()
                except Exception as rollback_exc:
                    rollback_errors.append(f"{participant.name}:{type(rollback_exc).__name__}")
            try:
                _strict_atomic_write(prepared.config_path, prepared.before_bytes)
                reload_config(str(prepared.config_path))
            except Exception as rollback_exc:
                rollback_errors.append(f"operator_config:{type(rollback_exc).__name__}")
            status = "rollback_failed" if rollback_errors else "rolled_back"
            _update_transaction_manifest(
                artifacts,
                status=status,
                failure_phase="participant_or_reload",
                error_type=type(exc).__name__,
                rollback_errors=rollback_errors,
            )
            raise OperatorConfigTransactionError(
                status=status,
                operation_id=prepared.operation_id,
                manifest_path=prepared.manifest_path,
            ) from exc
```

`_write_transaction_artifacts()` writes exact before/after backup files plus a redacted manifest before `_strict_atomic_write()` can touch the operator config. `_update_transaction_manifest()` stores only hashes, paths, participant names, phases and error classes.

- [ ] **Step 6: Run GREEN and commit Task 3**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_operator_config_transaction.py tests/test_config_panel.py tests/test_model_config_migration.py -q
git add config/toml_writer.py config/operator_config_transaction.py tests/test_operator_config_transaction.py tests/test_config_panel.py
git commit -m "feat(config): add source-preserving transactions"
```

Expected: PASS; comments and unknown fields survive, stale hashes stop before writes, participant failures restore exact bytes, and manifests never contain secrets or full config content.

**Review Gate:** Reject complete TOML reserialization, writes before backup creation, best-effort rollback, or a manifest containing raw config/credentials.

---

### Task 4: Promote an observed model and bind it to one Agent atomically

**Files:**

- Create: `core/web/services/agent_model_promotion_service.py`
- Modify: `core/web/routes/agents.py`
- Modify: `core/web/services/agent_config_workspace_service.py`
- Modify: `core/web/services/agent_directory_service.py`
- Test: `tests/test_agent_model_promotion_service.py`
- Test: `tests/test_agent_config_workspace_routes.py`
- Test: `tests/test_agent_llm_runtime.py`
- Test: `tests/test_agent_directory_service.py`

**Interfaces:**

- Produces: `promote_agent_model(agent_id, slot, model_ref, expected_base_hash, expected_agent_updated_at, confirmed) -> dict`.
- Produces: `replace_agent_llm_bindings_if_current(agent_id, *, expected_updated_at, llm_bindings) -> dict` under the Agent registry lock.
- Adds: `POST /api/agents/{agent_id}/llm-bindings/{slot}/promote`.
- Returns: `status`, `modelRef`, `source`, `agent`, `operatorConfigHash`, `manifestPath`.
- Consumed by: Task 5 and Task 8 transaction reuse.

- [ ] **Step 1: Write promotion success and compensation RED tests**

```python
def test_observed_model_is_pinned_then_bound(monkeypatch, tmp_path):
    result = promote_agent_model(
        "agent-a",
        slot="dialogue",
        model_ref="ai-pixel/gpt-5.6-luna",
        expected_base_hash=_saved_hash(),
        expected_agent_updated_at="2026-07-13T00:00:00Z",
        confirmed=True,
        config_path=tmp_path / "config.toml",
    )
    assert result["status"] == "completed"
    assert result["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert get_agent("agent-a")["llmBindings"]["dialogue"]["modelId"] == result["modelRef"]
    saved = load_public_config(tmp_path / "config.toml")
    assert saved["llm"]["providers"]["ai-pixel"]["models"]["gpt-5.6-luna"]["upstream_id"] == "gpt-5.6-luna"


def test_agent_write_failure_restores_config_and_original_binding(monkeypatch, tmp_path):
    before = (tmp_path / "config.toml").read_bytes()
    monkeypatch.setattr(promotion, "update_agent_instance", Mock(side_effect=RuntimeError("agent write failed")))
    with pytest.raises(RuntimeError, match="agent write failed"):
        promote_agent_model(
            "agent-a",
            slot="dialogue",
            model_ref="ai-pixel/gpt-5.6-luna",
            expected_base_hash=_saved_hash(),
            expected_agent_updated_at="2026-07-13T00:00:00Z",
            confirmed=True,
            config_path=tmp_path / "config.toml",
        )
    assert (tmp_path / "config.toml").read_bytes() == before
    assert get_agent("agent-a")["llmBindings"]["dialogue"]["modelId"] == "ai-pixel/old"
```

Also cover `confirmed=False`, stale config hash, stale Agent timestamp, an Agent write racing after preflight, stale/disappeared candidate, incompatible slot, catalog fingerprint mismatch, already-pinned fast path and rollback failure.

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_agent_model_promotion_service.py tests/test_agent_config_workspace_routes.py tests/test_agent_llm_runtime.py -q
```

Expected: FAIL because there is no promotion coordinator or route.

- [ ] **Step 3: Define the strict route payload**

```python
class AgentModelPromotionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modelRef: str
    expectedBaseHash: str
    expectedAgentUpdatedAt: str
    confirmed: bool = False


@router.post("/agents/{agent_id}/llm-bindings/{slot}/promote")
def agent_model_promote(agent_id: str, slot: str, payload: AgentModelPromotionPayload) -> dict:
    try:
        result = promote_agent_model(
            agent_id,
            slot=slot,
            model_ref=payload.modelRef,
            expected_base_hash=payload.expectedBaseHash,
            expected_agent_updated_at=payload.expectedAgentUpdatedAt,
            confirmed=payload.confirmed,
        )
        return _with_agent_workspace_cache_invalidated(result)
    except AgentNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (AgentModelPromotionConflict, AgentStateConflictError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
```

- [ ] **Step 4: Implement promotion preflight and safe pinned model materialization**

Preflight must re-read all canonical sources:

```python
def _promotion_preflight(agent_id, slot, model_ref, expected_base_hash, expected_agent_updated_at, config_path):
    agent = get_agent(agent_id, include_archived=False)
    if not agent:
        raise AgentNotFoundError(agent_id)
    if str(agent.get("updatedAt") or "") != str(expected_agent_updated_at):
        raise AgentModelPromotionConflict("Agent changed after the selection dialog opened")
    public_config = load_public_config(config_path)
    if public_config_hash(public_config) != str(expected_base_hash):
        raise AgentModelPromotionConflict("operator config changed after the selection dialog opened")
    catalog = load_model_catalog_state()
    candidate = next(
        (item for item in project_agent_model_candidates(public_config, catalog) if item["modelRef"] == model_ref),
        None,
    )
    if not candidate:
        raise AgentModelPromotionConflict("model candidate is no longer available")
    if candidate.get("catalogStale") is True or candidate.get("availability") in {"stale", "unavailable", "missing_remote"}:
        raise AgentModelPromotionConflict("model candidate catalog is stale or unavailable")
    compatibility = candidate.get("slotCompatibility", {}).get(slot, {})
    if compatibility.get("allowed") is not True:
        raise AgentModelPromotionConflict(str(compatibility.get("reasonCode") or "slot_incompatible"))
    return agent, public_config, candidate
```

Only verified capability facts may enter the pinned record:

```python
def _pinned_model_from_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    model = {
        "upstream_id": str(candidate["upstreamId"]),
        "label": str(candidate.get("label") or candidate["upstreamId"]),
        "enabled": True,
    }
    if candidate.get("verificationStatus") == "verified":
        confirmed = {
            key: value
            for key, value in dict(candidate.get("capabilities") or {}).items()
            if isinstance(value, dict) and value.get("source") in {"runtime_probe", "operator_override"}
        }
        if confirmed:
            model["capabilities"] = confirmed
    if candidate.get("capabilityStatus") in {"confirmed", "verified"} and candidate.get("reasoningEffortValues"):
        model["defaults"] = {
            "reasoning_effort_values": list(candidate["reasoningEffortValues"]),
            "default_reasoning_effort": str(candidate.get("defaultReasoningEffort") or ""),
            "reasoning_effort_adapter": str(candidate.get("reasoningAdapter") or "none"),
            "reasoning_effort_map": dict(candidate.get("reasoningEffortMap") or {}),
        }
    return model
```

- [ ] **Step 5: Coordinate config and Agent participants**

Add a compare-and-swap helper that rechecks `updatedAt` inside `_STATE_LOCK`. Both normal apply and rollback use it, so neither can overwrite an unrelated concurrent Agent edit:

```python
class AgentStateConflictError(AgentDirectoryError):
    """Raised when an Agent changes during a compare-and-swap update."""


def replace_agent_llm_bindings_if_current(
    agent_id: str,
    *,
    expected_updated_at: str,
    llm_bindings: dict[str, Any],
) -> dict[str, Any]:
    with _STATE_LOCK:
        state = load_state()
        agent = _find_agent(state, agent_id)
        if agent is None:
            raise AgentNotFoundError(f"Agent not found: {agent_id}")
        if str(agent.get("updatedAt") or "") != str(expected_updated_at):
            raise AgentStateConflictError("Agent changed during model promotion")
        agent["llmBindings"] = normalize_agent_llm_bindings(llm_bindings)
        agent["updatedAt"] = utc_now_iso()
        save_state(state)
        return _agent_to_api(agent)
```

Already-pinned models call this helper directly and never write operator config. Observed models append one TOML table, reload, resolve the new modelRef, then apply the Agent participant:

```python
old_bindings = normalize_agent_llm_bindings(agent.get("llmBindings"))
new_bindings = copy.deepcopy(old_bindings)
new_bindings[slot] = {"modelId": candidate["modelRef"]}
binding_write: dict[str, str] = {}


def apply_binding() -> None:
    updated = replace_agent_llm_bindings_if_current(
        agent_id,
        expected_updated_at=expected_agent_updated_at,
        llm_bindings=new_bindings,
    )
    binding_write["updatedAt"] = str(updated["updatedAt"])


def rollback_binding() -> None:
    replace_agent_llm_bindings_if_current(
        agent_id,
        expected_updated_at=binding_write["updatedAt"],
        llm_bindings=old_bindings,
    )

participant = TransactionParticipant(
    name="agent_binding",
    apply=apply_binding,
    verify=lambda: _assert_agent_binding(agent_id, slot, candidate["modelRef"]),
    rollback=rollback_binding,
)

prepared = prepare_operator_config_transaction(
    operation_kind="model_promotion",
    expected_base_hash=expected_base_hash,
    config_path=config_path,
    mutate_text=lambda text: append_toml_table(
        text,
        ("llm", "providers", candidate["providerId"], "models", candidate["modelKey"]),
        _pinned_model_from_candidate(candidate),
    ),
)
result = apply_operator_config_transaction(prepared, participants=[participant])
```

After success invalidate Agent/config caches and emit `config.model.promotion_completed` plus `agent.llm_binding.updated`. Failure emits one bounded event with phase/reasonCode; it never logs the raw TOML or secret.

- [ ] **Step 6: Run GREEN and commit Task 4**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_agent_model_promotion_service.py tests/test_agent_config_workspace_routes.py tests/test_agent_llm_runtime.py tests/test_agent_directory_service.py tests/test_model_reference_service.py -q
git add core/web/services/agent_model_promotion_service.py core/web/routes/agents.py core/web/services/agent_config_workspace_service.py core/web/services/agent_directory_service.py tests/test_agent_model_promotion_service.py tests/test_agent_config_workspace_routes.py tests/test_agent_llm_runtime.py tests/test_agent_directory_service.py
git commit -m "feat(agent): promote discovered model bindings"
```

Expected: PASS; a successful operation leaves both facts valid, every failure leaves the original binding/config valid, and an already-pinned selection does not write operator config.

**Review Gate:** Reject any path that updates Agent first, pins every discovered model, bypasses the confirmation boolean, or allows stale catalog/config/Agent state.

---

### Task 5: Replace the Agent model select with a Provider-grouped candidate picker

**Files:**

- Create: `web/src/routes/AgentModelPicker.tsx`
- Create: `web/src/routes/AgentModelPicker.styles.ts`
- Create: `web/src/routes/AgentModelPicker.test.tsx`
- Create: `web/src/routes/configDraftPresence.ts`
- Create: `web/src/routes/configDraftPresence.test.ts`
- Modify: `web/src/routes/AgentCoreConfigPanel.tsx`
- Modify: `web/src/routes/AgentCoreConfigPanel.styles.ts`
- Modify: `web/src/routes/AgentsRoute.tsx`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Modify: `web/src/routes/AgentsRoute.layout.test.ts`

**Interfaces:**

- Produces: `AgentModelPicker` grouped by `providerId` with search/status/disabled reason.
- Produces: `publishConfigDraftPresence(dirty: boolean)` and `readConfigDraftPresence()`; only a boolean/timestamp is stored.
- Consumes: Task 4 promotion route and Task 2 candidate DTO.

- [ ] **Step 1: Write picker and draft-presence RED tests**

```typescript
it("groups all Ai-Pixel candidates and marks observed models as fixed-on-select", () => {
  const html = renderToStaticMarkup(
    <AgentModelPicker
      candidates={candidates}
      slot="dialogue"
      selectedModelRef="ai-pixel/image2"
      disabled={false}
      pendingModelRef=""
      configDraftDirty={false}
      onSelectPinned={() => undefined}
      onPromote={() => undefined}
    />,
  );
  expect(html).toContain("Ai-Pixel");
  expect(html).toContain("Luna");
  expect(html).toContain("Sol");
  expect(html).toContain("Terra");
  expect(html).toContain("固定并选择");
  expect(html).toContain("non_dialogue_model");
});


it("shares only dirty presence and never serializes config content", () => {
  publishConfigDraftPresence(true, { now: () => 1000, storage });
  expect(readConfigDraftPresence({ now: () => 1001, storage })).toBe(true);
  expect(storage.getItem(CONFIG_DRAFT_PRESENCE_KEY)).not.toContain("publicConfig");
});
```

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/routes/AgentModelPicker.test.tsx src/routes/configDraftPresence.test.ts src/routes/AgentsRoute.layout.test.ts
```

Expected: FAIL because Agent settings still use a flat native select and there is no cross-route dirty indicator.

- [ ] **Step 3: Implement the bounded Config draft presence signal**

```typescript
export const CONFIG_DRAFT_PRESENCE_KEY = "vibelution.config-draft-presence.v1";
const MAX_AGE_MS = 30 * 60 * 1000;

export function publishConfigDraftPresence(
  dirty: boolean,
  deps = { now: () => Date.now(), storage: window.localStorage },
) {
  deps.storage.setItem(CONFIG_DRAFT_PRESENCE_KEY, JSON.stringify({ dirty, updatedAt: deps.now() }));
}

export function readConfigDraftPresence(
  deps = { now: () => Date.now(), storage: window.localStorage },
) {
  try {
    const value = JSON.parse(deps.storage.getItem(CONFIG_DRAFT_PRESENCE_KEY) || "{}");
    return value.dirty === true && deps.now() - Number(value.updatedAt || 0) <= MAX_AGE_MS;
  } catch {
    return false;
  }
}
```

In `ConfigRoute`, publish `hasUnsavedConfigChanges || hasPendingSecretChanges(draftMeta)` in an effect and publish `false` after a successful apply. Do not store config text, secret state or draft hashes.

- [ ] **Step 4: Build the accessible grouped picker**

Use one dialog/listbox with stable grouping:

```typescript
const groups = useMemo(() => groupAgentModelCandidates(candidates, slot, query), [candidates, query, slot]);

return (
  <div className={styles.root}>
    <VButton aria-haspopup="dialog" aria-expanded={open} onPress={() => setOpen(true)}>
      {selected?.label || selectedModelRef || "选择模型"}
    </VButton>
    {open ? (
      <div role="dialog" aria-label="选择 Agent 模型" className={styles.dialog}>
        <VNativeInput value={query} onChange={(event) => setQuery(event.target.value)} aria-label="搜索模型" />
        <div role="listbox" className={styles.list}>
          {groups.map((group) => (
            <section key={group.providerId} aria-label={group.providerLabel}>
              <h4>{group.providerLabel}</h4>
              {group.items.map((candidate) => (
                <AgentModelCandidateRow
                  key={candidate.modelRef}
                  candidate={candidate}
                  selected={candidate.modelRef === selectedModelRef}
                  pending={candidate.modelRef === pendingModelRef}
                  onPress={() => candidate.runtimeSelectable
                    ? onSelectPinned(candidate.modelRef)
                    : onPromote(candidate)}
                />
              ))}
            </section>
          ))}
        </div>
      </div>
    ) : null}
  </div>
);
```

Rows display `pinned/discovered/stale/unverified/unavailable` text, `upstreamId`, effort values and an explicit disabled reason. Escape closes and returns focus; keyboard arrows move among enabled options.

- [ ] **Step 5: Integrate promotion without losing other Agent edits**

Extend `AgentCoreConfigLlmSlotView` with the full candidates instead of native options. Block promotion when the Config draft presence is dirty or the Agent form itself is dirty:

```typescript
const promotionMutation = useMutation({
  mutationFn: ({ candidate, slot }: { candidate: AgentModelChoice; slot: AgentLlmSlotDefinition }) =>
    fetchJson<AgentModelPromotionResult>(
      `/api/agents/${encodeURIComponent(selectedAgent.agentId)}/llm-bindings/${encodeURIComponent(slot.slot)}/promote`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          modelRef: candidate.modelRef,
          expectedBaseHash: workspace?.operatorConfigHash || "",
          expectedAgentUpdatedAt: selectedAgent.updatedAt,
          confirmed: true,
        }),
      },
    ),
  onSuccess: async () => {
    await queryClient.invalidateQueries({ queryKey: queryKeys.agentConfigWorkspace() });
    setNotice({ tone: "success", text: "模型已固定并绑定到 Agent。" });
  },
});
```

Before mutation, show a confirmation summary containing Provider, upstream ID, modelRef and “将修改 operator config + 当前 Agent”。If `configDraftDirty || configDirty`, show “请先保存或放弃未保存修改” and do not call the API.

- [ ] **Step 6: Run GREEN and commit Task 5**

```powershell
npm --prefix web test -- src/routes/AgentModelPicker.test.tsx src/routes/configDraftPresence.test.ts src/routes/AgentsRoute.layout.test.ts src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
git add web/src/routes/AgentModelPicker.tsx web/src/routes/AgentModelPicker.styles.ts web/src/routes/AgentModelPicker.test.tsx web/src/routes/configDraftPresence.ts web/src/routes/configDraftPresence.test.ts web/src/routes/AgentCoreConfigPanel.tsx web/src/routes/AgentCoreConfigPanel.styles.ts web/src/routes/AgentsRoute.tsx web/src/routes/ConfigRoute.tsx web/src/routes/AgentsRoute.layout.test.ts
git commit -m "feat(agent): add provider model picker"
```

Expected: PASS and build exit `0`; the picker handles hundreds of models without horizontal overflow, and promotion cannot discard either Config or Agent drafts.

**Review Gate:** Reject a flat unsearchable native select, hidden incompatible models, color-only status, or a promotion that silently saves unrelated Agent fields.

---

### Task 6: Make Session reasoning effort the only chat-time selection

**Files:**

- Modify: `config/models.py`
- Modify: `config/public_config.py`
- Modify: `core/llm/reasoning_effort.py`
- Modify: `core/llm/adapters.py`
- Modify: `core/llm/agent_runtime.py`
- Modify: `core/web/routes/sessions.py`
- Modify: `core/web/services/session_service.py`
- Test: `tests/test_session_llm_selection.py`
- Test: `tests/test_agent_llm_runtime.py`
- Test: `tests/test_llm_payload_builder.py`
- Test: `tests/test_session_detail_contract.py`

**Interfaces:**

- Replaces: `SessionLlmSelectionPayload(modelId, reasoningEffort)` with `SessionReasoningEffortPayload(reasoningEffort)`.
- Produces: `PATCH /api/sessions/{session_id}/reasoning-effort`.
- Produces: `resolve_reasoning_effort_request(profile) -> ReasoningEffortResolution`.
- Session model is always read from the bound Agent; the Session record stores only `reasoning_effort`.
- Consumed by: Task 7.

- [ ] **Step 1: Rewrite the current tests as the new RED contract**

```python
def test_session_effort_update_never_writes_agent(monkeypatch):
    update_agent_calls = []
    monkeypatch.setattr(session_service, "update_agent_instance", lambda *args, **kwargs: update_agent_calls.append((args, kwargs)))
    monkeypatch.setattr(session_service, "_is_session_running", lambda _session_id: False)
    monkeypatch.setattr(session_service, "_session_fixed_model_choice", lambda *_args: _reasoning_model_choice())
    _install_chat_state(monkeypatch, reasoning_effort="medium")

    payload = session_service.update_session_reasoning_effort("session-live", reasoning_effort="high")

    assert payload["currentModelId"] == "ai-pixel/gpt-5.6-luna"
    assert payload["currentReasoningEffort"] == "high"
    assert payload["model"]["modelRef"] == "ai-pixel/gpt-5.6-luna"
    assert "models" not in payload
    assert update_agent_calls == []
    assert _saved_conversation()["reasoning_effort"] == "high"


def test_two_sessions_keep_independent_efforts(monkeypatch):
    _install_two_sessions(monkeypatch, first="low", second="high")
    session_service.update_session_reasoning_effort("session-a", reasoning_effort="medium")
    assert _saved_effort("session-a") == "medium"
    assert _saved_effort("session-b") == "high"
```

Add payload tests for `reasoning_object`, `reasoning_effort`, `thinking_toggle` and `none` adapters, including requested/effective mapping.

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_llm_selection.py tests/test_agent_llm_runtime.py tests/test_llm_payload_builder.py -q
```

Expected: FAIL because the current Session route rewrites Agent model/binding metadata.

- [ ] **Step 3: Add typed model-level reasoning adapter fields**

Add the same typed contract to `PinnedModelDefaults` and `LLMProfile`, then copy it from the selected pinned model in `config_for_agent_llm_model()`:

```python
reasoning_effort_values: List[str] = Field(default_factory=list)
default_reasoning_effort: str = ""
reasoning_effort_adapter: Literal["", "reasoning_object", "reasoning_effort", "thinking_toggle", "none"] = ""
reasoning_effort_map: Dict[str, str] = Field(default_factory=dict)
```

Replace the inline constructor comprehension with an explicit, complete override key list:

```python
selected_payload = current_primary.model_dump()
for key in (
    "transport",
    "contract",
    "protocol",
    "compat",
    "reasoning_state_field",
    "strict_compatibility",
    "temperature",
    "max_output_tokens",
    "timeout",
    "connect_timeout",
    "streaming",
    "tool_calling_mode",
    "discovery_enabled",
    "prompt_cache",
    "thinking_type",
    "thinking_display",
    "reasoning_effort",
    "reasoning_effort_values",
    "default_reasoning_effort",
    "reasoning_effort_adapter",
    "reasoning_effort_map",
    "supports_image_input",
):
    if key in entry:
        selected_payload[key] = copy.deepcopy(entry[key])
selected_payload.update(
    {
        "profile_id": runtime_profile_id,
        "provider_id": provider_id,
        "model_ref": normalized_model_id,
        "model": model_name,
        "api_key_env": str(entry.get("api_key_env") or "").strip(),
        "prompt_cache": entry.get("prompt_cache") if "prompt_cache" in entry else PromptCacheConfig(),
    }
)
selected = LLMProfile(**selected_payload)
```

Validators normalize values with `normalize_reasoning_effort()`, require the configured default and every map key to appear in `reasoning_effort_values`, and validate adapter-specific targets: `thinking_toggle` accepts only `on/off`, while effort adapters accept the known upstream effort enum. An empty values list forces adapter `none` and an empty default/map.

- [ ] **Step 4: Centralize requested/effective mapping**

```python
@dataclass(frozen=True)
class ReasoningEffortResolution:
    requested: str
    effective: str
    adapter: str
    payload: dict[str, Any]


def resolve_reasoning_effort_request(profile: Any) -> ReasoningEffortResolution:
    requested = normalize_reasoning_effort(getattr(profile, "reasoning_effort", ""))
    adapter = str(getattr(profile, "reasoning_effort_adapter", "") or "none").strip().lower()
    mapping = dict(getattr(profile, "reasoning_effort_map", {}) or {})
    effective = str(mapping.get(requested) or requested).strip().lower()
    if not requested or adapter == "none":
        return ReasoningEffortResolution(requested, "", "none", {})
    if adapter == "reasoning_object":
        return ReasoningEffortResolution(requested, effective, adapter, {"reasoning": {"effort": effective}})
    if adapter == "reasoning_effort":
        return ReasoningEffortResolution(requested, effective, adapter, {"reasoning_effort": effective})
    if adapter == "thinking_toggle":
        return ReasoningEffortResolution(requested, effective, adapter, {"enable_thinking": effective not in {"off", "none"}})
    raise ValueError(f"unsupported reasoning effort adapter: {adapter}")
```

`ProviderAdapter.payload_thinking_parameters()` returns `.payload`. Its safe log fields include only `reasoningEffortRequested`, `reasoningEffortEffective` and `reasoningEffortAdapter`.

- [ ] **Step 5: Initialize Session effort once and take an immutable turn snapshot**

Project the stored scalar as `reasoningEffort` in `_normalize_conversation()` and `_build_session_summary()` without deriving it on every read. When a Session is created or first bound to an Agent, resolve `Agent slot default -> pinned/capability model default -> empty` and persist the first supported value once:

```python
def _initial_session_reasoning_effort(agent: dict[str, Any], model: dict[str, Any]) -> str:
    supported = [normalize_reasoning_effort(value) for value in model.get("reasoningEffortValues") or []]
    supported = [value for value in dict.fromkeys(supported) if value]
    agent_default = normalize_reasoning_effort(_session_agent_reasoning_effort(agent))
    model_default = normalize_reasoning_effort(model.get("defaultReasoningEffort"))
    return next((value for value in (agent_default, model_default) if value in supported), supported[0] if supported else "")


conversation["reasoning_effort"] = _initial_session_reasoning_effort(agent, fixed_model)
```

For an old Session that lacks the field, `_ensure_session_reasoning_effort_initialized(session_id)` performs the same resolution and persists it exactly once before the options response or the next submission. Later Agent default changes must not rewrite that field.

Change `get_session_llm_options()` to return the fixed Agent model rather than a switchable array:

```python
def get_session_llm_options(session_id: str) -> dict[str, Any]:
    _ensure_session_reasoning_effort_initialized(session_id)
    detail = get_session_detail(session_id, message_limit=0, transcript_scope="none")
    if detail is None:
        raise SessionNotFoundError(f"Session not found: {session_id}")
    model = _session_fixed_model_choice(session_id)
    return {
        "sessionId": str(session_id),
        "currentModelId": str(model.get("modelRef") or model.get("modelId") or ""),
        "currentReasoningEffort": normalize_reasoning_effort(detail.get("reasoningEffort")),
        "model": model,
    }
```

The update service mutates only the matching conversation and rechecks running state while holding `_CHAT_STATE_LOCK`:

```python
def update_session_reasoning_effort(session_id: str, *, reasoning_effort: str) -> dict[str, Any]:
    model = _session_fixed_model_choice(session_id)
    normalized = normalize_reasoning_effort(reasoning_effort)
    supported = set(model.get("reasoningEffortValues") or [])
    if normalized not in supported:
        raise SessionValidationError(f"模型 {model.get('label') or model.get('modelId')} 不支持推理强度 {normalized or '-'}。")
    with _CHAT_STATE_LOCK:
        if _is_session_running(session_id):
            raise SessionBusyError("会话运行中，不能切换推理强度。")
        payload = load_chat_state(PROJECT_ROOT)
        conversation = _require_raw_conversation(payload, session_id)
        conversation["reasoning_effort"] = normalized
        conversation["updated_at"] = _now_timestamp()
        save_chat_state(PROJECT_ROOT, payload)
    _invalidate_session_list_cache()
    return get_session_llm_options(session_id)
```

Read that persisted value once at worker start, then pass it to runtime resolution:

```python
session_reasoning_effort = _session_reasoning_effort_snapshot(session_id)
resolved_agent_llm = _resolve_session_agent_llm(
    agent_instance,
    llm_slot,
    reasoning_effort=session_reasoning_effort,
)
```

Add `reasoning_effort_override: str | None = None` to `resolve_agent_llm()`. The Session caller always passes the snapshot, including an empty string for models without reasoning; the resolver applies it after Agent/model defaults and records requested/effective values in `ResolvedAgentLlm.log_fields()`. Other callers that pass `None` keep existing Agent-default behavior.

- [ ] **Step 6: Replace the route and preserve a bounded compatibility response**

```python
class SessionReasoningEffortPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reasoningEffort: str


@router.patch("/sessions/{session_id}/reasoning-effort")
def session_reasoning_effort_update(session_id: str, payload: SessionReasoningEffortPayload) -> dict:
    try:
        return update_session_reasoning_effort(session_id, reasoning_effort=payload.reasoningEffort)
    except SessionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except SessionBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SessionValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Remove `/llm-selection` after its frontend consumer is migrated in the same integration sequence; do not leave a second write path.

- [ ] **Step 7: Run GREEN and commit Task 6**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_session_llm_selection.py tests/test_agent_llm_runtime.py tests/test_llm_payload_builder.py tests/test_session_detail_contract.py -q
git add config/models.py config/public_config.py core/llm/reasoning_effort.py core/llm/adapters.py core/llm/agent_runtime.py core/web/routes/sessions.py core/web/services/session_service.py tests/test_session_llm_selection.py tests/test_agent_llm_runtime.py tests/test_llm_payload_builder.py tests/test_session_detail_contract.py
git commit -m "feat(chat): scope reasoning effort to sessions"
```

Expected: PASS; changing Session A never changes its Agent or Session B, unsupported fields are not sent, and turn logs contain immutable requested/effective selection.

**Review Gate:** Reject any remaining Chat route that writes `llmBindings`, any name-only GPT heuristic that overrides explicit capability, or silent mapping without effective-value logs.

---

### Task 7: Render a Codex-style Chat Composer with a fixed model and effort menu

**Files:**

- Create: `web/src/components/conversation/ConversationInferenceControl.tsx`
- Create: `web/src/components/conversation/ConversationInferenceControl.styles.ts`
- Create: `web/src/components/conversation/ConversationInferenceControl.test.tsx`
- Delete: `web/src/components/conversation/ConversationModelSelector.tsx`
- Delete: `web/src/components/conversation/ConversationModelSelector.styles.ts`
- Delete: `web/src/components/conversation/ConversationModelSelector.test.tsx`
- Modify: `web/src/api/types/chat.ts`
- Modify: `web/src/components/conversation/conversationViewTypes.ts`
- Modify: `web/src/components/conversation/ConversationView.tsx`
- Modify: `web/src/components/conversation/ConversationView.styles.ts`
- Modify: `web/src/components/conversation/ConversationView.test.tsx`
- Modify: `web/src/routes/chat/ChatConversationComposerBridge.tsx`
- Modify: `web/src/routes/chat/ChatConversationComposerBridge.test.ts`
- Modify: `web/src/routes/ChatCodingRoute.tsx`
- Modify: `web/src/routes/ChatCodingRoute.layout.test.ts`

**Interfaces:**

- Replaces: `ConversationLlmControl.models/onSelectionChange` with one fixed `model/onReasoningEffortChange` contract.
- Adds: `composerVariant?: "compact" | "codex"` to `ConversationViewProps`.
- `ChatConversationComposerBridge` always passes `codex`; other callers receive `compact` by default.

- [ ] **Step 1: Write inference-control and shell RED tests**

```typescript
it("shows one fixed model and only opens its effort choices", () => {
  const html = renderToStaticMarkup(
    <ConversationInferenceControl
      model={luna}
      currentReasoningEffort="high"
      disabled={false}
      pending={false}
      onReasoningEffortChange={() => undefined}
    />,
  );
  expect(html).toContain("Luna 5.6");
  expect(html).toContain("高");
  expect(html).not.toContain("选择模型");
  expect(html).not.toContain("Sol");
});


it("keeps models without reasoning as a non-interactive label", () => {
  const html = renderToStaticMarkup(
    <ConversationInferenceControl
      model={{ ...luna, reasoningEffortValues: [], reasoningEffortOptions: [] }}
      currentReasoningEffort=""
      disabled={false}
      pending={false}
      onReasoningEffortChange={() => undefined}
    />,
  );
  expect(html).toContain("Luna 5.6");
  expect(html).not.toContain('aria-haspopup="listbox"');
});
```

Add source/layout assertions that Chat bridge passes `composerVariant="codex"`, compact callers do not, the codex shell has a single rounded container, and the action button is inside the bottom toolbar.

- [ ] **Step 2: Run the focused RED**

```powershell
npm --prefix web test -- src/components/conversation/ConversationInferenceControl.test.tsx src/components/conversation/ConversationView.test.tsx src/routes/chat/ChatConversationComposerBridge.test.ts src/routes/ChatCodingRoute.layout.test.ts
```

Expected: FAIL because the existing control can switch models and the send action sits outside the Composer field.

- [ ] **Step 3: Replace the DTO with a fixed-model control**

```typescript
export type SessionLlmOptions = {
  sessionId: string;
  currentModelId: string;
  currentReasoningEffort: string;
  model: SessionLlmModelOption | null;
};

export type ConversationLlmControl = {
  model: SessionLlmModelOption | null;
  currentReasoningEffort: string;
  disabled: boolean;
  pending: boolean;
  onReasoningEffortChange: (reasoningEffort: string) => void;
};

export type ConversationComposerVariant = "compact" | "codex";
```

Add `modelRef: string` and optional `reasoningAdapter`/`reasoningEffortMap` fields to the existing `SessionLlmModelOption`. Add `composerVariant?: ConversationComposerVariant` to the existing `ConversationViewProps`; no existing prop is removed or renamed.

- [ ] **Step 4: Implement the effort-only inference control**

```typescript
export function ConversationInferenceControl({
  model,
  currentReasoningEffort,
  disabled,
  pending,
  onReasoningEffortChange,
}: ConversationInferenceControlProps) {
  const [open, setOpen] = useState(false);
  const values = model?.reasoningEffortValues ?? [];
  const effective = values.includes(currentReasoningEffort)
    ? currentReasoningEffort
    : values.includes(model?.defaultReasoningEffort ?? "")
      ? model?.defaultReasoningEffort ?? ""
      : values[0] ?? "";
  const current = model?.reasoningEffortOptions.find((item) => item.value === effective);
  if (!model) return null;
  if (!values.length) return <span className={styles.fixedLabel}>{model.label || model.model}</span>;
  return (
    <div className={styles.root}>
      <VButton
        className={styles.trigger}
        isDisabled={disabled || pending}
        aria-haspopup="listbox"
        aria-expanded={open}
        onPress={() => setOpen((value) => !value)}
      >
        <span>{model.label || model.model}</span>
        <span>{current?.label || effective}</span>
        <ChevronDown size={13} aria-hidden="true" />
      </VButton>
      {open ? (
        <div role="listbox" className={styles.menu} aria-label="选择推理强度">
          {model.reasoningEffortOptions.map((option) => (
            <VButton
              key={option.value}
              role="option"
              aria-selected={option.value === effective}
              onPress={() => { onReasoningEffortChange(option.value); setOpen(false); }}
            >
              <span>{option.label}</span><small>{option.description}</small>
            </VButton>
          ))}
        </div>
      ) : null}
    </div>
  );
}
```

Add outside-pointer/Escape handling and focus return, copying the tested behavior from the deleted selector without retaining a models panel.

- [ ] **Step 5: Add the explicit Composer variant and one internal action renderer**

Default to compact and reuse one action subtree:

```typescript
const resolvedComposerVariant = composerVariant ?? "compact";
const renderComposerActions = () => (
  <div className={styles.composerActionStack}>
    {renderPrimaryComposerAction()}
    {renderStopComposerAction()}
  </div>
);

<div className={resolvedComposerVariant === "codex" ? styles.composerCodex : styles.composer}>
  <div className={resolvedComposerVariant === "codex" ? styles.composerFieldCodex : styles.composerField}>
    {renderComposerLayers()}
    <VNativeTextarea className={resolvedComposerVariant === "codex" ? styles.inputCodex : styles.input} />
    <div className={resolvedComposerVariant === "codex" ? styles.composerToolbarCodex : styles.composerToolbar}>
      <div className={styles.composerToolbarStart}>{renderAttachmentAction()}{renderRealModeStatus()}</div>
      <div className={styles.composerToolbarEnd}>
        {llmControl ? <ConversationInferenceControl {...llmControl} /> : null}
        {resolvedComposerVariant === "codex" ? renderComposerActions() : null}
      </div>
    </div>
  </div>
  {resolvedComposerVariant === "compact" ? renderComposerActions() : null}
</div>
```

The extracted local render functions must contain the existing attachment/edit/reference/slash/action behavior unchanged; do not duplicate handlers.

- [ ] **Step 6: Apply the Codex shell tokens and responsive contract**

```typescript
composerCodex: cv(
  "composerCodex",
  "mx-auto grid w-full max-w-[960px] min-w-0 rounded-[24px] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] shadow-[var(--vui-elevation-panel)] max-[719px]:rounded-[18px]",
),
composerFieldCodex: cv("composerFieldCodex", "grid min-h-[120px] min-w-0 grid-rows-[auto_minmax(48px,1fr)_auto] gap-2 px-4 py-3"),
inputCodex: cv("inputCodex", "min-h-[48px] max-h-[220px] w-full resize-none overflow-y-auto border-0 bg-transparent p-0 text-[var(--fg-primary)] shadow-none focus:ring-0"),
composerToolbarCodex: cv("composerToolbarCodex", "flex min-h-10 min-w-0 items-center justify-between gap-2"),
composerToolbarStart: cv("composerToolbarStart", "flex min-w-0 items-center gap-2"),
composerToolbarEnd: cv("composerToolbarEnd", "ml-auto flex min-w-0 items-center justify-end gap-2"),
```

Use only VUI tokens. At `<720px`, low-priority mode text may hide, model label truncates, effort and the 36x36 action remain visible, and `scrollWidth <= innerWidth`.

- [ ] **Step 7: Change Chat mutation to effort-only and mark the bridge**

```typescript
const sessionReasoningEffortMutation = useMutation({
  mutationFn: ({ sessionId, reasoningEffort }: { sessionId: string; reasoningEffort: string }) =>
    fetchJson<SessionLlmOptions>(`/api/sessions/${encodeURIComponent(sessionId)}/reasoning-effort`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reasoningEffort }),
    }),
  onSuccess: (payload, variables) => {
    queryClient.setQueryData(queryKeys.sessionLlmOptions(variables.sessionId), payload);
    queryClient.setQueryData<SessionDetail>(queryKeys.session(variables.sessionId), (current) => current
      ? { ...current, reasoningEffort: payload.currentReasoningEffort }
      : current);
  },
});
```

Build `llmControl` with `model: sessionLlmOptions?.model ?? null` and `onReasoningEffortChange`. In `ChatConversationComposerBridge`, pass `composerVariant="codex"`; no other caller passes it.

- [ ] **Step 8: Run GREEN, build and commit Task 7**

```powershell
npm --prefix web test -- src/components/conversation/ConversationInferenceControl.test.tsx src/components/conversation/ConversationView.test.tsx src/routes/chat/ChatConversationComposerBridge.test.ts src/routes/ChatCodingRoute.layout.test.ts
npm --prefix web run build
git add web/src/api/types/chat.ts web/src/components/conversation/conversationViewTypes.ts web/src/components/conversation/ConversationInferenceControl.tsx web/src/components/conversation/ConversationInferenceControl.styles.ts web/src/components/conversation/ConversationInferenceControl.test.tsx web/src/components/conversation/ConversationView.tsx web/src/components/conversation/ConversationView.styles.ts web/src/components/conversation/ConversationView.test.tsx web/src/routes/chat/ChatConversationComposerBridge.tsx web/src/routes/chat/ChatConversationComposerBridge.test.ts web/src/routes/ChatCodingRoute.tsx web/src/routes/ChatCodingRoute.layout.test.ts
git rm web/src/components/conversation/ConversationModelSelector.tsx web/src/components/conversation/ConversationModelSelector.styles.ts web/src/components/conversation/ConversationModelSelector.test.tsx
git commit -m "feat(chat): add fixed-model Codex composer"
```

Expected: tests PASS and build exits `0`; main Chat has a Codex shell, compact embedded conversations are unchanged, and no UI path can change the Agent model.

**Review Gate:** Reject route-detected CSS, duplicated Composer markup, a fake permission label, an inert microphone, or any model-switching menu in Chat.

---

### Task 8: Add a previewed and reversible duplicate Provider merge

**Files:**

- Create: `config/provider_merge_migration.py`
- Modify: `core/web/services/provider_config_service.py`
- Modify: `core/web/routes/config.py`
- Modify: `web/src/api/types/config.ts`
- Modify: `web/src/routes/configProviderLogic.ts`
- Modify: `web/src/routes/configProviderLogic.test.ts`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.tsx`
- Modify: `web/src/routes/ConfigProviderRegistryPanel.test.tsx`
- Modify: `web/src/routes/ConfigRoute.tsx`
- Test: `tests/test_provider_merge_migration.py`
- Test: `tests/test_provider_config_service.py`
- Test: `tests/test_web_config_routes.py`

**Interfaces:**

- Produces: `preview_provider_merge(*, canonical_provider_id, duplicate_provider_ids, credential_decisions, config_path=CONFIG_PATH, project_root=PROJECT_ROOT) -> ProviderMergePreview`.
- Produces: `apply_provider_merge(preview_id, *, expected_base_hash, confirmed, config_path=CONFIG_PATH, project_root=PROJECT_ROOT) -> dict[str, Any]`.
- Produces: `rollback_provider_merge(migration_id, *, expected_current_hash, config_path=CONFIG_PATH, project_root=PROJECT_ROOT) -> dict[str, Any]`.
- Adds: `/api/config/migration/providers/merge/preview|apply|{migrationId}/rollback`.
- Reuses: Task 3 source-preserving transaction and existing `build_model_reference_rewrite_plan()`.

- [ ] **Step 1: Write merge preview/apply/rollback RED tests**

```python
def test_preview_maps_duplicate_luna_to_canonical_provider_without_touching_history(tmp_path):
    preview = preview_provider_merge(
        canonical_provider_id="ai-pixel",
        duplicate_provider_ids=["ai-pixel_ad214f09"],
        credential_decisions={"ai-pixel_ad214f09": "use_canonical"},
        config_path=_write_ai_pixel_config(tmp_path),
        project_root=tmp_path,
    )
    assert preview.status == "READY"
    assert preview.model_ref_map == {
        "ai-pixel_ad214f09/gpt-5.6-luna": "ai-pixel/gpt-5.6-luna",
    }
    assert preview.historical_reference_count > 0
    assert preview.historical_rewrite_count == 0


def test_merge_preserves_comments_rewrites_live_refs_and_can_rollback(tmp_path):
    config_path = _write_ai_pixel_config(tmp_path, comment="# keep operator note")
    preview = _ready_preview(config_path, tmp_path)
    applied = apply_provider_merge(
        preview.preview_id,
        expected_base_hash=preview.base_hash,
        confirmed=True,
        config_path=config_path,
        project_root=tmp_path,
    )
    text = config_path.read_text(encoding="utf-8")
    assert "# keep operator note" in text
    assert "ai-pixel_ad214f09" not in tomllib.loads(text)["llm"]["providers"]
    assert _agent_binding(tmp_path) == "ai-pixel/gpt-5.6-luna"
    rolled_back = rollback_provider_merge(applied["migrationId"], expected_current_hash=applied["hash"], config_path=config_path)
    assert rolled_back["status"] == "rolled_back"
    assert "ai-pixel_ad214f09" in tomllib.loads(config_path.read_text(encoding="utf-8"))["llm"]["providers"]


def test_failed_precommit_probe_leaves_config_and_references_untouched(monkeypatch, tmp_path):
    config_path = _write_ai_pixel_config(tmp_path)
    before_config = config_path.read_bytes()
    before_agent = _agent_registry_path(tmp_path).read_bytes()
    preview = _ready_preview(config_path, tmp_path)
    monkeypatch.setattr(migration, "run_draft_llm_test", lambda *_args, **_kwargs: {"ok": False, "status": 503})
    with pytest.raises(ProviderMergeVerificationError):
        apply_provider_merge(
            preview.preview_id,
            expected_base_hash=preview.base_hash,
            confirmed=True,
            config_path=config_path,
            project_root=tmp_path,
        )
    assert config_path.read_bytes() == before_config
    assert _agent_registry_path(tmp_path).read_bytes() == before_agent
```

Cover endpoint mismatch, credential mismatch without decision, model-key collision, stale preview, active reference hash drift, bounded callability failure and rollback reload failure.

- [ ] **Step 2: Run the focused RED**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_provider_merge_migration.py tests/test_provider_config_service.py tests/test_web_config_routes.py -q
```

Expected: FAIL because duplicate Provider merge does not exist.

- [ ] **Step 3: Build a deterministic preview**

```python
@dataclass(frozen=True)
class ProviderMergePreview:
    preview_id: str
    status: str
    base_hash: str
    canonical_provider_id: str
    duplicate_provider_ids: tuple[str, ...]
    model_ref_map: dict[str, str]
    models_to_add: tuple[dict[str, Any], ...]
    live_references: tuple[dict[str, Any], ...]
    historical_references: tuple[dict[str, Any], ...]
    conflicts: tuple[dict[str, str], ...]
    required_probe_model_ref: str


def _target_model_key(canonical_models, duplicate_key, duplicate_model):
    upstream_id = str(duplicate_model.get("upstream_id") or "")
    for model_key, model in canonical_models.items():
        if isinstance(model, dict) and str(model.get("upstream_id") or "") == upstream_id:
            return str(model_key), False
    candidate = make_model_key(upstream_id)
    if candidate in canonical_models:
        raise ValueError("canonical model key collision")
    return candidate, True
```

Preview must compare exact endpoint, driver, protocols and credential refs; differences become explicit conflicts. A `credential_decisions` entry resolves only credential choice and never proves endpoints equivalent.

- [ ] **Step 4: Build separate verification and final candidates**

The verification candidate adds missing canonical models but retains every duplicate Provider and every live reference. The final candidate starts from that verified shape, patches structured public-config scalar refs using `replace_toml_scalar()`, then removes duplicate Provider table trees:

```python
def _merge_verification_text(text: str, preview: ProviderMergePreview) -> str:
    candidate = text
    for model in preview.models_to_add:
        candidate = append_toml_table(
            candidate,
            ("llm", "providers", preview.canonical_provider_id, "models", model["modelKey"]),
            model["pinnedModel"],
        )
    tomllib.loads(candidate)
    return candidate


def _merge_final_text(
    text: str,
    preview: ProviderMergePreview,
    reference_plan: ModelReferenceRewritePlan,
) -> str:
    candidate = _merge_verification_text(text, preview)
    candidate = _patch_public_config_reference_scalars(candidate, preview.model_ref_map, reference_plan.public_config)
    for provider_id in preview.duplicate_provider_ids:
        candidate = remove_toml_table_tree(candidate, ("llm", "providers", provider_id))
    tomllib.loads(candidate)
    return candidate
```

Create a transaction participant around `reference_plan.file_rewrites`: apply only if all before hashes match, verify every live reference moved, and rollback exact `before_bytes` in reverse order.

- [ ] **Step 5: Discover and call the canonical model before any live mutation**

Parse the verification candidate in memory. Against that draft, run canonical discovery and require Luna, Sol and Terra to be present, then reuse the existing bounded draft probe for the canonical Luna modelRef. Only after both checks pass may the final transaction write operator config or reference files:

```python
source_bytes = Path(config_path).read_bytes()
source_public = tomllib.loads(source_bytes.decode("utf-8"))
if public_config_hash(source_public) != preview.base_hash:
    raise ProviderMergeConflictError("operator config changed after merge preview")
reference_plan = build_model_reference_rewrite_plan(
    preview.model_ref_map,
    public_config=source_public,
    project_root=project_root,
)
reference_participant = _model_reference_transaction_participant(reference_plan)
verification_text = _merge_verification_text(source_bytes.decode("utf-8"), preview)
verification_public = tomllib.loads(verification_text)
scratch_catalog = _merge_scratch_catalog_path(preview.preview_id)
try:
    discovered = discover_provider_models(
        verification_public,
        preview.canonical_provider_id,
        catalog_path=scratch_catalog,
    )
finally:
    scratch_catalog.unlink(missing_ok=True)
required = {"gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra"}
if not required.issubset({item.upstream_id for item in discovered.models}):
    raise ProviderMergeVerificationError("canonical Provider discovery is incomplete")
probe = run_draft_llm_test(verification_public, model_id=preview.required_probe_model_ref)
if not bool(probe.get("ok")):
    raise ProviderMergeVerificationError(_bounded_probe_reason(probe))

prepared = prepare_operator_config_transaction(
    operation_kind="provider_merge",
    expected_base_hash=preview.base_hash,
    config_path=config_path,
    mutate_text=lambda text: _merge_final_text(text, preview, reference_plan),
)
result = apply_operator_config_transaction(prepared, participants=[reference_participant])
```

`_merge_scratch_catalog_path()` resolves inside the migration preview directory, never to the live catalog, and is deleted after the check. Discovery or probe failure exits before backup/write/apply. A later transaction or live-reference verification failure restores exact config/reference bytes. Diagnostics retain only candidate IDs, error type/status and phase; no response body or secret is stored.

- [ ] **Step 6: Add strict migration routes and Config UI**

```python
class ProviderMergePreviewPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonicalProviderId: str
    duplicateProviderIds: list[str]
    credentialDecisions: dict[str, Literal["use_canonical", "keep_separate"]] = Field(default_factory=dict)


class ProviderMergeApplyPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previewId: str
    baseHash: str
    confirmed: bool
```

The Provider panel shows canonical/duplicate IDs, endpoints, credential refs, models to add, live/historical counts and conflicts. Apply remains disabled until `status === "READY"`, `confirmed === true`, and the current Config draft is clean. Success offers a rollback button tied to `migrationId` and result hash.

- [ ] **Step 7: Run GREEN, frontend tests/build, and commit Task 8**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_provider_merge_migration.py tests/test_provider_config_service.py tests/test_web_config_routes.py tests/test_model_reference_service.py -q
npm --prefix web test -- src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
git add config/provider_merge_migration.py core/web/services/provider_config_service.py core/web/routes/config.py web/src/api/types/config.ts web/src/routes/configProviderLogic.ts web/src/routes/configProviderLogic.test.ts web/src/routes/ConfigProviderRegistryPanel.tsx web/src/routes/ConfigProviderRegistryPanel.test.tsx web/src/routes/ConfigRoute.tsx tests/test_provider_merge_migration.py tests/test_provider_config_service.py tests/test_web_config_routes.py
git commit -m "feat(config): add reversible provider merge"
```

Expected: all tests PASS and build exits `0`; preview is deterministic, historical records remain unchanged, discovery/callability pass before live mutation, the final transaction leaves zero duplicate live refs, and rollback restores exact bytes.

**Review Gate:** Reject endpoint equivalence inferred only from `/v1`, credential equality inferred from environment variable names, historical rewrites, or any live config/reference mutation before callability verification.

---

### Task 9: Integrate, refresh, verify real models, and gate the live merge

**Files:**

- Create at runtime: `logs/runtime_scenes/<timestamp>-agent-provider-chat-composer/manifest.json`
- Create at runtime: browser screenshots listed below
- Update only through the project-memory owner: relevant `.docs/project-memory/` proposal/sync

**Interfaces:**

- Consumes: integrated Tasks 1-8.
- Produces: focused test evidence, build evidence, Launcher state, browser screenshots, real Luna/Sol/Terra calls, effort wire evidence, merge preview, and final claim/memory reconciliation.

- [ ] **Step 1: Reconcile branches and re-run hot-file claim checks**

Use the task graph order. Before merging a Task touching a hot file, run:

```powershell
py -3 "C:\Users\17533\.codex\skills\ccdawn-dawn-agent-html-memory\scripts\agent_work_guard.py" "C:\Users\17533\Desktop\Vibelution" check --lane "llm-provider-model-config" --scope "core/web/services/agent_directory_service.py" --scope "core/web/services/session_service.py" --scope "web/src/routes/AgentsRoute.tsx" --scope "web/src/components/conversation/ConversationView.tsx"
```

Expected: no overlapping active/ready claim. If overlap exists, stop that merge and reconcile with the owner; do not overwrite.

- [ ] **Step 2: Run the complete focused backend gate**

```powershell
C:\Users\17533\Desktop\Vibelution\.venv\Scripts\python.exe -m pytest tests/test_llm_identity.py tests/test_provider_discovery_adapters.py tests/test_model_catalog.py tests/test_agent_model_candidate_service.py tests/test_agent_model_promotion_service.py tests/test_agent_config_workspace_service.py tests/test_agent_config_workspace_routes.py tests/test_agent_directory_service.py tests/test_operator_config_transaction.py tests/test_session_llm_selection.py tests/test_agent_llm_runtime.py tests/test_llm_payload_builder.py tests/test_session_detail_contract.py tests/test_provider_merge_migration.py tests/test_provider_config_service.py tests/test_web_config_routes.py tests/test_model_reference_service.py -q
```

Expected: PASS with no skipped task-owned test.

- [ ] **Step 3: Run the complete focused frontend gate and build**

```powershell
npm --prefix web test -- src/routes/AgentModelPicker.test.tsx src/routes/configDraftPresence.test.ts src/routes/AgentsRoute.layout.test.ts src/components/conversation/ConversationInferenceControl.test.tsx src/components/conversation/ConversationView.test.tsx src/routes/chat/ChatConversationComposerBridge.test.ts src/routes/ChatCodingRoute.layout.test.ts src/routes/configProviderLogic.test.ts src/routes/ConfigProviderRegistryPanel.test.tsx src/routes/ConfigRoute.layout.test.ts
npm --prefix web run build
```

Expected: tests PASS and build exits `0` without TypeScript/Vite errors.

- [ ] **Step 4: Perform scoped self-review before runtime refresh**

Review the integrated diff for these concrete failures:

```text
- Session route still accepts or writes modelId
- observed catalog writes operator config outside promotion
- TOML patch drops comments or unknown tables
- capability name heuristic becomes confirmed
- requested effort differs from effective effort without a log field
- Chat exposes a models panel
- compact Evolution/SelfEvolution receives codex styles
- migration manifest contains raw config, credential, prompt or provider payload
```

Expected: zero unresolved findings. Fix and rerun the affected focused gate before continuing.

- [ ] **Step 5: Refresh through Launcher**

Use the project Launcher refresh path. If the guard reports active work, output exactly:

```text
有进行中的任务，无法重启 Vibelution。请等待任务完成或先停止任务。
```

Do not force takeover unless the user provides `确认强制接管并刷新 Vibelution`.

- [ ] **Step 6: Capture browser evidence**

Save these screenshots in one bounded runtime-scene package:

```text
01-agent-picker-ai-pixel-1440x900.png
02-agent-promotion-confirm-1440x900.png
03-chat-codex-idle-light-1440x900.png
04-chat-codex-running-dark-1024x768.png
05-chat-codex-mobile-390x844.png
06-session-effort-isolation-1440x900.png
07-provider-merge-preview-1440x900.png
```

For every viewport assert `document.documentElement.scrollWidth <= window.innerWidth`. Also assert Luna/Sol/Terra are grouped under Ai-Pixel, Chat has no models panel, running disables effort, action position does not move, and Evolution/SelfEvolution retain compact Composer classes.

- [ ] **Step 7: Verify real model invocation and effort mapping**

Use the saved canonical Provider identity/credential and the existing bounded draft-model probe. For a model that is still observed-only, create one in-memory draft pinned entry for that upstream ID and do not save it to operator config. Invoke:

```text
ai-pixel/gpt-5.6-luna
ai-pixel/gpt-5.6-sol
ai-pixel/gpt-5.6-terra
```

Each call must return a non-empty minimal text result. For every model that declares at least two effort values, clone the in-memory draft twice with the requested `reasoning_effort`, invoke both values, and confirm the bounded payload trace records:

```json
{
  "modelRef": "ai-pixel/gpt-5.6-luna",
  "requestedEffort": "high",
  "effectiveEffort": "high",
  "reasoningEffortAdapter": "reasoning_object"
}
```

Do not persist the ephemeral model entries and do not save raw request/response bodies. A 4xx/5xx is a failed acceptance result, not a UI success.

- [ ] **Step 8: Generate the live Ai-Pixel merge preview and stop at the user gate**

Generate a fresh preview against the current operator config and report canonical Provider, duplicate Provider, endpoint/credential decisions, model mapping, live/historical reference counts and conflicts. Do not apply it until the user sends:

```text
确认应用 Ai-Pixel Provider 合并
```

After that exact confirmation, apply, verify Luna, rescan live references, and retain `migrationId`, result hash, manifest path and rollback action in the evidence package.

- [ ] **Step 9: Save bounded evidence and reconcile memory/claims**

Write `manifest.json` with commands, exit codes, branch/commit IDs, viewport/theme, session/turn IDs, modelRefs, requested/effective effort, migration ID/hash, screenshot names and event counts. Then sync or propose project memory under the single-writer rule and release every task claim.

Do not force-add ignored runtime logs. Commit only tracked documentation/memory files owned by the executing task.

**Review Gate:** Completion requires backend/frontend GREEN, successful build, Launcher refresh, seven screenshots, three real model calls, effort wire evidence, and—only after the exact user confirmation—a verified Provider merge with rollback evidence.

---

## Task Splitting Decision

**Decision:** `SPLIT` — one implementation task card per Agent, with the primary Agent reviewing each diff before integration.

**Critical Path:** `(Task 1 || Task 3) -> Task 2 -> Task 4 -> (Task 5 || Task 6) -> (Task 7 || Task 8) -> Task 9`

**Permitted parallelism:**

- Task 1 and Task 3 may run concurrently because their owned files are disjoint.
- After Task 4 lands, Task 5 and Task 6 may run concurrently; Task 5 owns Agent UI, Task 6 owns Session/runtime.
- Task 7 starts only after Task 6 because its API contract changes from model+effort to effort-only.
- Task 8 starts after Task 5 so its Config UI cannot overlap the `ConfigRoute.tsx` owner; it may then run concurrently with Task 7.
- Task 9 is serial integration/acceptance only.

| Task | Development mode | Independent test anchor | Primary risk |
| --- | --- | --- | --- |
| 1 | `BDD_TDD` | endpoint candidates + stop policy + fingerprint stale | masking auth/upstream errors or unsafe override |
| 2 | `BDD_TDD` | pinned/observed union and slot-disabled reason | catalog becoming a second writable config |
| 3 | `BDD_TDD` | exact-byte rollback and comment preservation | data loss in operator config |
| 4 | `BDD_TDD` | config/Agent compensation on every phase | dangling binding or partially pinned model |
| 5 | `BDD_TDD` | grouped picker + dirty-draft block | silent unrelated draft loss |
| 6 | `BDD_TDD` | two-Session isolation + wire mapping | Agent mutation or silent effort degradation |
| 7 | `BDD_TDD` | fixed model label + effort-only menu + compact regression | Chat model switch or shared Composer regression |
| 8 | `BDD_TDD` | preview/apply/rollback with reference zero | wrong Provider deletion or unrecoverable config |
| 9 | `SIMPLE` | focused gates, build, refresh, screenshots, real calls | claiming success without live evidence |

## Spec Coverage Audit

| Approved requirement | Owning task(s) | Evidence |
| --- | --- | --- |
| One Provider exposes all relay models | 1, 2 | discovery candidate tests and Agent candidate union |
| Agent fixed model chosen in Agent settings | 4, 5 | promotion transaction and grouped picker |
| Session-only reasoning override | 6, 7 | no Agent writes, two-session isolation, effort-only UI |
| Model-specific effort values/adapters | 1, 2, 6 | fingerprinted capability and requested/effective payload tests |
| Codex-style main Composer | 7 | component/layout tests and browser screenshots |
| Evolution/SelfEvolution remain compact | 7, 9 | explicit variant ownership and visual regression |
| No profile-style whole-config switching | 3, 4, 6 | source-preserving bounded transaction only for promotion/migration |
| Duplicate Ai-Pixel Provider migration | 8, 9 | preview/apply/rollback plus exact confirmation gate |
| No secret/raw payload logging | 1, 3, 4, 6, 8, 9 | bounded event/manifest tests and evidence review |
| Launcher and real model acceptance | 9 | refresh, screenshots, Luna/Sol/Terra calls |

## Self-Review

- [x] Every approved design section maps to a task and an observable test or runtime gate.
- [x] Function names, DTO field names and API paths are consistent across producers and consumers.
- [x] Existing project primitives are reused: catalog, modelRef, Agent registry, model reference plan, atomic IO, Launcher and bounded runtime scenes.
- [x] No task requires a new third-party dependency.
- [x] Normal Agent/Session operations cannot write operator config.
- [x] Promotion rechecks Agent `updatedAt` inside the registry lock and uses compare-and-swap rollback.
- [x] Session effort is initialized/migrated once and snapshotted at worker start; later Agent defaults cannot drift into it.
- [x] Provider discovery and Luna callability pass against an isolated draft before merge can mutate live config/references.
- [x] Live migration has a separate exact user confirmation gate.
- [x] Task boundaries permit one Agent per card without parallel writes to the same hot file.
- [x] Version impact remains a future minor release candidate; this planning commit changes no version metadata.

## Execution Handoff

Plan execution should use one fresh Agent per task card with a review gate between dependent tasks. Task 1 and Task 3 are the first eligible cards; their branches/worktrees must start from the same accepted-plan base, and Task 2 must rebase onto the reviewed Task 1 result before implementation.
