# Architecture Decision Records

重大设计决策与**为何如此**。不替代 `docs/standards/` 的日常流程。

| ID | 标题 | 状态 |
| --- | --- | --- |
| [0001](0001-gym-v1-uses-promotion-proposals-before-baseline-rewrite.md) | Gym v1 先写 promotion proposal，不自动改 baseline | Accepted |
| [0002](0002-agent-collaboration-session-addressing.md) | 协作消息以 Session 为 body SSOT，inbox 仅索引 | Accepted |
| [0003](0003-operator-config-lives-outside-repo.md) | 活跃 operator config 在用户 Documents，不在仓库根 | Accepted |
| [0004](0004-product-ui-uses-vui-shadcn-only.md) | 产品 UI 强制 VUI + shadcn/Radix，禁止并行设计系统 | Accepted |
| [0005](0005-docs-authority-and-archive-policy.md) | 文档权威层与 archive 策略 | Accepted |
| [0006](0006-challenge-cup-workflow-runtime-and-single-canvas.md) | 挑战杯科研流程使用 LangGraph 运行权威与单画布三阶段投影 | Accepted |

## 写法

- 一决策一文；写 Context / Decision / Consequences。
- 被 supersede 时更新 Status，并链到新 ADR。
- 日常操作细节进 standards / ops / 模块 README，不堆在 ADR。
