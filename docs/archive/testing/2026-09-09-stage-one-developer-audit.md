# 挑战杯第一阶段全链路审查与开发交接报告

日期：2026-09-09。审查对象：第一阶段假说产生、资料搜集、评审修订及结果包链路。

## 1. 给接手开发 Agent 的结论

**尚不能判定为稳定、高质量的前端闭环。**上一轮修复已经解决部分错误恢复入口与完成判定问题，但仍有信息丢失、重放重复、修订内容质量退化、最终版本选择和前端作用域问题。

本报告是独立交接文件，可以直接交给开发 Agent，不需要先阅读聊天记录。包含 **6 项可定位的问题**：3 项通过生产函数局部复现，1 项通过生产物化函数及临时存储复现，2 项通过前后端调用链确认。未做本轮真实浏览器验收；这些证据不能替代一次完整现场闭环。

本轮只新增本报告，未修改产品代码、Operator 配置、模型绑定、活数据或运行中的任务，未调用付费模型。历史五项修复已合入；不要撤销逐项豁免门、真实来源回执门、模型分级，或引入第二阶段实验模板。

审查开始基线：a5f3f77d8032d0c6648ab2f1e82ea08010889a7f。报告工作区基线：c2a33ca259411d380d309a53f0f320eee2937fa1。后者新增自动交接对账恢复，已查看其变更说明；没有把已合入的旧故障重新列为未修问题。正文行号以本次快照为准，接手时以函数名定位并核实最新 main。

## 2. 证据等级与范围

- **存储复现**：生产物化函数，项目已有测试 fixture + TemporaryDirectory；仅临时数据。
- **局部复现**：生产函数，手工构造输入或替换只读来源；证明函数行为，不声称完整 UI 已触发。
- **调用链确认**：输入、调用参数和消费端逻辑形成直接因果链；需开发补组件/集成回归。
- **待核实**：存在局部现象，但尚未证明当前入口可达或违反产品约定，不可直接据此开发。

| 阶段 | 当前判断 | 本轮检查重点与限制 |
| --- | --- | --- |
| 题目、运行与执行者绑定 | 方向合理 | README 与 real_domain_ports 按冻结运行、节点和任务祖先解析；未重查全部活 Agent 配置，不宣称当前模型档位已验收 |
| 搜索与补源 | 既有约束应保留 | 复用前次审查的检索边界与回执结论；本轮未触发新搜索、不可达来源或真实超时 |
| 原文提炼与证据卡 | 不应放宽 | 证据 read-back、来源 scope、合法引用清单存在；完整原文质量与搜索召回率未现场测量 |
| 关系图写回 | 不可靠 | A01 缺口丢失、A02 错误重放累积；之前不同修订重建图仍应保留 |
| 入库与交接 | 有严格门，但上游输入可失真 | 缺口计数器只能统计图里已有的缺口；A01 会使严格门失去输入；自动交接补丁见 W04 |
| 假说评审 | 有独立评分与回执检查 | FORMAL 验证 provider receipt、步骤数量、候选 ID 和引用；未证明所有语义质量约束都能落实 |
| 假说修订 | 内容门不足 | A03 允许清空预测、证伪和引用后宣告实际修订；R1 质量检查不能自动代表 R2 |
| 研究计划与最终假说 | 版本一致性不足 | A04 结果包不消费 FORMAL R2，且可混用评审正文和候选库的预测/证伪；计划旧详情优先见 W03 |
| 结果包与反馈迭代 | 部分合同需进一步贯通 | canonical/hash/人工审核边界存在；多轮合同差异见 W01，不把死代码现象当线上故障 |
| 前端纠错与豁免 | 有恢复入口，但不全可靠 | A05 团队最新图与所选子运行不一致；A06 重试固定旧 offer |
| 预算、取消、对账 | 已有近期修复 | 保留 outbox、预算及执行者准入；本轮未注入进程故障或并发竞速，不对这些情况签发通过结论 |

## 3. 可修复问题

### A01 / P1：显式证据缺口被关系图物化丢弃

**证据：局部复现；对应前份复评 R1。**

位置：`core/web/services/team_workflow/source_collection/writeback_materialize.py`，`_source_collection_stage_writeback_agent_graph_payload`（2331 附近）、`_merge_source_collection_stage_writeback_agent_graph`（2481–2583）。

输入提取器支持 `candidateGraph.missingLinks`，也支持根级图的 `missingLinks`。但 merger 只从基础图复制 missingLinks，并添加端点解析失败的关系；没有消费本次 Agent 显式声明的 missingLinks。

