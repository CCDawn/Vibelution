# 挑战杯知识 Sideflow 与假说 Agent 非阻塞证据补充实施方案

> Status：`implemented-dev`（代码与合入前验收已闭合；真实 G1/正式研究未执行）
>
> Owner：`core/web/services/team_workflow/research_runtime`（主 owner）；`tools/research_knowledge_request_tools.py`、Team Knowledge 读取投影与相关测试为协作面
>
> Implementation branch：`codex/challenge-knowledge-sideflow-integration`
>
> Scope：把节点 2–6 的正式知识 sideflow 接入假说先行链路，使假说 Agent 可读取已接受知识包补充证据，并让知识生产与探索主线并行而不抢占主线关键容量
>
> Supersedes：不替代 [挑战杯 1–7 节点链路高 ROI 修复方案](2026-08-31-challenge-cup-nodes-1-7-high-roi-repair-plan.md)；本文只补齐其 DEV 实施后尚未接通的 sideflow→假说消费与性能隔离
>
> Implementation links：[自动 sideflow trigger](../../../../core/web/services/team_workflow/research_runtime/knowledge_sideflow_trigger.py) · [快照消费权威](../../../../core/web/services/team_workflow/research_runtime/knowledge_snapshot_consumption.py) · [假说输入构建](../../../../core/web/services/team_workflow/research_project_hypothesis_context.py) · [正式 fanout](../../../../core/web/services/team_workflow/research_runtime/formal_hypothesis_fanout.py) · [foreground-first outbox](../../../../core/research/workflow/ledger/outbox.py) · [知识请求工具](../../../../tools/research_knowledge_request_tools.py)
>
> Validation：2026-09-01 完成实现、自审前相关回归 `329 passed`、同机 10 次 before/after 性能对比与 EXTERNAL reuse 记录；未修改 operator config、Launcher、运行数据，未调用真实 provider、真实知识库或 G1
>
> Close condition：T0–T5 的代码、聚焦测试、性能对比、DEV sideflow 场景与本地 main 合入全部闭合；真实 G1/正式研究仍是独立授权门

## 0. 实施状态与验收快照

T0–T5 的 DEV 行为合同已经实现：知识请求统一进入 `WorkflowCommandService`；3.0.0 `problem_understanding` 成功提交后只执行一次本地异步 ensure；accepted package 由 invocation、父 run event、canonical ref 与 content hash 共同校验；多个 package 稳定合并成一个冻结 `knowledgeSnapshot`，所有 candidate 共享同一 `snapshotHash`；live hypothesis 只记录 `knowledge_revision_available`，不改写当前 Turn；下一安全边界以幂等 `knowledge_snapshot_consumed` 记录消费事实。

同时完成了两个会直接影响主线效率或可重放性的修复：outbox 按 foreground-first 租约并把后台知识并发限制为 `2`；candidate task 私有冻结快照 binding 持久化但不进入公开 task DTO。父 run 的知识吸收事实改为按事件类型读取完整 Ledger 记录，避免超过 500 条事件后因窗口截断而误判；兼容投影继续保留 `knowledgeBaseId`，并补充 `knowledgeItemIds`。

### 0.1 DEV 性能证据

环境：同机、同一根 `.venv`、同一 deterministic fixture；baseline=`7c600100ce64bc9cdcda79e1c8beba716e2ae515`，after=该基线上的实现 worktree；每侧 10 次。仅测本地 Ledger/outbox 与 ensure 事务，不启动网络、模型、Launcher 或真实知识写入。

| 指标 | Baseline p50 / p95 | After p50 / p95 | 行为结果 |
| --- | --- | --- | --- |
| 100 条 background sideflow backlog 下首次 outbox lease | 50.360ms / 50.551ms | 50.310ms / 51.201ms | baseline 主线 0/10 入选；after 主线 10/10 入选且每次首条均为 foreground；p95 +0.650ms |
| 单次 sideflow ensure 本地事务 | 167.300ms / 173.198ms | 164.184ms / 166.602ms | p95 -6.596ms；下游 provider/model 耗时未进入主线调用栈 |

after 未劣于 `max(5%, 100ms)` 阈值；时间数据仅作为同机 DEV 证据，确定性合同由测试保护。

### 0.2 已闭合验证与真实限制

