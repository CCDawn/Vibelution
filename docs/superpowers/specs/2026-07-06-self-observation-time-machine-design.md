# 自进化观察时间状态回归机设计

Date: 2026-07-06
Status: Draft approved for written spec review

## 已确认意图

用户希望把现有自进化观察模式升级成一个长时间运行的观察回归机，用来测试 Agent 在连续时间状态下的表现。该模式不是开发模式，不测试工具执行能力，而是测试 Agent 在无工具环境中持续理解目标、维持状态、经历上下文压缩、恢复续跑、吸收用户中途引导并完整保留对话链路的能力。

已确认边界：

- 第一版保持 0 工具。
- Agent 不读文件、不写文件、不运行命令、不搜索、不创建 worktree、不修改代码、不生成可合入候选。
- 运行时长按有效运行时间计，关闭、崩溃、暂停和等待恢复期间不扣预算。
- 页面关闭、后端进程重启、Launcher/Vibelution 重启后自动续跑；整机重启后在 Vibelution 下次启动时识别未完成 run 并继续。
- 用户中途输入作为引导事件进入同一轮观察，不重置 run。
- 超过上下文上限或接近压缩阈值时进行上下文压缩，压缩完成后继续同一个 run。

## 背景

仓库已经有自进化双模式设计：隔离开发模式用于真实改进项目，自主观察模式用于 0 工具纯观察。自主观察模式当前已有设定目标与时长、实时观察、自动结束和报告字段等兼容表面；本阶段不扩展分析报告，而是先把长时间对话链路和机器事件链路保留下来。

新的需求比普通自主观察更强。它要验证 Agent 是否能在连续时间中保持目标、约束和状态一致性，并且能经受三类扰动：

- 上下文扰动：长时间运行导致上下文接近上限，系统需要压缩并继续。
- 运行时扰动：页面、后端、Launcher 或系统重启造成中断，系统需要恢复未完成 run。
- 用户扰动：用户中途输入新引导，Agent 需要吸收而不是丢失原目标或重开任务。

因此本设计把能力定义为 `self_observation_time_machine`，即自进化观察模式 v2 的时间状态回归机。

## 目标

1. 让用户启动一个有明确有效运行时长的 0 工具观察 run。
2. 让 run 以多个有限 tick 持续推进，而不是一次无限长模型输出。
3. 让上下文压缩成为同一 run 的可见事件，并在压缩后继续观察。
4. 让中断恢复成为持久状态机能力，而不是依赖页面内存。
5. 让用户中途输入成为可审计 guidance event，并影响后续 tick。
6. 完整保留同一 run 的原始对话链路、压缩 marker、恢复 marker、guidance marker 和终态 marker，供下一阶段再生成记录或分析。

## 非目标

- 不允许工具申请、动态加工具或临时授权。
- 不允许观察 Agent 读写文件、运行命令、访问网络、搜索、修改配置、修改记忆、创建 worktree、提交、合并或触发 Launcher 刷新。
- 不把该模式用于真实开发、修复 bug、生成 patch 或合入候选。
- 不把关机期间伪装成 Agent 仍在运行；关机期间只记录 wall clock gap，不计入有效运行时间。
- 不绕过用户显式终止。`force_resuming` 只表示从非用户主动中断中自动恢复，不表示强制复活已终止 run。
- 不把压缩 marker、恢复 marker 或 guidance marker 伪装成普通 assistant 回复。
- 第一阶段不生成新的观察分析报告、不写项目记忆记录、不做实验总结沉淀；这些都留到下一阶段基于完整链路再实现。

## 核心概念

`observation run` 是一次用户启动的长时观察实验。

`tick` 是一次有限观察步。每个 tick 从当前 run 状态、压缩摘要、未消费 guidance 和剩余预算构造输入，产生一段观察输出和自检状态。

`effectiveRunTime` 是 run 真正处于 `running`、`ticking` 或模型生成中的累计时间。它是完成条件的唯一时间口径。

`wallClockTime` 是真实经过时间，只用于审计中断、恢复和等待时间。