复现输入：基础图含 a/b 两节点，Agent 输出合法 a→b supports，同时声明 `gap-real: missing independent replication`。生产 merger 输出 `edgeCount=1, missingLinkCount=0, missingLinks=[]`。

影响：Agent 已诚实报告问题，物化却丢掉问题。原始写回里保留字段，不代表最终证据图和入库门能看到它。修正共享计数器不足以解决此问题。

最小修复：明确并复用一种规范化缺口身份，消费本次缺口，保留真实未解决项；不要继续维护互不相通的根级/图内语义，也不要把 Agent 自报 waiver 当成人工授权。缺口不是必须拥有两个端点的错误边，接入前需检查前端/豁免协议能否表达研究性缺口。

验收：真实写回→存储→read-back→关系 closure→入库 readiness 全链都能看见该缺口；合法边存在不抵消真实缺口；修订解决后消失；错误端点与研究缺口并存；伪造 waived 字段不能获得人工豁免。

### A02 / P2：相同错误写回重放会重复累计缺口

**证据：生产物化 + 临时存储复现；对应前份复评 R2。**

位置：同文件 `_merge_source_collection_stage_writeback_agent_graph` 的 `seen_edges`（2514 附近）和 `missing_links.append(edge)`（2553 附近）；`knowledge.py::build_candidate_graph`（1879 附近）。

修订摘要让相同 taskId/agentGraph 复用同一张图。但复用图已经含第一次错误，物化仍再次 merge。seen_edges 仅来自有效 edges，未包括已有缺口，导致同一非法端点再次 append。

真实物化复现：`sameGraph=True, firstMissing=1, secondMissing=2, reused=True`。不是模型多产生了一条关系。重复对账或相同工具写回即可扩大错误集合。

最小修复：缺口按稳定身份去重，或相同修订直接复用已完成物化结果；沿用当前图存储，保留不同修订隔离，不使用每次 forceRebuild 规避幂等。检查更新 updatedAt/元数据是否还会让同一内容的审计或 canonical 回执漂移。

验收：连续三次同一错误写回仍为一条；不同错误不误去重；修正后的新修订不继承旧错误；成功和失败修订重放都幂等。上一轮测试只测了成功重放，这是明确的覆盖遗漏。

### A03 / P1：修订可以清空科学要素，仍被认定为实际完成

**证据：生产 `_revision_step` 局部复现。**

位置：`hypothesis_review_executor.py::_revision_step`（1120–1199）、`canonical_hypothesis_revision_snapshot`（276–318）；`llm_review_runners.py::revision_runner`（2308–2380）。

触发：父候选已有预测、证伪条件及引用，模型返回不同 claim，但显式写 `testablePrediction=""`, `falsifier=""`, `axisProfile={}`, `lineageRefs=[]`，changes 非空、unresolvedIssues 为空且附合规回执。

当前结果：接受并返回 `revision.actual=True`，R2 快照中这些字段为空。runner 对 lineageRefs 检查“不能超白名单”，空列表会通过；执行器复制显式空值，快照只强制 candidateId/claim。提示词要求保留完善科学要素，服务端合同并未实现该要求。

影响：合法 JSON、真实模型回执和不同正文，只能证明发生过调用及文本变化，不能证明形成了合格修订。质量退化可能延迟到结果包暴露，或被 A04 的旧值掩盖。

最小修复：复用现有候选内容与 coherence 校验，明确哪些科学字段在该阶段必填、哪些允许缺失；显式空值违反必填契约时直接返回具体反馈。不要静默用旧值覆盖模型空值以制造成功。语义正确性需要对 R2 的质量检查，不能沿用 R1 分数冒充 R2 分数；是否增加模型调用须先核实既有预算和可复用评审步骤。

验收：空/错误类型字段被准确拒绝并返回字段路径；合法修订通过；缺省可选字段与显式删除必填字段区别明确；保持非空 changes、允许空 unresolvedIssues、真实 provider receipt 与引用白名单。

### A04 / P1：最终假说未绑定单一修订版本，可能遗漏 R2 或拼接新旧字段

**证据：结果包投影局部复现 + 调用链确认；必须按路径限定影响。**

位置：`result_package_v2.py::_hypotheses_from_accepted_round`（601–719）、`_hypotheses`（722–776）、`build_challenge_result_package_v2`（1321 附近）；`hypothesis_review_executor.py::execute_hypothesis_review`（1470–1520）；`hypothesis_rounds.py` 保存 candidates/revisionEnvelope（887–918）。

