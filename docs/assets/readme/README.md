# README 展示素材

本目录服务仓库首页。素材日期与演示性质分别标注，不以截图代替功能验收。

| 文件 | 来源与用途 |
| --- | --- |
| `vibelution-showcase.png` | 2026-09-08 制作的多 Agent 协作封面。主画面为科研流程与图谱回放截图，复用项目图标，角落以小尺寸 Q 版桌宠点缀；是展示合成图，不是完整产品窗口。 |
| `companions.png` | 2026-09-08 从本地运行中的 `/companions` 页面取得的人物大厅截图；未进入私人对话、未改写展示数据。 |
| `desktop-pet.gif` | 2026-09-08 本地运行中的 `/desktop-pet` 页面实录，截取约 5 秒待机动效。使用真实页面与现有角色资产，不模拟任务完成或确认事件。 |
| `challenge-cup-demo.mp4` | Codex 视频制作工作区中的 `SCI-003真实历史流程演示_AI配音_2026-09-08.mp4` 原始成片，未重新编码。157.376 秒，1920 × 1080，H.264 / AAC，22,742,480 字节。 |
| `challenge-cup-preview.gif` | 上述成片第 3–6、40–43、94–97 秒，按原速串接研究画布、团队讨论、图谱三个片段；880px 宽、7fps，用于 README 自动预览。2026-10-19 起更名为 `research-preview.gif` 并挂中英文 README 首屏。 |
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

首页定位更新为「本地 AI Agent 工作台」。第二轮把完整工作台放在标题后，随后是单 Agent 上手与能力导览；能力示意和局部对话图折叠，记忆图展示同一公开任务的约定、来源与下一步。历史科研演示仍放在可展开案例中。中英文保持相同章节、能力与边界。

| 素材 | 性质、来源与用途 |
| --- | --- |
| `workbench.zh.png` / `workbench.en.png` | 生产 `App` → `AppShell` → `/chat` 路由的紧凑取景，展示公开 task-board 示例的 Agent 列表、问题、工具过程、完整回答和输入区。首屏使用原生 18px 字号偏好，提高 GitHub 正文宽度下的可读性；右栏由产品收起。 |
| `workbench.mobile.zh.png` / `workbench.mobile.en.png` | 同一生产路由在 390px 视口中的原生窄屏状态，保留问题、工具过程、完整回答和输入区；侧栏由产品收起。 |
| `workbench-overview.zh.png` / `workbench-overview.en.png` | 同一任务在原生宽屏三栏停靠布局中的完整截图，额外展示文件 diff 与仓库改动，放在首页可展开区域，并链接原图。 |
| `product-overview.zh.svg` / `product-overview.en.svg` | 可编辑能力示意，四组主能力与模型、工具、Git、运行记录；复用项目 V 图标路径，无外部图像或字体依赖。不是产品窗口。 |
| `product-overview.mobile.zh.svg` / `product-overview.mobile.en.svg` | 手机独立纵向排版，避免缩小桌面横图。与桌面图文字、颜色一致。 |
| [product-overview.html](product-overview.html) | 四份 SVG 的内联可编辑预览，按语言和视口切换；独立 SVG 是 GitHub 使用的素材。 |
| `conversation.zh.png` / `conversation.en.png` | 当前 `ConversationView` 局部组件的隔离截图，使用固定项目审查示例。外框是文档取景壳，不是完整 Chat 路由；未调用模型，未读取真实会话。 |
| `conversation.mobile.zh.png` / `conversation.mobile.en.png` | 同一生产组件在 390px 视口中的截图，保留问题、回答和输入区。 |
| `memory.zh.png` / `memory.en.png` | 当前 `MemoryAgentMemoryPanel` 局部组件的隔离截图，展示 task-board 的三份公开笔记及选中笔记的完整正文；不是私人 Agent 记忆。 |
| `memory.mobile.zh.png` / `memory.mobile.en.png` | 同一生产组件在 390px 视口中点击记忆文件后显示正文，使用正式阅读状态。 |

