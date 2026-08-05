# Vibelution Agent Kernel MVP Test Strategy

日期：2026-06-19
状态：重构前测试治理契约草案
归属分线：quality-and-operations / agent-runtime-core
范围：测试策略文档，不包含测试代码或运行时代码改动

## 1. 目的

VAKP / Agent Kernel MVP 重构不能以“旧测试全绿”作为唯一正确性标准。

旧测试里有三类东西混在一起：

- 真正的用户行为契约；
- 必须保留的数据和 API 兼容性；
- 旧实现细节、旧字段、旧服务调用顺序、旧 UI 私有状态。

如果全部旧测试都作为阻塞条件，新内核会被旧结构锁死。如果直接忽略旧测试，又会丢失真实兼容风险。

因此本文定义一套重构期测试治理规则：

```text
新内核行为契约优先。
旧测试逐条分类处理。
全绿不是正确性的充分条件。
红灯必须解释，不允许无分类跳过。
```

## 2. 已确认原则

本策略基于以下已确认原则：

1. 新 Kernel MVP 的最高事实源是用户确认的行为契约和内核不变量，不是旧测试本身。
2. 旧测试不能默认阻塞重构，必须先判断它保护的是行为、兼容性还是旧实现细节。
3. 允许建立 `legacy test quarantine` 清单。
4. 每个被隔离的旧测试必须标注分类、原因、替代 contract test、退出条件。
5. 旧测试失败不能被静默忽略；要么修，要么迁移，要么隔离并登记理由。

## 3. 完成标准

Kernel MVP 重构阶段的完成标准不是“全量旧测试全绿”。

建议完成标准：

```text
新 kernel contract tests 通过
+ 必要 compatibility tests 通过
+ 旧测试失败已分类、说明原因、给出迁移动作
+ 没有未解释红灯
```

换言之：

- 全绿但缺少新 contract tests，不算正确。
- 有红灯但已分类、替代测试存在、迁移路径明确，可以继续推进。
- 有未解释红灯，不允许合并为稳定版本。

## 4. 测试分级

### 4.1 `contract`

含义：保护新内核行为契约。

优先级：最高。

是否阻塞：阻塞。

应该覆盖：

- `Event -> Task -> Execution -> Outcome` 最小闭环；
- idempotency；
- terminal outcome；
- Agent inbox read / ack；
- missing recipient；
- proposal non-blocking；
- Session / Room 只作为 projection；
- TaskLedger 和 WorkRun 的事实源边界。

示例：

```text
Given an Agent message event with idempotencyKey X
When the kernel handles it twice
Then only one task is created
And the second handling reuses the existing task
```

### 4.2 `compatibility`

含义：保护必须兼容的旧数据、旧 API、旧入口。

优先级：高。

是否阻塞：通常阻塞，除非有明确迁移窗口。

应该覆盖：

- 旧 session / room / agent 数据可读取；
- 旧 Agent bindings 可迁移或 repair；
- 旧 API 在兼容期仍返回必要字段；
- 用户已有会话不会因新 kernel store 失效。

注意：

compatibility 不是保留旧实现。它只保护用户数据和外部契约。

### 4.3 `implementation-lock`

含义：锁死旧实现细节的测试。

优先级：低。

是否阻塞：不应默认阻塞。

常见特征：

- 断言旧私有函数调用顺序；
- 断言旧内部 JSON 字段必须继续作为 source of truth；
- 断言旧 UI 私有状态或旧文案结构；
- 断言旧 service 拆分方式；
- 断言旧 mock 调用路径，而不是用户可见行为。

处理方式：

- 如果仍保护真实行为，改写为 contract 或 compatibility test。
- 如果只保护旧实现，删除或进入 quarantine。

### 4.4 `characterization`

含义：临时记录旧系统行为，用来辅助迁移。

优先级：中。

是否阻塞：不作为长期阻塞。

使用场景：

