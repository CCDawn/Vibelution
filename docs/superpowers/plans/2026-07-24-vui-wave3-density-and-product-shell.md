# VUI 前端统一 Wave 3：密度几何与 product shell 搭页

**Date:** 2026-07-24
**Status:** in progress（3A 完成；**3B 示范页 = 会话页 Chat session workbench**）
**Owner:** `web-workbench-surface` / VUI design-system owner
**Mode:** `TASK_GRAPH`
**Risk:** `STANDARD_TASK`
**Depends on:** Wave 0–2 完成（surface token、recipes、alpha policy、壳层 opaque）

## 0. 目标

在表面契约已统一的前提下，继续收敛：

1. **控件几何密度** — 高度 / 内边距 / 字号走 token + chrome recipe，页面少手写
2. **Product shell 搭页** — 新页优先 `VListDetailPage` / `VDenseOpsPage` / `VSettingsFormPage`
3. **Reference Lab 映射** — 文档化已批准 token 对应关系
4. **不** 引入 cva / 平行 `components/ui` / shadcn init

## 1. 非目标

- 不重写 Chat / Agent 领域 shell 信息架构
- 不强行 100% style map 零 Tailwind
- 不迁移 Base UI

## 2. 分层

```
Wave 3A  chrome density recipes（quiet control / icon / pill）+ AppShell 与高频 style map 消费  ✅
Wave 3B  示范页：会话页 Chat（domain shell composition）                                   ✅ 本轮
Wave 3C  Reference Lab ↔ tokens 映射表
Wave 3D  （可选）第二仓库时再评估 registry
```

### 为什么示范页是「会话页」而不是 Config / Tools？

| 候选 | 含义 | 适合 Wave 3B 吗 |
|---|---|---|
| **会话页（Chat）** | `/chat` 三栏：会话索引 + 对话中区 + 状态栏 | **是** — 最高流量 domain shell；不硬套 `VListDetailPage` |
| **偏 Config** | 设置/配置类表单页，适合 `VSettingsFormPage` | 适合以后 3B-alt：证明「标准 page recipe」 |
| **偏 Tools** | 工具密集运维表，适合 `VDenseOpsPage` | 适合以后 3B-alt：证明 dense ops 搭页 |

此前说「偏 Config / Tools」是 **通用 page recipe 的两条备选示范**，不是否定 Chat。
**Chat 是领域壳示范**（data-vui-recipe + region + surface/chrome recipes）；Config/Tools 是 **通用 page recipe 示范**（可另开）。

## 3. Wave 3A — chrome recipes（本轮）

| 导出 | 语义 |
|---|---|
| `vuiControlQuietClass` | 紧凑静音按钮（含 hover/disabled） |
| `vuiControlQuietChromeClass` | 同上，无 `inline-flex`（节点已有 flex） |
| `vuiControlIconSmClass` | 方形 sm 图标控件几何 |
| `vuiControlPillClass` | 紧凑 pill 壳 |

**文件：** `web/src/design/vuiChromeRecipes.ts`（Tailwind `@source`）
**消费：** AppShell + 批量替换 style map 中重复 quiet chrome 串
**验证：** foundation 导出；AppShell / Chat layout 相关 vitest

## 3B. 会话页 composition 示范（本轮）

**Recipe id：** `chat-session-workbench`

| 区域 | DOM | 配方 |
|---|---|---|
| 根布局 | `data-vui-recipe="chat-session-workbench"` | domain 三栏 grid（保留 Chat 信息架构） |
| 会话索引 | `data-vui-region="chat-session-index"` | rail fill；行 = dense + selected + chrome |
| 对话中区 | `data-vui-region="chat-conversation-center"` | `vuiChatFillClass` 实色 |
| 状态栏 | `data-vui-region="chat-status-rail"` | rail fill |

**契约测试：** `web/src/design/vuiWave3ChatCompositionContract.test.ts`

**不做什么：** 不把 Chat 强行改成 `VListDetailPage`。

## 4. Close condition（Wave 3 全量）

1. 高频 quiet control 串主要走 chrome recipe ✅ 3A
2. 至少 1 条示范路径 composition 可测 ✅ 3B Chat 会话页
3. （可选）另 1 条通用 page recipe 示范：Config 或 Tools
4. Lab 映射文档存在（3C）
5. 不回退 Wave 2 surface 契约

## 5. 与 Wave 2 关系

Wave 2 = 表面 / 透明 / 状态 tint。
Wave 3 = 几何密度 / 搭页方式。两者互补，不互斥。
