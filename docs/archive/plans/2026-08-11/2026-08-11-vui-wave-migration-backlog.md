# VUI 波次迁移待办（2026-08-11 快照）

> 状态：historical（2026-08-16 迁入 archive；现行进度以 `web/src` 契约测试为准，本文件只是 2026-08-11 快照）
> 背景：2026-08-11 对话链路完成度评估时对前端全量测试做基线核对，
> 17 个契约失败中 11 个已裁决并修复（见下），剩余 6 个为 VUI 波次迁移
> 未收尾的目标态契约。

## 已裁决修复（本日完成，提交待定）

- `SessionContextMenu.test.tsx`：Radix portal 组件静态渲染断言过时 → 改源码契约式
- `ConversationIndexTree.test.tsx`：成员数断言 `0人` → `0 人`
- `useConfigProviderDraftActions.contract.test.ts`：migration URL 已抽离到
  `useConfigMigrationActions`，旧"migration stays on route"断言过时
- `fullStackApiBoundary.test.ts` + `api/researchWorkflow.ts` +
  `useResearchWorkflowProjectContext.ts`：route 层直接 `fetchJson` 迁移到
  domain API 函数 `fetchTeamWorkflowResearchProjects`（契约要求不登记债务）
- `useEvolutionRunMutations.contract.test.ts`："最终审批方式" label 已抽到
  `EvolutionSupervisedLiveSetupPanel`，断言改 route 接线
- `web/ChatCodingRoute.layout.test.ts`：next-turn toggle 顺序断言改为
  mental chip 在 runtime chip 前（preset map 循环已随 VUI 化移除）
- `web/ConfigRoute.layout.test.ts`（根目录遗留版）：leave guard 已 VDialog 化，
  旧 `leaveGuardOverlay` 断言更新

## 剩余 6 个契约红（= VUI 波次迁移任务清单）

| 契约测试 | 缺口 | 归属波次 |
| --- | --- | --- |
| `src/design/vuiWave3cLabTokenMapContract.test.ts` | lab token 映射漂移（18 项） | Wave 3c |
| `src/design/vuiWave3ChatCompositionContract.test.ts` | Chat workbench 根缺 `data-vui-region="chat-conversation-center"` | Wave 3b |
| `src/components/layout/workbenchLayoutIds.test.ts` | `ChatCodingRouteWorkbench` 未用 `WORKBENCH_LAYOUT_IDS.chat` | Wave 4c |
| `src/design/typographyTokenContract.test.ts` | 生产源码残留 `text-[var(--vui-font-*)]` 颜色陷阱 | Wave 9/9b |
| `src/design/vuiSurfaceAlphaPolicy.test.ts` | `TeamsRoute.styles.ts`、`ConversationTranscriptLoadingState.styles.ts` 的 `color-mix(...transparent)` 结构 wash | Wave 9b |
| `src/components/vui/vuiDesignCssContract.test.ts` | 生产样式表 raw color 字面量未集中 tokens.css | Wave 9b |
| `src/i18n/dictionary.test.ts` | shell 与 full 路由字典对齐 | 波次附属 |

## 建议

1. 以专用 worktree 立项（如 `vui-wave3b-4c-migration`），按 3b → 3c → 4c → 9/9b 顺序
   推进，契约红作为进度清单保留，每完成一项即转绿。
2. 迁移过程中禁止以「删契约测试」代替「完成迁移」。
3. 环境依赖 `langgraph` 1.2.10 + `langgraph-checkpoint-sqlite` 3.x 组合下，
   `test_session_detail_contract.py` 的 `needs_continue` 断言与
   `test_web_app.py` 的「新会话占位标题」断言为既有红（干净 HEAD 复现），
   归属 lastTurnError 系列 Agent 收尾。
