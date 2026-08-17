# Config / Provider / Model 迷你索引（R10）

**读者：coding Agent。**
**目标：30 秒内定位 operator config、Provider 草稿流、模型引用与主测；不要在 route 里堆业务。**

权威细则：[`docs/ops/config/INDEX.md`](../../../docs/ops/config/INDEX.md) · [`01-authority-and-paths.md`](../../../docs/ops/config/01-authority-and-paths.md) · ADR0003（operator config 真源）。
全量 facade 表：[`README.md`](README.md) § Config / Provider / Model / Theme。

---

## 30 秒编辑表

| 你在改… | 先打开 | 禁止 |
| --- | --- | --- |
| 改 Provider 注册 / 草稿 CRUD / 路由预览 | `provider_config_service.py` → `config/provider_merge_migration.py` · `config/model_config_migration.py` | 直接写 `%USERPROFILE%\Documents\Vibelution\config\config.toml` 绕过 draft/apply；在 route 复制 registry 逻辑 |
| 工作台 config 草稿 / apply / 模型 CRUD / LLM test | `config_service.py` → `config/public_config.py` · `config/model_catalog.py` | 把 provider registry 编排塞进 `config_service`；仓库根 `config.toml` 当运行时真源 |
| 删模型 / 重绑引用 / 引用冲突 | `model_reference_service.py` | 只扫单一 JSON 文件当全局 SSOT；忽略 live run 引用 |
| 模型能力推断（image-input 等） | `model_capability_service.py` | 在 UI/route 硬编码厂商表当唯一真相 |
| 头像 / 主题背景图存储 | `avatar_image_service.py` · `theme_background_service.py` | 把二进制路径写进 Prompt 或日志 |
| Agent ToolPolicy 配置投影 | `tool_policy_configuration_service.py`（route：`agents.py`） | 与 `tool_authorization_service` 双写 enforcement |
| Workbench 默认/可用性契约 | `workbench_contract_service.py` | 与 operator config 混为第二写入者 |
| Workbench UI 布局偏好（项目本地） | `workbench_ui_preferences_service.py` | 写 operator `config.toml` |
| HTTP 路由 / DTO | `core/web/routes/config.py` + `config_*_models.py` | route 直连 `config/` 包绕过 service；泄露完整 API key |

**「改 provider 挂哪？」** → `provider_config_service.py`（draft）+ `config/llm_provider_registry.py`（持久 registry）+ apply 经 `config_service.apply_config_workspace`；活跃文件始终是 operator `config.toml`（非仓库根 template）。

---

## 权威与边界

```text
Operator config 真源
  → %USERPROFILE%\Documents\Vibelution\config\config.toml
  → override: VIBELUTION_CONFIG_PATH | VIBELUTION_CONFIG_HOME
  → 仓库根 config.toml / config.example.toml = legacy template only

Draft → Apply 流（工作台）
  → route config.py 薄委托
  → config_service：workspace 投影、模型草稿、apply/preview、LLM test
  → provider_config_service：provider 草稿专用（draft-only registry orchestration）
  → public_config.build_effective_config / validate_* 为读侧真源

Model 生命周期
  → model_reference_service：删除/重绑前 workspace 级引用扫描
  → model_capability_service：单 record 能力推断（显式配置 > 启发式）

Secrets
  → API key 经 env alias + pending token；redaction 见 test_config_redaction
  → 禁止日志/Prompt 输出完整 key 或 operator config 全文
```

产品配置索引（键语义）：[`docs/ops/config/`](../../../docs/ops/config/)。

---

## 主测（可复制）

```powershell
# Provider 草稿 / registry / redaction
.\.venv\Scripts\python.exe -m pytest tests\test_provider_config_service.py tests\test_config_redaction.py tests\test_llm_config_v2_integration.py -q

# Config workspace / apply / routes
.\.venv\Scripts\python.exe -m pytest tests\test_agent_config_workspace_service.py tests\test_agent_config_workspace_routes.py tests\test_web_config_routes.py -q

# Model reference 生命周期
.\.venv\Scripts\python.exe -m pytest tests\test_model_reference_service.py tests\test_public_config_model_refs.py -q

# 影响面（改 facade 后）
.\.venv\Scripts\python.exe tests\select_tests.py --changed-file core/web/services/provider_config_service.py --commands-only
```

触 FE Config 面板时另跑：`web/` 下相关 colocated test +（若改可见 UI）`vuiShadcnRouteContract` + `npx tsc -b --pretty false`。

---

## 相关

| 文档 | 用途 |
| --- | --- |
| [`docs/ops/config/INDEX.md`](../../../docs/ops/config/INDEX.md) | operator config 键表 |
| [`docs/guides/loop.md`](../../../docs/guides/loop.md) | 验证/完成块 |
| [`docs/guides/agent-dev-roi-backlog.md`](../../../docs/guides/agent-dev-roi-backlog.md) | R10 DoD |
| [`launcher_runtime.md`](launcher_runtime.md) | 同类迷你索引范例 |