- 当前无法确定旧行为是 bug 还是契约；
- 需要先冻结旧行为样本，辅助写新 contract；
- 迁移期间需要证明新旧输出差异是有意改变。

退出条件：

- 转成 contract test；
- 转成 compatibility test；
- 被明确判定为 implementation-lock 后删除或隔离。

### 4.5 `smoke`

含义：主路径安全网。

优先级：中。

是否阻塞：阻塞主路径严重失败。

应该覆盖：

- Kernel event API 能写入事件；
- Agent inbox 能读到消息；
- 一个最小 task 能进入 terminal outcome；
- 系统不因 kernel store 缺失而崩溃。

smoke 不追求覆盖全部旧细节。

## 5. 红绿灯规则

### 5.1 绿灯

绿灯只有在新契约测试存在时才有意义。

如果只是旧测试绿，而没有覆盖 kernel MVP 行为，不能作为正确性证据。

### 5.2 红灯-阻塞

必须阻塞：

- 用户可见行为破坏；
- 旧数据不可读；
- API 兼容契约破坏；
- 权限、安全、记忆边界破坏；
- TaskLedger / WorkRun / Session / Room 事实源边界破坏；
- kernel contract test 失败。

### 5.3 红灯-可迁移

可以继续推进，但必须登记：

- 失败测试名；
- 失败原因；
- 分类；
- 替代 contract test；
- 后续迁移动作；
- 负责人或 claim。

常见情况：

- 旧测试断言旧字段继续作为 source of truth；
- 旧测试断言旧 route 私有返回 shape；
- 旧测试断言旧 service 内部 repair 顺序；
- 新架构已有更高层 contract 覆盖。

### 5.4 红灯-待判定

不能直接忽略，也不能马上修。

处理：

1. 先读测试名、断言、fixture、对应代码。
2. 判断它保护的是行为、兼容性还是实现细节。
3. 如果仍不清楚，转为 characterization。
4. 写入 quarantine 候选，不进入稳定合并。

## 6. Legacy Test Quarantine

允许建立 `legacy test quarantine`，但它是受控迁移清单，不是跳过测试的垃圾桶。

### 6.1 进入条件

旧测试可进入 quarantine，必须满足至少一个条件：

- 它锁定旧实现细节，与新内核契约冲突；
- 它保护的行为已被新 contract test 覆盖；
- 它依赖即将删除的旧 source of truth；
- 它当前保护的行为无法判断，需要 characterization；
- 它与用户确认的新行为相冲突。

### 6.2 禁止进入条件

不得 quarantine：

- 安全测试；
- 权限测试；
- 数据不可丢失测试；
- 旧数据读取兼容测试；
- Kernel contract tests；
- 用户明确依赖的行为测试；
- runtime evidence 和错误可诊断性测试。

### 6.3 Quarantine 记录格式

每个条目必须包含：

```text
test_id:
file:
classification:
current_failure:
protected_behavior:
why_not_blocking:
replacement_test:
exit_condition:
owner_or_claim:
target_phase:
created_at:
```

建议存储位置：

```text
docs/testing/agent-kernel-legacy-test-quarantine.md
```

如果实现阶段需要机器可读清单，再增加：

```text
docs/testing/agent-kernel-legacy-test-quarantine.json
```

第一阶段不建议直接改 pytest skip 标记。先建立清单，再决定哪些测试需要代码级 skip/xfail。

## 7. Kernel MVP 必测契约

MVP 最少需要以下 contract tests。

### 7.1 Event idempotency

```text
Given the same EventEnvelope idempotencyKey
When the kernel handles it twice
Then only one TaskLedgerEntry is created
And the second result points to the existing task
```

### 7.2 Missing recipient

```text
Given an Agent message event with a missing recipient Agent
When the kernel handles it
Then no execution starts
And task status becomes failed or blocked
And runtime evidence records agent resolve failure
```

### 7.3 Inbox delivery and ack

```text
Given Agent A sends a message to Agent B
When the event is accepted
Then Agent B inbox contains the event
When Agent B acknowledges it
Then the inbox item is marked handled or acknowledged
```

