# LLM v1 路径型模型标识显式裁决方案

## 目标

为 `artifact_path_suspected` 增加显式、可审计、fail-closed 的迁移裁决流程，使路径样式的 v1 `model` 值既不会被静默当成 v2 `upstream_id`，也不会迫使用户删除一个曾经可用的本地推理服务记录。

当前现实样本是 `local_model_server_c`：它属于局域网 OpenAI-compatible 本地推理服务，历史运行曾成功，但当前服务离线；其 v1 `model` 是 `.gguf` 绝对路径样式。实现必须支持离线生成裁决后的只读预览，但真实迁移仍保留现有最终确认、备份、哈希校验和回滚门禁。

## 范围

本轮做：

- 为迁移预览请求增加按 legacy model ID 绑定的显式 resolution。
- 支持两种互斥裁决：保留路径型值为服务端 `upstream_id`，或将其拆为 Provider `deployment.artifact_path` 并要求提供新的 `upstream_id`。
- 将裁决内容绑定到 preview ID、base hash 和后续 apply token。
- 在配置 UI 中展示冲突、裁决选项、离线风险和裁决后的新预览状态。
- 增加后端、路由投影、前端状态和安全/日志测试。

本轮不做：

- 不自动猜测文件名、模型别名或 runtime framework。
- 不把路径型值静默迁移为 `upstream_id`。
- 不要求迁移预览阶段强制联网，也不伪造 discovery 成功。
- 不修改或应用真实 operator `config.toml`。
- 不扩展普通 Provider CRUD、模型发现协议或 Launcher 生命周期。

## 前置审查证据

- `config/model_config_migration.py` 当前对 `.gguf`、`.safetensors`、`.bin`、Windows/UNC/POSIX 绝对路径统一产生 `artifact_path_suspected`，并从映射中排除该模型。
- 原 Provider-first 方案明确禁止路径样式 `model` 被静默当作 `upstream_id`。
- v2 已把 `provider.deployment.artifact_path` 与模型 `upstream_id` 分开保存和展示。
- `local_model_server_c` 指向 `192.168.20.66:8080/v1`，当前 TCP 不可达；本地历史记录显示 2026-07-09 曾以该 legacy model ID 完成多轮自观察输出。
- 当前 preview/apply 已有 15 分钟 preview TTL、确定性 preview ID、base hash、防漂移检查、备份与 rollback。
- 当前 API conflict 投影不会输出路径值；该安全边界必须保持。

## 推荐路径

### 1. 定义显式 resolution 契约

在迁移领域层增加不可变 resolution 类型，按 legacy `modelId` 索引：

```text
preserve_upstream_id
  - 仅允许 provider.kind 属于 local / local_runtime / ollama
  - 不接收浏览器回传的路径值
  - 服务端从当前 v1 配置读取原 model 值作为 upstream_id
  - 同时把原值记录为 provider.deployment.artifact_path，作为服务端部署来源
  - preview 标记 resolutionSource=explicit_manual

split_deployment_artifact
  - 必须提供非路径型 upstreamId
  - 服务端从当前 v1 配置读取原 model 值写入 provider.deployment.artifact_path
  - 模型只保存新 upstream_id
```

preview request 使用 `artifactResolutions` 数组，每项包含唯一 `modelId` 和 decision；领域层据此可靠检测重复 `modelId`。未知 model ID、重复 resolution、非法 mode、路径型新 `upstreamId`、不适用的 Provider kind 或额外字段全部以 422 拒绝。resolution 不得包含 secret、credential ref、base URL 或 artifact path 原文。

### 2. 保持两阶段预览

第一次 `POST /api/config/migration/llm-v2/preview` 可继续使用空 payload，返回 `artifact_path_suspected`，并增加安全的 `allowedResolutions` 枚举和 `requiresExplicitResolution=true`，不返回原路径。

用户选择后，再次调用同一 preview endpoint，body 只携带 resolution。迁移器基于当前磁盘配置重新计算 proposed config、引用影响与冲突；resolution 进入 stable preview payload，因此不同裁决必然生成不同 preview ID。

apply endpoint 不新增 resolution 参数，只接受第二次 preview 返回的 `previewId + baseHash`。这样 apply 只能消费服务端保存的、已裁决 proposed config，避免浏览器在 apply 时替换语义。

### 3. Provider 与模型映射

