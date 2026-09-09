# 第一阶段纠错反馈机制审查

审查日期：2026-09-09。代码基线：`2075ef49ccdedbf78633e3a801805ee808ed57de`。只读审查产品代码和既有运行证据；只新增本报告，不修改产品或活数据、不触发模型、暂停或重试。

## 结论

局部有可信的错误检测和定向重试，但整体还不是稳定的纠错闭环。核心缺陷是修正没有可靠替换旧错误、各层成功口径不同，以及恢复入口依赖拼接文本。不能以增加模型能力或提示词长度代替工程修复。

审查沿“发现错误 → 返回具体原因 → 选择恢复节点 → 提供当前输入 → 提交修正 → 清除旧错误 → 重验并关闭”检查。代码结构检查不等于真实模型闭环通过；终端知识包与结果包仍须独立前端验收。本次未审核第二阶段模板或实验。

## 各环节评价

| 环节 | 已有机制和证据 | 判断与缺口 |
| --- | --- | --- |
| 候选生成、问题理解 | 正式 run 绑定、当前草稿隔离、失败讨论的 supersede/reopen；只允许最新有效讨论推进 | 恢复机制存在；未在本审查触发新的生成，不能宣称每类生成错误均有有效模型自修 |
| 搜索与补源 | source_repair_message 使用最新提炼任务缺口及真实 failed fetch；限定原题和冻结检索范围；要求可访问替代来源并排除失效定位符；prior query memory 有界保留既往失败搜索 | 方向合理，明显优于原样重搜；外部不可达应保留阻塞，不能当作模型不合规 |
| 原文提炼 | 写回使用生产 evidence-card builder 提前校验字段和来源锚；quote 不符有定向纠正；retry_missing/retry_evidence 给具体 ID、保留已就绪证据；合规写回清除旧 quoteAnchorRemediation | 局部闭环较完整；上下文超限换会话和回执续写已有修复，仍需实机连续验收 |
| 证据关系 | 允许端点闭集、确定性语义解析、evidenceRefs 清单、非法端点降为 missingLinks | 存在本报告 F1/F2：正确新边不能消除历史错误，完成反馈遗漏旧缺口，是当前最严重断点 |
| 知识入库、交接 | readiness 图检查、人工入库边界、canonical/hash/真实结果权威；下游缺口映射到上游重跑 | F3 多阻塞丢恢复入口；F4 豁免判断放行未豁免缺口；不得把人工接受等同于补齐证据 |
| 假说评审、修订 | revision runner 接收父候选、整个候选集及 meta-review；校验候选身份、真实内容变化、模型回执、父子 refs/hash；保留 changes/unresolvedIssues | 可追溯性较强；没有“改了即质量提高”的证据。F5 强制未解决问题非空不适合表达问题全部解决 |
| 收敛与结果包 | 硬轮数上限、搜集自动恢复次数限制；明确记录带缺口收敛；结果包交接验证 canonical 身份并拒绝 blocked/failed 来源 | 有停止边界，但带缺口收敛不是完整高质量验收。未运行终端验收，不为其签发通过结论 |
| 跨层故障与 UI | runVersion/幂等键、预算补充入口、陈旧阻塞消解、父子 run 对账、僵尸 attempt 修复 | 基础设施恢复逐步完善；“重新执行”仍不能保证错误输入、历史图和反馈已更新。最新对账代码需现场复验 |

## 已确认问题

### F1 / P1：重写正确关系仍保留历史错误

- `knowledge.py:1823` 的 build_candidate_graph 按输入候选指纹复用旧图；`source_collection/writeback_materialize.py:1548` 的正式写回未要求重建。
- `writeback_materialize.py:2468` 从旧图复制 missingLinks；合并正确新边不会撤销旧的错误关系。
- 既有 SCI-009 两次 relations 任务 `stagetask-20260908223931-c1aa1991` 和 `stagetask-20260908230830-853f9771` 都指向 `candidate-graph-20260908224138-afcc83a4`。两份保存的 result 中未发现错误 ID `candidate-20260908171904-9143d4d6`，错误 ID 存在于物化图的 missingLinks。
- 独立最小复现：旧图含 a→不存在端点；新输出为合法 a→b，调用生产 merger，返回 `edgeCount=1, missingLinkCount=1, danglingEdgeCount=0`，旧缺口保持原样。
- 因此不能把该现场重试无效直接归因为模型反复生成错误。错误第一次出现的完整工具调用不在本次取证范围，最初来源尚不下结论。
- 最小修复方向：明确同一关系阶段的修订替换/撤销语义；从当前合法输入和此次修订生成本次图，旧版本保留审计但不能继续决定新版本缺口。不能无差别删除仍然真实存在的证据缺口。
- 验收：错误→正确重写后旧错误不再阻塞；真实未修缺口仍在；重复写回幂等；旧正式回执保持可追溯。

