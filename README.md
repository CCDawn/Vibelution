<p align="center">
  <img src="docs/assets/readme/vibelution-showcase.png" alt="Vibelution — 本地多 Agent 协作工作台。让 Agent 分工，让协作看得见。" width="100%">
</p>

<p align="center"><strong>组织你的 AI 团队，从分工、讨论到执行与评审。</strong></p>

<p align="center">
  中文 · <a href="README.en.md">English</a><br>
  <a href="#看一支科研团队如何工作">挑战杯演示</a> · <a href="#核心能力">核心能力</a> · <a href="#从协作能力长出来的小产品">附加产品</a> · <a href="#开始使用">开始使用</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Code-MIT-38bdae?style=flat-square" alt="代码许可证：MIT"></a>
  <a href="docs/guides/install-windows.md"><img src="https://img.shields.io/badge/Desktop-Windows-4979e8?style=flat-square" alt="Windows 桌面工作台"></a>
  <a href="https://github.com/CCDawn/Vibelution/issues"><img src="https://img.shields.io/badge/Feedback-welcome-f2b36d?style=flat-square" alt="欢迎反馈"></a>
</p>

**Vibelution 是一个本地多 Agent 协作工作台。** 为成员配置角色、模型和工具，让他们分工、讨论、执行与评审；你在一个界面里跟进过程、接手关键决策、查看交接产物。

## 看一支科研团队如何工作

挑战杯科研演示：看不同角色如何围绕一个问题搜集资料、形成假说，再根据评审意见修改方案。

[![点击观看挑战杯演示：研究画布、团队讨论与知识图谱](docs/assets/readme/challenge-cup-preview.gif)](docs/assets/readme/challenge-cup-demo.mp4)

**[▶ 观看完整演示 · 2 分 37 秒 · 1080p](docs/assets/readme/challenge-cup-demo.mp4)** · [下载 MP4](docs/assets/readme/challenge-cup-demo.mp4?raw=true) · [放大查看图谱](docs/assets/readme/challenge-cup-graph.png)

**团队讨论 → 资料搜集与提炼 → 知识图谱 → 假说与评审修订。**

重点看一条假说修改前后的区别，以及它如何关联到来源资料：协作留下的不只有对话，还有下一步可以继续使用的研究记录。

> 2026-09-08 录制的真实历史数据回放，含配音和字幕；不代表现场执行、实验验证或比赛正式验收。[素材说明](docs/assets/readme/README.md)

[了解研究工作流](core/web/services/team_workflow/README.md)

## 核心能力

### 让不同角色一起完成任务

给 Agent 分配职责，在个人会话和团队群聊中推进工作。讨论、工具调用、任务状态与交接产物集中可查，需要时可以停止、继续或由人接手。

### 把长任务组织成可见的工作流

用画布连接任务、条件分支和人工确认环节，查看每一步的进展与上下游关系。科研流程把资料、知识、假说和评审串起来，保留候选方案与修订记录。

### 让下一次任务用得上这一次积累

个人记忆与团队知识库保存资料和研究记录；检索与知识图谱帮助追溯来源、发现联系。GitHub 项目库让 Agent 查找可借鉴的代码。

### 为每个角色配好模型与工具

按 Agent 选择模型，复用提示词、技能和插件，连接文件、终端、搜索与代码工具。可按需接入外部 CLI Agent、MCP、浏览器自动化和图像生成，并查看模型用量。

### 用评测检查改进是否有效

监督进化支持基线与候选对照；自进化支持有明确目标和停止条件的自检、修改与验证。保留评测、审核和回滚记录，让改进有据可查。

<details>
<summary>展开全部功能与配置入口</summary>

功能可用性取决于模型、权限与运行配置；浏览器自动化默认关闭，技能库页面目前以浏览为主。

#### 对话、群聊与任务追踪

- **单 Agent 会话：** 创建和管理对话，查看流式回复、工具调用、待确认操作与历史记录，停止或继续任务。
- **多 Agent 群聊：** 让多个成员围绕同一主题讨论，在统一会话入口查看个人对话和团队群聊。
- **编码工作区：** 浏览项目文件、阅读内容，结合终端与工具执行推进代码任务；查看关联的子会话。
- **Kernel 任务中心：** 按状态和目标 Agent 查找任务，沿时间线查看派发、执行、投递结果与产物引用。
- **外部 Agent 接入：** 为配置好的 CLI Agent 提供执行与终端入口；也可通过 MCP 网关，让外部开发工具调用项目内受管 Agent，提交任务并查询结果。需要先完成对应接入配置。

[会话工作台](web/src/routes/chat/README.md) · [MCP 接入指南](docs/agents/mcp-managed-agent-gateway.md)

#### Agent、提示词、工具与技能

- **Agent 管理：** 创建、编辑、归档和批量管理角色，查看角色配置、模型绑定与能力范围。
- **Prompt 模板：** 浏览和维护提示词模板，为不同角色复用工作方法，查看会话实际装配的上下文。
- **工具管理：** 查看工具目录与 Agent 的授权范围；文件读写、代码修改、命令与测试执行、网页获取、论文／新闻／项目搜索等能力按配置开放。
- **技能库：** 搜索、浏览技能说明与详情，让 Agent 查找可复用的方法。当前页面以浏览为主。
- **Agent 插件：** 为指定角色绑定可选能力，虚拟人生活插件就是一个例子。
- **浏览器自动化：** 提供受控的 Computer Use 沙箱浏览器能力，默认关闭，需配置启用。
- **图像生成：** 为 Agent 提供图片生成工具，需要配置对应图像服务并授予工具权限。

[Agent 配置](core/web/services/agent_directory/README.md) · [工具目录](tools/README.md) · [工具授权说明](docs/agents/tool-authorization-entrypoints.md)