- `preserve_upstream_id`：Provider 仍按现有 endpoint + credential 分组；路径样式值精确保留为模型 `upstream_id`，同时写入 `deployment.artifact_path`。前者保证迁移前后的 wire model 完全一致，后者只记录 server-side artifact provenance；Vibelution 不因此声明管理该文件，也不在 operator 主机执行 `Path.exists()`。
- `split_deployment_artifact`：原路径进入 `provider.deployment.artifact_path`，新 `upstreamId` 生成 canonical model key/ref；`runtime_framework` 保持空值，因为 v1 没有权威来源，后续只能通过正常 Provider 编辑流程显式维护。
- 同一 Provider 分组若出现多个不同 artifact path，preview 产生新的 blocking conflict；不得任选、覆盖或把多个路径折叠成一个 Provider-level deployment 值。
- 两种模式都继续使用现有 live-reference rewrite、alias 兼容、hash、backup、reload 和 rollback 流程。

### 4. UI 行为

`ConfigModelMigrationPanel` 对每个 `artifact_path_suspected` 显示一张裁决卡：

- 明确说明“路径值未展示，也不会写入日志”。
- 提供“服务端模型 ID”与“部署产物路径”两个选择。
- `preserve_upstream_id` 要求一次显式风险确认，说明离线时无法核验服务端目录。
- `split_deployment_artifact` 只展示 `upstreamId` 输入；输入未通过本地校验时不提交，不在迁移界面猜测 runtime framework。
- 提交裁决只重新生成预览，不应用迁移。
- 只有新预览 `READY` 时才恢复现有“应用迁移”按钮；最终 apply 仍使用危险操作确认。

当前 `artifactWarnings` 依赖 `fields.includes("artifact_path")`，而后端 conflict 没有该字段。本轮统一改为按 `code === "artifact_path_suspected"` 识别，避免专用提示永远不出现。

### 5. 离线策略

服务离线不阻止用户生成带显式裁决的预览，因为迁移预览必须可重复且默认零网络；但 UI 必须显示 `unverified_offline` 风险。真实 apply 不自动联网，也不把历史成功记录当成实时健康证明。

对当前 Server C，推荐先实现机制并保留真实迁移未执行；待服务恢复后，用显式 discovery 验证 `/models` 是否仍返回同一标识，再由用户确认 apply。

## 影响面

后端与契约：

- `config/model_config_migration.py`：resolution 解析、适用性验证、proposed config 生成、preview ID 绑定。
- `core/web/routes/config.py`：preview request DTO；apply/rollback 契约不变。
- `core/web/services/provider_config_service.py`：接收 resolution、投影安全字段、记录无敏感值的 resolution mode/count。
- `web/src/api/types/config.ts`：conflict allowed resolutions、preview request、resolution union。

前端：

- `web/src/routes/ConfigModelMigrationPanel.tsx`：裁决卡和重新预览动作。
- `web/src/routes/ConfigRoute.tsx`：resolution 状态、preview mutation；apply 逻辑保持 token-only。
- 必要时增加一个小型纯 reducer/helper 文件承载 resolution 状态，避免把状态分支继续堆入 Route。

测试：

- `tests/test_model_config_migration.py`
- `tests/test_web_config_routes.py`
- `tests/test_provider_config_service.py`
- `tests/test_llm_config_v2_integration.py`
- `web/src/routes/ConfigRoute.layout.test.ts`
- 新增或扩展纯前端 migration resolution 状态测试。
- `tests/test_config_redaction.py` 或等价现有 redaction 测试面。

## 保护边界

- conflict、API 响应、日志和 runtime scene 不出现 artifact path 原文、credential ref、API key 或响应 body。
- 不读取浏览器提供的 artifact path；只使用与 base hash 对应的当前服务端 v1 配置值。
- resolution 只作用于点名的 legacy model ID，不做全局默认。
- relay、official API、aggregator 的路径型模型值继续 fail-closed，不能选择 `preserve_upstream_id`。
- `runtime_framework` 在两种 resolution 中都保持空值，不根据 endpoint、文件后缀或 Provider label 猜测；迁移后由正常 Provider 编辑流程负责。
- 同一 Provider 分组存在多个 artifact path 时保持 fail-closed。
- apply 前继续校验 preview 未过期、base hash 未漂移、preview status 为 `READY`。
- 不更改现有 alias 清理退出条件，不删除历史引用，不放宽回滚校验。

## 验证策略

后端单元测试至少覆盖：

- 无 resolution 时仍为 `NEEDS_REVIEW`。
- local Provider 的 `preserve_upstream_id` 产生 READY 映射，且 proposed model 精确保留 wire `upstream_id`、proposed provider 记录同值 deployment artifact。
- relay/official Provider 使用 preserve 被拒绝。
- split 模式把原路径放入 deployment，并使用显式非路径 upstream ID。
- 新 upstream ID 仍为路径、未知/重复 model ID 均失败。
- 不同 resolution 产生不同 preview ID；相同输入稳定复现。
- 同一 Provider 分组出现多个不同 artifact path 时产生 blocking conflict。
- runtime projection 始终只把 `upstream_id` 放入请求，不会用 `deployment.artifact_path` 替代 wire model。
- apply 只能消费已存 preview，hash drift/TTL/未解决冲突仍失败。