FORMAL executor 刻意保持 reviewed_candidates 为 R1，把实际 R2 单独保存进 revisionEnvelope。结果包缺少 candidateDetails 时，从 round.candidates 取 claim、从候选库取 falsifier/prediction/axis；不读取 revisionEnvelope 中的 R2。

局部复现：同一个 round 中 candidates 含 `R1 old a`，revisionEnvelope 有 `R2 new a`，调用生产 `_hypotheses`，输出 statement 仍为 `R1 old a`。另一方面，即使 chain 路径中 round 的 claim 已更新，预测/证伪仍取按 candidateId 匹配的候选库值，缺少同版本 hash 的约束。

范围限制：这不是“所有前端路径一定丢 R2”的结论。chain-driven 和 FORMAL executor 是不同入口；问题明确适用于上述 fallback 投影，不影响有完整 canonical candidateDetails 的其他分支。

最小修复：选择并贯通唯一最终候选版本，正文、预测、证伪、机制、引用应来自同一份可追溯内容；让研究计划、selection 和结果包绑定该版本。保留历史 R1 评分，不直接把 R1 评分标记为 R2 已评审。不要再靠跨版本补字段满足 schema。

验收：R0→R1→R2 的 claim、prediction、falsifier 和引用故意设为不同值；验证结果包、研究计划、前端详情读的是同一目标版本；历史 R1 可查看且不被覆盖；版本/hash 不匹配应在交接处阻塞，而不是最后导出才失败。

### A05 / P1：前端豁免区读取团队最新图，而不是当前子运行的图

**证据：调用链确认，尚未进行双运行浏览器复现。**

位置：`web/src/routes/teams/research-workflow/KnowledgeChildNodeInspector.tsx::KnowledgeChildReadPanel`（105–133）、`MissingLinkWaiverSection.tsx::submitWaiver`；`teamRouteShellModel.ts::latestWorkflowCandidate`。

候选图 queryKey 仅有 teamId；请求只过滤 candidateType，取团队最近 20 条，然后选 latest。props.runId 只影响 enabled 和豁免提交目标，没有参与图查询/缓存身份。旁边 EvidenceGraphView 却按当前 runId 读取。

触发：同一团队有 A/B 两个资料搜集运行，B 的图更新较晚，用户查看 A 子运行。图展示与豁免清单可能来自不同运行；清单取 B，提交却发给 A。服务端重新按 A 限定作用域会拒绝无匹配缺口，但不能纠正用户已看到的错误清单；相同语义端点是否可能匹配 A 是待测项，不宣称已跨运行写入成功。

最小修复：复用 run-scoped 图投影/冻结 sourceCollectionRunId；图展示与豁免清单共享同一份权威结果，queryKey 含运行身份。不要依赖“团队最新图恰好等于这个子运行图”的假设，也不要增加后端宽松查找兜底。

验收：A/B 同团队、不同缺口，B 更新时间更新；打开 A 只能看到/操作 A；切换运行不泄漏旧缓存；错误或不可读图不展示另一运行的图；豁免后刷新对应图、readiness 和 offer。

### A06 / P2：错误区的重试固定旧 CommandOffer，可能持续版本冲突

**证据：调用链确认，需补组件与服务集成回归。**

位置：`KnowledgeChildNodeInspector.tsx`（35、39–46、59–65）；`useResearchWorkflowCommand.ts::submit`；`web/src/api/research-workflow/commands.ts::submitResearchWorkflowCommandOffer`；`command_service.py` 的 expected_run_version 比较。

错误区保存 lastOffer，重试直接 submit(lastOffer)。finally 虽刷新 run/detail，但不会更新保存的 offer。传输层原样提交 offer.expectedRunVersion、idempotencyKey 和 payload；后端仍严格检查版本。

触发：第一次请求因旧 runVersion 被拒绝，或第一次失败后修复上游使 runVersion 前进；新 offers 已加载，错误区重试却仍发送旧版本，因此可连续冲突。正常节点按钮可收到新 offer，不等于这个错误区重试已修复。

最小修复：刷新后按 command/node/业务身份从最新 offers 中重新解析动作；不存在或变为 unavailable 时展示新原因。对于结果未知的网络失败，先保留原幂等语义查明结果，不能无条件换新 key 重复执行；也不能只手改 expectedRunVersion 绕过服务端 offer。

验收：vN 拒绝→刷新 vN+1→错误区重试使用合法新 offer；动作撤销时不重发；已受理但响应丢失时不创建重复 attempt；切换节点/运行后不保留可执行的旧目标。

## 4. 待核实项：不得直接当成开发任务

### W01：反馈轮数合同差异，当前不可判定为线上阻断