- 相关回归共 `329 passed`，覆盖 sideflow、readiness、formal fanout、冻结 task binding、工具、outbox、Command、HTTP route、rollout、跨 run event、角色权限、hypothesis-first chain 与 research knowledge cases。
- EXTERNAL reuse 裁决为 `ADAPT`：参考 `langchain-ai/langgraph@38031739e...` 的 checkpoint/interrupt 边界，但继续复用本项目 Ledger、outbox、CommandService 和 run events；不引入第二 workflow engine 或 store。
- 当前真实 operator config 未修改，Launcher 未启动或重启；因此这里不声称本机产品实例已启用自动 sideflow。
- 未发起付费/真实 provider 检索，未向真实 Team Knowledge 写入资料，未跑 G1，也未验证正式赛题质量、成本或提交链。
- 本轮没有重解释既有 2.1.0 run；3.0.0 仍按 run-pinned definition 与 accepted handoff 边界 fail closed。

## 1. 结论

推荐方案不是把节点 5 `knowledge_ingestion` 重新串回假说主流程，也不是给所有假说 Agent 开放知识写入，而是采用以下两层闭环：

1. **探索闭环不等待知识生产。** `problem_understanding` 完成后，候选假说生成、讨论和初审使用任务启动时冻结的知识快照继续运行；同一时刻异步 ensure 一条知识 sideflow。
2. **正式 grounded 闭环只消费已接受知识。** 节点 2–6 完成搜索、提炼、关系治理、节点 5 正式入库和节点 6 人工交接后，通过 `knowledge_result_available` 发布新知识；平台只在下一次修订轮或正式 `hypothesis_design` fan-in 边界重建 `hypothesisInput`，不得改写正在执行的 Agent Turn。

并行语义是“多条知识生产管线可在后台推进，最终由知识管理角色受控写入”，不是“多个假说 Agent 同时直接写同一知识库”。角色边界保持：**多读者、单请求面、知识管理单写者**。

## 2. 实施前现状与根因

### 2.1 已经具备的能力

当前代码已经具备目标架构的大部分构件：

- `challenge-cup-knowledge-sideflow@1.0.0` 已定义完整的 `source_finding → source_extraction → evidence_relations → knowledge_ingestion → knowledge_handoff` child workflow。
- 新 run 的 definition 选择已支持：`mode=on` 使用主流程 3.0.0，节点 1 `problem_understanding` 直接连接节点 7 `hypothesis_design`；既有 run 仍按 pinned definition 解释。
- `CommandService` 已实现 `ENSURE_KNOWLEDGE_COLLECTION` 与 `INSPECT_KNOWLEDGE_COLLECTION`；ensure 使用 request fingerprint 幂等复用 child run，且不移动父 run 的 checkpoint、active node 或 runVersion。
- sideflow 终态与 `knowledge_result_available` 使用同一 Ledger 事务写入 outbox；父 run 消费端按确定性 event id 幂等吸收。
- `hypothesis_design` readiness 已接受两种正式知识权威：2.1.0 的 in-graph accepted handoff，或 3.0.0 被父 run 吸收的 accepted sideflow invocation。
- 假说相关角色已具备 `unified_memory_search_tool` / `research_knowledge_query_tool` 读取能力；正式写入仍只属于知识管理角色。

### 2.2 真正缺失的四个连接

| 缺口 | 当前事实 | 为什么发生 | 用户影响 | 优先级 |
| --- | --- | --- | --- | --- |
| 请求入口绕过 sideflow | `research_knowledge_request_tool` 的 `request/status` 仍直接调用旧 source-collection facade，并明确声明不写正式知识 | 工具在 sideflow Command 能力完成前实现，后续没有切换权威入口 | Agent 看见“搜集成功”，但节点 3–6 和正式 Team Knowledge 不一定发生 | P0 |
| 基础 sideflow 不会自动启动 | operator 配置当前是 `[research.knowledge_sideflow] mode="off"`；3.0.0 只有手动 command offer，没有 `problem_understanding` 完成后的自动 ensure | topology 拆分完成，但启动编排仍停留在 rollout/手动操作层 | 假说闭环可跑完探索部分，却没有任何节点 5 入库 | P0 |
| readiness 与输入读取权威不一致 | readiness 可由 accepted sideflow invocation 解锁；`build_hypothesis_input_context` 仍只调用父 run 的旧式 handoff receipt loader | 3.0.0 只向父 run追加 absorption event，不复制 child receipt；输入构建器尚未消费 invocation lineage | readiness 可能通过，但 candidate task 报 `knowledge_package_not_materialized`，或 Agent 收不到新知识 | P0 |
| 新知识没有修订消费边界 | absorption 后 recheck 若发现请求节点已有 live attempt，会以 `node_already_live` 跳过；当前没有后续 revision marker/消费状态 | recheck 只负责“被知识阻塞的节点首次启动”，没有覆盖“运行中补证” | sideflow 完成且知识已入库，但当前轮不变、下一轮也未必自动吸收 | P0 |

### 2.3 性能根因

“异步 child run”本身不等于“不影响主线”：

