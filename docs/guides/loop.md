# Agent 执行环（分级 · 命令 · 完成）

---

## 1. 分级（必须选一）

| Tier | IF | THEN |
| --- | --- | --- |
| `FAST_PATCH` | 单面、可逆；无 API/权限/删除/迁移/生命周期 | 必须使用任务 worktree 与 `codex/<task-slug>` 分支；仅验证可精简；Router 可静默 |
| `STANDARD_TASK` | 功能/Bug/多文件 UI/用户可见 | 默认任务 worktree；claim；聚焦测试；刷新判断 |
| `HIGH_RISK` | 删档/密钥/迁移/Launcher/LLM 路由/RAG/发布/热文件/共享 DTO | 全证据；隔离；破坏性先确认 |

升级优先。定义：`development-standard.md` §2.1。

---

## 2. 循环（逐步）

```text
1 CLASSIFY  tier + route.md 行
2 LOCATE    ownership.md → 模块 README → 现有 test
3 RESEARCH  §2.2：始终评估本地；架构/依赖/复杂能力/真实复用分歧才做仓外对照与排序；已定位小修不付固定扫描成本
4 ISOLATE   worktree if STANDARD+|ISOLATION_REQUIRED；pre-commit 按 staged paths 自动取得或复核窄 claim，真实重叠才阻止
5 IMPLEMENT 只改 owner；SSOT 表 if 状态/API
6 VERIFY    稳定修改批次按影响面跑最窄反馈测试；同一 HEAD/命令/输入未变不重复跑；完整 selector 计划留给最终 closeout 一次执行
7 EVIDENCE  实现文件变更：已定位小修记 `LOCAL_ONLY`，需仓外对照记 `EXTERNAL`；logging/runtime 证据按影响面；验收在 merge 前闭合
8 INTEGRATE 默认用 `scripts/task_closeout.py` 一次完成最终验证、短时 integration claim、ff-only merge 与清理；不得先手动 closeout 后无参重跑，不得等用户再下令审查/合入
9 CLEAN     merge 成功即清理本任务临时内容/进程、claim、junction、worktree、本地分支；不等待 post-merge validation
10 CLOSE     对用户汇报（根 `AGENTS.md` §5）；内部合入/清理仍做，不贴完成块
```

---

## 3. 命令（复制即用）

```powershell
# 影响面
.\.venv\Scripts\python.exe tests\select_tests.py --from-git main --commands-only

# pytest 聚焦
.\.venv\Scripts\python.exe -m pytest tests\test_TARGET.py -q

# 实现文件变更：已定位小修用 LOCAL_ONLY；复杂/开放复用决策用默认 EXTERNAL
.\.venv\Scripts\python.exe scripts\reuse_research_evidence.py record --help

# 最终收口必须从根 main cwd 调用；pre-commit 已记录 claim binding 时可省略 claim-id/agent-id；未生成 manifest 时只执行一次 selector 计划
Set-Location "<ROOT_MAIN>"
.\.venv\Scripts\python.exe scripts\task_closeout.py --task-worktree "<TASK_WORKTREE>"
# selector 中的 .venv 是逻辑命令；同 requirements 指纹时由 gate 只读解析到根 main .venv，禁止在任务树创建 junction
# 已有 manifest 或 integration 冲突返回 manifest：原样复用，禁止再跑测试
.\.venv\Scripts\python.exe scripts\task_closeout.py --task-worktree "<TASK_WORKTREE>" --manifest "<MANIFEST_PATH>"
# 仅 stale_main：同步/提交最新 main 后，携带返回的一次性 token 做一次 reserve retry
.\.venv\Scripts\python.exe scripts\task_closeout.py --task-worktree "<TASK_WORKTREE>" --reserve-integration --stale-retry-token "<TOKEN_PATH>"
# merged_cleanup_pending 表示已合入，只补清理，不验证/不 merge
.\.venv\Scripts\python.exe scripts\task_closeout.py --task-worktree "<TASK_WORKTREE>" --branch "codex/<TASK>" --agent-id "<AGENT_ID>" --cleanup-only

# FE focused Vitest（仓库根执行，selector 输出格式）
node web/node_modules/vitest/vitest.mjs run --changed main --passWithNoTests --root web
node web/node_modules/typescript/bin/tsc -b web/tsconfig.json --pretty false

# 连不上 / 无响应：先解析本机工作台实开 URL，再进下面三件套。不要默认打 :8000。
# 必须在 Launcher 打开的那个 checkout 根目录跑（通常是本地 main），不要在任务 worktree 里跑。
.\.venv\Scripts\python.exe scripts\vibelution_desktop_entry.py --action resolve-workbench --output json
# 只对返回的 workbenchUrl 探 /api/health。:8000 无监听只说明默认口空，不能当工作台未启动。
# 实开口权威：env → .runtime/launcher/ports.json → config.toml backend_port（默认 8000）。
# —— 日志诊断（统一入口；细则见 docs/guides/agent-log-routing.md）——
# 1) 所有 Agent 第一步：路径 + 当前 scene + agent_brief（可选 session/turn）
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>"
.\.venv\Scripts\python.exe scripts\agent_log_context.py --project "<ROOT>" --session-id ID --turn-id TID
# 2) 本机环境医生（venv / hooks / 关键模块）
powershell -NoProfile -File .\scripts\doctor.ps1

# Launcher
# %LOCALAPPDATA%\Vibelution\Launcher\VibelutionLauncher.exe --project "<ROOT>" start|stop|restart
```

