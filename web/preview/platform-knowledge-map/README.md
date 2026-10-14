# 平台知识图谱隔离预览

本页用于确认“平台主题星系 → 中文语义关系 → 来源依据”的交互方向。所有内容为合成示例，不连接真实知识、Agent、组织目录或业务接口。

在任务 worktree 的 `web` 目录运行 `node node_modules/vite/bin/vite.js --config preview/platform-knowledge-map/vite.config.ts`，使用 Vite 输出的 loopback 地址，打开 `/preview/platform-knowledge-map/index.html`。端口由 Vite 分配，以实际启动输出为准。代理已关闭。

## 预览内容

- 三个主题、25 个节点（24 个可读、1 个受限占位）、31 条关系、5 个来源记录。
- 真实 Three.js 三维星域和体积星云，支持拖动环绕、缩放与主题点选；空闲时停止请求渲染帧。
- 知识关联、组织归属、来源证据分别阅读；关系显示中文谓语、方向、解释和确认状态。
- 搜索、关系类型筛选、待确认关系开关、来源对话框、深浅主题及窄屏抽屉。
- 受限来源按钮不可读。示例权限状态仅演示产品交互，不能证明真实 ACL。

复用现有 VUI 页面 recipe、工作台布局 ID、主题 token 和 NebulaField 着色器。`previewNebula.ts` 与 `GalaxyOverview.tsx` 仅服务本隔离预览；正式实现须回到现有图谱 renderer 扩展，不新增第二套生产引擎。

## 验证记录

2026-10-14：预览严格 TypeScript 检查及现有 `web/tsconfig.json` 构建类型检查通过。VUI component design contract 通过；route contract 初次因文件扫描超过默认 5 秒超时，设 30 秒后通过，未修改产品测试。

Headless Chromium 验证 1600×1000、1200×800、390×844：星系到主题、三种关系视图、关系解释与来源对话框、搜索结果和空结果、候选关系、禁用受限来源、返回全景、深浅主题、移动详情抽屉。无 pageerror、无 `/api/` 请求、无移动横向溢出；空闲 RAF 计数不增长，离开总览 canvas 被移除。截图位于本任务 Codex visualization 目录。

尚未接入全平台数据、真实权限、语义关系抽取、分页/邻域服务和真实来源定位。该预览不表示正式页面已上线。界面结果等待用户确认，确认后再实施正式 surface。