### 7.4 Terminal outcome

```text
Given a running task with a WorkRun
When a terminal outcome is recorded
Then task status becomes terminal
And later attempts cannot move it back to running
```

### 7.5 Proposal non-blocking

```text
Given an outcome that contains a memory proposal
When the outcome is recorded
Then a proposal stub is queued
And the task can still complete
And no memory is directly applied
```

### 7.6 Projection boundary

```text
Given a Session or Room projection update fails
When the TaskLedger has a terminal outcome
Then the task result remains authoritative
And projection repair is recorded separately
```

## 8. 测试迁移流程

每轮实现或重构遇到旧测试失败，按以下流程处理：

```text
1. Identify
   记录失败测试、断言、涉及文件。

2. Classify
   contract / compatibility / implementation-lock / characterization / smoke。

3. Decide
   修复、改写、迁移、隔离、删除。

4. Replace
   如果隔离或删除，必须先有替代 contract/compatibility test，或说明为什么不需要。

5. Record
   写入 final report 或 quarantine 清单。

6. Exit
   合并前不能有未解释红灯。
```

## 9. 实现阶段建议测试顺序

### Phase 1：纯模型和存储

优先测试：

- DTO normalization；
- JSONL append/read；
- index rebuild；
- idempotency lookup；
- invalid event rejection。

不跑全量旧前端测试作为阻塞。

### Phase 2：Agent inbox

优先测试：

- Agent exists；
- missing Agent；
- inbox write/read；
- ack；
- duplicate event；
- no auto wake by default。

旧 ChatRoom / Session 测试只跑相关兼容切片。

### Phase 3：Minimal execution

优先测试：

- fake executor success；
- fake executor failure；
- blocked execution；
- terminal outcome；
- proposal non-blocking。

不在此阶段测试完整 LLM 能力。

### Phase 4：接入真实 Agent runtime

优先测试：

- LLM invocation context 带 agent/task/workRun metadata；
- tool policy denied path；
- runtime scene evidence；
- old session still readable。

此阶段再扩大到相关集成测试。

## 10. 评审视角

### 10.1 核心用户

关注：

- 任务状态可信；
- Agent 消息不会丢；
- 失败原因可见；
- 不会因为旧测试迁移导致用户会话损坏。

### 10.2 维护者

关注：

- 测试保护行为而不是旧结构；
- 失败测试有分类；
- quarantine 有退出条件；
- 新 contract 足够小且稳定。

### 10.3 QA

关注：

- 红灯是否可复现；
- 失败是否能被归类；
- 合并时是否仍有未解释红灯；
- runtime evidence 是否支持诊断。

### 10.4 架构评审

关注：

- TaskLedger / WorkRun / Session / Room 边界是否被测试保护；
- EvaluationGate 是否没有进入 runtime critical path；
- Context 是否没有过早实现成 memory OS。

### 10.5 迁移评审

关注：

- 旧数据读取；
- 旧 API 兼容；
- 新写入不再写旧 source of truth；
- compatibility readers 有退出计划。

## 11. 不允许的测试处理方式

禁止：

- 因为旧测试挡路就直接删除；
- 用宽泛 skip 跳过整类测试；
- 用 mock 改到绿但没有行为契约；
- 把 implementation-lock test 伪装成 compatibility test；
- 合并带有未解释红灯的重构；
- 用“全绿”替代 kernel contract 覆盖；
- 让 EvaluationGate 自动写入长期记忆来满足测试。

## 12. 后续行动

建议后续按这个顺序推进：

1. 新增 Kernel MVP contract test 文件。
2. 建立 quarantine 文档模板。
3. 实现 DTO 和 JSONL store。
4. 用最小 contract tests 驱动第一版 kernel event API。
5. 每轮实现结束时输出失败测试分类报告。

在这套测试治理规则落地前，不建议直接开始大规模替换旧 Session / ChatRoom / Agent runtime 测试。