#### 团队、科研与知识积累

- **团队与工作流：** 管理成员和角色关系，复用团队模板，通过画布查看任务节点、条件分支、人工确认和阶段交接。
- **科研流程：** 从题目、资料搜集、知识整理推进到假说、评审与实验设计；保留候选方案、修订记录和各阶段产物。实验执行与结果验收有独立条件。
- **资料处理：** 为 Agent 提供资料接收、处理与检索工具，关联来源，供后续整理和研究使用。
- **个人记忆与团队知识库：** 分别查看 Agent 记忆和团队知识，管理知识提案、入库与审核记录。
- **检索与知识图谱：** 搜索记忆和知识，沿图谱查看关系；可选向量索引用于增强检索，需相应配置。
- **GitHub 项目库：** 保存公开仓库的浅克隆并建立索引，让 Agent 搜索可借鉴的项目代码。
- **用户文档与知识治理：** 管理用户 Markdown 内容、来源和索引，查看生效内容；清理前预览范围，再执行受保护的删除。

[团队工作流](core/web/services/team_workflow/README.md) · [知识库](core/web/services/team_knowledge/README.md) · [记忆与检索](core/web/services/memory_rag_services.md)

#### 监督进化与自进化

**监督进化：先比较，再决定。** 管理评测数据集和测试包，运行基线与候选对照，查看当前运行、历史结果和资料库。会话样本有独立审核入口；改进提案与建议基线保留记录，候选执行和集成经过隔离验证。

**自进化：给一次改进明确的目标。** 查看仓库与运行状态，发起有边界的自检、自修改和验证，保留事务、审计与回滚记录。持续迭代需要用户批准和明确停止条件。

两种模式都不意味着系统可以无条件修改项目，也不把“生成了提案”当成“能力已经提升”。

[进化模式与运行说明](core/web/services/evolution_services.md) · [相关配置](docs/ops/config/06-agent-evolution.md)

#### 模型配置与用量

- **模型与服务商：** 管理服务商、模型库、角色绑定和运行参数，为不同 Agent 选择不同模型；按服务商设置协议、输出限制与缓存选项。
- **配置工作台：** 查看和调整运行配置、模型引用与服务商草稿，密钥保存在仓库之外。
- **Token 用量：** 查看累计、今日、最近七日和最近一次调用的用量，按 Agent、会话或模型查看统计，同时查看缓存读取、上下文窗口与延迟信息。记录会区分服务商回传、估算与缺失数据。
- **界面偏好：** 调整中英文、主题与背景，并保留工作台面板布局。

[模型与配置指南](docs/ops/config/INDEX.md)

#### Git、运行管理与问题排查

- **Git 工作台：** 查看状态、diff 和历史，选择文件提交，并生成提交说明草稿。
- **Launcher 与系统托盘：** 统一启动、停止、重启和打开工作台；有进行中的任务时，生命周期操作受活动任务保护。
- **分支实例管理：** 查看独立分支工作区及其运行状态，管理隔离开发实例。
- **日志与运行现场：** 浏览日志文件、诊断信息和按次整理的运行记录，关联会话、工具与进程问题；可查看和导出现场包。
- **维护与重置：** 预览清理范围，按允许的对象执行受保护维护，避免随意删除工作数据。

[Launcher 与桌面说明](desktop/electron/README.md) · [日志与诊断](core/logging/README.md) · [配置入口](docs/ops/config/07-launcher-runtime-workbench.md)

</details>

## 从协作能力长出来的小产品

<p align="center">
  <img src="docs/assets/readme/companions.png" alt="虚拟人人物大厅" width="52%">
  <img src="docs/assets/readme/desktop-pet.gif" alt="桌面伙伴待机动效实录" width="16%">
</p>

- **虚拟人：** 带日程、心情、日记和长期记忆的角色，可主动发来消息；生活与对话的连续性仍在打磨。[人物能力](core/agent_plugins/virtual_human_life/README.md)
- **桌面伙伴：** 在桌面提示会话状态，点击查看对话，拖动调整位置，关闭后可从系统托盘重新打开。
- **宠物空间：** 查看宠物等级、经验、状态与成就。

## 开始使用

目前以 **Windows 本地桌面体验**为主。准备好 **Python 3.11+（推荐 3.12）、Node.js 18+ 和 Git**，在 PowerShell 中执行：

```powershell
git clone https://github.com/CCDawn/Vibelution.git
cd Vibelution
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

安装完成后，打开桌面上的 **Vibelution Launcher**。首次启动会准备外部配置文件；按[模型配置指南](docs/ops/config/INDEX.md)配置模型与密钥后，就可以开始对话。

[Windows 安装说明](docs/guides/install-windows.md) · [开发环境与贡献](CONTRIBUTING.md) · [Linux 部署参考](docs/ops/linux-bootstrap.md)

工作台运行在本机，模型由你配置。**使用云端模型时，相应请求会发送给所选模型服务商**；本地运行不等于所有推理都离线。模型调用可能产生服务商费用，密钥与运行配置保存在仓库之外。

## 文档与贡献

首页展示 2026 年 9 月的开发进展，发布记录见 [CHANGELOG](CHANGELOG.md)。使用中遇到问题或有具体场景，欢迎提 [Issue](https://github.com/CCDawn/Vibelution/issues)，或从[贡献指南](CONTRIBUTING.md)开始。

---

[文档地图](docs/README.md) · [开发规范](docs/standards/README.md) · [安全问题](SECURITY.md) · [第三方组件](THIRD_PARTY_COMPONENTS.md) · [MIT 代码许可证](LICENSE)

角色名称与第三方素材的权利归各自权利人所有；代码的 MIT 许可不授予第三方角色或素材的权利。