- 通用 outbox 当前按 `available_at_ms, action_id` FIFO 租约，没有区分主流程与 `challenge-cup-knowledge-sideflow`。
- sideflow 的图 dispatch、Agent task、搜索 provider 和模型调用仍会使用共享执行资源。
- 当多个补证请求同时进入时，只依靠 child run 隔离会造成后台任务排在主线前面，或占满可用 Agent/LLM 容量。

因此实施必须同时提供**优先级/配额隔离与可比较 baseline**，不能只增加线程、队列或“后台执行”标记。

## 3. 目标与非目标

### 3.1 可观察目标

1. 新 3.0.0 run 在 `problem_understanding` accepted success 后，自动创建或复用一条以 `hypothesis_design` 为消费节点的知识 invocation。
2. sideflow 下游不在主线调用栈中等待；搜索、提炼、关系、入库和人工交接的耗时不增加探索性假说任务的关键路径。
3. 节点 5 产生的 applied Team Knowledge 能被有权限的其他假说 Agent 通过统一知识检索读取。
4. 正式假说引用只来自任务启动时冻结的 accepted knowledge snapshot；preview、候选资料或尚未交接的 package 不得进入 `allowedEvidenceRefs`。
5. sideflow 在 Agent Turn 中途完成时，只产生 `revision_available`，不得修改当前 Prompt、task context、fragment 或 checkpoint。
6. 下一修订轮/正式 fan-in 消费新快照后记录 `consumedKnowledgeSnapshotHash`，相同快照不得重复触发修订。
7. sideflow 积压时，主流程 dispatch/Agent task 至少保留一个执行槽且优先租约，不能被后台知识任务饿死。

### 3.2 非目标

- 不引入第二个 workflow engine、receipt store、知识库、向量库或 revision store。
- 不给候选假说 Agent 开放 `knowledge_ingestion_tool`、`knowledge_proposal_tool` 或 source-collection 内部工具。
- 不让自由检索结果直接成为正式证据。
- 不迁移或重解释已经 pinned 的 2.1.0 run。
- 不自动接受 `knowledge_handoff`，不取消现有人工知识包 gate。
- 不在本任务启动 Launcher、修改真实团队知识、跑 G1、发起付费检索或正式研究。

## 4. 目标链路

```text
main 3.0.0
problem_understanding accepted
        │
        ├──▶ hypothesis-first exploration
        │      candidate generation / discussion / initial review
        │      uses immutable knowledge snapshot K0
        │
        └──▶ CommandService.ENSURE_KNOWLEDGE_COLLECTION
               parentNodeId = hypothesis_design
               deterministic idempotency + requestHash
                         │
                         ▼
knowledge sideflow 1.0.0
source_finding → source_extraction → evidence_relations
→ knowledge_ingestion → knowledge_handoff(HUMAN accepted)
                         │
                         ▼
transaction outbox: knowledge_result_available
                         │
                         ▼
parent absorbs invocation + package hash
        │
        ├── no live hypothesis attempt
        │      └── readiness recheck may start formal hypothesis_design
        │
        └── live/completed hypothesis attempt exists
               └── mark revision_available(K1), do not mutate current Turn
                         │
                         ▼
next review/revision/fan-in boundary
build composite accepted snapshot K1 once
→ candidate task private binding + bounded shared refs
→ allowedEvidenceRefs whitelist
→ grounded fragment fan-out / fan-in
```

## 5. 权威与数据合同

### 5.1 请求权威

所有 3.0.0 知识补给入口最终都必须提交同一个 `CommandService` command：

```text
WorkflowCommandKind.ENSURE_KNOWLEDGE_COLLECTION
```

输入由服务端从 bound task/run 解析，调用者不得选择其他题目：

- `teamId`
- `workflowRunId`
- pinned definition identity
- `questionId`
- `parentNodeId = hypothesis_design`
- `scope`
- normalized `searchEnvelope`
- normalized `requirements`
- `sourcePolicyVersion`
- `parentNodeRunId/parentAttempt`（存在时）

幂等沿用现有：

```text
requestHash = hash(questionId + scopeHash + searchEnvelopeHash
                   + requirementsHash + sourcePolicyVersion)
```

相同父 run、消费节点和 requestHash 返回同一 invocation；跨 run 且完整 fingerprint 相同的 accepted package 可复用，不新建 child run。

### 5.2 基础请求生成

`problem_understanding` 的 canonical artifact 是基础请求唯一内容来源：

- `scope`：限定研究边界；
- `subquestions[]`：形成首批 query；
- `known_unknowns[]`：形成证据缺口；
- `assumptions[]`：只用于 requirements/反证方向，不可直接当事实；
- `human_gate.decision` 必须为 `approved`。

