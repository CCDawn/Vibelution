# Stop painting 排队中 under a guide that already landed

- `splitTurn` 在引导被消费后会保留一个空的 running tail shell，等待下一步工作；这个 tail 原先继承 turn 在引导之前的 `queued` stage，导致刚插入的引导下方显示"排队中"，读起来像是引导还在排队。
- 现在空 tail shell 固定用 `running` stage：引导已纳入当前轮，tail 表达的是"继续处理"，不是"还在排队"。有内容的 segment 行为不变。
- 验证：`conversationGuidanceSegments.test.ts` 与 `ConversationView.test.tsx` 163 项通过；`npx tsc -b` 通过。
