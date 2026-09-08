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

## 现场成本补核与第二轮主审

- 2026-09-08 再次通过 `agent_log_context` 确认 active instance 为 `bcabd5ca`。只读查询该实例 `workspace/usage/usage_ledger.sqlite3` 的 `usage_events`，按明确 session ID、`provider_usage/chat_session` 聚合；未混入其他题目。
- 初次 `session-20260908-124218-168766`：18 次模型调用，累计输入 661,266、输出 20,526、cached input 299,670、单次最大输入 77,067；模型调用延迟合计 316,055 ms。
- 重试 `session-20260908-125613-559737`：12 次模型调用，累计输入 641,520、输出 30,506、cached input 214,011、单次最大输入 93,930；模型调用延迟合计 434,313 ms。两次均为 `qwen3.8-flash`。延迟合计不等于完整业务墙钟时间，token 数不等于已结算人民币费用。
- 重试 Journal 中两条 `source_collection_context_tool` 的完整 toolCall JSON 分别约 119,886 / 166,561 字符（包含工具参数与回包）；已将原始文件的只读定位交给检索 Agent，要求拆分 result 字段并重放测量，不能把此长度直接当作模型 token 数。原始 Prompt/回包不复制进仓库。
- 主审退回的新增问题：回执数不超过 4 时原样返回仍允许单条超大上下文；两个冲突 DOI 都曾出现在当前 run 的回执集合时，集合包含判断仍不能证明同源。已要求统一有界投影，以及“两个 DOI 都有真实回执但同一候选混用”的拒绝测试。
- 带 session 的日志上下文扩展扫描长时间无输出，已终止本任务这次只读扫描进程，改用已确认 active path 下的精确 Journal 和用量账本；未停止产品进程。

## 检索分支接管与输入体积验收

- 检索 Agent 交回现场测量后仍有未提交改动、旧 fixture 和未闭合的预算摘要。主 Agent 接管其文件，移除残余未使用的兼容分支，统一单条/多条回执投影，展示最新回执及完整数量摘要；独立通过 23 项查询种子/上下文测试后提交并组合进集成分支。
- 找到预算丢失的真实落点：`stage_reconcile._source_collection_context_task_summary` 丢弃 task 的批次账本，后续 compact helper 无数据可用；minimal 模式又省略 task 卡。修复从冻结 searchEnvelope 与真实批次派生预算摘要，在 compact/minimal/retry_missing 三种模式统一保留；不保存第二份预算权威。
- 原写回工具仅回传计数，来源 ID 与完整失败原因在裁剪中丢失。现在复用物化 lineage 与本批 fingerprint，只返回本批 record/candidate ID、各自写入状态、真实 receipt gate 和剩余预算；完成时不再邀请继续搜索。相关工具/摘要/JSON 测试 20 项通过，原批次/失败诊断/检索记忆/写回合同回归另 28 项通过。
- 主 Agent 只读重放 SCI-011 重试 Journal 第 10 / 66 行的 result；用同一 UTF-8 JSON 紧凑序列化和项目 `estimate_tokens_precise` 比较，不复制原文到仓库。第 10 行 compact：47,810 → 28,697 字符，估算 14,940 → 9,170 tokens。第 66 行 minimal：66,150 → 15,837 字符，估算 20,078 → 4,774 tokens。均可 JSON round-trip；保留全回执数量、当前可见回执 scope/locator，以及从当前任务快照派生的预算。此测量并未修改历史 task，也不证明重试继承后的新预算已在活数据执行。
- Journal 同时保存 toolCall.summary/result 的重复文本属于存储事实；本轮没有据此声称模型一定重复读取两份，也未修改普通 Session。
- 再查 SCI-011 父/知识子运行的冻结路由：搜索为 Flash，提炼/整合/修订为 Plus，评估为 Max；实际两个 finding session 的用量回执均为 Flash。未运行的后续节点只证明冻结配置。
- 前端首版已交回选择入口及单一 canonical action 校验；主 Agent 核查后端 pending 前置条件明确要求正式候选少于两个，不能凭推测删除 phase fence。外层 Inspector 路由、会议刷新与第一阶段进度正在补充限定验收。
- 来源排除的独立缺陷已确认：DataRecord 按既有 exclusion store 过滤，但 `_source_collection_candidates_for_run` 和 finding canonical candidate reader 未使用该决定。主 Agent已在 CandidateStore owner 新增同一主题/身份的活跃过滤，并接入下游候选消费；历史 authority list 保持原始记录。隔离测试中错误 DOI 排除后正确 DOI 仍可用、旧候选与纠正证据仍保留、其他主题不受影响、仅缺回执不被自动排除；2 项新测试与 3 项原排除/质量回归通过。待来源 Agent 交付后串行接入 finding receipt reader；活数据仍未处理。

