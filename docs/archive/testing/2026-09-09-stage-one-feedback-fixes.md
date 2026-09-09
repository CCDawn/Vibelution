# 第一阶段纠错反馈修复

范围：修复 `2026-09-09-stage-one-error-feedback-audit.md` 的 F1–F5。基线 `28ff5cba8`。首轮派遣两个叶子 Agent；F1/F2 在一次收窄后未产出补丁，由主 Agent 接管，F5 由另一叶子 Agent 完成。主 Agent 负责 F1–F4、独立验收与统一集成。不修改活数据、不触发模型，不引入第二阶段模板或更改模型分级。

## 复用与实现

- F1：候选指纹叠加 taskId 和本轮 agentGraph 的稳定摘要；不同修订从基础候选新建图，保留旧图审计记录，相同修订重放仍复用。
- F2：物化结果传递逐项 missingLinks 和实际 waiverCount；关系闭环与入库共享缺口统计，未豁免缺口参与完成门、状态、blockedCount 和重试指引。来源排除计数仅在寻找/提取阶段允许构成有效产物。
- F3：复用现有 `_RERUN_BLOCKER_TARGET_NODES` 和下游命令准入。将当前协议以分号序列化的 blocker codes 规范化为精确集合，按既有上游依赖顺序选择修复节点；不增加第二套错误字段，不改变预算/权限准入。
- F4：共享 `evidence_graph_gap_counts`，只统计当前 missingLinks 上的逐条豁免标记；不以汇总 waiverCount 代替实际条目。入库门判断剩余未豁免数，不能因一条豁免放行整个图。
- F5：修订提示词与两个输出验证器统一允许显式空 unresolvedIssues；保留字段/类型、真实修订和非空 changes 要求。

## 验证记录

- F3 回归先失败：多阻塞 detail 导致恢复目标 None。
- F3/F4 定向组合（新 recovery 测试 + 原 missing-link waiver 测试）26 项通过；覆盖错误顺序变化、上游优先、非精确 code 不误匹配、部分豁免、高估的汇总豁免数不能放行、全部实际豁免。
- 原 readiness/provider/command-offer 60 项中 59 项通过。余下一项 `test_fetch_candidate_stats_unlocks_with_tagged_candidates` 在原 main 同样因虚构搜索来源无回执失败，已独立复现为基线 fixture 问题。测试仅验证 candidate scope readback，采用本地已有 `_stub_source_finding_receipt_binding` 隔离搜索提供者边界，单项复验通过；生产搜索回执门未改动。
- 原有“2 缺口、1 豁免也就绪”的测试更新为全部缺口有豁免才就绪；部分豁免由新增反例验证。

## 交付边界

最终需主 Agent 独立审查合并 diff、联合验证三条修复面并通过 managed closeout。真实前端模型闭环须在更新运行版本后单独验收，代码测试不构成高质量假说产出的证明。本次未操作活数据或启动真实模型。

## 独立验收结果

- 主 Agent 联合运行修订契约、恢复入口、图纠正、逐项豁免和来源就绪测试：57 项通过。覆盖真实存储写回的错误→修订→缺口消失→相同修订重放，以及无悬空边但仍有缺口时不能报成功。
- 关系图既有 6 项回归通过。三处旧夹具更新：重放原输出不得冒充修订；坏端点写入真实测试 payload；新写回不再要求复用未绑定修订的旧图。
- F5 子 Agent 验证 11 项新契约和 136 项相关既有测试通过；主 Agent 已独立审查三处生产 diff，并重新运行新契约测试。
- 完整 selector 与集成结果以 managed closeout 的绑定 manifest 为准。