局部对话图沿用第一轮源码基线 `0b2d09edc5eec468b1f76cbfaa15edb864ed722f`；第二轮工作台和记忆图取自固定基线 `3a466cd5fae82eabe9556a859cafcb44b6b10774`，日期均为 2026-10-11。截图证明生产界面如何显示示例数据，不证明模型执行、检索命中、团队任务完成或当前发布版本。示例中的任务、文件内容与工具结果都是固定公开数据；不会在磁盘上创建 task-board 项目。英文图保留生产组件现有的中文工具动作标签，未改图替换文字。

### 再生成界面图

局部组件入口为 [capture.html](capture.html)、[capture.tsx](capture.tsx) 和 [capture.css](capture.css)，参数 `lang=zh|en`、`view=conversation|memory`；文档壳负责取景，正文使用生产组件、VUI 与生产 tokens，请求统一返回 403。

完整工作台入口为 [workbench-capture.html](workbench-capture.html)、[workbench-capture.tsx](workbench-capture.tsx) 和 [workbench-capture.css](workbench-capture.css)，参数 `lang=zh|en`。它直接加载生产 App 与路由，没有手绘导航或替换产品布局。精确的同源 GET 请求由静态表返回，流为无事件的本地流；唯一的 `POST /api/sessions/showcase-session/select` 返回固定会话，不修改任何状态。其他写操作、未知请求和跨域请求返回 403。Vite 无 backend proxy 且阻断 `/api/`；截图浏览器再次阻断真实 API 与跨域访问。

主图使用产品 `compact` 布局，通过原生 `vibelution.workbench.font-base-px=18` 字号偏好提高阅读清晰度。完整三栏图使用 `wide` 布局；宽度均通过正式 `vibelution.pane-layouts.v1` 的 `chat.left/right` 设置为 260/340，没有覆盖产品断点或增加产品 CSS。公开示例的 Agent 头像复用仓库 [Vibelution 图标](../../../web/public/vibelution-icon-192.png)。两种取景的回答内容相同，主图以列表呈现按键，宽屏图用表格。截图使用原生展开控件显示工具摘要，并滚动文件差异到新增行。取景不启动、停止或刷新共享产品。

使用已有前端依赖，从仓库根目录启动独立取景服务：

```powershell
node web/node_modules/vite/bin/vite.js --config docs/assets/readme/capture.vite.config.mjs --configLoader native
```

打开 `http://127.0.0.1:5188/docs/assets/readme/workbench-capture.html` 看完整工作台，或打开 `capture.html` 看局部组件。该端口只服务隔离文档素材，发生冲突时退出；无需启动 Launcher 或后端。停止预览用 `Ctrl+C`。Vite 缓存写入系统临时目录的 `vibelution-readme-preview`，不改工作树。

截图脚本 [capture.py](capture.py) 需要可选的 Python Playwright 与 Chromium。已有工具链可直接使用；若需准备，在开发虚拟环境执行 `python -m pip install playwright` 与 `python -m playwright install chromium`。然后：

```powershell
python docs/assets/readme/capture.py
```

可用 `--chromium <绝对路径>` 指定已安装的 Chromium。脚本固定浅色、Asia/Shanghai 时区与 2 倍像素。工作台主图桌面 960 × 820、手机 390 × 900；完整三栏图 1440 × 900；局部会话桌面 960 × 740、手机 390 × 820；记忆桌面 960 × 660、手机 390 × 780。脚本仅允许 `127.0.0.1:5188`，另行阻断真实 API；遇组件错误、水平溢出、对话不能完整入镜或选中记忆笔记被裁切时停止。默认生成十四张 PNG，可用 `--view workbench|workbench-overview|conversation|memory` 更新一组；请在文档任务分支中运行。

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

## 2026-10-16 完整功能展示

中英文首页采用简洁封面、团队分工图、能力索引、快速开始和六组完整截图。所有新素材位于 `showcase/`；旧素材保留，避免破坏已有引用。英文正文与图解独立翻译，产品截图保留原有中文界面。

