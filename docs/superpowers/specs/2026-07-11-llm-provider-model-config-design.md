# Vibelution LLM Provider 与模型配置重构设计

> 状态：设计已确认，等待书面规格复核
> 日期：2026-07-11
> 分支：`codex/llm-provider-model-config-design`
> 任务等级：`HIGH_RISK`，涉及配置 schema、凭据路由、LLM 协议解析和存量引用迁移

## 1. 目标

把当前以“每个模型内嵌一套 provider”为核心的配置，重构为稳定的三层关系：

```text
Provider Instance
└── Pinned Model
    └── Agent / Tool / Feature Binding
```

完成后，用户应当可以：

1. 一个中转站、官方 API 账号或本地推理服务只配置一次 endpoint 和凭据。
2. 自动获取该服务暴露的模型 ID，并按 provider instance 稳定区分同名模型。
3. 清楚区分官方 API、聚合网关、中转站、远程自部署和本地推理框架。
4. 清楚区分 OpenAI GPT 模型家族、服务来源、API 驱动和实际 wire protocol。
5. 在同一 provider 下管理多个模型，不复制 provider、endpoint 和凭据字段。
6. 安全迁移现有 `config.toml`、Agent、Tool、Team、ChatRoom 和工作区模型引用。
7. 在发现失败、模型消失、协议不明确或能力未知时看到显式状态，不接受静默降级。

## 2. 非目标

- 不在本轮引入 Vercel AI SDK、LiteLLM 替代层或 Models.dev 运行时依赖。
- 不新增 ChatGPT、Codex 或第三方平台 OAuth 登录流程；schema 允许未来接入，首轮只迁移已有凭据来源。
- 不让配置加载过程访问网络。
- 不自动固定远端返回的全部模型。
- 不在迁移时自动删除模型、Provider、Agent 绑定或本地模型文件。
- 不重写正常 LLM 请求、流式解码或 tool-call 执行链；本轮只调整它们消费的已解析配置。
- 不把模型显示名、模型家族或文件路径当成服务身份。

## 3. 当前问题与证据

### 3.1 Provider 在公开配置与运行时之间反复拆装

当前外部 operator 配置的模型条目各自内嵌 provider。`config/settings.py::_materialize_inline_llm_providers()` 在加载时为每个模型生成 `inline_model_*` provider，并为每个 materialized profile 生成 `inline_profile_*` provider。

在 2026-07-11 的脱敏审查中：

- operator config 有 7 个模型条目；
- effective config 产生 19 个 provider 记录，包括默认 provider、7 个模型 provider 和多个 profile provider；
- 同一中转 endpoint 下的图像模型和 GPT 模型被表示为两个 provider；
- 同一 Xiaomi endpoint 下的两个模型也各自复制一套 provider。

结果是 provider 不再代表服务实例，只代表“某个模型或 profile 的一次展开”。

### 3.2 前端通过启发式指纹重新猜账号

`web/src/routes/configRouteLogic.ts::accountIdForModelOption()` 使用：

```text
provider kind + base_url + key_env
```

重新推断哪些模型属于同一个账号。这个派生值没有公开 provider ID，无法可靠表达：

- 相同 endpoint、不同 API Key 的两个账号；
- 相同 endpoint、相同凭据、不同协议的多模型网关；
- credential rotation 与切换账号的差异；
- 本地框架、远程自部署和普通 OpenAI-compatible 服务的差异。

### 3.3 模型引用由显示字段生成

当前 `_model_library_id()` 和前端 `modelLibraryIdFromParts()` 从显示名、模型名生成 ID，冲突时追加 `_2`、`_3`。该 ID：

- 受创建顺序影响；
- 不包含 provider instance 身份；
- 修改显示名可能产生新的引用；
- 无法天然区分多个服务暴露的同名模型。

当前 operator config 中还有一个模型条目的 `model` 字段保存了 `.gguf` 文件路径，证明 served model ID 与 deployment artifact 已经混为一层。

