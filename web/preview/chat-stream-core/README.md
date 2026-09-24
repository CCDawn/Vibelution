# Chat Stream Core 隔离预览（Wave 1b）

聊天流核心升级的**隔离预览**：A/B 对比长列表渲染、流式双模 markdown、投影不变量演示。
本目录不接入生产 router，不属于 `web/` 构建图（`web/tsconfig` 不包含本目录），`web/src` 零改动；
预览通过只读 import 复用 `web/src` 的真实纯逻辑模块。

## 启动

```bash
cd web/preview/chat-stream-core
npm install        # 首次；依赖仅限本目录（见 package.json）
npm run dev        # http://localhost:5199/
```

截图脚本（需系统 Python 带 playwright，浏览器缓存已在 `%LOCALAPPDATA%/ms-playwright`）：

```bash
python shoot_preview.py   # 输出到 docs/screenshots/
```

类型检查：`npx tsc -b --pretty false`（本目录自己的 tsconfig，strict）。

## 三个面板

### ① A/B 长列表对比

同一份确定性合成会话（520 条：中文文案、代码块、表格、长工具输出；mulberry32 固定 seed）。

- **A 现状复刻**：按诊断复刻 `ConversationView` 现行策略——客户端消息窗口
  （首屏 12、上滚 +12、软上限 72）+ 自研 spacer 虚拟化。直接 import 真实生产模块：
  `resolveConversationVirtualRange` / `recordConversationRowHeight`（行高缓存 +
  ResizeObserver + minDelta 噪声门）/ `resolveTimelineFollowState`（贴底跟随）/
  `shouldLoadEarlierConversationMessages` / `captureTimelineRowKeyAnchor` /
  `restoreTimelineRowKeyAnchor`（前插行键锚定），来源
  `web/src/components/conversation/{conversationHistoryWindow,conversationTimelineFollowState,timelineScrollAnchor}.ts`。
- **B 新方案**：整段历史 `@tanstack/react-virtual` 虚拟化——动态测高
  （`measureElement`）、行高缓存按稳定 key 保留、无 12/72 窗口上限；运行中 turn
  在虚拟化窗口外独立渲染为 live-tail 块；贴底跟随复用真实
  `resolveTimelineFollowState`；前插锚定用 react-virtual 内建的
  「完全在视口上方的行测量补偿」（virtual-core measure 路径默认行为）。

### ② 流式双模模拟

确定性 mock 流（定时器，无网络）同喂两栏：

- 左 = 现状复刻：真实 `projectStreamingMarkdownBlocks`（`web/src/components/conversation/streamingMarkdown.ts`）
  的 stable/live 拆分（960 字符 live-tail 上限 + stable 块缓存），live 区每帧跑完整
  react-markdown；不完整语法靠「留在 live 区」而非解析器修复。解析计数器可证。
- 右 = Streamdown 模式（Apache-2.0；Streamdown `parseIncompleteMarkdown` 概念 +
  zai-org/ZCode 的双模用法）：流式中做不完整语法补全（关围栏、补表分隔行、配平
  行内标记；高亮/mermaid 关），完成后切 static 全量 AST + memo（比较器 = 引用相等，
  FNV-1a 哈希兜底）。剧本含 python 围栏与表格从残缺到完整的全过程。

### ③ 投影不变量演示

mock 序列演示 ZCode 三不变量（对照 `conversationProjectionStore` 模式，Apache-2.0）：

1. **seq 连续才应用**：`seq === lastAppliedSeq + 1` 才合并；重复/回退丢弃；断档 HOLD。
2. **断档带水位重订阅**：断档后从 `watermark = lastAppliedSeq + 1` 发起恢复，
   单飞（恢复飞行中不再叠加），指数退避 200/400/800/1600ms 上限 5s；
   mock 服务器以权威快照补齐缺口。
3. **乐观 overlay 权威对账**：乐观消息先挂 overlay 显示，权威投影对账后移除。

「朴素投影」对照盘来一个应用一个：同一断档注入下右盘直接缺字、无水位可恢复，
左盘最终与真实序列一致。决策日志逐条给出 APPLY/HOLD/DROP/RESUB/RESUME/RECONCILE。

## 复用的 web/src 真实模块（只读 import，零改动）

- `web/src/components/conversation/conversationHistoryWindow.ts`
- `web/src/components/conversation/conversationTimelineFollowState.ts`
- `web/src/components/conversation/timelineScrollAnchor.ts`
- `web/src/components/conversation/streamingMarkdown.ts`
- `web/src/components/conversation/codexStreamController.ts`（面板 ② 说明引用；左栏流水线同构复刻）

## 新依赖（仅本预览目录，APPROVED 后才进正式集成）

- `@tanstack/react-virtual` ^3.13（实装 3.14.13）
- 其余 react 19 / react-markdown 10 / remark-gfm 4 / vite 8 与生产同版本对齐

正式集成阶段的 bundleBudget 验证、依赖引入与 VUI/shadcn 落地不在本预览范围。

## 归属

- Streamdown（vercel/streamdown，Apache-2.0）：`parseIncompleteMarkdown` 模式。
- zai-org/ZCode（Apache-2.0）：ConversationTimeline 虚拟化 + live-tail、
  ai-elements message 双模思路、conversationProjectionStore 不变量。
  本目录为其裁剪/等价实现，非上游源码拷贝。
