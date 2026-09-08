# 挑战杯第一阶段 SCI-026 前端验收

日期：2026-09-08。负责人：主 Agent。状态：修复已合入并 push，已刷新程序，由前端启动 SCI-026，运行验收进行中。

## 验收契约

- 新题候选：SCI-026，Why can only some cells become other cells?；前端题目列表显示“生物学 · 尚未开始”。尚未点击启动，无本轮新题模型调用。
- 所有业务变更由已登录前端操作，后台只读核对当前实例、冻结定义、Ledger、产物与调用回执。
- 新运行应固定 `challenge-cup-research@3.1.0-stage-one`，主图为问题理解 → 假说形成 → 结果包；知识搜集使用原独立五节点子流程。
- 按功能使用 Flash / Plus / Max；第一阶段不要求实验模板、GPU 或实验 STOP。真实来源、评审和人工批准条件必须保留。
- 代码测试通过、运行闭环、假说科研质量分别记录。同一根因再次失败即停止付费重试。
- SCI-011 保留其旧冻结定义、失败与来源审计，不能由新图自动改为成功。

## 合入验证中的问题

1. 完整验证曾因另一个桌宠任务更新本地 main 而失效。已同步其提交，通过项目一次性预约机制重试；未修改或回滚其他任务。
2. 预约重试在 `test_v2_scope_lock_serializes_cross_process_claim_and_side_effect` 失败：两个子进程未在 10 秒内完成导入并到达启动屏障，尚未执行受测的副作用。未修改锁逻辑、断言或放宽门槛。原测试单独运行通过（1 passed，8.04 秒），随后同一 HEAD 完整 selector 全部通过；本次属于启动超时偶发失败，无证据表明锁行为回归。
3. 文档预检参数误用了不支持的 `docs`，已改用 `mechanical` 并对当前文档 worktree 通过预检；没有产生主目录写入。

## 待执行与证据边界

- 主要修复已合入、push 和刷新；本次验收中新发现的显示小修待独立合入。
- SCI-026 已由前端启动，继续核验知识交接、正式候选、评审和结果包。
- 实际冻结模型、预算、来源回执、评审、人工动作、终态及失败现场需以新运行记录补齐。
- 本文档自身不要求产品刷新；源代码需要 Launcher 刷新后才能进行有效运行验收。

## 实际执行轨迹

- 完整验证返回 `merged_clean`，代码合入 `803c99cba0cf06263bfd142a21e373bf9b17df4a`；普通 push 成功，远端 main 从 `a4c7eba34` 更新到该提交。
- 通过规定的 Launcher `restart` 刷新，重新发现桌面调试目标并确认 active instance 仍为 `bcabd5ca`。前端 reload 后标题由“选择题目并开始实验”变为“选择题目并开始假说研究”；SCI-026 仍显示尚未开始。
- 17:55 左右点击“开始假说研究”，URL 进入 `questionId=SCI-026&node=hf_generation&panel=node`。记录后续状态前不把加载期“待同步/已阻塞”当作最终失败。
- 已清理本轮三个已合入子 Agent worktree 和本地分支；前端树依赖 junction 仅删除链接，主目录共享依赖保留。
- 在候选生成节点点击“创建第一阶段运行”，创建 `run-d8fded98c181`；页面自动带入 runId，显示主流程 `0/3`。只读当前实例 Ledger 确认 `workflow_version_id=wv-26ff976466f4`、`structure_hash=26ff976466f4ff355b975869a46cd5566a58bd2529f4cd424ba1b5ab577f819e`，当前节点 `problem_understanding`，状态 running。
- 新运行 frozen policy 确认：检索 Flash，提炼/整合/修订/执行 Plus，关键评估 Max；policy hash 为 `541f7973ec80920dbf8d02ad56cd7a75396d5280ff619f342c9ce04e7790745a`。预算快照为 tokens 2,000,000、toolCalls 600、wallClockSeconds 14,400、maxRetries 3、maxParallelTasks 3；这是配置上限，不是实际消费。
- 候选讨论 `hf-candgen-5c7ba096a38dcbe4-r0` 的前端发言计数无需整页刷新由 `0/4` 更新到 `2/4`。