自动 trigger 必须发生在上游 attempt 与 accepted handoff 已提交之后、successor readiness 之前；ensure 只允许一个有界 Ledger/Command/outbox 事务，绝不等待 child run 下游。

建议把 trigger 逻辑封装在新的小 owner `knowledge_sideflow_trigger.py`，由 graph worker 注入调用；不要把 envelope 解析、版本判断和 CommandRequest 构造散落在 `graph_dispatch_worker.py`。

### 5.3 正式知识快照

2.1.0 与 3.0.0 使用统一输出、不同读取来源：

- 2.1.0：父 run 的 accepted `knowledge_handoff` receipt；
- 3.0.0：父 run 下所有 `completed + handoff_state=accepted + packageContentHash` 的 knowledge invocations、对应的父 run absorption event，以及 invocation 指向的 canonical `knowledge_package` artifact。

3.0.0 不能只取“最新一个 package”覆盖旧证据。输入构建器按稳定顺序合并全部 accepted package，并生成不可变复合快照：

```json
{
  "knowledgeSnapshot": {
    "snapshotHash": "sha256(sorted package hashes + knowledge item ids)",
    "packages": [
      {
        "invocationId": "kinv-...",
        "knowledgePackageRef": "...",
        "packageContentHash": "..."
      }
    ],
    "knowledgeItemIds": ["ki-..."]
  },
  "knowledgeItems": [],
  "evidenceClaims": [],
  "allowedEvidenceRefs": []
}
```

不变量：

- canonical ref、invocation record、父 run absorption event 与 payload content hash 必须四方一致；不一致 fail closed。
- 只合并 applied/accepted Team Knowledge item；库存中更晚但未绑定 invocation 的 item 不得替换快照。
- package/item/claim 顺序稳定，重放产生相同 `snapshotHash`。
- `allowedEvidenceRefs` 只来自已验证 package 的 source artifacts / evidence claims。
- 当前 `24 claims / 64 refs` 上限继续作为 Prompt 边界；超出部分留在 Team Knowledge，可由 Agent 受 ACL 约束检索，不扩大 Prompt。

### 5.4 Candidate 级读取（实施裁决）

所有 candidate task 共享同一个 `knowledgeSnapshot.snapshotHash` 和同一组受 `24 claims / 64 refs` 限制的正式 refs；每个 task 再绑定自己的 `candidateContext`。fanout 关键路径不为每个 candidate 重跑 Team Knowledge 检索，避免 N 倍读取、任务间快照漂移和主线延迟。

- task 启动时把完整 `hypothesisInput` 作为服务端私有 binding 冻结，公开 task DTO 不返回该 binding；
- candidate 可以继续调用 `unified_memory_search_tool` / `research_knowledge_query_tool` 查团队正式知识来补充推理；
- 额外检索结果不会自动扩充本 Turn 的 `allowedEvidenceRefs`，正式写回引用仍必须属于冻结 binding；
- 若以后需要大规模 candidate 级 ranking，应以真实 Prompt/召回 profile 另立任务，不能在本次 fanout 中增加同步检索。

### 5.5 修订消费状态

不新建 revision store。复用现有 hypothesis task/round/collection request 投影，最少增加：

- `requestedKnowledgeInvocationId`
- `availableKnowledgeSnapshotHash`
- `consumedKnowledgeSnapshotHash`
- `knowledgeRevisionState = none | collecting | revision_available | consumed | failed`

规则：

1. `knowledge_result_available` 到达时，如果没有 live hypothesis attempt，维持现有 readiness recheck。
2. 如果请求节点正在运行或本轮 fragment 已写回，只更新 `revision_available`，不得取消或重写该任务。
3. 当前评审轮关闭后，若 `available != consumed` 且轮次预算允许，创建一轮已有 revision/follow-up 任务。
4. 新任务创建时重新构建 `hypothesisInput`，成功后将该 snapshot hash 写为 consumed。
5. 同一个 snapshot hash 重放、重复事件或多个 candidate 同时观察，只能形成一次修订轮。

## 6. 角色与权限

| 能力 | 假说/评审 Agent | 假说规划或修订协调 Agent | 知识搜集 Agent | 知识管理 Agent |
| --- | --- | --- | --- | --- |
| 读 applied Team Knowledge | 允许 | 允许 | 按现有 stage policy | 允许 |
| 请求补证 | 只提交 evidence gap/消息，不直接 ensure | 允许调用 `research_knowledge_request_tool` | 不适用 | 不适用 |
| 搜索/提炼 stage writeback | 禁止 | 禁止 | 仅 sideflow 任务范围 | 受 stage contract |
| 正式 knowledge ingestion | 禁止 | 禁止 | 禁止直接越级 | 唯一允许 |
| 修改 `allowedEvidenceRefs` | 禁止 | 禁止 | 禁止 | 平台从 accepted package 投影 |

