# Challenge Question Stage Zones（题目阶段分区）

单题验收页把内容分为「假说生成」与「研究计划与实验」两个描述性分区，
并由同一个题目状态投影驱动状态章和说明文字。

## ChallengeQuestionStageZones

### 功能

1. `ChallengeQuestionDetailPanel` 使用两组锚点和两个
   `ChallengeQuestionStageZoneHeading`，不使用序数命名阶段。
2. 假说区显示「假说生成中 / 假说已定」。研究计划与实验区在假说确定前
   显示「等待假说确定」，确定后显示「进行中」。
3. `deriveChallengeQuestionStageProjection` 是唯一推导源：题目记录已批准或
   selection human gate 已批准时，`stageTwoActive` 为 `true`。
4. `ChallengeQuestionPlanSection` 直接呈现当前研究计划；无产物时根据
   `stageTwoActive` 区分「等待假说」和「主流程推进中」。

### 适用范围

- 单题验收视图的阶段导航、分区标题、状态章和计划空态。
- 状态仅用于展示；执行权威仍是 `challenge-cup-research@3.0.0` 的运行快照。

### 使用方式

```tsx
const stage = deriveChallengeQuestionStageProjection(detail);
<ChallengeQuestionStageZoneHeading
  zone="hypothesis"
  stageOneStatus={stage.stageOne}
  lang={lang}
/>
<ChallengeQuestionStageZoneHeading
  zone="plan"
  stageTwoActive={stage.stageTwoActive}
  lang={lang}
/>
```

状态文案统一来自 `challengeQuestionStageModel` 的
`stageOneStatusCopy`、`stageTwoStatusCopy`、`stageTwoProgressHint` 与
`stageZoneTitle`。
