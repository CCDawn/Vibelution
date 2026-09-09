# 第一阶段纠错反馈复评

日期：2026-09-09。代码基线：bdd4edbdd66871425f78020e91bcfe1fc7a23b13。

## 结论

上一轮 F1–F5 修复改善了不同修订的图隔离、部分豁免、多阻塞恢复与空 unresolvedIssues 契约，但不能据此宣称稳定闭环。新增复查发现两处确定性漏项，均在关系图物化层，不应归因模型能力。此次只读审查生产代码，在临时目录/内存复现，没有调用模型、改变活数据、重启服务或操作前端任务。

## R1 / P1：Agent 显式报告的缺口被物化丢弃

位置：core/web/services/team_workflow/source_collection/writeback_materialize.py:2492、2552–2575。

输入提取器支持 candidateGraph.missingLinks 和根级图的 missingLinks；但 merger 只复制旧图 missingLinks，并添加无法绑定端点的边，没有消费 agent_graph.missingLinks。复现：基础图 a/b 两节点，Agent 写回合法 a→b supports，同时声明 gap-real（缺少独立复现）；调用生产 merger 后 edgeCount=1、missingLinkCount=0、missingLinks=[]。原始 writeback 可保留字段，但最终图不含该缺口；新增共享计数器无法统计已被上游丢弃的信息。

影响：诚实的研究缺口可能从最终图及其就绪统计消失。不能把这类情况解释为模型没有报告风险；这也是之前“只保留真实未修缺口”的验收不足。

修复方向：复用现有 graph missing-link 协议，明确接入本次声明的真实缺口，并与非法端点缺口按稳定身份合并；不要导入 Agent 自报的人工豁免权限。验证应穿过实际写回→存储→统计→闭环门，而不止单测计数器。

## R2 / P2：相同错误写回不幂等，缺口重复累积

位置：同文件:2492、2514–2553；knowledge.py:1879–1894。

修订摘要使相同 taskId/agentGraph 重放复用同一张图；物化随后仍对已合并图运行 merger。seen_edges 只由有效 edges 建立，未包含已经记录的 missingLinks，因此同一非法端点边再次 append。

使用既有来源测试 fixture、TemporaryDirectory 和生产 _materialize_source_collection_stage_writeback_candidate_graph 连续调用两次，结果：sameGraph=True、firstMissing=1、secondMissing=2、reused=True。所有写入只在临时存储。内存 merger 同样复现 1→2。

影响：自动对账或相同工具写回重放会增加相同错误数量；重复缺口会改变展示与逐条豁免工作量。这不是模型生成了新的问题。上一轮回归只验证了成功修订重放，未覆盖失败修订重放。

修复方向：让既有缺口参与稳定身份去重，或使相同修订物化复用已完成的结果；保留不同修订重建和历史审计。验收至少包括相同错误重放数不变、纠正后归零、不同真实缺口不会被误去重。

## 尚需核实的质量门

局部 closure 在两节点、零关系、零缺口且 checklist 完成时返回 candidate_graph_ready / succeeded；readiness evaluator 也没有独立检查 edge_count。此结果只证明这两层不要求有效关系，其他 artifact/coverage 校验尚未贯通复现，不能据此声称整个链路已被绕过。需要明确“真实没有可建立关系”和“未做关系分析”的产物差异，再决定门槛，不能盲目强制每图有边。

## 前端与整体评价

当前 main 的 bdd4edbdd 已为知识子节点检查器加入 412 错误原因显示和重试/清除入口；代码及其测试覆盖了阻塞文本可见性。这改善操作反馈，但重试同一拒绝命令不等于已解决上游原因。本轮没有进行浏览器现场验收。

运行权威已通过 agent_log_context 重新解析，active instance 为 bcabd5ca；没有把 checkout 数据或旧日志中的状态当成当前完整验收结果。另有交接相关修复 claim 活跃，不能抢写其 command_service 或假定其已合入。

阶段判定：恢复入口和诚实修订表达已有进展；关系缺口保存、失败重放仍不可靠；前端从纠错到知识交接再到高质量假说结果包，仍缺当前版本的完整现场证据。优先修复 R1/R2 并补真实物化回归，再进行一次完整前端验收。