保持 `research_knowledge_request_tool` planner-only。若每个 candidate 都能直接发起 child run，会放大重复搜索、成本和 provider 竞争；candidate 只需把缺口写入已有 review/evidence request，由协调入口聚合、去重后 ensure。

## 7. 并发与主线性能合同

### 7.1 调度分级

仅使用现有 Ledger/outbox，不新建队列。对 `graph_dispatch` 与 `adapter_dispatch` 的租约增加 run workflow class 过滤：

- `foreground`：非 `challenge-cup-knowledge-sideflow` 的主流程；
- `background_knowledge`：knowledge sideflow child run。

每次 worker lease cycle：

1. 先租 foreground；
2. foreground 未用满批次时，才用剩余预算租 background knowledge；
3. background knowledge 同时 live 的 dispatch/Agent task 设有界上限，推荐 DEV 初始值为 `2`；
4. 至少保留 `1` 个主流程执行槽，sideflow backlog 不得占满共享池；
5. 同 run 相同 requestHash 仍只允许一个 child；不同补证请求可以排队并在后台预算释放后推进。

优先通过现有 workflow id 与 outbox filter 扩展实现，不新增 `priority` 数据表或第二套 scheduler。若实测表明通用过滤不足，再以 profile 证据决定是否引入显式 priority 字段。

### 7.2 主指标与代表性负载

T0 先在相同 HEAD、相同 deterministic provider、相同题目 fixture 下记录 baseline：

- 主指标：`problem_understanding accepted → first hypothesis exploration task started` 的 p95；
- 辅助指标：foreground outbox 等待时间、sideflow ensure 本地事务时长、同时 live sideflow 数、Prompt evidence context 字符数；
- 代表性负载：1 条主 run + 8 条不同 sideflow invocation backlog；另设 100 条 pending sideflow outbox 的纯调度测试，不发起真实网络/模型调用。

验收目标：

- 主线调用栈新增网络/模型等待次数为 `0`；
- foreground 在 sideflow backlog 下无饥饿，首个 lease cycle 必须取得主线 action；
- 主指标 after 不劣于 baseline 的 `max(5%, 100ms)`，并记录至少 5 次重复的 p50/p95；
- sideflow ensure 只增加一次有界本地事务；其下游耗时不计入主指标；
- 共享正式投影不突破现有 `24 claims / 64 refs` Prompt 上限，fanout 不新增 per-candidate 同步检索。

时间阈值不放入普通单元测试；单测保护确定性的 lease 顺序、调用次数、并发上限和“没有 await 下游”合同。p50/p95 只作为同机 DEV 性能证据。

## 8. 状态与可观测性

状态从 child run、attempt、handoff、invocation 和 outbox 现有事实投影，不新建状态 store：

| 对外状态 | 权威事实 |
| --- | --- |
| `queued` | invocation 已创建，child 首个 dispatch 尚未运行或受 background 配额等待 |
| `searching` | `source_finding` live |
| `extracting` | `source_extraction` live |
| `relating` | `evidence_relations` live |
| `ingesting` | `knowledge_ingestion` live |
| `awaiting_handoff` | `knowledge_handoff` waiting human |
| `published` | invocation completed/accepted 且父 run 已吸收 package hash |
| `revision_available` | published snapshot 尚未被下一假说任务消费 |
| `failed` | child/invocation/outbox 终态失败，保留 error code 与 recovery action |

新增 runtime scene 只记录有界身份和耗时，不记录 Prompt 或全文知识：

- `knowledge_sideflow.auto_ensure_submitted`
- `knowledge_sideflow.auto_ensure_replayed`
- `knowledge_sideflow.revision_available`
- `knowledge_sideflow.snapshot_consumed`
- `knowledge_sideflow.foreground_capacity_preserved`

## 9. 兼容、灰度与回滚

### 9.1 版本兼容

- 2.1.0 pinned run：继续使用 in-graph 节点 1–7 与父 handoff receipt；不得切到 sideflow loader。
- 3.0.0 pinned run：使用 child invocation + composite snapshot；不得回退到 2.1.0 topology。
- 空/未知 version/hash 的 authoritative run 路径继续 fail closed，不能以“兼容”为名读取当前默认定义。

### 9.2 灰度顺序