### 3.4 模型发现没有形成 provider-scoped 目录

`core/web/services/config_service.py::_discover_openai_compatible_model_list()` 会尝试 `/models` 或 `/v1/models`，但发现结果只返回编辑器，成功结果没有 provider-scoped 持久化目录。当前只有：

- 临时发现结果；
- 进程内失败负缓存；
- 只覆盖图像输入能力的 `model-capabilities.json`。

这无法表达远端模型新增、消失、陈旧目录、能力来源和最后成功时间。

### 3.5 协议与身份属性混杂

`core/llm/protocol_resolver.py` 目前需要综合 `kind`、`api`、`transport`、`model`、`base_url` 和 endpoint 路径进行协议推断。`kind` 同时承担供应商、服务类别、框架和兼容模式，导致：

- GPT 被误当作协议类别；
- relay 与普通 OpenAI-compatible API 容易混淆；
- local、Ollama、llama.cpp 的框架身份与 wire protocol 混在一起；
- 缺少显式字段时只能依赖模型名和 URL 启发式。

## 4. 外部参考与复用决策

### 4.1 Hermes Agent

Hermes 的可复用设计点：

- `ProviderProfile` registry 统一提供 `base_url`、`env_vars`、`api_mode` 和 fallback catalog；
- CLI、gateway、cron、ACP 和辅助模型共用 runtime provider resolver；
- 模型目录采用实时 provider API 优先、静态目录兜底；
- 明确区分 custom endpoint、聚合服务、原生 Anthropic 和 Codex Responses；
- provider/model 选择独立于任务槽位。

不照搬的部分：Hermes 主模型配置仍可以把 provider、model、base URL 和 API mode 聚在单个 slot 中；Vibelution 需要一个服务实例下的多模型资产管理和可回滚迁移。

官方来源：

- <https://hermes-agent.nousresearch.com/docs/user-guide/configuring-models>
- <https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/provider-runtime.md>
- <https://github.com/NousResearch/hermes-agent/blob/main/hermes_cli/models.py>

### 4.2 OpenCode

OpenCode 的可复用设计点：

- provider 是独立命名空间，模型完整身份为 `providerID/modelID`；
- credential 与普通配置分离；
- provider 拥有 driver、base URL、models 和 provider options；
- 标准 provider 使用 Models.dev 获取能力、限制和价格元数据；
- custom provider 使用独立 provider ID，并可配置 allowlist、blacklist 和模型覆盖；
- 配置层有明确的 merge precedence。

不照搬的部分：OpenCode custom provider 仍主要依赖手动模型元数据，Models.dev 也不是 Vibelution operator config 的适当运行时依赖。

官方来源：

- <https://opencode.ai/docs/providers>
- <https://dev.opencode.ai/docs/config>
- <https://github.com/anomalyco/opencode/blob/dev/packages/opencode/src/cli/cmd/models.ts>
- <https://github.com/anomalyco/models.dev>

### 4.3 主决策

复用结论：`REFERENCE_ONLY`。

Vibelution 在现有 Python 配置、LLM resolver、配置草稿和 runtime-scene 体系内自研 provider registry 与 derived model catalog；不复制外部代码，不新增外部运行时依赖。

## 5. 术语与身份

### 5.1 Provider Instance

Provider instance 表示一个可独立配置、测试、授权和诊断的服务连接。

其业务身份由以下事实构成：

- endpoint；
- credential reference；
- operator 指定的稳定 `provider_id`。

同 endpoint、同 credential reference 的多个模型属于同一 provider。相同 endpoint 但不同 credential reference 的账号必须使用不同 provider ID。

secret value 在同一个 credential reference 下轮换时仍是同一 provider。把 credential reference 从账号 A 换为账号 B 属于 provider route replacement，保存前必须显示影响预览；需要并存时必须创建第二个 provider。

### 5.2 Pinned Model

Pinned model 是 operator 已选择进入稳定模型库的模型。它有：

