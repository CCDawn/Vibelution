<p align="center">
  <img src="docs/assets/readme/vibelution-showcase.png" alt="Vibelution — 本地多 Agent 协作工作台。让 Agent 分工，让协作看得见。" width="100%">
</p>

<p align="center"><strong>组织你的 AI 团队，从分工、讨论到执行与评审。</strong></p>

<p align="center">
  中文 · <a href="README.en.md">English</a><br>
  <a href="#多-agent-如何一起工作">多 Agent 协作</a> · <a href="#看一支科研团队如何工作">挑战杯演示</a> · <a href="#从协作能力长出来的小产品">附加产品</a> · <a href="#开始使用">开始使用</a>
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/Code-MIT-38bdae?style=flat-square" alt="代码许可证：MIT"></a>
  <a href="docs/guides/install-windows.md"><img src="https://img.shields.io/badge/Desktop-Windows-4979e8?style=flat-square" alt="Windows 桌面工作台"></a>
  <a href="https://github.com/CCDawn/Vibelution/issues"><img src="https://img.shields.io/badge/Feedback-welcome-f2b36d?style=flat-square" alt="欢迎反馈"></a>
</p>

一个复杂任务，往往需要不同的角色：有人搜集资料，有人提出方案，有人负责执行，也有人检查结果。

**Vibelution 是一个本地多 Agent 协作工作台。** 你可以为角色配置模型、工具与技能，把任务组织成团队和工作流，在同一个界面里查看讨论、执行过程与交接产物。挑战杯科研团队是这套能力的实际应用；虚拟人和桌宠则是基于工作台探索的附加产品。

## 多 Agent 如何一起工作

![研究画布历史回放：任务节点与前后环节的交接关系](docs/assets/readme/research-workflow.png)

### 分工清楚，过程看得见

- **先组队：** 为 Agent 指定角色，配置各自的提示词、模型、工具与技能，让不同任务由合适的成员承担。
- **再串起任务：** 用工作流画布组织节点、条件分支和人工确认环节，查看前后步骤如何交接。
- **一起讨论和执行：** 在会话中查看成员讨论、工具调用和任务状态；需要时停止、继续或由人接手。
- **把产物留下来：** 将资料、知识关系、假说和评审记录放回工作流程，方便下一步使用和回看。

你不必为每个 Agent 分别翻找聊天窗口，也不必只等一个最终答案。团队现在走到哪里、哪一步需要你，都应该能在工作台里找到。

## 看一支科研团队如何工作

### 挑战杯：从一个问题，到可讨论、可追溯的研究方案

[![点击观看挑战杯演示：研究画布、团队讨论与知识图谱](docs/assets/readme/challenge-cup-preview.gif)](docs/assets/readme/challenge-cup-demo.mp4)

**[▶ 观看完整演示 · 2 分 37 秒 · 1080p](docs/assets/readme/challenge-cup-demo.mp4)** · [下载 MP4](docs/assets/readme/challenge-cup-demo.mp4?raw=true) · [放大查看图谱](docs/assets/readme/challenge-cup-graph.png)

不同角色围绕同一个问题讨论、搜集资料、提取内容、建立知识关系，再提出和评审研究假说。视频把这些环节串成一段完整的展示：

**研究画布 → 团队讨论 → 资料搜集与提炼 → 知识图谱 → 交接记录 → 假说与评审修订。**

这段 SCI-003 历史回放保留了 **21 个节点、56 条关系**，并展示一条具体假说修改前后的区别。沿着图谱连线，可以看到结论关联的来源资料。

> 录制于 2026-09-08，使用已确认的真实历史数据回放展示页，带配音和字幕。它展示研究过程，不代表现场重新执行、假说已被实验验证或比赛已正式验收。

[了解研究工作流](core/web/services/team_workflow/README.md)

## 协作之外，日常工作也在这里

