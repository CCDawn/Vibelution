# 产品语境（现行）

> 从根 `PRODUCT.md` 提炼的**现行**产品定位。完整历史快照见 [`../archive/product/PRODUCT.md`](../archive/product/PRODUCT.md)。
> 实现与红线以 [`AGENTS.md`](../../AGENTS.md)、[`../standards/`](../standards/)、代码为准。

## 产品目的

Vibelution 是**本地优先**的 AI Agent 工作台，面向工程协作、仓库阅读、Git、自进化、监督评测、runtime-scene 证据与模型配置。
不是营销站，也不是托管型助手壳。界面存在的目的，是让开发者与后续 Agent 用**清晰证据和可逆操作**理解、验证并改进同一本地项目。

## 主要用户

| 角色 | 关注点 |
| --- | --- |
| 开发操作者 | Web Workbench：编码、审查、调试、Git、配置 |
| 维护者 | Runtime scenes、监督进化记录、worktree、操作风险 |
| 后续 Agent | UI、日志、project-memory、稳定术语，避免靠过期截图猜 |

## 核心产品面

- **Chat / Coding**：多会话、文件树、只读预览、消息态、任务上下文、运行状态
- **Agent 管理**：注册表、提示词、工具、技能、记忆、权限边界
- **Git**：worktree、diff、选文件提交、AI 提交说明草稿
- **Supervised Evolution**：dataset/bundle、active run、提案库、决策记录、建议基线
- **Self Evolution**：有界自改进、审计、回滚边界、fitness
- **Logs / Runtime Scenes**：生命周期证据包
- **Config / Reset / Pet**：运营配置、受保护清理、长期陪伴体

## 产品语气

冷静、精确、运营向、证据优先。像严肃的本地控制室：信息密度够用、长时间可待、状态/风险/出处明确。不把不确定包装成确定。

## 战略原则

1. **证据先于理论**（日志、runtime scene、测试、当前数据）
2. **产品清晰先于视觉新颖**
3. **跨路由一致性是一种可用性**
4. 用户可见行为变更必须有**日志决策**与**测试决策**
5. **本地优先信任**：不隐藏路径、状态、错误或不可逆动作
6. 优化人和 Agent 的**事后可重建**

## 相关入口

| 主题 | 文档 |
| --- | --- |
| Windows 最终用户安装（Phase 1） | [2026-08-06-windows-end-user-install.md](2026-08-06-windows-end-user-install.md) · [../guides/install-windows.md](../guides/install-windows.md) |
| 产品 UI 注册表 / 视觉禁令 | [design-register.md](design-register.md) |
| 领域词汇 | [../agents/domain.md](../agents/domain.md) |
| Gym 产品意图 | [../prds/README.md](../prds/README.md) |
| VUI 实现 | [../../web/src/components/vui/README.md](../../web/src/components/vui/README.md) |
| 文档地图 | [../README.md](../README.md) |
| Agent 开发路由 | [../guides/README.md](../guides/README.md) |