- `model_key`：Vibelution 内、provider scope 下的稳定键；
- `upstream_id`：发送给服务端的精确模型 ID；
- `model_ref`：`provider_id/model_key`；
- operator overrides；
- 运行态目录中可刷新的 observed metadata。

### 5.3 Observed Model

Observed model 是远端 endpoint 或本地框架本次发现到的模型。它只存在于 derived catalog，除非用户将其固定或首次绑定。

### 5.4 Profile / Binding

Profile、Agent slot、Tool 或 Feature 只引用 `model_ref`，不再复制 provider、model、endpoint 或凭据。

## 6. 分类维度

当前 `kind` 拆成正交字段：

| 字段 | 作用 | 示例 |
|---|---|---|
| `service_class` | 服务部署和商业关系 | `official_api`, `aggregator`, `relay`, `self_hosted`, `local_runtime` |
| `vendor` | 商业或平台归属 | `openai`, `anthropic`, `xiaomi`, `deepseek`, `multi_model`, `custom` |
| `driver` | Vibelution 使用的客户端/适配器族 | `openai`, `anthropic`, `gemini` |
| `wire_protocol` | 实际请求协议 | `responses`, `chat_completions`, `messages`, `generate_content` |
| `runtime_framework` | 本地部署框架，可选 | `ollama`, `llamacpp`, `lmstudio`, `vllm`, `sglang`, `custom` |
| `auth_kind` | 凭据解析方式 | `api_key`, `oauth`, `none` |

GPT 是模型家族或 vendor metadata，不是 provider service class，也不是 wire protocol。

## 7. Operator Config Schema v2

### 7.1 存储结构决策

模型在公开 TOML 中嵌套于 provider 下，避免 `provider_ref` 冗余。运行时可以生成扁平 `model_library` projection，供迁移期现有消费者使用。

```toml
[llm]
schema_version = 2

[llm.providers.pixel_relay]
label = "Pixel Relay"
service_class = "relay"
vendor = "multi_model"
driver = "openai"
base_url = "https://relay.example"
auth_kind = "api_key"
credential_ref = "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY"
requires_credential = true

[llm.providers.pixel_relay.protocols]
default = "responses"
allowed = ["responses", "chat_completions", "messages"]

[llm.providers.pixel_relay.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 3600
include = []
exclude = []

[llm.providers.pixel_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
label = "GPT-5.6 Luna"
enabled = true

[llm.providers.pixel_relay.models."anthropic_claude-sonnet-4.6~3e041007"]
upstream_id = "anthropic/claude-sonnet-4.6"
label = "Claude Sonnet 4.6"
enabled = true
wire_protocol = "messages"

[llm.profiles.primary]
model_ref = "pixel_relay/gpt-5.6-luna"

[llm.profiles.primary.overrides]
temperature = 0.7
max_output_tokens = 32000
```

### 7.2 本地部署结构

```toml
[llm.providers.lab_llamacpp_a]
label = "Lab llama.cpp A"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8080/v1"
auth_kind = "none"
credential_ref = ""
requires_credential = false

[llm.providers.lab_llamacpp_a.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.lab_llamacpp_a.discovery]
mode = "auto"
adapter = "llamacpp"
cache_ttl_seconds = 300

[llm.providers.lab_llamacpp_a.deployment]
runtime_framework = "llamacpp"
artifact_path = "D:\\models\\Qwen.gguf"

[llm.providers.lab_llamacpp_a.models."qwen3.6-35b-a3b"]
upstream_id = "qwen3.6-35b-a3b"
label = "Qwen 3.6 35B"
enabled = true
```

`artifact_path` 只用于本地部署诊断和展示；请求 payload 始终使用 `upstream_id`。

### 7.3 Credential Reference

首轮支持：

```text
env:VARIABLE_NAME
none
```

schema 允许后续增加：

```text
oauth:<provider>/<account-id>
file:<credential-id>
```

operator config 只保存 reference，不保存 secret value。UI、日志和 API 不返回 secret。

### 7.4 模型运行默认值