![Agent 配置工作台：模型绑定与工具配置](docs/assets/readme/web-workbench-chat.png)

- **编码与对话：** 管理多个会话，查看工具调用，停止或继续任务。
- **知识与 Git：** 整理资料，查看代码 diff，选择要提交的文件。
- **评测与改进：** 比较基线与候选结果，保留评测记录；自修改能力有明确的验证与回滚边界。

<details>
<summary>查看监督评测工作台</summary>

![监督评测工作台演示截图](docs/assets/readme/web-workbench-supervised.png)

</details>

## 从协作能力长出来的小产品

工作台也承载了一些更轻松的尝试。这些是附加体验，项目的核心仍是多 Agent 协作。

<p align="center">
  <img src="docs/assets/readme/companions.png" alt="虚拟人人物大厅" width="72%">
  <img src="docs/assets/readme/desktop-pet.gif" alt="桌面伙伴待机动效实录" width="22%">
</p>

**虚拟人 · 聊完之后，她的一天还在继续。** 人物有日程、心情、日记与长期记忆，也能主动发来消息。生活经历与对话的连续性仍在打磨。为 Agent 启用「虚拟人生活」能力后，可从人物大厅进入。[了解人物能力](core/agent_plugins/virtual_human_life/README.md)

**桌面伙伴 · 不用一直盯着会话窗口。** 角色随会话运行、等待确认、完成或出错切换提示与轻动效；点击查看实时对话，拖动调整位置，关闭后从系统托盘重新打开。

[展示素材与录制说明](docs/assets/readme/README.md)

## 开始使用

目前以 **Windows 本地桌面体验**为主。准备好 **Python 3.11+（推荐 3.12）、Node.js 18+ 和 Git**，在 PowerShell 中执行：

```powershell
git clone https://github.com/CCDawn/Vibelution.git
cd Vibelution
powershell -ExecutionPolicy Bypass -File scripts/install_windows.ps1
```

安装完成后，打开桌面上的 **Vibelution Launcher**。首次启动会准备外部配置文件；按[模型配置指南](docs/ops/config/INDEX.md)配置模型与密钥后，就可以开始对话。

也可以通过正式 Launcher 入口启动：

```powershell
& "$env:LOCALAPPDATA\Vibelution\Launcher\VibelutionLauncher.exe" --project "$PWD" start
```

[Windows 安装说明](docs/guides/install-windows.md) · [开发环境与贡献](CONTRIBUTING.md) · [Linux 部署参考](docs/ops/linux-bootstrap.md)

工作台运行在本机，模型由你配置。**使用云端模型时，相应请求会发送给所选模型服务商**；本地运行不等于所有推理都离线。模型调用可能产生服务商费用，密钥与运行配置保存在仓库之外。

## 最近在做什么

这份首页展示 **2026 年 9 月的开发进展**；具体发布版本以 [VERSION](VERSION) 和 [CHANGELOG](CHANGELOG.md) 为准。

- **团队与工作流：** 持续改进多 Agent 分工、任务交接、节点运行与中断恢复，让长流程更稳定。
- **科研应用：** 打磨第一阶段资料、知识和假说评审链路；第二阶段实验结果另行验证。
- **附加产品：** 虚拟人继续改善生活经历与对话的衔接，桌宠继续丰富会话反馈和动作。

如果你喜欢其中一个方向，欢迎带着具体场景来提 [Issue](https://github.com/CCDawn/Vibelution/issues)，或从[贡献指南](CONTRIBUTING.md)开始。一次体验反馈、一张问题截图、一处文档修正，都能帮助项目往前走。

---

[文档地图](docs/README.md) · [开发规范](docs/standards/README.md) · [安全问题](SECURITY.md) · [第三方组件](THIRD_PARTY_COMPONENTS.md) · [MIT 代码许可证](LICENSE)

角色名称与第三方素材的权利归各自权利人所有；代码的 MIT 许可不授予第三方角色或素材的权利。