### F2 / P1：关系阶段成功口径与下游不同

- `writeback_materialize.py:1347` 以本轮 danglingEdgeCount 而非全部未解决缺口判关系完整。
- 同两次任务均为 `missingLinkCount=1`，但 closure 为 `advanceOutcome=succeeded, artifactStatus=candidate_graph_ready, blockedCount=0, completionGatePassed=true`。
- 模型看到成功反馈，无法得知仍须修正哪条旧关系；下游 knowledge_ingestion 又被 evidence_graph_incomplete 拦截。
- 最小修复方向：写回反馈与下游复用同一份图就绪判断，返回具体未解决端点和来源；有阻断缺口就不能发全成功反馈。
- 验收：同一份图的写回、节点状态、UI 和入库门禁结论一致，纠正后这些层一起解除。

### F3 / P1：多个阻塞原因使上游纠错入口消失

- `command_service.py:808` 把多个 blocker code 用 `; ` 拼成 detail；`command_offers/retry_node.py:succeeded_node_rerun_target` 对整段 detail 做字典精确匹配。
- 独立复现：`evidence_graph_incomplete` 返回 evidence_relations；`evidence_graph_incomplete; budget_safety_limit_reached` 返回 None；`source_candidates_missing; source_scope_missing` 同样返回 None。
- 最小修复方向：按结构化 blocker 集合匹配恢复责任节点，显式处理恢复顺序和前置条件；不依赖展示文本，也不允许绕过预算准入。
- 验收：单阻塞、多阻塞及原因顺序变化均保留正确、受门禁约束的恢复入口。

### F4 / P1：一条豁免放行整个缺口集合

- 新豁免入口逐条登记；`research_runtime/readiness/knowledge.py:44` 却只判断 `missing_links > 0 and waivers <= 0`。
- 独立调用现有测试辅助器与生产 evaluator：2 个缺口、1 个豁免，得到 blockers=[]。
- 最小修复方向：只按真实匹配且具有适用授权的豁免逐条消解；剩余缺口仍阻塞。人工接受只表明接受风险，不能被当作证据补齐；错误 ID 可修时应优先修正。
- 验收：部分豁免不放行其他缺口；图更新后旧豁免不能套用到不同缺口。

### F5 / P2：提示词和验证器强制“仍有未解决问题”

- `llm_review_runners.py:1892` 要求 changes 和 unresolvedIssues 都不能为空；`hypothesis_review_executor.py:1164` 使用同一非空列表校验；feedback_iterations_artifact_writer 亦要求非空。
- 独立复现 `_required_text_list([], field='unresolvedIssues')` 抛出 `formal revision unresolvedIssues must contain explicit evidence`。
- 当此次具体反馈已全部解决时，诚实的空列表不能被接受，只能追加未解决项或形式占位。科研普遍存在限制，不等于每次纠错必须凭空新增未解决任务。
- 最小调整建议：保留字段且允许空列表；把研究固有限制与待修问题分开表达，并由后续评审验证解决情况。非空 changes 和真实修订证据仍应保留。

## 提示词与纠错输入

现有提示词有真实证据、闭集 ID、明确工具和非编造约束，不建议改成更长的通用提醒。优先让已有上下文/写回工具提供可执行差量：错误项、当前合法值、旧版本身份、修改或撤销范围、成功条件。搜索、提炼已部分具备；关系阶段尤其缺少可靠的旧错误清除语义和一致反馈。

现有硬轮数/重试深度限制负责止损，不等于每次重试都改变了失败条件。应先修本报告确定性重复错误，不另建通用重试框架。对缺资料、输出不合规、工具/执行错误和账本状态漂移分别使用现有的补源、原任务修订、基础设施恢复和对账路径。

## 验证边界与顺序

本次最小复现均在内存运行，没有调用模型或修改产品存储；成功证明 F1/F3/F4/F5 的对应分支行为。F2 由真实任务回执与代码共同确认。未运行全量测试，也未执行新的前端流程。报告仅审查，截至该代码快照不代表后续并发任务的最终状态。

建议顺序：F1/F2 一起修正并复验 → F3 恢复入口 → F4 豁免逐条性 → F5 提示词/输出契约校准 → 用前端完成错误→修正→交接→最终结果包的一条完整链。先做定向测试，最后集中真实模型验收，避免无改变量的重复付费运行。
