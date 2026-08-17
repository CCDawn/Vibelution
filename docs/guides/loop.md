# Agent 执行环（分级 · 命令 · 完成）

---

## 1. 分级（必须选一）

| Tier | IF | THEN |
| --- | --- | --- |
| `FAST_PATCH` | 单面、可逆；无 API/权限/删除/迁移/生命周期 | 必须使用任务 worktree 与 `codex/<task-slug>` 分支；仅验证可精简；BRT 可静默 |
| `STANDARD_TASK` | 功能/Bug/多文件 UI/用户可见 | 默认任务 worktree；claim；聚焦测试；刷新判断 |
| `HIGH_RISK` | 删档/密钥/迁移/Launcher/LLM 路由/RAG/发布/热文件/共享 DTO | 全证据；隔离；破坏性先确认 |

升级优先。定义：`development-standard.md` §2.1。

---

## 2. 循环（逐步）

```text
1 CLASSIFY  tier + route.md 行
2 LOCATE    ownership.md → 模块 README → 现有 test
3 RESEARCH  §2.2：评估本地 + 对照仓外成熟方案 → 评估排序，只借最符合项目的切片；未闭合不写
4 ISOLATE   worktree if STANDARD+|ISOLATION_REQUIRED；claim if multi-agent
5 IMPLEMENT 只改 owner；SSOT 表 if 状态/API
6 VERIFY    select_tests → focused → UI contract if FE；所有验证在 merge 前完成
7 EVIDENCE  logging decision；runtime_scenes if 运行时；closeout/验收证据在 merge 前闭合
8 INTEGRATE 合入门全绿后必须主动 `git merge --ff-only`；不得等用户再下令审查/合入
9 CLEAN     merge 成功即清理本任务临时内容/进程、claim、junction、worktree、本地分支；不等待 post-merge validation
10 CLOSE     完成块（§6）；refresh 三选一
```

---

## 3. 命令（复制即用）

```powershell
# 影响面
.\.venv\Scripts\python.exe tests\select_tests.py --from-git main --commands-only

# pytest 聚焦
.\.venv\Scripts\python.exe -m pytest tests\test_TARGET.py -q

# FE（cwd=web）
npm test -- --run PATTERN
npx tsc -b --pretty false

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

## 5. Refresh 三选一（必报）

| 值 | WHEN |
| --- | --- |
| `not needed` | 纯 docs/注释/不进运行时 |
| `recommended before user testing` | FE 需肉眼或热更新可能不够 |
| `required before release` / 需 restart | `agent.py` / `core/llm` / runtime / launcher / 配置加载路径 |

active-work 挡 restart → 固定句（`AGENTS.md`§4），禁止强杀。

---

## 6. 完成报告模板（Agent 输出）

```text
## 变更
- 改：…
- 未改：…

## 验证
- 命令：…
- 结果：pass|fail
- 未覆盖：…

## Runtime
- Launcher refresh: not needed | recommended | required
- 无控制台: n/a | helper=… | 证据=…

## 协作
- worktree/branch/claim: …
- review: pass | blocker=…
- merge: merged | not merged + 精确原因
- cleanup: removed=… | cleanup pending=精确残留与原因 | not merged（仅当有精确 blocker）
- project-memory: not affected | 更新点=…
- version impact: none | …

## 风险
- fallback/partial: 无 | 原因/可信范围/剩余信号=…
```

缺字段 = 未完成（有意义任务）。

---

## 7. HARD STOP

| 条件 | 动作 |
| --- | --- |
| 与他人 diff/claim 重叠 | 停；查 claim；不覆盖 |
| 合入门已通过却未主动合入 | 未完成；立即 ff-only 或写精确 blocker |
| 需 remote push/PR/force | 停；要用户授权 |
| 需 force、远端删除、或归属不明的删/重置 | 停；要确认；已合入本任务的安全本地清理不重复询问 |
| SSOT 表填不出 | 停；不实现 |
| 调研门未闭合（未评估本地复用/改造，未对照仓外方案，或未评估排序并选出最值得借鉴的部分） | 停；不实现 |
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