安全与路由测试至少覆盖：

- API conflict 只暴露 code、modelId、allowedResolutions、verification state。
- projection、日志和异常不含原路径、credential ref、secret。
- preview body 有额外字段时 fail-closed。

前端测试至少覆盖：

- 初始 conflict 显示裁决卡且 apply disabled。
- preserve 必须显式确认；split 必须填写合法 upstream ID。
- resolution 只触发重新 preview，不触发 apply。
- 新 preview READY 后才允许 apply。
- 390×844 与 1440×900 无页面级横向溢出。

执行验证命令：

```powershell
& '.venv\Scripts\python.exe' -m pytest tests\test_model_config_migration.py tests\test_web_config_routes.py tests\test_provider_config_service.py tests\test_llm_config_v2_integration.py tests\test_config_redaction.py -q
npm --prefix web run test -- ConfigRoute.layout.test.ts configProviderLogic.test.ts --reporter=dot
npm --prefix web run build
git diff --check
```

## 风险决策

- 允许离线裁决与应用会保留既有配置语义，但不能证明服务当前健康；通过 `unverified_offline` 显示承接该风险。服务在线状态是瞬态事实，不应让确定性的 preserve 迁移失效。
- 把路径型值保留为 upstream ID 是兼容例外，不应成为普通向导的默认输入能力；限制在 v1 迁移 resolution 中。
- split 模式若由用户提供错误 alias，会在运行时失败；因此推荐在真实 apply 前恢复服务并显式 discovery，但不把网络依赖写入确定性 preview。
- 不从历史日志自动批准 resolution。历史成功仅用于解释当前记录不是明显垃圾数据。

## 方案审查循环

- 用户意图：PASS。方案解决当前唯一迁移阻塞，并保留自动模型 ID 管理与 Provider/部署分离目标。
- 前置审查：PASS。继承既有 fail-closed 约束、preview token、hash、backup、rollback 和 redaction 边界。
- 实施者：PASS。接口、数据流、文件影响和错误条件均已枚举。
- 测试验证：PASS。测试同时证明兼容、拒绝路径、安全投影、token 绑定和 UI 门禁。
- 风险边界：PASS。真实 operator config 迁移仍是独立自然闸门；本计划不授权 apply。
- 维护者：PASS。复用现有 preview/apply 流程，不新增平行迁移器或依赖。

## 方案修正

- 将最初可能的“服务在线才能裁决”修正为“preview 零网络、离线可显式裁决、apply 前推荐 discovery”，避免迁移流程被临时网络状态永久锁死。
- 将 resolution 放在 preview 而非 apply，确保 proposed config、引用影响和 token 是同一不可替换事实。
- 根据独立审查，将 preserve 模式修正为同时保留 wire `upstream_id` 与 server-side `deployment.artifact_path`，并新增 Provider-level 多 artifact 冲突门禁。
- 增加按 conflict code 识别 artifact warning 的 UI 修正，避免当前专用提示失效。

## 路由出口

方案门禁为 `PASS`。下一阶段进入 `ccdawn-task-splitting`，判定后端迁移契约、Web/UI 契约和集成验证是否需要独立任务牌；任何实现都不得执行真实 operator config 迁移。

## 任务拆分

Decision：`SPLIT`。

Critical Path：Task 1 -> Task 2 -> Task 4；Task 3 在冻结的 API 契约上可与 Task 1 并行，最终进入 Task 4。

### Task 1：迁移领域层显式 resolution

- Goal：`preview_v1_to_v2` 在无 resolution 时保持 fail-closed，在合法 resolution 下生成语义保持、token 绑定的 READY preview。
- Inputs：本计划的 resolution union、Provider kind 限制、双字段语义和多 artifact 冲突规则。
- Outputs：领域层 resolution 解析、proposed config、稳定 preview ID 与单元测试。
- Files：`config/model_config_migration.py`、`tests/test_model_config_migration.py`、必要的 `tests/test_llm_config_v2_integration.py`。
- Boundary：不修改 Web route/service、前端、真实 operator config 或 reference rewrite owner。
- Dependencies：无。
- Criticality：critical。
- Development Mode：`BDD_TDD`。
- BDD/TDD Anchor：Given 路径型 local v1 model；When 无 resolution、preserve、split、重复或多 artifact resolution；Then 分别保持 NEEDS_REVIEW、生成语义正确 READY preview 或 fail-closed，并先写失败测试。
- Verification：`pytest tests/test_model_config_migration.py tests/test_llm_config_v2_integration.py -q`。
- Review Gate：wire `upstream_id` 不被 artifact 字段替代；resolution 进入 preview ID；无网络和无真实写入。
- Risk：错误分组或 Provider-level artifact 覆盖。