Provider 只拥有连接和默认协议。Pinned model 拥有该模型在当前 provider 下的协议覆盖、兼容策略、能力声明和运行默认值：

```toml
[llm.providers.pixel_relay.models."gpt-5.6-luna"]
upstream_id = "gpt-5.6-luna"
wire_protocol = "responses"
interaction_contract = "tool_chat"
model_protocol = "relay_responses"

[llm.providers.pixel_relay.models."gpt-5.6-luna".defaults]
temperature = 0.7
max_output_tokens = 32000
timeout = 120
connect_timeout = 20
streaming = true
tool_calling_mode = "auto"

[llm.providers.pixel_relay.models."gpt-5.6-luna".compatibility]
tool_choice_mode = "native"
```

迁移映射：

- 旧 `transport` 映射到 `wire_protocol`；
- 旧 `contract` 映射到 `interaction_contract`；
- 旧 `protocol` 映射到 `model_protocol`；
- 旧 `compat` 映射到 `compatibility`；
- sampling、timeout、streaming、tool mode 和 prompt-cache 默认值进入模型 defaults 或对应模型子表；
- profile 的 `overrides` 继续只表达任务槽位覆盖，不复制模型默认值。

`base_url` 表示服务根，不表示最终请求 URL。driver 根据 wire protocol 构造默认 endpoint；自定义服务可以在 provider protocol 配置中覆盖相对 route。迁移只在 adapter 能确认旧 URL 末尾是协议 route 时去除该后缀，否则保留原有 path，避免改错自定义网关。

## 8. ID 生成与稳定性

### 8.1 Provider ID

- 创建向导根据模板、显示名或 endpoint host 给出建议。
- 用户在首次保存前可以修改。
- 首次保存并被引用后视为稳定键。
- 修改 endpoint 或 credential reference 会显示 route replacement 影响预览。
- 精确重复的 endpoint + credential reference 默认阻止创建第二个 active provider，并建议复用现有实例。

Provider identity fingerprint 使用规范化后的 endpoint 和 credential reference 计算，不包含 secret value：

```text
sha256(normalized_endpoint + "\0" + canonical_credential_ref)
```

- endpoint 的 scheme 和 host 转为小写；移除默认端口和末尾 `/`，但保留有语义的 path。
- provider base URL 不允许 query、fragment 或内嵌 userinfo。
- Windows 上 `env:` 后的变量名按大小写不敏感规则规范化；其他 credential backend 由各自 resolver 定义 canonical form。
- `auth_kind = "none"` 时 credential identity 固定为空值。
- `service_class`、vendor、driver 和 protocol 不进入 identity fingerprint；它们是同一服务实例的分类与路由属性，出现冲突时由 validation 阻止静默合并。

### 8.2 Model Key

输入是精确 `upstream_id`：

1. Unicode NFKC 规范化。
2. 若原值已经是小写且匹配 `[a-z0-9][a-z0-9._-]*`，直接使用，最大保留 96 字符。
3. 否则生成小写可读 slug，非安全字符折叠为 `_`。
4. 对包含大写、路径分隔符、空白或其他非安全字符的原值追加 `~<sha256 前 8 位>`，保证结果与发现顺序无关。
5. 超长 key 截断可读部分，但必须保留哈希后缀。
6. 用户可在首次 pin 前修改 key；被引用后不可静默变化。

例子：

```text
gpt-5.6-luna
→ gpt-5.6-luna

anthropic/claude-sonnet-4.6
→ anthropic_claude-sonnet-4.6~3e041007

C:\models\Qwen.gguf
→ c_models_qwen.gguf~88f2e351
```

最后一个例子仍会触发“疑似 artifact path”警告，建议把路径移入 deployment metadata。

### 8.3 两种身份

- 远端身份：`(provider_id, upstream_id)`，用于发现对账。
- 稳定引用：`(provider_id, model_key)`，序列化为 `provider_id/model_key`。

