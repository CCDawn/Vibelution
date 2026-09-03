# Challenge Question Stage Zones（题目阶段分区）

单题验收页的两阶段严格分区呈现：把锚点目录与正文分区重组为「假说生成」与「研究计划与实验」两个描述性命名分区（不用序数），并给题目级阶段状态一个统一推导源。

## ChallengeQuestionStageZones

### 功能

题目详情（单题验收）视图的信息架构分区与阶段状态呈现，由三部分组成：

1. **锚点目录两段分组**：`ChallengeQuestionDetailPanel` 的锚点导航改为「假说生成」（题目与接单/来源与证据/全链谱系/候选假设/七维评价/选择/假说选择/评审讨论/评审轮次）与「研究计划与实验 · 未激活」（研究计划/人工审核/最终工件）两组，组标题为描述性命名，不用「第一阶段/第二阶段」序数。
2. **正文分区标题**：`ChallengeQuestionStageZoneHeading`（`routes/teams/challenge-cup/ChallengeQuestionStageZoneHeading.tsx`）在正文两处分区插入标题行：假说生成区携带推导出的阶段状态章（假说生成中=accent / 假说已定=success）；研究计划与实验区恒显示「未激活」状态章（neutral）加一行激活语义说明——二阶段永不自动激活（`allowPhaseTwoAdvance=false`），需按题显式开启。
3. **阶段推导模型**：`challengeQuestionStageModel.ts` 的 `deriveChallengeQuestionStageProjection` 是唯一推导源——`record.status === "approved"` 或 `output.selection.human_gate.decision === "approved"` 即「假说已定」（与面板头部状态章同源，不引入第二套真相）；`stageTwoActive` 恒为 `false`；`hasResearchPlanProposal` 判断本 run 输出是否携带历史研究计划产物。

研究计划分区（`ChallengeQuestionPlanSection`）：分区标题旁恒挂「未激活」状态章；有历史计划产物时卡片顶部挂「预投影（proposal only）」章并说明其为阶段一期间的预投影、仅供参考（如 SCI-091 的历史研究计划）；无产物时显示未激活空态说明，不渲染空字段卡片。

### 适用范围

- 仅单题验收视图（`ChallengeQuestionDetailPanel` 非 `readOnlyArchive` 分支）；题目档案只读摘要保持原有极简锚点。
- 适用：需要区分「假说生成产物」与「研究计划与实验产物」的题目详情呈现、二阶段灰置语义说明。
- 不适用（改用 `…`）：画布上的二阶段灰置节点组（改用 `阶段未激活区域`，见 product/workflow.md）；二阶段激活动作本身（本分区只读，不提供任何激活入口）。

### 使用方式

```tsx
import { ChallengeQuestionStageZoneHeading } from "./ChallengeQuestionStageZoneHeading";
import { deriveChallengeQuestionStageProjection } from "./challengeQuestionStageModel";

const stageProjection = deriveChallengeQuestionStageProjection(detail);
// 正文两处分区：
<ChallengeQuestionStageZoneHeading zone="hypothesis" stageOneStatus={stageProjection.stageOne} lang={lang} />
// …假说产物分区…
<ChallengeQuestionStageZoneHeading zone="plan" lang={lang} />
// …研究计划与实验分区（ChallengeQuestionPlanSection 自带「未激活」章与预投影标注）…
```

状态章文案与分区标题统一来自 `challengeQuestionStageModel`（`stageOneStatusCopy` / `stageTwoStatusCopy` / `stageZoneTitle` / `stageTwoInactiveHint`），页面内不得手写第二份阶段文案。