### Task 2：Web API、投影与 redaction 契约

- Goal：preview endpoint 接收严格的 resolution 数组并只投影安全字段；apply 继续只接受 preview token 与 base hash。
- Inputs：Task 1 的领域 API 和本计划的安全投影字段。
- Outputs：请求 DTO、service 传递、safe conflict projection、bounded runtime log 与测试。
- Files：`core/web/routes/config.py`、`core/web/services/provider_config_service.py`、`tests/test_web_config_routes.py`、`tests/test_provider_config_service.py`、`tests/test_config_redaction.py`。
- Boundary：不修改迁移领域算法、前端、apply/rollback payload 形状或 operator config。
- Dependencies：Task 1。
- Criticality：critical/high risk。
- Development Mode：`BDD_TDD`。
- BDD/TDD Anchor：Given 合法/非法 resolution body；When 请求 preview；Then 严格校验、只返回 allowlisted metadata，且 artifact path/credential/secret 永不出现在响应或日志中。
- Verification：`pytest tests/test_web_config_routes.py tests/test_provider_config_service.py tests/test_config_redaction.py -q`。
- Review Gate：apply 无 bypass；extra fields、重复 model ID、未知 decision 为 422；日志负断言通过。
- Risk：公共 API 放宽或路径泄漏。

### Task 3：前端冲突裁决与重新预览

- Goal：用户可在迁移面板中显式选择 preserve 或 split，裁决只重新生成 preview，READY 前始终禁用 apply。
- Inputs：冻结的 preview request/response 契约；可使用 mock response 独立实现。
- Outputs：类型、纯 resolution 状态逻辑、裁决 UI、layout/behavior tests。
- Files：`web/src/api/types/config.ts`、`web/src/routes/ConfigModelMigrationPanel.tsx`、`web/src/routes/ConfigRoute.tsx`、必要的新纯 helper/test、现有 styles。
- Boundary：不修改后端、通用 Provider wizard、真实 config editor 或 apply confirmation 语义。
- Dependencies：契约依赖本计划；代码可与 Task 1 并行，Task 4 前与 Task 2 对齐。
- Criticality：critical。
- Development Mode：`BDD_TDD`。
- BDD/TDD Anchor：Given artifact conflict；When 用户选择 preserve 或填写 split upstream ID；Then 只发送重新 preview 请求、显示 offline warning、阻止非法输入和未 READY apply。
- Verification：`npm --prefix web run test -- ConfigRoute.layout.test.ts configProviderLogic.test.ts --reporter=dot` 和相关新增测试。
- Review Gate：按 conflict code 命中专用提示；不显示原路径；390×844 无页面级溢出。
- Risk：本地 UI 状态冒充服务端 preview 授权。

### Task 4：集成、回归与运行态验收

- Goal：证明三层契约组合正确且真实 operator config 未被改写。
- Inputs：Task 1、Task 2、Task 3。
- Outputs：聚焦回归、前端 build、diff/redaction 检查、Launcher 刷新决策与只读迁移预览验收。
- Files：原则上不新增业务修改；仅在集成发现契约偏差时回到对应任务牌修复。
- Boundary：不点击或调用 apply，不执行真实迁移，不清理 alias，不修改版本文件。
- Dependencies：Task 1、Task 2、Task 3。
- Criticality：critical。
- Development Mode：`SIMPLE`，因为只组合已验证产物并执行现有门禁。
- BDD/TDD Anchor：无需；实现行为测试由前三张任务牌承担。
- Verification：计划中完整 pytest、web tests、`npm --prefix web run build`、`git diff --check`、桌面/移动只读浏览器验收。
- Review Gate：无 secret/path 泄漏、preview token 一致、apply 保持禁用或需独立确认、operator config hash 不变。
- Risk：集成时误触真实迁移或遗漏跨层字段名偏差。

拆分自审：覆盖方案 `PASS`；依赖清晰 `PASS`；粒度合适 `PASS`；验证可行 `PASS`。每张任务牌拥有独立文件面和验证锚点，Task 1 与 Task 3 可并行，Task 2 在 Task 1 后串行，Task 4 统一收口。