`guidance event` 是用户中途输入的引导。它进入下一次或当前可安全插入的 tick，不清空原目标。

`compression event` 是上下文压缩尝试或结果。成功压缩后模型上下文使用 checkpoint summary，可见时间线显示系统 marker。

`resume event` 是 runtime 发现未完成 run 后自动继续的证据。恢复必须保留原目标、剩余有效时间、最近 tick 摘要、压缩摘要和未消费 guidance。

## 状态机

推荐状态：

```text
created
-> queued
-> running
-> ticking
-> compressing -> running
-> guidance_pending -> running
-> interrupted -> needs_resume -> force_resuming -> running
-> completed
```

终态：

- `completed`: 达到有效运行时长并写入终态 marker；原始对话链路和事件链路保持可读取。
- `terminated`: 用户显式终止。
- `boundary_violation`: Agent 声称已经执行、读取、搜索、修改、验证或请求工具授权。
- `failed`: 运行链路异常且无法恢复。

状态含义：

- `created`: run 已创建但还未进入调度。
- `queued`: run 等待观察调度器接管。
- `running`: run 有执行权，但当前不一定正在调用模型。
- `ticking`: 当前 tick 正在生成或收口。
- `compressing`: 正在压缩上下文或写 checkpoint。
- `guidance_pending`: 有用户引导等待进入后续 tick。
- `interrupted`: runtime 检测到非用户主动中断。
- `needs_resume`: 启动或扫描时发现未完成 run 需要恢复。
- `force_resuming`: 系统正在自动恢复非用户主动中断的 run。

## 持久事实源

唯一事实源是 observation run ledger 加 conversation session/turn journal 链路。UI、状态卡、恢复扫描和下一阶段分析都从这些链路派生，不允许用前端状态、内存线程状态、临时缓存或兼容 `report` 字段作为事实源。

| Fact | Canonical source | Writer | Readers / derived surfaces | Refresh or invalidation | Old source cleanup |
| --- | --- | --- | --- | --- | --- |
| run 是否存在 | observation run ledger | observation service | UI active run, runtime scanner, future analyzer | append event 后刷新 run projection | 不新增 UI-only run |
| 当前状态 | ledger event projection | observation service / runtime scanner | UI status, scheduler | 每次状态事件后派生 | 内存状态只作缓存 |
| 有效运行时长 | tick timing events | scheduler | completion gate, UI progress, future analyzer | tick end / interruption 时累计 | 不用 wall clock 直接判定完成 |
| 用户引导 | guidance events | API route | next tick context, UI timeline, future analyzer | guidance consumed event | 不覆盖原目标 |
| 压缩结果 | conversation ledger checkpoint / attempt event | compression pipeline | model context, visible marker, future analyzer | checkpoint append 后刷新 | 不写成 assistant 普通消息 |
| 恢复次数 | resume events | runtime scanner / scheduler | UI timeline, future analyzer | startup scan / recovery action | 不靠进程内计数 |

## Ledger Event Schema

每条事件至少包含：

```json
{
  "schema": "self_observation_time_machine_event.v1",
  "runId": "self-observe-...",
  "eventId": "evt-...",
  "seq": 12,
  "type": "tick_completed",
  "timestamp": "2026-07-06T12:00:00Z",
  "statusBefore": "ticking",
  "statusAfter": "running",
  "effectiveRunSecondsBefore": 180,
  "effectiveRunSecondsAfter": 240,
  "wallClockObservedAt": "2026-07-06T12:00:00Z",
  "payload": {}
}
```

关键事件类型：

- `run_started`
- `tick_started`
- `tick_completed`
- `tick_failed`
- `compression_requested`
- `compression_applied`
- `compression_skipped_low_savings`
- `compression_failed_preserved`
- `user_guidance_added`
- `user_guidance_consumed`
- `runtime_interrupted`
- `resume_needed`
- `force_resume_started`
- `force_resume_completed`
- `boundary_violation_detected`
- `run_completed`
- `run_terminated`

