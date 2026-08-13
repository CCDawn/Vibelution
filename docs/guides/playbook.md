# Agent Playbook（边界摘要）

**不替代** `docs/standards/development-standard.md`。
只保留 Agent 实现时高频边界；细则下钻标准章节。

---

## 1. 运行时拓扑

```text
Launcher → Runtime Manager → FastAPI (core/web) + agent.py turn
                          → React Workbench (web/)
Config: Documents\Vibelution\config\config.toml   (ADR0003)
State: %LOCALAPPDATA%\Vibelution\projects\<projectId>\instances\<instanceId>\
Evidence: <active-state>\logs\runtime_scenes\
Turn SSOT: turn_journal.jsonl → SessionTurnItem 投影
```

Chat 地图：`docs/agents/conversation-flow-map.md`
LLM：`core/llm/PROTOCOL.md`

---

## 2. 红线（FAIL CLOSED）

| ID | 规则 |
| --- | --- |
| R1 | Windows 产品路径 **无可见控制台**（§8.0） |
| R2 | 产品 UI = **VUI + shadcn renderer only**（ADR0004） |
| R3 | 不覆盖无关用户/Agent 改动；先 claim |
| R4 | archive/plan 历史 **非**现行规则（ADR0005） |
| R5 | 每事实 **单一写入权威**；projection 只读派生（§3.1） |
| R6 | 用户内容进模型/索引前隔离清洗 |
| R7 | remote/force 需明确授权 |
| R8 | 有意义任务必须有验证 + refresh + claim/memory 判断 |

---

## 3. 分层 MUST

### BE

| 层 | MUST | MUST NOT |
| --- | --- | --- |
| route | 解析、DTO、`response_model`、委托 | 业务决策、直改 store |
| facade | 稳定 import / re-export | 无界堆实现 |
| pack | 命令/查询/投影/生命周期 | 跨域垃圾场 |

### FE

| 层 | MUST | MUST NOT |
| --- | --- | --- |
| Route | 组合 recipe + domain | 新 transport、renderer 直连 |
| `api/*` | path + DTO + keys | React 状态 |
| `vui` | `V*` + designs 登记 | 业务 endpoint |

### LLM

| MUST | MUST NOT |
| --- | --- |
| 经 `core.llm` invoke/stream | 业务层拼裸厂商 body 常态化 |
| cache 策略跟 profile.mode | 中途改写打断 automatic 前缀的稳定头 |
| status bar 等易变块放 **消息列表尾** | 插在 user/tool 前缀中间 |

---

## 4. 全栈顺序（跨 HTTP）

```text
1 domain + SSOT 表
2 Pydantic 合同 + TS DTO
3 service/pack
4 薄 route
5 web/src/api/<domain>.ts + query keys
6 VUI 组合
7 分层测试 + cache 收敛
```

目录表：§24.1。完成：§24.5。

---

## 5. Fallback

用户可见或决策相关 → 必须暴露 `fallback|degraded|partial|…` + reason + scope + 可信范围。
禁止报 success 掩盖失败（§3.2）。

---

## 6. 下钻索引

| 需要 | 打开 |
| --- | --- |
| 分级/BRT/SSOT/日志/测试策略 | `docs/standards/development-standard.md` |
| 任务→文件 | `docs/guides/route.md` |
| 路径 owner | `docs/guides/ownership.md` |
| 命令/完成块 | `docs/guides/loop.md` |
| 配置字段 | `docs/ops/config/INDEX.md` |
| 协作 claim | `docs/agents/worktree-collaboration.md` |
| 工具权 | `docs/agents/tool-authorization-entrypoints.md` |
| 领域词 | `docs/agents/domain.md` |
