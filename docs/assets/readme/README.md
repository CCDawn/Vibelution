# README 展示素材

本目录服务仓库首页。素材日期与演示性质分别标注，不以截图代替功能验收。

| 文件 | 来源与用途 |
| --- | --- |
| `vibelution-showcase.png` | 2026-09-08 制作的多 Agent 协作封面。主画面为科研流程与图谱回放截图，复用项目图标，角落以小尺寸 Q 版桌宠点缀；是展示合成图，不是完整产品窗口。 |
| `companions.png` | 2026-09-08 从本地运行中的 `/companions` 页面取得的人物大厅截图；未进入私人对话、未改写展示数据。 |
| `desktop-pet.gif` | 2026-09-08 本地运行中的 `/desktop-pet` 页面实录，截取约 5 秒待机动效。使用真实页面与现有角色资产，不模拟任务完成或确认事件。 |
| `challenge-cup-demo.mp4` | Codex 视频制作工作区中的 `SCI-003真实历史流程演示_AI配音_2026-09-08.mp4` 原始成片，未重新编码。157.376 秒，1920 × 1080，H.264 / AAC，22,742,480 字节。 |
| `challenge-cup-preview.gif` | 上述成片第 3–6、40–43、94–97 秒，按原速串接研究画布、团队讨论、图谱三个片段；880px 宽、7fps，用于 README 自动预览。 |
| `challenge-cup-graph.png` | 同一制作工作区的 `checked-scene-5.png`，用于放大查看图谱和封面排版。 |
| `research-workflow.png` | 同一制作工作区的 `checked-scene-0.png`，展示原生研究画布的历史回放与知识搜集段放大画面。 |
| `web-workbench-*.png` | 沿用仓库已有的工作台演示截图，说明 Agent 配置、团队、Git 与评测布局（`web-workbench-chat.png` 的实际内容为 Agent 配置）；不作为 2026-09-08 运行状态证明。 |
| `vibelution-github-hero.png` | 仓库原有封面，保留供已有引用使用；两张旧封面均保留供已有引用使用。 |

视频源文件 SHA-256：

```text
85fd3a52cc6508e90d1892efe090221affe9bbf0bdce7623d33ee50c890dbd26
```

科研演示来自已确认的历史回放展示页，包含研究画布、讨论、资料搜集、内容提炼、图谱、交接、假说与评审修订。它不是当次现场运行，也不代表实验结论或正式比赛验收。配音与字幕为中文。

README 使用可点击动图和相对 MP4 链接。GitHub 的 Markdown 不依赖自定义脚本或 HTML 视频播放器；若文件页未内嵌播放，可使用正文中的下载链接。完整视频只有在读者点击后才加载。

封面复用的角色资产与人物配置相同。角色名称和第三方素材的权利归各自权利人所有；仓库代码许可证不替代素材授权。

## 2026-09-29 首页改版

首页以科研回放作为首屏演示，旧合成封面与监督进化空状态截图保留文件，退出首页展示。Agent 配置图复用历史素材，未补拍或伪造当前运行结果。桌宠动图改为链接，避免在首页默认加载。

| 新增素材 | 内容与事实依据 | 可编辑源文件 |
| --- | --- | --- |
| `agent-handoff.zh.png` / `agent-handoff.en.png` | 通信机制示意：指定目标会话、写入会话历史、请求唤起、分别追踪执行状态；依据 [ADR 0002](../../adr/0002-agent-collaboration-session-addressing.md) | [中文 HTML](agent-handoff.zh.html) / [English HTML](agent-handoff.en.html) |
| `evolution-paths.zh.png` / `evolution-paths.en.png` | 自进化与监督进化的概念流程；依据 [进化服务索引](../../../core/web/services/evolution_services.md) 与 [进化配置](../../ops/config/06-agent-evolution.md)，不含效果指标或成功承诺 | [中文 HTML](evolution-paths.zh.html) / [English HTML](evolution-paths.en.html) |