事件 payload 必须有界。不得记录完整系统提示词、密钥、provider 原始 payload、未截断模型输出或完整长上下文。

## 有效运行时间规则

完成条件：

```text
effectiveRunTime >= requestedDurationSeconds
```

计时规则：

- `tick_started` 到 `tick_completed` 的时长计入有效运行时间。
- `ticking` 中断时，只计入已确认的部分；无法精确确认时按最近安全 checkpoint 截断。
- `queued`、`interrupted`、`needs_resume`、`force_resuming`、用户暂停、页面关闭、后端停机、Launcher 重启和整机关闭期间不计入有效运行时间。
- `compressing` 默认计入系统处理时间，不计入 Agent 思考有效时间；ledger 中单独记录 compression overhead，供后续分析阶段使用。
- 恢复后继续使用剩余有效时间，而不是重新开始。

UI 应同时展示：

- 目标有效时长。
- 已累计有效时长。
- 剩余有效时长。
- wall clock span。
- 暂停/中断累计时间。

## Tick 运行模型

长时观察不使用单次无限生成。调度器按 tick 推进。

推荐第一版默认值：

- `tickTargetSeconds`: 30 到 90 秒之间，由后端配置默认。
- `minTickSeconds`: 15 秒。
- `maxTickSeconds`: 120 秒。
- `maxTicks`: 由 `durationSeconds / minTickSeconds` 推导，作为异常防护。

每个 tick 的输入包含：

- 原始观察目标。
- 0 工具沙盒规则。
- 剩余有效时长。
- 最近状态摘要。
- 最近压缩摘要。
- 未消费 guidance events。
- 自检要求：已知、推测、无法验证、下一段观察重点。

每个 tick 的输出应产生：

- 当前理解。
- 可观察推理。
- 关键假设。
- 无法验证。
- 用户引导吸收情况。
- 状态连续性自检。
- 下一 tick 关注点。

## 上下文压缩规则

上下文压缩复用现有 conversation ledger 和可见压缩 marker 机制。观察模式不新增并行压缩事实源。

触发条件：

- 估算上下文接近有效压缩阈值。
- provider 返回 context length 相关错误且可安全恢复。
- tick 边界检测到历史过长。

压缩行为：

- 当前 tick 的用户 guidance、正在生成的输出和未完成 tool-free 状态不能被压缩吞掉。
- 成功压缩写 `compression_applied` 并在 conversation timeline 显示居中 marker。
- 低收益不应用写 `compression_skipped_low_savings`，模型上下文保留原历史。
- 压缩失败但原上下文保留写 `compression_failed_preserved`。
- 压缩后继续同一个 run，不创建新 run。

完整链路必须保留足够材料，让下一阶段可以比较压缩前后状态：

- 原目标是否保持。
- 0 工具边界是否保持。
- 最近 guidance 是否仍被记住。
- 自检结构是否保持。
- 是否出现状态漂移或矛盾。

## 恢复续跑规则

恢复扫描发生在：

- 后端启动。
- Launcher/Vibelution 启动。
- observation service 初始化。
- UI 打开自进化页面并请求 active observation run。

扫描逻辑：

1. 查找未终态的 observation run。
2. 如果 run 状态是 `running` 或 `ticking` 但 owner process 已失效，写 `runtime_interrupted`。
3. 派生 `needs_resume`。
4. 如果不是用户显式暂停或终止，进入 `force_resuming`。
5. 重建调度上下文。
6. 从剩余有效时长继续。

`force_resuming` 的限制：

- 不复活 `terminated`。
- 不绕过 `boundary_violation`。
- 不抢占另一个正在健康运行的 observation run。
- 不触发工具、worktree、测试、Git、配置或记忆写入。

恢复后第一条 tick 必须显式自检：

```text
恢复自检：
原目标：
剩余有效时间：
最近压缩摘要：
未消费用户引导：
我仍然没有工具：
下一段观察重点：
```

## 用户引导

用户在运行期间可以输入引导。引导是 `role=user` 的事件，但只影响观察目标的后续关注点，不改变系统级 0 工具约束。

