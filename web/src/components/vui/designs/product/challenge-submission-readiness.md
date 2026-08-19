# Product — Challenge submission readiness

## ChallengeSubmissionReadiness

### 功能

在团队科研工作流中提供低信息密度的挑战杯提交材料检查：显示必需/可选材料状态、一个主操作，以及按需展开的阻塞项。检查动作只返回材料清单的 `ready/blocked` 状态与阻塞数量，不宣称已经生成可下载提交包。

### 适用范围

- **适用**：`ChallengeMvpProgressPanel` 内的提交材料 readiness 区域。
- **不适用**：DEV 批次控制、完整运行收据、静态站点或文件路径浏览器。

### 使用方式

- 通过 `VStatusChip` 表达材料与总体状态，主操作使用 `VButton`。
- 阻塞详情使用原生 `<details>`，默认折叠；主操作根据 canonical action 的 `kind/target/questionId` 导航到真实题目或检查交付材料。
- UI 本地化由 `key/code` 映射承担，不直接渲染后端 label；不得显示内部 ID、路径、主题或 campaign。
- 材料检查成功后在区域内显示返回的 `ready/blocked` 和 blocker 数量，不能写成「已生成」或提供伪下载链接。