图解使用本地系统字体与静态 SVG HTML 源文件，经浏览器导出为 PNG；中英文分别排版。它们是机制说明，不是产品截图或实验记录。

### 首页事实溯源

| 首页内容 | 来源 |
| --- | --- |
| 克隆地址、安装入口与首次启动 | 仓库 Git remote、[Windows installer](../../../scripts/install_windows.ps1)、[安装指南](../../guides/install-windows.md) |
| Python 与 Node.js 前提 | [安装指南](../../guides/install-windows.md)、[前端锁文件](../../../web/package-lock.json) 中 Vite 的 `engines.node`；首页采用 Node.js 22.12+，安装器自身的旧 18+ 检查尚未调整 |
| Agent 身份、模型、工具与记忆 | [Agent directory](../../../core/web/services/agent_directory/README.md)、[配置索引](../../ops/config/INDEX.md)、[工具授权](../../agents/tool-authorization-entrypoints.md) |
| 会话投递与权限约束 | [ADR 0002](../../adr/0002-agent-collaboration-session-addressing.md) |
| 研究画布、知识与实验记录 | [Team workflow](../../../core/web/services/team_workflow/README.md)、[Team knowledge](../../../core/web/services/team_knowledge/README.md) |
| 自进化、监督进化及隔离验证 | [Evolution services](../../../core/web/services/evolution_services.md)、[进化配置](../../ops/config/06-agent-evolution.md) |
| 虚拟人状态、记忆与主动消息 | [虚拟人插件](../../../core/agent_plugins/virtual_human_life/README.md) |

章节变化：取消重复能力表与长目录；快速开始移到演示后；五项能力各用图像、收益句与少量要点；配套工具、贡献、相关项目合并为页尾入口。中文为主版本，英文保持相同顺序与边界说明。

## 2026-10-11 工作台导览

首页定位更新为「本地 AI Agent 工作台」，先展示完整能力与单 Agent 上手，再介绍记忆、团队研究与进化。历史科研演示移入可展开案例；旧配置图退出首页，文件继续保留以兼容已有引用。中英文保持相同章节、能力与边界。

| 素材 | 性质、来源与用途 |
| --- | --- |
| `product-overview.zh.svg` / `product-overview.en.svg` | 可编辑能力示意，四组主能力与模型、工具、Git、运行记录；复用项目 V 图标路径，无外部图像或字体依赖。不是产品窗口。 |
| `product-overview.mobile.zh.svg` / `product-overview.mobile.en.svg` | 手机独立纵向排版，避免缩小桌面横图。与桌面图文字、颜色一致。 |
| [product-overview.html](product-overview.html) | 四份 SVG 的内联可编辑预览，按语言和视口切换；独立 SVG 是 GitHub 使用的素材。 |
| `conversation.zh.png` / `conversation.en.png` | 当前 `ConversationView` 局部组件的隔离截图，使用固定项目审查示例。外框是文档取景壳，不是完整 Chat 路由；未调用模型，未读取真实会话。 |
| `conversation.mobile.zh.png` / `conversation.mobile.en.png` | 同一生产组件在 390px 视口中的截图，保留问题、回答和输入区。 |
| `memory.zh.png` / `memory.en.png` | 当前 `MemoryAgentMemoryPanel` 局部组件的隔离截图，展示固定 `review-notes.json` 公开笔记；不是私人 Agent 记忆。 |
| `memory.mobile.zh.png` / `memory.mobile.en.png` | 同一生产组件在 390px 视口中点击记忆文件后显示正文，使用正式阅读状态。 |

截图组件版本取自本轮同步的本地 `main` 基线 `0b2d09edc5eec468b1f76cbfaa15edb864ed722f`；日期为 2026-10-11。截图只证明这些生产组件如何显示示例数据，不证明模型执行、检索命中、团队任务完成或已发布的完整窗口。文件快照与对话使用证据仍遵循当前产品边界。

### 再生成界面图