`feedback_iterations_artifact_writer.validate_feedback_iteration` 能接受第 3 轮 review_revision；`result_package_v2._same_run_hypothesis_feedback_iterations` 只接受恰好 2 份且 phase 为 grounded_revision/review_revision。局部实验：1 份拒绝、2 份通过、3 份拒绝。

进一步检索发现，支持任意多轮的 `_materialize_review_feedback_iterations_authority` 在 core/tests 中只有定义、没有调用；正式两阶段 writer 恰好产出 1/2。**因此撤回“已证明当前线上多轮必卡”的推断。**

升级条件：从真实入口证明可以合法产生 3 份 schemaVersion=2 同运行反馈，再进入结果包失败。否则记录为死代码/合同整理项，不改生产门、不无条件增加兼容分支。

### W02：零边关系图的完成语义

局部 closure 接受有 graphId、零边、零缺口、checklist 完成；readiness 只检查节点和未豁免缺口。上游仍可能有 coverage/evidenceRefs 门，未贯通验证整个零边图能完成正式节点。

升级条件：构造已覆盖多个候选、没有做关系分析的写回，证明能通过正式 adapter.verify；必须区分真实“不存在可建立关系”和“没执行分析”，不能简单强制所有图至少一条边。

### W03：研究计划优先使用题目级旧 approved detail

`hypothesis_first_chain.py::_materialize_stage_one_plan_authority` 首先取 `question_launch._approved_details(team_id)[questionId]`，存在时不调用绑定 workflow_run_id 的 live projection。函数本身未核实旧详情是否匹配当前 run/selection。

升级条件：同一题目两个运行，旧 approved detail 与当前 selectedCandidateId 不同，证明下游 writer 未阻断并写入旧计划；应先检查 writer 的引用与选择校验。未复现前不改此路径。

### W04：自动交接修复是否只恢复旧状态，未覆盖新成功路径

c2a33ca25 已为 reconcile 增加 orphaned ready auto-gate handoff 的接受动作，应认可该修复。其提交说明表明故障原本来自回执成功路径未走 graph worker 的 finalize。

验收应证明新节点从该成功入口完成后无需人工反复对账，或证明已有自动对账会可靠触发。不能仅以“手动对账能接受 handoff”宣称自动推进闭合。未现场重跑，不另报已确定的新 P1。

### W05：R2 的语义质量与接受口径

“不同 claim”不等于“实质解决反馈”。当前 coherence/评分针对哪一版本，是否允许修改后的候选未经复验直接继续，需结合 A03/A04 对照。同样，unresolvedIssues=[] 只是模型声明，不是独立验证结果。

关闭条件：最后版本绑定质量回执，预测由机制推出、falsifier 能推翻机制、边界一致、引用可读；若保留未解决项，结果包必须准确标明限制。不得把研究计划假说写成已经实验验证的结论。

## 5. 给开发 Agent 的修复分工与顺序

以下是建议任务边界，不是本轮已派遣的新 Agent。

1. **关系图负责人：A01+A02。** owning files 为 source_collection/writeback_materialize.py、必要的 knowledge.py/knowledge_kernel.py 和相关回归。先确定缺口身份，再接入显式缺口和重放去重；不得新建图存储或通用防御框架。
2. **修订与结果负责人：A03+A04。** owning files 为 hypothesis_review_executor.py、llm_review_runners.py、result_package_v2.py 及必要的现有 artifact writer/chain 投影。先明确最终版本合同，再修字段校验和计划/结果消费；保留历史版本与分数归属。
3. **前端负责人：A05+A06。** owning files 为 KnowledgeChildNodeInspector.tsx、其现有 hook/model/测试；复用 VUI 和 run-scoped 读取。此负责人独占该组件，不能让两人同时写它。

关系图和修订版本两条可独立推进。前端 A06 可先做，A05 的缺口展示契约需与 A01 协商。单个共享事实源只能一个 writer。开始前重新查 main、active claim 和当前 diff，防止接手与其他开发任务重叠。

本地高 ROI 复用点：现有候选图 builder/merger、evidence_graph_gap_counts、scoped artifact loader、candidate coherence 校验、revision snapshot/hash、VUI 错误区和服务端 CommandOffer。已定位的缺陷不需要引入外部框架；若确需新增依赖/重构，再做外部方案对照。实现文件按仓库规则记录 LOCAL_ONLY 复用证据。

## 6. 验收要求

### 自动化验收

