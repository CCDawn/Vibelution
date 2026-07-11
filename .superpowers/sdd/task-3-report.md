# Task 3 Report: 前端冲突裁决与重新预览

## 状态

- Development Mode: `BDD_TDD`
- Branch: `codex/llm-artifact-resolution-domain`
- Claim: `claim-f9b0e7efc189`
- 范围：仅修改 Task 3 brief 列出的前端 API types、迁移面板、Route、样式与测试；未修改后端、operator config、apply confirm、版本文件或依赖。

## 行为契约

- Given schema v1 preview 返回 `artifact_path_suspected` 与服务端允许的裁决。
- When 用户为每个 modelId 选择 preserve 或 split 并提交裁决。
- Then 前端只构造冻结 union request 并重新调用 preview endpoint；`migrationPreview` 只由新响应更新。
- And preserve 必须显式确认，split 必须是非空且非路径型 upstreamId；本地 draft 不会解锁 apply，只有服务端 preview `READY` 才能解锁。

## RED

先新增 `configMigrationResolutionLogic.test.ts` 与 `ConfigRoute.layout.test.ts` 合同断言，再运行：

```powershell
npm --prefix web run test -- ConfigRoute.layout.test.ts configMigrationResolutionLogic.test.ts --reporter=dot
```

结果：exit 1。纯逻辑模块尚不存在；layout 合同因缺少 code 识别、只-preview 提交与响应式裁决样式而失败，失败原因与目标行为一致。

## GREEN

- 新增纯逻辑模块，集中拥有 draft 初始化、服务端 allowedResolutions 约束、preserve 确认、split upstreamId 即时校验、modelId 去重与稳定 request 顺序。
- 扩展前端 API types，准确表达 artifact conflict、决策 union 与 preview request。
- 迁移面板按 `conflict.code` 渲染每-modelId 裁决卡，仅显示安全字段和 `unverified_offline` 状态；未显示、请求或推断实际部署文件路径。
- preserve 只在服务端允许时出现且需要 checkbox；split 拒绝相对、绝对、UNC 与权重文件后缀输入。
- 普通预览发送空 resolutions；裁决提交只调用 preview handler。Route 使用冻结 request body 并只更新 `migrationPreview`。
- apply 继续只由 `preview.status === "READY"` 控制，本地 draft 与允许列表不参与授权。
- 响应式样式使用 `min-w-0`、可换行 action、auto-fit card grid 与局部 table 横向滚动，覆盖 390px 与桌面布局合同。

## 验证

```powershell
npm --prefix web run test -- ConfigRoute.layout.test.ts configProviderLogic.test.ts configMigrationResolutionLogic.test.ts --reporter=dot
# 4 files passed, 91 tests passed

npm --prefix web run build
# tsc -b + vite build passed, 4344 modules transformed

git diff --check
# passed, no output
```

## 自审

- 输出契约：PASS。10 个 required scenarios 由纯逻辑测试、layout/source contract 与 TypeScript build 覆盖。
- 权威边界：PASS。服务端 preview response 是 apply 状态唯一来源；本地 draft 仅用于 UX 校验和 request 构造。
- 安全边界：PASS。未调用真实 apply，未执行迁移，未读取或修改真实 operator config，未新增依赖。
- 范围：PASS。未改 Task 1/2 tests、后端、Provider wizard、operator config editor、apply confirm 或版本文件。
- Logging：不新增。该切片没有新的后端/runtime 决策点；preview/apply 请求错误继续由 Route 现有错误路径处理。
- Launcher refresh：`recommended before user testing`；本任务未刷新运行时，也未执行真实 preview/apply。
- Project memory：由主协调/集成 owner 在 Task 3 交接后统一同步；本任务不直接写共享 memory。
- Version impact：建议 `minor`，属于兼容新增的迁移裁决控制面；本任务不改版本文件。

## Concerns

- 未进行 Launcher 浏览器截图或真实 390×844 / 1440×900 运行态 QA；当前证据是响应式结构测试与 production build。应在集成阶段用只读 preview fixture/安全环境补做视觉验证，且不得触发真实 apply。
- 前端 split 校验仅是即时 UX 防线；服务端仍是最终权威，按 frozen contract 拒绝任何遗漏或伪造输入。
