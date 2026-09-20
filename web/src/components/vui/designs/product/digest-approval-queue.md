## DigestApprovalQueuePanel

### 功能

R4.x 纪要批量审批队列面板：把全队 `awaiting_approval` 会议纪要聚合成单一队列（最老置顶），每行显示题目、候选/风险计数、等待时长、TTL 超时提示与纪要摘要；多选后一次「批量通过」，服务端逐条执行单审权威（`approve_meeting_digest`），逐行带回 approved/failed 结果与失败原因，单条失败不阻断整批。

### 适用范围

- **适用**：研究工作台操作员一次确认多条会议纪要（多题并行扩容时的最高频人工门）。
- **不适用**（改用 `…`）：单条纪要的详细内容与逐字修订（单题会议操作面 `HypothesisFirstMeetingOps`）、题目级异常队列（`ResearchAnomalyInboxPanel`）。

| 场景 | 选择 |
| --- | --- |
| 跨题目批量确认待审纪要 | 用本组件 |
| 单题会议内容/修订 | 改用 `HypothesisFirstMeetingOps` |
| 阻塞/心跳/预算异常队列 | 改用 `ResearchAnomalyInboxPanel` |

### 使用方式

```tsx
import { DigestApprovalQueuePanel } from "@/routes/teams/research-workflow/DigestApprovalQueuePanel";

<DigestApprovalQueuePanel teamId={teamId} />
```

### 数据与契约

- `GET .../hypothesis-first/chain/digest-approvals/pending` → `{items, count, fetchedAtMs}`（只读投影，含 `digestContentHash`）。
- `POST .../hypothesis-first/chain/digest-approvals/batch-approve` → `{results[], approvedCount, failedCount}`；逐条隔离，hash 逐字回显（与单审同一 CAS 契约）。
- 查询键 `queryKeys.digestApprovals(teamId)`，成功后失效重取。