## 持久化中断与第三轮主审

- 主 Agent 独立注入五个持久化边界：DataRecord 写入前失败、写入后响应丢失、candidate 导入前失败、导入后响应丢失、最终 task 保存失败。使用隔离实际文件存储，固定搜索投影，不调用模型。相同批次恢复并再次重放后均为一条 DataRecord、一条候选、一批预算；保存的 lineage 可对上候选 ID。5 项通过，因此不新建事务框架。此证据仅覆盖同一批次重放，不宣称跨多个 JSON 文件原子提交，也不等于 SCI-011 活数据已恢复。
- 来源分组主审再次定位到旧平铺回执的 union fallback：一个不含 DOI 的 A URL 与另一个 B DOI 可混为同一候选，并因只有一个 DOI 通过。已要求删除该兼容推断；没有逐 result 映射的旧回执只能用 locator 自身可规范化的同一身份，不能猜测 A URL 与 B DOI 同源。
- 前端主审发现无 canonical action 时隐藏全部正式候选会丢失已选定后的只读回看能力。已要求复用原列表的 committed/locked projection；缺动作禁止提交，正式候选仍可查看，只有 R0/无正式候选进入等待态。

## 组合验收与主 Agent 接管收尾

- 来源 Agent 交付 `7233b979c` 后停止写入。主 Agent 独立复现并修复两个遗漏：record projection 将原 URL 移至 rawLocation，导致预校验忽略它；同 query/provider 聚合新旧事件时，有新分组便漏掉旧单 locator 回执。现在预校验保留原输入 locator，旧 locator 分别保留独立组，仍禁止跨结果拼接 URL/DOI。两项先 RED 后 GREEN。
- finding canonical reader 已接入同一 exclusion store 的活跃候选过滤；真实 DataRecord 导入→明确排除→canonical batch 读回测试先 RED 后 GREEN，历史候选与纠正证据仍保留。
- 来源/排除/紧凑回包/中断恢复组合 44 项通过。更深的 source cases 发现读取 stage card 时，`stage_reconcile` 重新用通用记录计数晋升 completed，忽略 receiptGate；已复用写回的真实 postcheck 与同一 closure helper 修正，相关 writeback/finding 30 项通过。
- 并发导入测试旧 fixture 创建无 owner research project 的 processing run，被现行合同正确拒绝；测试改用已有 owned-run helper，不修改生产权限或兼容入口，5 项通过。
- 前端 Agent 的两个已提交选择修复和外层 Inspector 两文件由主 Agent接管集成。正式候选无操作权限时复用原列表只读查看并隐藏提交；候选尚未生成时明确等待问题理解/知识搜集。未选题的假说入口显示研究文案，不显示实验运行配置；原独立实验入口保留自身语义，未改变预算或 API。
- 主 Agent独立前端相关回归 151 项通过，选择面板/来源展开与 VUI route/design 另 34 项通过。测试中部分既有 telemetry 请求 localhost:3000 被拒绝，但无测试失败；这些不是浏览器真实验收证据。现有 chain 保留 4 秒有界轮询、250 ms SSE invalidation、team/question/run 缓存身份与 reconnect/focus 刷新，无依据新增第二套轮询。
- 检索上下文 Agent 接到新的独立只读验收：核对当前 12 节点主流程是否确实在第一阶段终止。`projection_builder` 当前按整份 pinned definition 计数；必须先查清真实执行与终止合同，不能只改 UI 分母掩盖阶段边界缺口。本项尚待结论。
- 集成树用正常 `npm ci` 安装测试依赖，没有新建 junction。前端子树已有 node_modules junction 属任务残留，最终清理只处理其链接。
