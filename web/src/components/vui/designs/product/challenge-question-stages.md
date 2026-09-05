# Challenge Question Stage Zones（题目阶段分区）

单题验收页把内容分为「假说生成」与「研究计划与实验」两个描述性分区，
并由同一个题目状态投影驱动状态章和说明文字。

## ChallengeQuestionStageZones

### 功能

1. `ChallengeQuestionDetailPanel` 使用两组锚点和两个
   `ChallengeQuestionStageZoneHeading`，不使用序数命名阶段。
2. 假说区显示「假说生成中 / 假说已定」。研究计划与实验区依据服务端阶段
   边界显示「未激活 / 已解锁」；状态未取得或请求失败时显示「状态待确认」。
3. `deriveChallengeQuestionStageProjection` 是唯一推导源：题目审批只决定假说
   状态，`stageTwoActive` 只投影 `phase-boundary` 的 `phase2Activated`。
   页面复用既有查询接口与团队隔离缓存，每 15 秒刷新；归档不发起该请求。
4. `ChallengeQuestionPlanSection` 接收同一投影，不重复推断。已有计划不证明
   实验开始；已解锁不等于正在执行，实际进度以运行记录为准。

### 适用范围

- 单题验收视图的阶段导航、分区标题、状态章和计划空态。
- 状态仅用于展示；执行权威仍是 `challenge-cup-research@3.0.0` 的运行快照。

### 使用方式

```tsx
const stage = deriveChallengeQuestionStageProjection(detail, phaseBoundary);
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
