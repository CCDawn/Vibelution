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