- A01/A02 必须覆盖实际物化和 read-back，不能只检查 summary 字段或 mock 一个 ready 图。
- A03/A04 使用新旧内容故意不一致的 fixture，验证输出内容和版本，而非仅 assert artifact 存在或 hash 非空。
- A05 使用同团队双运行，A06 使用版本变化和丢失响应两类测试。
- 主 Agent 独立检查 diff，重跑必要测试；最后跑项目 selector/managed closeout。前端修改需类型构建与 VUI 合同；不要在每项小修后重复全量回归。
- W01–W04 先补可达性/端到端证据，不为假设编写生产兜底。

### 一次完整前端验收

1. 确认 Launcher 当前运行版本和 active instance；若已有其他 Agent 正在操作同一 run，使用独立题目/运行并明确归属。
2. 从前端发起新假说路径，记录父/子 run、sourceCollectionRunId、节点 attempt、任务/Turn 与实际模型回执。
3. 完成搜索、可读原文、证据卡、关系图、知识包交接；每一步核对写回事实与 UI 状态一致。
4. 用隔离测试输入验证真实缺口可见、同一错误重放不增加数量、正确修订能清除旧错误。不得向正式研究结果注入假数据。
5. 完成评审与修订，逐字段核对最终正文、预测、证伪、边界、引用，以及计划和结果包是否绑定同一最终版本。
6. 记录实际耗时、模型调用次数、付费重试次数和人工介入次数；没有可比较的真实数据，不编造效率评分。
7. 最终证明仅靠前端即可完成所需交接和导出；若需数据库改状态或人工改 canonical 文件，判验收失败并落盘原因。

完成口径：测试通过、模型调用结束、节点 succeeded、结果包可下载都只是分层证据；高质量第一阶段交付还需证据可追溯、科学要素完整、反馈已处理或诚实保留、最终版本一致。

## 7. 复现方法与原始短结果

均在本轮审查执行，未调用真实模型。

- A01：生产 merger，base.nodes=[a,b]，agentGraph.edges=[a→b supports]，agentGraph.missingLinks=[gap-real]。输出：`edgeCount=1, missingLinkCount=0, missingLinks=[]`。
- A02：用 `tests._support.team_workflow.cases_source_collection` 的 `_use_tmp_project_root`、`_use_fake_local_research_config`、`_create_owned_source_collection_processing_run` 建临时运行；register_candidate_source 创建 A；对同 taskId 连续两次 `_materialize_source_collection_stage_writeback_candidate_graph`，边为 A→missing-endpoint。输出：`sameGraph=True, firstMissing=1, secondMissing=2, reused=True`。
- A03：复用 `tests.test_stage_one_resolved_feedback_contract._revision_receipt` 的测试回执，调用 `_revision_step`；新 claim + 空预测/证伪/axis/引用 + changes=['revised'] + unresolvedIssues=[]。输出 `actual=True`，R2 科学字段为空。此合成回执仅测试验证器分支，不是真实模型证据。
- A04：MonkeyPatch 仅替换 `hypothesis_rounds.get_hypothesis_round` 和 `hypothesis_first_chain.list_hypothesis_candidates` 只读来源；round.candidates 为 R1、同 round.revisionEnvelope 为 R2，调用 `_hypotheses` 的无 candidateDetails 路径。输出 `package_statement='R1 old a'`。
- W01：用 `validate_feedback_iteration` 构造 1/2/3 份 payload，再调用 `_same_run_hypothesis_feedback_iterations`；结果拒绝/接受/拒绝。因未证明当前多轮入口可达，不列为已确认故障。

接手者可复用以下现有测试入口，新增针对上述因果关系的反例：

- tests/test_stage_one_graph_correction_feedback.py
- tests/test_stage_one_feedback_recovery.py
- tests/test_evidence_graph_missing_link_waiver.py
- tests/test_stage_one_resolved_feedback_contract.py
- tests/_support/team_workflow/cases_source_collection.py
- web/src/routes/teams/research-workflow/KnowledgeChildNodeInspector.test.tsx

## 8. 历史材料与使用边界

- `2026-09-09-stage-one-error-feedback-audit.md`：前次 F1–F5 原始诊断；不可把已修项再次列为新增开发任务。
- `2026-09-09-stage-one-feedback-fixes.md`：前次实现与验证范围。
- `2026-09-09-stage-one-feedback-reevaluation.md`：A01/A02 的前次复评。
- `2026-09-08-stage-one-frontend-runtime-acceptance.md`：另一个 Agent 的历史现场记录，仍可能继续更新；不能替代当前版本现场证据。

本报告是一次代码快照下的开发交接，不替代 docs/standards 或冻结运行合同。未证明的风险保持待核实，不以猜测扩大改造范围。
