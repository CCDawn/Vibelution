# 开发链路吞吐优化方案

- Status: implemented
- Owner: `codex-dev-loop-throughput-20260826`
- Branch: `codex/development-loop-throughput`
- Scope: Agent 验证提示词、本地质量门、managed closeout、`main` 集成锁与现行指南
- Close condition: 已完成。gate-definition 同负载由 103.545 秒降至约 47.924 秒；pre-commit focused 由 13.822 秒降至 5.508 秒；131 项 Prompt 契约由 111.04 秒降至 62.03 秒；行为契约已覆盖 manifest 复用、锁外验证和锁内复核。

## 1. 目标

减少 Coding Agent 在同一任务中重复跑相同测试的时间，并把 `main` 的全局集成 claim 从“整段测试期间”缩短到“最终复核与 fast-forward merge 期间”。正确性边界不变：测试结果仍绑定 task HEAD、本地 `main` SHA、changed files、claim 和 allowlisted command；任何输入变化都使旧证据失效。

## 2. 已确认瓶颈

1. `scripts/task_closeout.py` 在运行完整 `local_quality_gate.py closeout` 前获取 `integration/main` claim，TTL 为 30 分钟。一个 Agent 的分钟级测试会阻塞所有其他 Agent 合入，实际 `git merge --ff-only` 并不是长耗时部分。
2. 权威指南只描述手动 `closeout` + `verify-manifest`，没有登记 managed closeout。一旦 Agent先手动生成 manifest，再调用 managed closeout，后者会无条件重跑整套 selector 计划。
3. `tests/README.md` 明确写着 closeout 不复用早期结果；Agent Prompt 又要求每个逻辑修改批次结束后跑测试，却没有禁止对同一 HEAD/同一命令重复验证。
4. gate-definition 自测按单进程执行。相同 7 文件负载基线为 194 passed / 103.545 秒；4-worker `--dist load` 的 189 个 `not serial` 用例为 34.787 秒，5 个 `serial` 用例为 13.137 秒，合计 47.924 秒，预计减少约 53.7%。pre-commit 的 11 个 focused 用例从 13.822 秒降至 5.508 秒，预计减少约 60.2%。
5. 未被矩阵显式认领的多个 changed test files 原本整包串行执行；131 项 Prompt 契约耗时 111.04 秒。按文件隔离并行后为 62.03 秒，减少约 44.1%。

## 3. 推荐路径

### 3.1 单一收口入口与证据复用

- managed closeout 增加可选 `--manifest`。传入 manifest 时只做严格复核，不重跑测试；不传时仍由 managed closeout 生成一次 manifest。
- 文档明确二选一：通常直接调用 managed closeout；已经手动 closeout 的任务把 manifest 传给 managed closeout。禁止“手动 closeout 后再无参 managed closeout”。
- 只复用精确绑定当前 task HEAD、当前本地 `main`、changed files、claim、worktree clean 状态与命令清单的 manifest；不实现跨 HEAD 的结果缓存。

### 3.2 缩短 `main` 集成 claim

- 在没有持有 `integration/main` claim 时运行昂贵验证。
- manifest 首次通过后才获取短 TTL 集成 claim；获取后再次复核 manifest，再执行 fast-forward merge。
- 竞争期间 `main` 变化时返回 `stale_main`/validation failure，不强行合入；已有 manifest 路径随冲突结果返回，未变时重试不再跑测试。

### 3.3 消除质量门长尾

- gate-definition 自测拆为 `not serial` 与 `serial` 两条明确命令。
- `not serial` 使用 4 worker + `--dist load`，让单个大测试文件内互相隔离的用例跨 worker 分发；真实进程/环境医生仍保留 `serial`。
- pre-commit 的 11 个 gate focused 用例使用相同的 4-worker `load` 策略。
- changed-test fallback 对多个未标记 `serial` 的文件使用 bounded xdist + `loadfile`；显式 `serial` 文件拆到独立串行命令。

### 3.4 提示词约束

- 根 `AGENTS.md`、产品 `COMMON.md` 与 runtime SPEC 摘要统一写明：同一 HEAD、同一命令、相关输入未变化时复用已通过结果；修改期只跑最窄反馈测试；完整 selector 计划只在最终 closeout 跑一次。
- 失败后只重跑受影响失败项；变更测试输入、配置、依赖、HEAD 或 `main` 基线时必须重新验证。

## 4. 保护边界

- 不删除 serial 测试，不把 Launcher、端口、真实进程、Git/shared workspace 测试并行化。
- 不信任 Agent 文本报告作为测试证据；只复用质量门生成且可重新校验的 manifest。
- 不引入 pytest-testmon、Bazel、Nx 等新依赖。现有 selector、pytest-xdist 和 manifest 足以完成本轮最小改造。
- 不改变远端 CI/发布权限，也不把本地快速路径包装成完整发布证明。

## 5. 复用与外部方案裁决

1. 项目内 `local_quality_gate.py` + `select_tests.py` + `task_closeout.py` 最贴合现有 claim/HEAD/manifest 契约，作为 owning surface，改造后复用。
2. `pre-commit` 的 staged-file 过滤和显式 `require_serial` 思想只借“默认并行、危险项显式串行”的切片；不引入其整套框架。
3. Vitest 的 `--changed`/import affected-tests 思路支持“受影响测试优先”；前端现有命令已采用，Python 继续使用项目 AST selector。
4. pytest 的 duration/cache 能力用于测量和失败反馈；`--last-failed` 不作为 closeout 正确性证据，因为它不能绑定本地 `main` 与 changed-file 契约。

## 6. 验证与成功证据

- 单元契约：provided manifest 跳过 `run_closeout`；昂贵验证发生在 integration claim 之前；claim 后重新 verify；冲突/过期 manifest 不 merge。
- selector/quality gate：拆分命令被 allowlist、manifest 和 matrix 一致识别；serial 用例仍被收集。
- Prompt 契约：根规则和 runtime SPEC 均包含“输入未变不重复跑”和“closeout 一次”语义。
- 性能：同一 gate-definition 负载至少复测两次；目标总耗时低于串行 baseline 的 60%，且结果稳定通过。
- 合入：在最新本地 `main` 上生成 manifest；managed closeout 的全局 integration claim 仅覆盖最终 verify + merge。

## 7. 回滚

如果 `--dist load` 暴露跨测试污染，先保留单一收口与短锁修复，只把 gate-definition 自测恢复为串行。若短锁导致高频 `stale_main`，保留 manifest 复用接口，并将 acquisition 提前到最终 verify 前的最小可接受位置，不恢复“测试全程持锁”。