六张 PNG 来自用户在本次 README 任务中提供并明确允许使用的截图，逐字节保留原图，不裁剪、不替换文字、不补造运行结果。以下日期为收录日期，不推定为截图拍摄时间。

| 文件 | 原始附件标识 | 展示范围与限制 |
| --- | --- | --- |
| `showcase/conversation.png` | `68699234-76ad-4a80-a687-a610c3b6f67d` | 会话分组、标签与输入区；新会话状态不证明任务完成。 |
| `showcase/team.png` | `d50604b2-96f5-4b62-b905-0fb31ec22f16` | 团队成员、组织画布与详情；组织关系不表示当前任务进度。 |
| `showcase/knowledge.png` | `4b1453e2-f154-44d3-a7d7-ea3b27afbde2` | 平台知识全景；主题分组和空间距离不代表支持、反驳或因果关系。 |
| `showcase/evolution.png` | `104084c1-2af6-4c4c-8fd5-47fbe0675e9b` | 监督进化对话、候选与阶段；分数仅属图中个例，激活缺少运行版本证据。 |
| `showcase/finance.png` | `1a1ffc17-d75d-4281-83c5-d62dc179415b` | 金融工作台入口；空状态不证明研究完成、数据接通或实盘交易。 |
| `showcase/companion.png` | `5100607f-ea6b-44e5-a955-9c88750b5ed2` | 人物场景、状态与对话；不单独证明主动调度或动画运行。第三方角色权利归原权利人。 |

`showcase/cover.zh.svg`、`cover.en.svg` 及对应 `cover-mobile.*.svg` 是可编辑的文字封面。`showcase/team-flow.*.svg` 与 `team-flow-mobile.*.svg` 是依据团队截图整理的角色分工示意，明确标注为非产品界面、非执行记录；桌面横排和手机纵排分别排版。可编辑组合预览见 [中文图解](showcase/team-diagram.zh.html) / [English diagram](showcase/team-diagram.en.html)。这些图解无外部字体或图片依赖。

功能描述沿用上方事实来源，并补充 [团队前端](../../../web/src/routes/teams/TeamHomeSurface.tsx)、[金融工作台](../../../web/src/routes/finance/README.md) 与 [虚拟人插件](../../../core/agent_plugins/virtual_human_life/README.md)。本轮不修改产品界面或运行配置；首页素材更新不代表产品功能重新验收或远端发布。

## 2026-10-19 README 门面升级

中文与英文首页增加首屏操作循环动图、shields.io 徽章（license / release / platform）与交互式架构地图入口；05 陪伴节新增桌宠动图并排展示。除下表素材变更外，未改动其他资产。

| 变更 | 记录 |
| --- | --- |
| GIF 更名 | `challenge-cup-preview.gif` → `research-preview.gif`（对外名称去赛事化），挂两版 README 首屏并配一行说明文字。 |
| `desktop-pet.gif` | 新挂载点：两版 README 05 陪伴节，与 `showcase/companion.webp` 并排（静态全景 + 动态特写，宽度 320）。 |
| `showcase/companion.png` → `companion.webp` | 2513 × 1596、4,307,242 字节 → 1200 × 762、88,382 字节（LANCZOS 重采样 + WebP quality 80）；导出缩样目检界面文字仍可读；原 PNG 已删除。 |
| `showcase/knowledge.png` → `knowledge.webp` | 3013 × 1672、800,225 字节 → 1200 × 666、31,758 字节，同规格压缩；原 PNG 已删除。 |
| `showcase/evolution.png` → `evolution.webp` | 3013 × 1672、720,938 字节 → 1200 × 666、65,450 字节，同规格压缩；原 PNG 已删除。 |

压缩后，2026-10-16 表中 `showcase/companion.png`、`showcase/knowledge.png`、`showcase/evolution.png` 三个条目的文件现以 `.webp` 形式存在。`docs/architecture/index.html`（离线单文件交互式架构地图，约 14MB）首次在两版 README「文档与参与」节获得入口。