远端身份相同只更新 observed metadata，不创建重复模型。同一 provider 下两个仅大小写不同的 upstream ID 不自动合并；它们分别获得确定性 hash key，并显示冲突警告。

## 9. 模型发现与 Derived Catalog

### 9.1 发现规则

```text
保存 Provider 草稿
→ target/security validation
→ credential resolution
→ bounded connection test
→ provider discovery adapter
→ raw model normalization
→ observed/pinned diff
→ derived catalog atomic write
→ UI 展示
```

- 配置加载不联网。
- 新 provider 连接测试成功后自动执行首次发现。
- 后续刷新由用户触发，或模型页打开时在 TTL 过期后触发。
- 后台刷新失败保留上一次成功目录并标为 `stale`。
- 空响应不清空目录。
- 远端不再返回 pinned model 时标为 `missing_remote`，不自动删除。
- 全部 observed model 可浏览；只有显式 pin 或实际绑定的模型写入 operator config。

### 9.2 Adapter 接口

每个 adapter 返回统一结构：

```text
ProviderDiscoveryResult
- provider_id
- attempted_endpoints
- discovered_at
- models[]
  - upstream_id
  - label
  - capabilities
  - limits
  - metadata_source
```

首轮 adapter：

- `openai`
- `openai_compatible`
- `ollama`
- `llamacpp`
- `lmstudio`
- `vllm`
- `sglang`
- `anthropic`
- `gemini`
- `manual`

每个本地框架 adapter 可以先尝试原生目录，再尝试其 OpenAI-compatible surface；尝试顺序属于 adapter，不属于通用 URL 猜测器。

### 9.3 Catalog 文件

现有 `model-capabilities.json` 升级迁移为 operator config 同目录的：

```text
model-catalog-state.json
```

该文件是派生状态，不是 operator 配置。建议 schema：

```json
{
  "schemaVersion": 2,
  "providers": {
    "pixel_relay": {
      "providerFingerprint": "...",
      "status": "reachable",
      "lastAttemptAt": "...",
      "lastSuccessAt": "...",
      "models": {
        "gpt-5.6-luna": {
          "label": "GPT-5.6 Luna",
          "availability": "observed",
          "capabilities": {}
        }
      }
    }
  }
}
```

`model-capabilities.json` 只读一次并通过旧 ID 到新 `model_ref` 的迁移映射导入。迁移成功后旧文件退出读取链；不长期双写。

## 10. 能力与协议合并

### 10.1 能力三态

能力值使用：

```text
supported
unsupported
unknown
```

每个能力字段独立保存：

```text
value
source
confidence
checked_at
error
```

字段级合并优先级：

```text
operator override
→ runtime probe
→ provider endpoint metadata
→ curated snapshot
→ driver conservative default
```

一个来源对图像能力的判断不能覆盖另一个来源对 tool calling 或 context limit 的判断。

### 10.2 协议解析

Provider 声明默认协议和允许集合；model 可显式覆盖。解析顺序：

```text
model.wire_protocol
→ provider.protocols.default
→ driver-declared protocol
→ legacy-only diagnostic inference
```

旧式模型名、host 和 transport 推断只用于迁移诊断。新 schema 严格模式下，如果前三层无法解析，调用被阻止并返回 `protocol_unknown`，不静默退化到 basic chat。

同一 endpoint + credential 的多协议 gateway 仍是一个 provider；模型级 `wire_protocol` 决定实际调用路径。

## 11. Source Of Truth

| 事实 | 规范来源 | 写入者 | 派生面 | 失效/刷新 | 旧来源处理 |
|---|---|---|---|---|---|
| Provider 与 pinned models | 外部 `config.toml` | Config service | Settings UI、runtime projection | 保存后 reload | inline provider 迁移后移除 |
| Profile/Agent/Tool 模型引用 | 各 owning store 中的 `model_ref` | owning service / migrator | UI、runtime | 事务写入后刷新 | 临时 alias 兼容 |
| Secret value | credential backend | Credential resolver | configured/missing 状态 | provider test 时解析 | 不复制进 TOML |
| Observed models、能力、健康 | `model-catalog-state.json` | Discovery/probe service | 模型选择器、诊断、effective metadata | TTL 或显式刷新 | 导入旧 capability cache 后退役 |
| 最终协议与 endpoint | Runtime resolver 输出 | Resolver | 请求、日志、probe | 每次 resolve | 旧启发式仅诊断 |
| 本地 artifact | provider deployment metadata | Operator/config service | 本地部署诊断 | Provider 保存 | 从错误的 model 字段迁出 |