可编辑入口为 [capture.html](capture.html)、[capture.tsx](capture.tsx) 和 [capture.css](capture.css)。参数 `lang=zh|en`、`view=conversation|memory`。外框只负责取景排版，正文直接使用生产组件、VUI 与生产 tokens；请求默认返回 403。预览配置清空 backend proxy，并阻断 `/api/`。

使用已有前端依赖，从仓库根目录启动独立取景服务：

```powershell
node web/node_modules/vite/bin/vite.js --config docs/assets/readme/capture.vite.config.mjs --configLoader native
```

打开 `http://127.0.0.1:5188/docs/assets/readme/capture.html`。该端口只服务隔离文档素材，发生冲突时退出；无需启动 Launcher 或后端。停止预览用 `Ctrl+C`。Vite 缓存写入系统临时目录的 `vibelution-readme-preview`，不改工作树。

截图脚本 [capture.py](capture.py) 需要可选的 Python Playwright 与 Chromium。已有工具链可直接使用；若需准备，在开发虚拟环境执行 `python -m pip install playwright` 与 `python -m playwright install chromium`。然后：

```powershell
python docs/assets/readme/capture.py
```

可用 `--chromium <绝对路径>` 指定已安装的 Chromium。脚本固定浅色、Asia/Shanghai 时区与 2 倍像素，会话桌面 960 × 740、记忆桌面 960 × 660，手机会话 390 × 820、记忆 390 × 780；仅允许 `127.0.0.1:5188` 隔离预览，另行阻断 `/api/`，发现组件错误、水平溢出或对话内容无法完整放入画面时停止。默认重新生成上述八张 PNG，可用 `--view conversation|memory` 只更新一组；请在文档任务分支中运行。

### 新增内容的事实来源

| 首页内容 | 当前来源 |
| --- | --- |
| 单 Agent 上手、创建 Agent、开始会话、成功与排错 | [第一次对话](../../guides/first-conversation.md) 与其中列出的源码；[English](../../guides/first-conversation.en.md) |
| 会话、编码、工作区文件与预览 | [Chat / Coding](../../../web/src/routes/chat/README.md)、[file_service.py](../../../core/web/services/file_service.py)、[ConversationView](../../../web/src/components/conversation/ConversationView.tsx) |
| Agent、Skills 与 MCP 工具 | [Agent directory](../../../core/web/services/agent_directory/README.md)、[工具授权](../../agents/tool-authorization-entrypoints.md)、[MCP gateway](../../agents/mcp-managed-agent-gateway.md) |
| 私有记忆与知识入口 | [MemoryAgentMemoryPanel](../../../web/src/routes/MemoryAgentMemoryPanel.tsx)、[memory_rag_services](../../../core/web/services/memory_rag_services.md)、[team_knowledge](../../../core/web/services/team_knowledge/README.md) |
| Git 状态、差异与提交 | [GitRoute](../../../web/src/routes/GitRoute.tsx)、[Git 配置](../../ops/config/08-git-ui-user.md) |
| 模型、用量、日志和诊断 | [配置索引](../../ops/config/INDEX.md)、[本地模型监控](../../ops/local-model-monitor.md)、[UsageRoute](../../../web/src/routes/UsageRoute.tsx)、[RuntimeScenesPane](../../../web/src/routes/RuntimeScenesPane.tsx) |
| 金融专项扩展及部署边界 | [financial_research](../../../core/web/services/financial_research/README.md)、[财报服务接入](../../ops/config/financial-report-agent.md) |
| 平台 Node.js 要求 | [Vite 锁定版本的 engines](../../../web/package-lock.json) 与 [Windows](../../guides/install-windows.md) / [macOS](../../guides/install-macos.md) / [Linux](../../guides/install-linux.md) 安装指南；文档推荐 22.12+，安装器旧版检查未在本轮改动 |

### 本轮验证范围

已用 GitHub Markdown API 的实际清洗结果核对 `picture/source` 保留情况，并在本地隔离浏览器检查桌面与 390px、浅色与深色的 README 排版。图片、内部链接及中英文能力对应分别检查。此验证不等于线上发布，也不等于本轮安装、真实模型对话或产品运行验收。