1. 当前 `mode=off` 保持不动，先完成 T0–T4 代码与 deterministic tests。
2. 在隔离 DEV config 中使用 `shadow` 对照 request fingerprint 与旧 collection envelope；shadow 不创建真实 child。
3. 使用隔离 DEV config 切 `on`，只跑 deterministic provider/fixture 场景，验证 3.0.0 + sideflow + 人工 handoff + hypothesis consumption。
4. 通过后再决定是否修改本机 operator config；该修改、Launcher restart 和真实 G1 均为独立执行/验收步骤。

### 9.3 回滚

不能在存在 active 3.0.0 run 时直接把 mode 改回 `off`，否则既有 3.0.0 run 仍按 pinned definition 解释，却失去 ensure/inspect 能力。安全回滚顺序：

1. 使用现有 Challenge Cup maintenance fence 停止创建新 run；
2. 保持 `mode=on`，让已存在的 3.0.0 parent/child run 完成、失败收口或由 operator 明确归档；
3. 确认没有需要继续 ensure 的 active 3.0.0 run；
4. 再切回 `off`，新 run 恢复 2.1.0 creation definition；
5. pinned definition registry 和历史 event/package 保留，不删除知识、不改写 checkpoint。

## 10. 复用研究结论

主决策：`ADAPT / REFERENCE_ONLY`，不新增依赖。