## 12. 设置页设计

设置页从单层模型表改为 provider-first：

```text
Provider 列表
└── Provider 详情
    ├── 连接
    ├── 模型
    ├── 协议与能力
    └── 诊断
```

### 12.1 Provider 列表

展示：

- provider ID、显示名；
- service class、vendor、local framework；
- endpoint；
- credential state；
- 默认协议；
- observed、pinned、异常模型数；
- 最近连接和发现状态。

### 12.2 新增 Provider 向导

```text
选择服务类型/模板
→ 配置 endpoint 与凭据
→ 测试并发现模型
→ 选择模型并固定
```

模板分组：

- 官方 API；
- 聚合网关；
- 中转站；
- 远程自部署；
- 本地框架；
- 高级自定义。

GPT、Claude、Qwen 等作为模型家族 badge，不作为 Provider 创建类别。

### 12.3 编辑和删除

- 编辑 provider route 前显示全部受影响模型和引用。
- 修改 credential reference 到不同账号时提示创建新 provider；如果用户明确替换，则按 route replacement 处理。
- 删除 provider 必须先迁移或解除所有 live refs。
- 删除 pinned model 只从 operator config 移除；若远端仍能发现，它继续以 observed 状态显示。
- Provider 和模型删除复用现有 reference guard，不做前端-only 删除。

## 13. 迁移设计

### 13.1 迁移流程

```text
读取 v1 inline provider config
→ 解析每个模型的 effective credential source
→ 按 endpoint + credential identity 分组
→ 生成 provider/model_ref 建议
→ 扫描 live references
→ 展示冲突和影响预览
→ 用户确认
→ 原子写 v2 + 备份
→ 事务迁移引用
→ reload + validation
```

迁移只在用户明确执行时写入。普通 v1 load 继续兼容读取，但 UI 显示“旧 schema，建议迁移”。

### 13.2 Credential 分组

- 使用当前运行优先级解析每个模型的 effective credential reference。
- 相同 endpoint + 相同 reference 合并。
- 两个 reference 若解析到相同 secret，可在内存中比较不可逆指纹并建议合并；不记录 secret 或指纹明文映射。
- 相同 endpoint + 不同 effective secret 拆成不同 provider。
- credential 缺失、待清除或来源冲突时标为 `NEEDS_REVIEW`，不自动合并。

### 13.3 引用兼容

迁移写入临时别名：

```toml
[llm.model_aliases]
relay_gpt_5_6_luna = "pixel_relay/gpt-5.6-luna"
local_model_server_b = "lab_local_b/qwen3.6-35b-a3b"
```

- Resolver 可读 alias，但所有新写入使用 canonical `model_ref`。
- `model_reference_service` 报告 alias usage 和剩余 live refs。
- 所有 live refs 归零后删除 alias。
- alias 是有退出条件的迁移脚手架，不是永久第二套模型 ID。

### 13.4 写入和回滚

- 使用现有 draft、base hash 和 stale-write 拦截。
- 写入前生成 `.bak`。
- config、credential changes 和引用迁移必须在 migration manifest 中记录阶段状态。
- 任一必要验证失败时恢复 operator config；已改引用按 manifest 回滚。
- 不删除本地 artifact、环境变量或 OAuth token，除非另有明确凭据清理动作。

## 14. 状态、错误与安全

Provider 状态：

```text
configured
reachable
auth_failed
discovery_failed
stale
protocol_mismatch
blocked
```

模型状态：