Config 真源：`%USERPROFILE%\Documents\Vibelution\config\config.toml`
Override：`VIBELUTION_CONFIG_PATH` / `VIBELUTION_CONFIG_HOME`

Launcher / runtime 落点速查：[`core/web/services/launcher_runtime.md`](../../core/web/services/launcher_runtime.md)

---

## 4. 验证叠加

| 触面 | 最小证明 |
| --- | --- |
| docs only | 入口链接有效；写 refresh=`not needed` |
| py 逻辑 | 对应 pytest 绿 |
| service/route | service + HTTP/contract |
| FE 逻辑 | colocated test |
| FE 可见 UI | + `vuiShadcnRouteContract` + 触及 layout/route contract |
| LLM | 相关 pytest；实机需 restart 后看 cache/usage |
| process | launcher/runtime 测试 + 无控制台路径说明 |
| 全栈 API | §24.5 全行 |

---

## 5. Refresh 判断（内部）

Agent 内部必须判断要不要重启 Launcher。对用户只在需要对方动手时说「请重启后再试」；不要贴 `not needed / recommended / required` 枚举。

| 值 | WHEN |
| --- | --- |
| `not needed` | 纯 docs/注释/不进运行时 |
| `recommended before user testing` | FE 需肉眼或热更新可能不够 |
| `required before release` / 需 restart | `agent.py` / `core/llm` / runtime / launcher / 配置加载路径 |

active-work 挡 restart → 固定句（`AGENTS.md`§4），禁止强杀。

---

## 6. 对用户怎么写

对用户的完成说明以根 [`AGENTS.md` §5](../../AGENTS.md) 为准：第一句说清结果，再补怎么试和没做什么。不要输出下面这种完成块，也不要用「缺字段 = 未完成」强迫把闸门清单贴给用户。

内部仍须：聚焦验证、合入前 closeout、合入后清理。这些是执行义务，不是回复格式。合入失败或清理失败时用一句人话说明 blocker / 残留。

---

## 7. HARD STOP

| 条件 | 动作 |
| --- | --- |
| 与他人 diff/claim 重叠 | 停；查 claim；不覆盖 |
| 合入门已通过却未主动合入 | 未完成；立即 ff-only 或写精确 blocker |
| 需 remote push/PR/force | 停；要用户授权 |
| 需 force、远端删除、或归属不明的删/重置 | 停；要确认；已合入本任务的安全本地清理不重复询问 |
| SSOT 表填不出 | 停；不实现 |
| 未评估本地复用，或任务有复杂/开放复用决策却未完成必要仓外排序 | 停；不实现 |
| `validation_toolchain_mismatch|missing|unhealthy` | 停；修复根共享环境或依赖身份，不创建任务 `.venv` junction |
| 仅 archive 有「规定」 | 提炼到现行或标 historical；不直接执行 archive |

---

## 8. 禁止清单（执行时扫）

```text
[ ] 不调研不评估就开写 / 把本地能复用当成原样照搬
[ ] 调研后不排序、整仓照搬或只堆链接不裁决
[ ] archive 当现行规则
[ ] 非 VUI 交付可见 UI
[ ] route 直连 renderer / HeroUI
[ ] 仓库根 config 当已生效
[ ] projection 双写
[ ] 静默 fallback=success
[ ] 日志 secrets/全 prompt/无界输出
[ ] taskkill / 可见控制台产品路径
[ ] 无授权 push
```
