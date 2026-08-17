# Frontend routes — Agent 30 秒表

**读者：coding Agent。** 用户可见 UI 必须 VUI + page recipe；细则见 [`docs/guides/route.md`](../../../docs/guides/route.md) 与 [`ownership.md`](../../../docs/guides/ownership.md)。

**已有专节（优先读模块 README，勿重复广扫）：**

| 域 | 模块 README |
| --- | --- |
| Chat / Coding | [`chat/README.md`](chat/README.md) |
| Teams / SC | [`teams/README.md`](teams/README.md) |

## 用法

```text
1. URL path → 下表 Route 入口
2. api 列 → web/src/api/<module>.ts（禁止 Route 内新 fetchJson）
3. layout test 列 → 改壳/布局必跑
4. 后端行为 → docs/guides/route.md「后端任务 → services 域锚点」
```

## 路由表（非 Chat / Teams）

| URL path | Route 入口 | 域 / 职责 | API 模块 | Layout / contract test |
| --- | --- | --- | --- | --- |
| `/chat` | `ChatCodingRoute.tsx` → [`chat/ChatCodingRouteWorkbench.tsx`](chat/ChatCodingRouteWorkbench.tsx) | Chat workbench | [`api/chat.ts`](../api/chat.ts) · [`agents.ts`](../api/agents.ts) | [`ChatCodingRoute.layout.test.ts`](ChatCodingRoute.layout.test.ts) |
| `/teams` | `TeamsRoute.tsx` → [`teams/TeamsRouteWorkbench.tsx`](teams/TeamsRouteWorkbench.tsx) | Teams board / canvas | [`api/teams.ts`](../api/teams.ts) · [`teamWorkflow.ts`](../api/teamWorkflow.ts) · [`sourceCollection.ts`](../api/sourceCollection.ts) | [`TeamsRoute.layout.test.ts`](TeamsRoute.layout.test.ts) |
| `/agents` | `AgentsRoute.tsx` | Agent 目录 / workspace | [`api/agents.ts`](../api/agents.ts) | [`AgentsRoute.layout.test.ts`](AgentsRoute.layout.test.ts) |
| `/agents/prompts` | `PromptTemplatesRoute.tsx` | Prompt 模板 | [`api/agents.ts`](../api/agents.ts) | [`PromptTemplatesRoute.layout.test.ts`](PromptTemplatesRoute.layout.test.ts) |
| `/agents/tools` | `ToolsRoute.tsx` | Agent 工具治理 | [`api/tools.ts`](../api/tools.ts) · [`api/agents.ts`](../api/agents.ts) | [`ToolsRoute.layout.test.ts`](ToolsRoute.layout.test.ts) |
| `/agents/skills` | `SkillsRoute.tsx` | Skill 库 | [`api/skills.ts`](../api/skills.ts) | [`SkillsRoute.layout.test.ts`](SkillsRoute.layout.test.ts) |
| `/memory` (+ subpaths) | `MemoryRoute.tsx` | Memory / knowledge UI | [`api/memory.ts`](../api/memory.ts) · [`api/knowledge.ts`](../api/knowledge.ts) | [`MemoryRoute.layout.test.ts`](MemoryRoute.layout.test.ts) |
| `/config` | `ConfigRoute.tsx` | Operator 配置工作台 | [`api/config.ts`](../api/config.ts) | [`ConfigRoute.layout.test.ts`](ConfigRoute.layout.test.ts) |
| `/git` | `GitRoute.tsx` | Git 状态 / commit / diff | [`api/git.ts`](../api/git.ts) | [`GitRoute.layout.test.ts`](GitRoute.layout.test.ts) |
| `/logs` | `LogsRoute.tsx` · `RuntimeScenesPane.tsx` | 日志树 / runtime scenes | [`api/logs.ts`](../api/logs.ts) · [`api/diagnostics.ts`](../api/diagnostics.ts) | [`LogsRoute.layout.test.ts`](LogsRoute.layout.test.ts) · [`RuntimeScenesPane.layout.test.ts`](RuntimeScenesPane.layout.test.ts) |
| `/launcher` | `LauncherRoute.tsx` | Launcher 控制（FE 壳；产品控制面在 Electron） | [`api/launcher.ts`](../api/launcher.ts) · [`api/runtime.ts`](../api/runtime.ts) | [`LauncherRoute.layout.test.ts`](LauncherRoute.layout.test.ts) |
| `/self-evolution` · `/supervised-evolution/*` | `EvolutionRoute.tsx` · `SelfEvolutionTrack.tsx` · `SupervisedReviewRoute.tsx` | 进化轨道 | [`api/evolution.ts`](../api/evolution.ts) · [`api/selfEvolution.ts`](../api/selfEvolution.ts) | [`EvolutionRoute.layout.test.ts`](EvolutionRoute.layout.test.ts) · [`SupervisedReviewRoute.layout.test.ts`](SupervisedReviewRoute.layout.test.ts) |
| `/kernel` | `KernelTaskCenterRoute.tsx` | Kernel 任务中心 | [`api/kernel.ts`](../api/kernel.ts) | [`KernelTaskCenterRoute.layout.test.ts`](KernelTaskCenterRoute.layout.test.ts) |
| `/usage` | `UsageRoute.tsx` | Token / usage | [`api/usage.ts`](../api/usage.ts) | [`UsageRoute.layout.test.ts`](UsageRoute.layout.test.ts) |
| `/pet` | `PetRoute.tsx` | Pet 运行时 | [`api/pet.ts`](../api/pet.ts) · [`api/petRuntime.ts`](../api/petRuntime.ts) | [`PetRoute.layout.test.ts`](PetRoute.layout.test.ts) |
| `/reset` | `ResetRoute.tsx` | 维护 / reset | [`api/launcher.ts`](../api/launcher.ts) | [`ResetRoute.layout.test.ts`](ResetRoute.layout.test.ts) |

## 重定向 / 壳（通常不改业务）

| 文件 | 说明 |
| --- | --- |
| `HomeRedirect.tsx` | `/` → 默认 workbench |
| `WorkbenchDomainRoute.tsx` · `WorkbenchModeRoute.tsx` | Chat / evolution mode 包装 |

## 禁止

- Route 直连 `components/vui/renderers/shadcn/*` 或 `@heroui/react`
- Route 内新硬编码 API path（走 `web/src/api/`）
- 未登记 `V*` 或 [`vui/designs/INDEX.md`](../components/vui/designs/INDEX.md) 的新控件

## 相关

| 文档 | 用途 |
| --- | --- |
| [`web/src/api/README.md`](../api/README.md) | API SSOT / queryKeys |
| [`components/vui/README.md`](../components/vui/README.md) | VUI 产品 API |
| [`docs/guides/button-selection.md`](../../../docs/guides/button-selection.md) | 按钮选型 |