```text
observed
pinned
missing_remote
capability_unknown
protocol_unknown
disabled
```

规则：

- 发现失败不报告普通成功。
- stale catalog 显示最后成功时间和影响。
- 401/403 不尝试其他 provider 的凭据。
- 空模型列表不清空上一次成功目录。
- 严格模式协议未知时阻止调用。
- `unknown` 与明确 `unsupported` 分开。
- 保留并扩展 `validate_llm_provider_target()`；本地网络只允许明确 `local_runtime` 或 operator 允许策略。
- 发现请求限制超时、重定向、响应大小、模型数量、单个 ID 长度和 header 范围。
- 日志不记录 API Key、OAuth token、完整响应、完整 header 或敏感本地路径。

## 15. Runtime Scene 事件

新增或调整以下 bounded 事件：

```text
config.provider.created
config.provider.updated
config.provider.route_replacement_previewed
config.provider.discovery_succeeded
config.provider.discovery_failed
config.model.pinned
config.model.unpinned
config.model_reference.migrated
config.schema.migration_previewed
config.schema.migration_applied
config.schema.migration_rolled_back
llm.protocol.resolved
llm.protocol.blocked
```

字段只包含稳定 ID、状态、来源、数量、耗时、错误类型和有界修复摘要。

## 16. 组件边界

建议新增或收敛的职责：

| 组件 | 职责 |
|---|---|
| `ProviderRegistry` | Provider schema、唯一性、route replacement 和 credential reference |
| `ModelIdentity` | model key、model ref、alias 和 upstream identity |
| `ModelCatalogState` | observed catalog、capability provenance、TTL 和 atomic persistence |
| `ProviderDiscoveryAdapter` | 各 provider/framework 的模型发现 |
| `ModelConfigMigrator` | v1 预览、引用迁移、manifest 和 rollback |
| `ProtocolResolver` | 显式 provider/model protocol 解析 |
| `ConfigService` | 草稿、保存、API orchestration 和 runtime events |

现有文件影响面预计包括：

- `config/models.py`
- `config/settings.py`
- `config/public_config.py`
- `config/toml_writer.py`
- `config/runtime_capabilities.py`
- `config/paths.py`
- `core/llm/discovery.py`
- `core/llm/protocol_resolver.py`
- `core/llm/agent_runtime.py`
- `core/web/services/config_service.py`
- `core/web/services/model_reference_service.py`
- `core/web/routes/config.py`
- `web/src/api/types/config.ts`
- `web/src/routes/ConfigRoute.tsx`
- `web/src/routes/ConfigModelLibraryPanel.tsx`
- `web/src/routes/configRouteLogic.ts`
- 对应后端、前端和迁移测试

实施计划应优先新增窄组件，不继续扩大 `config_service.py`、`public_config.py` 和 `ConfigRoute.tsx`。

## 17. 测试与验证

### 17.1 Schema 与身份

- v2 provider/model/profile TOML round-trip。
- v1 兼容读取不写盘。
- 同 endpoint 同 credential 合并。
- 同 endpoint 不同 credential 拆分。
- provider route replacement 影响预览。
- ID 生成覆盖 Unicode、大小写、斜杠、Windows 路径、超长值和冲突。
- label 变更不改变 model ref。

### 17.2 发现与缓存

- 配置 load 不触发网络。
- 各 discovery adapter success/failure fixture。
- timeout、401、403、404、重定向、空列表和超限响应。
- stale cache 保留最后成功结果。
- missing remote 不删除 pinned model。
- observed model pin-on-use。
- 旧 `model-capabilities.json` 一次迁移和退出读取链。

### 17.3 能力与协议

- operator override 不被 probe 或 catalog 覆盖。
- capability 字段级 provenance。
- provider default protocol。
- model explicit protocol override。
- multi-protocol gateway。
- 新 schema 协议未知时 fail closed。
- legacy inference 只产生诊断。

### 17.4 引用迁移