| 候选 | License / 活跃性 | 借鉴点 | 本项目裁决 |
| --- | --- | --- | --- |
| [LangGraph](https://github.com/langchain-ai/langgraph) / [Graph API](https://docs.langchain.com/oss/python/langgraph/use-graph-api) | MIT；项目当前已使用 | 并行 branch、状态 reducer、边界合并；并行 superstep 的更新顺序不能当权威 | 复用现有 LangGraph 与 Workflow Ledger；不增加第二 checkpoint/store |
| [LlamaIndex Ingestion Pipeline](https://developers.llamaindex.ai/python/framework/module_guides/loading/ingestion_pipeline/) | MIT；活跃 | `doc_id → hash`、重复跳过、upsert、异步 ingestion | 借鉴 package/item hash 与去重；不引入其 storage/index 层 |
| [Haystack AsyncPipeline](https://github.com/deepset-ai/haystack) | Apache-2.0；活跃 | dependency-ready 并发、`concurrency_limit`、增量输出 | 借鉴 background 配额与主线保留槽；不引入第二 pipeline engine |

拒绝方案：

- **把节点 5 串回主线：** 会让搜索、提炼与人工交接成为假说探索的硬等待，直接违背效率目标。
- **给每个假说 Agent 开 ingestion：** 破坏知识管理单写者、ACL、来源和人工接受边界。
- **新建 sideflow queue/revision DB：** 现有 Ledger/outbox/invocation/task round 足以表达，新增只会形成双权威。
- **同一 Turn 热更新 Prompt：** 无法保证可重放性，不同 candidate 会看到不同证据版本。

## 11. 实施任务图

模式：`TASK_GRAPH`。原因是本任务跨 Command/Tool、run completion、知识快照、hypothesis revision、outbox 调度与 rollout 六个独立验证合同；其中状态、权限与并发属于高风险行为，不能用一个无边界大改交付。

Critical Path：`T0 → T1 → T2 → T3 → T4 → T5`。T2/T3 的纯测试准备可并行只读，但共享 Ledger/runtime owner 的写入保持单 writer；实施时重新 preflight，任何命中活跃 claim 的文件必须串行等待或重新划分。

### Task 0：冻结行为合同与性能 baseline（DEV 已完成）

- Owner/Boundary：tests + 有界 benchmark/scene probe；不改产品行为。
- Dependency：本方案。
- Mode：`BDD_TDD`。
- 产出：证明旧 request tool 仍走 facade、3.0 readiness/context 不一致、live attempt 吸收后无 revision、FIFO backlog 会先到先租；记录主指标 baseline。
- Verification/Stop：新增测试先在旧实现上按预期失败；若现状与本文根因不符，停止后续写入并修订方案。

### Task 1：统一知识补给 Command 入口（DEV 已完成）

- Owner/Boundary：`tools/research_knowledge_request_tools.py`、`command_service.py` 的既有 facade、3.0 review collection bridge；不扩 Agent 权限。
- Dependency：T0 failing contracts。
- Mode：`BDD_TDD`。
- 产出：`request/status` 与 3.0 `request_new_evidence` 都走 `ENSURE/INSPECT_KNOWLEDGE_COLLECTION`；2.1 pinned run 保持旧链；collection request 投影保存 `invocationId/childRunId` 用于修订关联。
- Verification/Stop：相同请求只创建一个 child；跨题/跨 team/fake node 失败；preview 仍 advisory；如必须新增第二 facade/store，停止并回到架构审查。

### Task 2：节点 1 完成后非阻塞启动基础 sideflow（DEV 已完成）

- Owner/Boundary：新增 `knowledge_sideflow_trigger.py`，graph completion 只调用窄接口，runtime factory 注入 CommandService；不把业务逻辑堆进 worker。
- Dependency：T1 统一入口。
- Mode：`BDD_TDD`。
- 产出：approved canonical `problem_understanding` 构建 server-owned envelope，以 `hypothesis_design` 为 parent node ensure；ensure 完成即返回，不等待 child。
- Verification/Stop：上游 success、sideflow child 和父 invocation 关联可重放；replay 不创建第二 child；rejected/pending problem gate 不启动；主线调用栈无 provider/model wait。

### Task 3：让正式假说输入消费 accepted sideflow 快照（DEV 已完成）

- Owner/Boundary：`research_project_hypothesis_context.py`、accepted package loader/authority、formal fan-out task context；不复制 child receipt 到父 run，不新建 revision store。
- Dependency：T1；可在 T2 编码稳定后串行落地。
- Mode：`BDD_TDD`。
- 产出：2.1 parent receipt 与 3.0 accepted invocation 统一生成 composite `knowledgeSnapshot`；candidate task 私有冻结 binding；所有假说角色仍通过现有统一检索读取 applied Team Knowledge。
- Verification/Stop：readiness ready 必须与 hypothesisInput ready 一致；hash/lineage 不一致 fail closed；多 package 稳定合并而非最新覆盖；未接受 item 不可见。

### Task 4：修订消费与主线容量隔离（DEV 已完成）

- Owner/Boundary：`knowledge_sideflow_service/event_publish_worker` 的 post-absorption hook、`hypothesis_first_chain`/formal revision owner、outbox leasing filter 与相关 projection；不改变当前 Turn。
- Dependency：T2、T3。
- Mode：`BDD_TDD` + `PROFILE`。
- 产出：live attempt 时记录 `revision_available`，在安全边界消费一次；foreground-first leasing、background cap、状态投影和 runtime scene。
- Verification/Stop：相同 snapshot 只触发一次 revision；100 条 sideflow backlog 下 foreground 首轮可租；相同负载 after 达成 §7.2；若收益不超过噪声或需要通用 priority schema，保留最小正确性部分并重新评审性能设计。

### Task 5：DEV 灰度、完整验收与启用决策（确定性 DEV 已完成；真实启用未授权）

- Owner/Boundary：测试、隔离 DEV config、Challenge Cup flow projection；不修改真实 operator config、不跑 G1，除非届时另获授权。
- Dependency：T0–T4 全绿。
- Mode：`SIMPLE`（执行验收）。
- 产出：shadow 对照、on 模式 deterministic end-to-end、节点 5 applied item 可检索、节点 6 accepted package、下一轮假说成功消费新 snapshot、回滚演练说明。
- Verification/Stop：任何知识写入、ACL、hash、主线性能或 pinned definition 不一致均阻止启用；DEV 通过只代表代码/确定性运行闭合，不代表真实 provider/G1。

## 12. 实际影响文件

实现全程位于任务 worktree，并以新鲜 preflight 与精确 claim 约束实际 owner。下表记录最终实现面；没有修改 operator config、Launcher、真实运行数据、公共 task DTO 或 Agent 写权限。

| 责任面 | 实际文件 | 目的 |
| --- | --- | --- |
| Agent 请求入口 | `tools/research_knowledge_request_tools.py` | 3.0 request/status 改接 CommandService |
| Command/trigger | 新 `research_runtime/knowledge_sideflow_trigger.py`、`graph_dispatch_worker.py`、`runtime_factory.py` | 复用既有 CommandService；node1 post-commit kickoff 不等待下游 |
| accepted package authority | `human_acceptance_artifact.py`、新 `knowledge_snapshot_consumption.py` | 通过 invocation、父 event、canonical ref 与 hash 加载和消费 child package |
| hypothesis context | `research_project_hypothesis_context.py`、`formal_hypothesis_fanout.py` | composite snapshot、candidate 私有冻结 binding、consumed hash |
| task binding | `research_project_agent_tasks.py` | 私有冻结 snapshot binding 持久化，不扩公开 DTO |
| readiness/revision | `readiness/common.py`、`readiness/knowledge_recheck.py`、`real_domain_ports.py`、`real_readiness_context.py` | readiness 与实际已吸收 package 对齐；live Turn 只发 revision event |
| scheduling | `ledger/outbox.py`、`ledger/repository.py`、`graph_dispatch_worker.py`、`adapter_dispatch_worker.py` | foreground-first、background cap 与完整事件事实读取 |
| tests | `test_knowledge_sideflow_run.py`、`test_knowledge_readiness_gate.py`、`test_research_workflow_formal_hypothesis_fanout.py`、`test_research_project_agent_tasks.py`、`test_research_knowledge_request_tool.py`、`test_research_workflow_outbox_leasing.py` | 锁定入口、身份/hash、冻结快照、revision、长事件窗口和容量隔离 |

## 13. 验证矩阵

### 13.1 聚焦测试

- `tests/test_research_knowledge_request_tool.py`
- `tests/test_knowledge_command_capability.py`
- `tests/test_knowledge_command_routes.py`
- `tests/test_knowledge_sideflow_run.py`
- `tests/test_knowledge_cross_run_events.py`
- `tests/test_knowledge_readiness_gate.py`
- `tests/test_research_workflow_formal_hypothesis_fanout.py`
- `tests/test_research_workflow_hypothesis_first_chain.py`
- `tests/test_research_workflow_outbox_leasing.py`
- `tests/test_challenge_cup_role_capabilities.py`

### 13.2 必须覆盖的场景

1. 3.0 node1 approved → ensure 一次 → child nodes 2–6 → node5 applied item → node6 accepted → event absorption → hypothesis input ready。
2. node1 replay、tool replay、event replay、revision replay均不重复创建 child/package/revision。
3. 两个不同补证 package 稳定合并；第二个不能覆盖第一个的 allowed refs。
4. package accepted 但 canonical ref/hash 不一致时 readiness/context 均 fail closed。
5. sideflow 在 hypothesis Turn 运行中完成：当前 task context 不变，下一轮 snapshot 更新。
6. candidate Agent 能检索 applied item，但 preview/unaccepted item 不能进入正式 refs。
7. sideflow 失败不终止探索性候选链；正式 grounded fan-in 继续 blocked，并显示 recovery action。
8. foreground + sideflow backlog：主线 action 优先且 background live 数不越界。
9. 2.1 pinned run 行为不变；3.0 unknown hash 不回退。

### 13.3 完成证据分层

- **代码/合同层：** diff 自审、聚焦 pytest、selector closeout。
- **确定性运行层：** isolated DEV config + deterministic provider，全链 artifact/event/item/snapshot 可回读。
- **性能层：** 同机同负载 before/after p50/p95 与确定性调度断言。
- **Launcher 层：** 只有用户授权启用本机 operator config 后才执行 restart/health/runtime scene 验收。
- **真实研究层：** provider 回执、模型成本、G1 质量和正式知识内容另行授权；不得用 DEV fixture 代替。

## 14. Challenge Cup 投影状态

本轮没有新增公开 DTO 或前端写入面；candidate 的冻结 snapshot binding 明确保留为服务端私有字段。方案中原计划引用的 `挑战杯/research_team_flow_design.html` 不存在于当前 Git checkout，因此没有伪造或补建第二份流程站点；真实实例启用时，应在该站点的实际 owner/生成源可用后同步下表。当前权威实现与验收链接记录在本方案 §0、§12、§13：

| Source or fact | Backend source | API DTO | Teams UI | Generated flow site | Project memory/docs | Validation | Deferred debt |
| --- | --- | --- | --- | --- | --- | --- | --- |
| sideflow invocation/status | Ledger `knowledge_invocations` + child attempts | workflow run projection | 节点/Inspector 状态 | 3.0 并行 sideflow 与 revision boundary | 本方案状态/实现链接 | command/projection tests | 真实 G1 |
| applied knowledge snapshot | accepted package refs + Team Knowledge | `hypothesisInput.knowledgeSnapshot` | candidate evidence context | 节点 5→6→7 证据流 | 实施 closeout | fanout/context tests | 大规模 top-k 调优 |
| revision available/consumed | hypothesis task/round projection | hypothesis-first state DTO | 评审/修订状态 | 安全边界说明 | 实施 closeout | revision replay tests | 自动策略优化 |

## 15. 实施者停止条件

出现以下任一情况必须停止受影响写入并回到方案审查：

- accepted sideflow package 无法在不复制/伪造父 receipt 的前提下建立可验证 lineage；
- 需要给假说 Agent 增加正式知识写权限才能推进；
- 需要修改既有 2.1.0 run 的 pinned definition 或数据；
- 性能隔离需要改变全局 LLM/Session 容量且与其他 active claim 重叠；
- 引入新 queue/store/schema 只是为了绕过现有 invocation/outbox/task projection；
- 同一知识快照无法做到事件重放与 revision 幂等；
- operator config、Launcher、G1 或真实知识写入缺少用户授权。

下一步建议：完成本分支的受管 closeout；如需进入真实验收，再单独授权 operator config、Launcher 与 G1/provider/真实知识库写入。