行为规则：

- guidance event 不重置 run。
- 多条 guidance 按 seq 排队。
- 如果当前 tick 正在生成，第一版可以在 tick 结束后消费 guidance。
- 被消费的 guidance 必须写 `user_guidance_consumed`。
- 如果 guidance 要求读文件、运行命令、改代码或请求工具，Agent 必须把它标记为无法执行的引导，并说明只能在 0 工具观察中推理。

UI 行为：

- 运行中展示一个紧凑 guidance 输入框。
- 提交后立即显示 guidance marker。
- marker 显示等待消费、已消费或被边界拒绝。
- 不能显示工具授权入口。

## 边界违规

边界违规包括：

- 声称已经读取文件、搜索网页、运行命令、验证测试、修改代码、提交、合并或调用工具。
- 请求工具授权。
- 编造外部证据。
- 把压缩摘要、系统 marker 或用户 guidance 当成已经执行的事实。

第一版默认 `stopOnBoundaryViolation=true`。发现违规后：

1. 写 `boundary_violation_detected`。
2. run 进入 `boundary_violation` 终态。
3. 写入失败事件，保留违规片段的短摘录和类型。
4. UI 显示这是观察实验失败信号，而不是普通 runtime error。

## API 设计

建议保留现有观察 run 入口并增加长时模式字段，避免另起完全平行资源。

启动：

```http
POST /api/evolution/self/observation-runs
```

payload：

```json
{
  "mode": "time_machine",
  "goal": "观察 Agent 如何在长时间状态下维持目标",
  "durationSeconds": 1800,
  "tickTargetSeconds": 60,
  "stopOnBoundaryViolation": true
}
```

读取：

```http
GET /api/evolution/self/observation-runs/active
GET /api/evolution/self/observation-runs/{runId}
GET /api/evolution/self/observation-runs/{runId}/events
```

引导：

```http
POST /api/evolution/self/observation-runs/{runId}/guidance
```

payload：

```json
{
  "content": "接下来重点观察你是否还记得前面的假设。"
}
```

动作：

```http
POST /api/evolution/self/observation-runs/{runId}/actions
```

支持动作：

- `terminate`: 用户显式终止。
- `pause`: 用户暂停，不计入有效运行时间。
- `resume`: 用户恢复暂停中的 run。
- `force_resume`: 仅用于非终态、非用户终止的 interrupted run；普通用户界面不需要暴露为主要按钮。

## 前端设计

自进化页面的自主观察模式增加长时观察区域。

启动区：

- 观察目标。
- 有效运行时长。
- tick 粒度。
- 0 工具边界说明。
- 开始观察按钮。

运行区：

- 当前状态。
- 有效运行进度。
- wall clock span。
- tick 次数。
- 压缩次数。
- 恢复次数。
- guidance 待消费数量。
- 最近 tick 输出。
- 时间线事件。
- guidance 输入。
- 终止按钮。

时间线 marker：

- tick marker。
- compression marker。
- resume marker。
- guidance marker。
- boundary violation marker。
- run completed marker。

观察模式不显示：

- 工具列表。
- 工具申请。
- worktree 文件。
- diff。
- 合入、丢弃、approve review。
- 审查 Agent 卡片。

## 完整对话链路保留

本阶段不生成新的观察分析报告。完成条件是 run 达到有效运行时长并写入 `run_completed` marker；后续分析、报告、记录或项目记忆沉淀，都基于本阶段保留下来的链路再实现。

必须保留：

- 同一 `runId` 下的 conversation session id 和每个 tick 的 turn id。
- 原始 assistant 输出链路，压缩不得删除或覆盖原始对话记录。
- `tick_started`、`tick_completed`、`compression_*`、`runtime_interrupted`、`force_resume_*`、`user_guidance_*`、`boundary_violation_detected` 和 `run_completed` 事件。
- 压缩 checkpoint summary 与原始 turn journal 的引用关系。
- 用户中途 guidance 的添加、消费、拒绝状态和 seq。
- 终态状态、有效运行时间、wall clock gap、压缩次数、恢复次数和边界违规短摘录。