- profiles、Agent slots、Tools、Git、Team、ChatRoom 和 durable workspace refs。
- alias usage 报告和退出条件。
- 删除 provider/model 的 live-ref guard。
- 中途失败的 manifest rollback。
- stale config hash 阻止迁移应用。

### 17.5 前端

- Provider 列表使用后端稳定 ID，不再前端猜账号。
- 创建向导与首次发现。
- 同名模型跨 provider 分开展示。
- 本地 artifact 与 upstream model ID 分开展示。
- route replacement 和 migration preview。
- stale、auth failed、protocol blocked 和 capability unknown 状态。
- 桌面和移动宽度截图验证。
- `npm --prefix web run build`。

## 18. 分阶段交付边界

实现计划至少拆成以下阶段，但是否进一步拆任务由 planning 阶段判定：

1. Provider/model schema、身份 helper 和 v1 read-only adapter。
2. Derived catalog、discovery adapters、能力 provenance 和协议 resolver。
3. Config API、Provider-first UI 和连接/发现流程。
4. Migration preview、reference rewrite、alias tracking 和 rollback。
5. operator config 受控迁移、Launcher refresh 和运行态验证。

每阶段必须保持 root local `main` 可运行，不允许在中间状态把 operator config 自动升级。

版本影响判断：该功能新增 operator config schema v2、Provider 管理和迁移能力，预期属于 `1.x` 的 minor 版本影响。普通任务分支只报告版本影响；`VERSION`、`CHANGELOG.md` 和前端包版本由最终集成或发布轮统一处理。

运行刷新判断：设计文档阶段不需要 Launcher refresh；实现合入后，在用户测试和 release/runtime verification 前必须通过 Launcher 刷新并验证真实 operator config 路径。

## 19. 被拒绝方案

### 19.1 保留 inline provider，只增加 group ID

拒绝原因：继续复制 endpoint、credential 和 protocol；运行时仍需拆装 provider，前端仍需推断，无法形成真正的 provider owner。

### 19.2 配置只保存 provider，所有模型永远动态加载

拒绝原因：离线和中转站不稳定时无法复现；远端模型消失会影响已有 Agent；能力元数据通常不完整。

### 19.3 每模型独立凭据

拒绝原因：同一个账号的密钥重复、轮换成本高、无法进行 provider 级健康和余额管理。特殊模型账号应建成独立 provider instance。

### 19.4 继续用模型名或 URL 推断协议

拒绝原因：同名模型可通过不同协议和服务提供；推断只能用于迁移诊断，不能成为新 schema 的运行事实。

## 20. 验收标准

设计实现完成需同时满足：

1. operator config 中每个 endpoint + credential account 只出现一个 provider instance。
2. 同一 provider 的多个模型不复制 endpoint、credential 或 service classification。
3. 所有新 canonical model refs 使用 `provider_id/model_key`。
4. upstream model ID 原样保存，显示名和 artifact path 不承担请求身份。
5. 配置加载期间零网络访问。
6. 发现目录失败时保留最后成功结果并显式 stale。
7. 严格模式协议未知时阻止调用。
8. v1 迁移有预览、备份、引用清单、alias 退出条件和 rollback。
9. secret 不进入 API、日志、runtime scene、测试 fixture 或 operator TOML。
10. 后端聚焦测试、前端测试/build、迁移 fixture 和 Launcher 后运行验证全部产生新鲜证据。

## 21. 已锁定决策

- Provider instance 边界：endpoint + credential reference。
- 同 endpoint、不同 credential 是不同 provider。
- 推荐方案：provider registry + pinned model catalog + derived observed catalog。
- 发现结果先进入派生目录，选择或绑定后才固定。
- 模型引用使用 provider-scoped stable key。
- 协议显式配置优先，启发式只保留迁移诊断。
- 现有 capability cache 迁移为 catalog state，不长期双写。
- Hermes 与 OpenCode 仅作架构参考，不引入新依赖。

本规格没有未决行为问题。下一阶段在用户完成书面规格复核后进入 `writing-plans`。
