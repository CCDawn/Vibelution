# 挑战杯第一阶段修复执行记录

日期：2026-09-08。状态：开发中；尚未完成真实前端恢复或新题验收。

依据：[修复方案](../plans/2026-09/2026-09-08-challenge-cup-stage-one-repair-plan.md)、[SCI-011 原始验收](2026-09-08-challenge-cup-stage-one-sci011-frontend-acceptance.md)。用户已授权子 Agent 并行开发，由主 Agent 派单、独立验收与本地集成。

## 责任与验收

| 责任 | 独占范围 | 验收 |
| --- | --- | --- |
| 来源写回 Agent | 批次预校验、来源身份、物化一致性 | 非法批次无副作用、重放与故障恢复、真实回执 |
| 检索上下文 Agent | 查询种子、任务上下文、工具紧凑回包 | URI 隔离、有效 JSON、保留来源与预算事实 |
| 前端 Agent | 选择入口、等待依赖、事件刷新、阶段进度 | canonical action、R0 不可冒充正式候选、VUI、类型检查 |
| 主 Agent | 问题范围与生成讨论、交接/评审/结果核验、组合验收 | 独立检查实际 diff 与测试；通过后才运行前端验收 |

## 问题与裁决

1. **选择问题需细分**：`hypothesis_first_state_v2.py` 将 R0 exploratory drafts 与正式 R1 candidates 分开。问题理解/知识未齐时进入 `formal_runtime` 是现有正确行为。前端提前返回确实会遮住合法选择动作，但不能由“已有四条 R0 草案”推导出现在应能选择。修复必须保留 canonical `record_selection` 权限。
2. **生成范围未传递，已确认**：`build_stage_one_grounded_generation_context` 仅返回已交接知识输入；`hypothesis_first_chain.open_candidate_generation_meeting` 只传证据摘要和 R0 草案；`meeting_runtime._generation_opening_topic` 只有目录题目/领域，没有当前 canonical 问题理解及其版本。因此正式生成仍可能沿用与当前范围冲突的草案。复用现有 Ledger attempt 和 canonical artifact reader 绑定范围，不新造范围仓库。
3. **知识交接已存在**：保留既有 `absorb_knowledge_result` 和 operator policy 下的自动接受，不增加强制人工按钮。仍需验证当前 invocation/hash 与父运行推进。
4. **写回已有预算自动收口**：修次序与一致性，不叠加另一套自动收口。`completionGate.passed` 旧投影不等于完整真实回执通过。
5. **运行验收保持未完成**：SCI-011 的两次原始失败、旧错误 DOI 与新增正确候选均保留事实；本轮尚未写活数据，未启动新付费运行。
6. **知识重投漏推进，已复现**：`event_publish_worker._handle` 只在 `absorbed` 时调用 readiness recheck。模拟接收提交后、recheck/ACK 前中断，事件重投返回 `already_absorbed`，父节点没有任何 attempt。修复将两种接收结果都送入现有幂等 recheck；不改写 checkpoint、不新增重试框架。
7. **预算诊断在阶段投影丢失，已复现**：Session `turn_failed` 提供 `problemCode/message`，但 `stage_reconcile` 只读取 summary/content/error/reason，丢掉结构化原因；随后任务重试无法可靠命中既有 fresh-session 分支。修复保留 journal/snapshot 的预算代码与错误摘要到 task failureCode/failureMessage，不修改普通 Session，不靠增大模型窗口处理。
8. **来源写回首稿被主审退回**：独立检查 worker 未提交 diff 时发现 compact receipt stub、legacy sourceRecords/records、needs_review 状态可绕过本批校验。已要求移除生产测试专用/兼容绕过，修测试 fixture 而非降低真实门；任何新增 lead 都先验证，无论状态或字段别名。此首稿未验收、未合入。
9. **新重试任务重置批次预算，已确认**：`stage_session` 创建任务时没有继承 `sourceCollectionWritebackBatches`，而接受上限只读当前 task 的该字段。现已沿 `retrySourceTaskId` 继承去重后的真实批次，并保持原 `searchEnvelope`；同 task 的 fresh session 保留预算。无关任务不参与，断裂血缘不能重置额度。

## 验证与剩余工作

- 初始 main 干净，四个任务 worktree 均从已落盘方案创建；无关 Companion/Operator/Pet 任务不在本次修改范围。
- 本地复用：优先 `load_canonical_problem_understanding_payload`、现有生成协议与质量 rubric；不新增依赖或通用防御框架。
- 范围传递：5 个聚焦测试通过，覆盖当前 attempt、拒绝旧成功 fallback、pending 状态保真、scope/hash 进入讨论以及 chain→meeting 传递。既有任务上下文和筛选恢复回归通过。
- 交接恢复：新增故障边界测试在修复前失败（父 `hypothesis_design` attempt 为 None）；修复后与现有 readiness/cross-run 共 13 项通过，无重复父事件/dispatch。
- 预算诊断：新增 journal→task→fresh retry 行为在修复前缺少 failureCode，修复后与既有 replay 共 14 项通过；保留已接收来源，不把旧 writeback 覆盖成虚构成功。
- 主线独立回归：假说状态/链路、知识子运行与交接回执共 343 项通过；阶段一合同、质量、结果包及第二阶段边界共 106 项通过。此处不等价于真实模型输出质量与前端闭环验收。
- 重试预算：继承/去重/断链/额度耗尽与问题上下文、子运行血缘共 12 项通过；实际 source collection task/session/retry 行为另 39 项通过。
- 当前浏览器只读复核：活跃实例仍为 `bcabd5ca`，SCI-011 仍显示旧运行待处理。新代码尚未刷新到运行实例，本轮没有点击“继续运行”或启动新题。
- 待记录：各 Agent 的实际变更、主 Agent 独立测试、组合合同、Launcher 刷新、SCI-011 恢复与新题全前端验收。
- 已知环境问题：此前 fetch 遇到无效 Agent checkpoint ref；不删除未知归属 ref，本轮未请求远端 push。