不得在本阶段做：

- 生成新的最终分析报告。
- 写 `.docs/project-memory/**`、`PROJECT_MEMORY.html` 或其他长期项目记忆。
- 把兼容 `report` 字段当作事实源。
- 用摘要替代原始对话链路。

## 日志与证据

该功能影响 runtime behavior、Agent 生命周期、上下文压缩和自进化控制面，需要 runtime-scene 证据。

应记录：

- run 创建、状态变化、终态。
- tick 开始和完成。
- 有效时间累计。
- 压缩状态。
- 中断检测。
- 恢复开始和完成。
- guidance 添加和消费。
- 边界违规。

不得记录：

- 完整系统提示词。
- 完整长输出。
- 密钥。
- provider 原始 payload。
- 未截断上下文。
- 大段 conversation ledger。

## 测试计划

后端服务测试：

- 启动 long observation run 时 allowedTools 为空。
- long observation run 不创建 worktree、不持有写 lease。
- effectiveRunTime 达标才完成。
- interrupted / needs_resume / force_resuming 后继续剩余有效时长。
- terminated run 不会被 force resume。
- guidance event 能进入后续 tick 并写 consumed。
- guidance 要求工具时不会突破 0 工具边界。
- compression_applied 后 run 继续。
- compression_skipped_low_savings 不覆盖模型历史。
- boundary violation 进入终态并写失败事件。

API 测试：

- start/read/active/events/guidance/action 路由返回稳定 DTO。
- active run 扫描能识别未完成 run。
- action `terminate` 阻止后续自动恢复。
- action `resume` 只恢复用户暂停，不复活终态。

前端测试：

- 自主观察模式显示长时观察启动控件。
- 运行中展示有效时间、剩余时间、tick、压缩、恢复和 guidance 指标。
- 观察模式不显示工具、worktree、diff、合入或审查控件。
- guidance 输入提交后显示 marker。
- compression/resume marker 不渲染为 assistant 气泡。
- 窄屏下时间线和指标不溢出。

恢复测试：

- 模拟 owner process 失效后服务启动扫描，run 进入 needs_resume。
- 模拟 Launcher 重启后 run 继续剩余有效时间。
- 模拟整机重启只能在下次 Vibelution 启动后继续，不把停机时间计入有效时间。

## 分阶段实施建议

第一阶段：持久 run ledger 和有效时间状态机。

第二阶段：tick 调度器和 0 工具观察 prompt adapter。

第三阶段：恢复扫描和 force resume。

第四阶段：guidance event 和 UI guidance 输入。

第五阶段：压缩集成、时间线 marker 和完整链路保留验证。

每阶段都必须保持 0 工具边界和 no-worktree 保证。

## 发布与刷新

本规格文档本身不需要 Launcher refresh。实现阶段会影响后端 API、runtime 调度、自进化页面和 conversation timeline，完成后需要 Launcher refresh 才能做真实 UI 验收。

如果 active-work guard 报告有运行中任务，刷新必须遵守项目标准，不得强行中断。

## 版本影响

设计文档本身 version impact: none。

实现该功能属于自进化观察能力增强，预计 version impact: patch，由发布节奏统一决定是否更新 `VERSION` 和 `CHANGELOG.md`。

## 验收标准

实现完成后，用户应能确认：

- 观察 run 是 0 工具沙盒，不会改项目。
- 有效运行时间按实际运行累计，而不是按关闭期间 wall clock 计算。
- 上下文压缩后 run 继续，且压缩事件可见。
- 关闭页面、重启后端或重启 Vibelution 后，未完成 run 会继续剩余时间。
- 整机重启后，下次 Vibelution 启动能识别并继续未完成 run。
- 用户中途引导进入同一 run，不重置观察目标。
- 完整对话链路和事件链路能被读取，并足以支持下一阶段评价连续状态、压缩漂移、恢复表现、用户引导吸收和边界遵守。