## 新发现的显示问题

- P2：新图主进度已为 `0/3`，但左侧仍把假说形成与结果核验标为“实验设计 / 执行迭代”。冻结定义中的阶段 label 已调整，页面可能仍按 stageId 使用固定文案；真实 Ledger 与画布节点确认为新三节点图。这是待修的显示问题，不能描述为已完全消除第二阶段混淆。
- P2：探索纪要确认前提示“确认后候选会进入假说选择”，实际确认后跳到缺知识包而阻塞的假说设计；手动打开选择卡也无表单。最初将其判断为选择修复失败，追溯当前题目的权威记录后更正：18 条全部为 `hypothesis_exploratory_draft`，正式候选为零。当前门槛要求先问题理解和知识交接，再形成有依据的正式候选，故阻止选择正确；真正问题是前端下一步承诺与真实前置步骤不一致。未删除 phase fence，也未将探索草案伪装为正式候选。
- 问题理解已成功，主流程到 `1/3`；于假说设计详情点击“发起知识搜集”。该动作只通过前端完成，未点击无效的“重试假设设计”。
- 知识来源运行 `dprun-20260908101213756078-3e9f641a`，finding task `stagetask-20260908101223-89ab02fb`。冻结搜集上限为 8 条来源、4 个写回批次、每批 4 条，实际四视角查询未混入 URI。检索中观察到 `paper_search_tool` 30 秒超时，后续仍有 provider 返回回执；尚不能判定整个阶段失败。

## 显示问题的有界修正

- 复用现有 `researchStageLabel` 与图适配层已经传入的 frozen stage.label；固定 stageId 文案此前优先级更高，覆盖了新图的“假说形成 / 结果核验”。现在优先采用冻结名称，既有资料搜集规范术语不变。
- 纪要确认说明改为“确认后，证据不足的草案先补充知识；正式候选再进入假说选择。”不改变选择权限或来源门槛。
- 此次只改既有显示模型，不增加组件、布局或设计系统；预览豁免理由是已确定的现有文案与定义名称修正。本地复用证据记为 LOCAL_ONLY，不需要仓外依赖。
- 首次窄测试揭示“知识搜集→资料搜集”的既有术语映射应保留；修正后 presentation/graph/context 共 30 项通过，TypeScript build 通过。

## 资料寻找实际通过

- 18:26:03 finding 写回成功，随后页面自动显示知识子流程 `1/5`，资料提炼进入 running；没有发起额外整轮 retry。
- 权威 receipt gate：candidateCount=8，counterEvidenceCandidateCount=4，perspectiveCount=4，queryCount=13，missingPerspectives/missingPrimarySources/missingTerminalTraces/unboundCandidateIds 均为空。两个成功批次各接受 4 条，未超出冻结 8 条上限。
- 两次中途写回因 DOI/PMC/PubMed 定位不在真实回执中被拒绝；最后使用实际返回的 Nature/MDPI URL 后通过。拒绝动作没有被伪装为成功。
- 新 finding session `session-20260908-181227-876119` 的 provider_usage：19 次 Flash 调用，输入 627,350、输出 23,223、cached input 307,840、最大单次输入 48,993、模型延迟合计 405,754 ms。搜集业务约 14 分钟；模型延迟合计不等于业务墙钟，token 不等于人民币结算。不同题目不能据此直接声称整体效率改善比例。
- 提炼 task `stagetask-20260908102644-c779f2c3` / session `session-20260908-182652-629884`，读取 candidateCount=8、recordCount=8。
- P2 统计残留：finding task 顶层 candidateCount/recordCount 仍为 0，但其 receipt gate 为 8 条、下游提炼实际读取 8 条；需统一旧任务卡统计投影。不可用 run 目录的空 candidates.jsonl 来否定 canonical candidate store 的真实结果。
