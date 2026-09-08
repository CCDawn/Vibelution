# 挑战杯第一阶段完整修复方案

- 日期：2026-09-08。
- 状态：规划完成，待实施；本文不代表业务代码已修复或运行已闭环。
- 目标：用户从前端选择一个新问题，完成候选生成、选择、证据搜集、评审修订和第一阶段结果核验；正常路径连续推进，证据不足时有明确、可操作的恢复路径。
- 本次范围：只读复核与方案落盘。实施、真实模型复验与活数据处理属于后续执行阶段。
- 证据基线：本地 `main` 的 `86c3de6dc`；[SCI-011 实测记录](../../testing/2026-09-08-challenge-cup-stage-one-sci011-frontend-acceptance.md)，正式运行 `run-f8c475d25254`、知识子运行 `run-c8c9acb54fae`。
- 约束：按角色分级模型；第一阶段不要求第二阶段模板、GPU、实验执行和批量提交；不降低回执真实性要求；不创建第二套状态机、候选仓或前端组件体系。

## 1. 先校正问题判断

验收记录是现象记录。以下代码复核对实施决策具有更具体的约束，避免按过强的旧结论修错方向。

| 现象 | 本轮复核 | 修复裁决 |
| --- | --- | --- |
| `hf_selection` 无法操作 | `HypothesisFirstNodeInspector.tsx` 的 `formalRuntime` 提前返回，先于生成与选择节点分支 | 确认的前端入口缺陷；按所选节点路由操作体，保留服务端动作权限 |
| 来源物化完成，但任务失败 | `stage_writeback.py` 已有预算饱和自动收口；物化发生在终态真实回执校验之前 | 不是缺少自动收口；先修写入次序、真实回执和一致的状态投影 |
| `completionGate.passed=true` 却存在 `unboundCandidates` | 当前 completion gate 不等价于完整搜索回执门；`running` 路径与终态路径校验不一致 | 不能凭旧 gate 自动晋升成功；完整 readiness 必须含真实来源绑定 |
| 目录 URI 污染检索 | `residual.py` 把 `input_refs` 转为种子，`_source_collection_seed_from_input_ref` 对未知引用原样返回；`question_launch.py` 正常生成目录引用 | 修搜索种子转换，不删除目录来源血缘 |
| 修正 DOI 后仍卡住 | 新增正确 DOI 候选不会修改旧的错误 DOI 候选；既有角色合同有排除入口 | 不能断言完全没有恢复能力；明确错元数据的纠正/替代语义，避免反复补搜同一错误引用 |
| 第二次尝试又耗尽上下文 | `stage_session_replay.py` 已有预算失败切换新会话逻辑；新会话仍在单轮中膨胀至硬上限 | 不能只加“换新会话重试”；缩小真实输入和工具回包，修补预算失败诊断传递 |
| 知识交接疑似无入口 | `knowledge_sideflow_service.py` 已有 `absorb_knowledge_result`；Inspector 已有 `handoff_collection` mutation 和按钮 | 修状态投影与可达性，先测试现有交接路径，不新造交接流程 |
| source run 下空 JSONL 疑似未物化 | `storage.py` 经 `data_processing_service` 读取；候选权威在项目 candidate store | 空投影/占位文件不能单独判定资料缺失；按当前 run 的权威记录读回 |
| 后续 claim 补证/结果核验疑似缺口 | SCI-011 未走到这些节点，仅有局部静态证据 | 纳入链路验收；先确认现有 command、档案页与回执投影，再补实际缺口 |

优先级按影响安排：数据提交不一致、不可操作入口与重复预算失败必须先修；不把所有局部问题都视为全产品 P0。资料有数量和视角标签，不能称为已通过科学质量审查的合格证据。

## 2. 推荐的第一阶段链路与状态合同

```text
选择问题 → 创建第一阶段运行
  ├─ 问题理解 → 固定问题范围与输入版本
  ├─ 候选草案生成 → 确认纪要 → 选择候选
  └─ 知识搜集：寻找 → 提炼 → 证据关系 → 知识入库 → 知识包交接
       ↓ 当前问题/运行/版本一致的候选与证据汇合
假说评审 → 明确缺口 → 定向补证或候选修订 → 再评审
       ↓ 满足现有第一阶段收敛条件
物化第一阶段结果包 → 前端核验/确认 → 第一阶段完成
```

继续复用假说先行结构，不加生成前预检索子流程。候选草案可以与问题理解、搜集并行；在问题理解完成前产生的草案必须标记待范围核验，并在最终入选/评审前绑定当前范围版本。若问题理解本身声明人工确认必需，则复用现有人工任务决定其生效状态，不能把 `pending` 当已批准。

正式 `hypothesis_design` 的可执行条件是：当前运行所需候选已选定、所需评审已收敛、知识包已形成且必要交接已接受。前置条件未齐时不启动无效模型调用；页面显示等待具体依赖，并能前往该依赖。复用现有 waiting/blocked 表达及原因分类，不为显示文案新增平行状态机，也不把正常等待提示为可通过重跑恢复的故障。

| 事实 | 唯一权威 | 前端/调度消费方式 |
| --- | --- | --- |
| 执行与重试 | Workflow Ledger 的 run、node、attempt | 查询和事件刷新；不得按消息数合成成功 |
| 原始来源与检索身份 | 当前 source run 的 DataRecord、candidate store、真实 search events | 同一身份归一化函数用于注册、去重和回执比较 |
| 阶段写回 | stage task 的已接受批次、已提交结果及完成判断 | 计数、预算、状态使用同一批次事实 |
| 候选与评审 | 当前问题/运行的候选版本、selection、meeting/review 记录 | 后端 canonical action 决定允许操作 |
| 知识交接 | 子运行输出 hash、invocation、父运行吸收记录 | 幂等交接；读页面不等于接受交接 |
| 第一阶段结果 | canonical result package 与对应 artifact/model/review receipts | 展示内容与 hash；程序成功和人工确认分别标明 |
| 第二阶段放行 | 既有 phase boundary 与真实知识发布回执 | 保持锁定，不能由单题第一阶段完成直接解锁 |

## 3. 本地复用裁决

| 能力 | 采用的现有落点 | 不采用的扩张 |
| --- | --- | --- |
| 写回、批次去重、预算自动收口 | `source_collection/stage_writeback.py`、`writeback_materialize.py` | 再建写回引擎或靠异常后自动标成功 |
| 搜索真实性 | `search_execution.py`、`research_runtime/artifact_readback_registry.py` | 信任 Agent 自报 `searchTrace` 或题名相似就视为同源 |
| 来源修订与排除 | `source_collection/candidates.py`、`residual.py` 和现有排除记录 | 任意覆盖历史 DOI、删掉真实反证以绕门 |
| 上下文与恢复 | 现有 compact/retry focus、`stage_session_replay.py`、`core/orchestration/turn_compression.py` | 自建总结器、通用 session 改造或简单提高硬上限 |
| 前端状态 | `useHypothesisFirstChain.ts`、React Query、已有 SSE invalidation、共享 polling policy | 新轮询框架、双份 UI 状态、全页刷新当常态 |
| 人工选择和交接 | `HypothesisFirstNodeInspector.tsx`、`HypothesisSelectionList`、既有 canonical commands | 新 Teams 页面、第二套表单和直接后台 API 绕过 UI |
| 科学质量 | `hypothesis_quality.py`、claim belief、既有评审与候选 revision | 再叠一套打分体系、全部换 Max、每个小缺口都重开会议 |
| 结果与阶段边界 | `result_package_v2.py`、`question_result_package_adapter.py`、既有 challenge phase boundary | 把第二阶段模板引入第一阶段 |

已查本地既有质量效率计划，其状态为 superseded，仅借用证据追溯与角色分级原则，不恢复其中废弃的预热链、额外开关和评审重构。当前根因已有本地 owner 与成熟机制，本方案不新增依赖，因此不以仓外框架扫描替代根因修复；实施前按项目要求为实现改动记录 LOCAL_ONLY 复用证据。只有发现当前存储无法提供必要一致性时，才在该具体边界补充外部方案比较。

## 4. 分步实施

### R1：统一来源身份、写回校验与提交结果

**Owner/文件**：`core/web/services/team_workflow/source_collection/{stage_writeback,writeback_materialize,candidates,search_execution,residual}.py`；必要时 `research_runtime/artifact_readback_registry.py`。单一 writer 持有该共享写入面。

1. 抽出无副作用的批次准备与校验：解析输入、当前来源身份、真实搜索回执、去重、批次预算和预期来源集合；`running` 新增资料也校验其来源绑定，不把错误身份留到终态才发现。
2. 引用绑定使用相同的规范化器。仅接受服务端实际获得的 DOI/URL 映射，支持已验证的出版方展示 URL；拒绝仅靠标题近似或 Agent 自报 DOI 合并。正确 DOI、错误 DOI、带参数展示 URL、同名不同论文分别测试。
3. 先验证本批可写数据再物化；区分“本批写入是否合法”和“整个阶段是否可完成”。合法批次已接受但全局仍缺证据时，持久化批次事实并返回明确的 `needs_review`/缺口，不能事后抛出仿佛没有写入的通用失败。
4. 复用现有锁、原子文件写入、批次 fingerprint；任务批次接收记录作为操作结果权威。注入 DataRecord 成功、candidate 导入失败、task 保存失败等故障，保证可按同一批次恢复且不重计预算。若现有存储无法在本模块闭合，形成精确的持久化缺口再设计最小提交记录，不能宣称跨多个 JSON 文件天然具有事务性。
5. `completionGate` 纳入当前 run 的来源、视角、真实回执、检查清单、物化结果；所有显示成功的字段从这一完整判断派生。视角不足或未绑定来源不能被自动收口提升为成功。
6. 复用排除/修订动作处理错误元数据：保存旧 ID、修订理由、权威证据和新版本/替代关系，旧错误版本退出活跃消费集合。可验证但回执缺失的真实论文进入补证，不为了通过门禁标成无效来源。

**验收**：非法批次零候选/记录副作用；合法增量与未完成全局状态并存时回执准确；相同批次重放不增记录/预算；故障恢复无幽灵候选；错误 DOI 不再要求无限补搜；当前 run 校验不能引用其他 run 的历史回执。回归 `test_source_finding_receipt_gate.py`、`test_source_collection_writeback_json.py` 及 source collection cases，补真实注册→拒绝→读回测试。

### R2：缩短检索与上下文，修复终态和重试

**依赖**：R1 的完整完成判断与批次事实。

**Owner/文件**：`source_collection/{residual,stage_writeback,stage_session,stage_session_replay,stage_reconcile}.py`、`source_collection_context.py`、`source_collection_stage_tasks.py`、`tools/source_collection_stage_tools.py`。通用压缩模块首先只读诊断，只有证明通用预算实现有独立缺陷才另设最小修复面。

1. 搜索种子只来源于问题文本、冻结子问题、明确关键词；目录 URI/hash/path 保留为 lineage，禁止原样拼入自然语言检索。精确 DOI/出版方 URL 的定向核验仍允许。原有冻结计划不就地改写，修复计划产生新版本并记录来源。
2. 搜索任务初始上下文只给一次范围摘要、冻结查询、已有来源 ID/定位符、视角覆盖、缺口和剩余预算。去除同时嵌入的重复 contract、旧写回大数组、重复 canonical 问题正文；全文只在提炼阶段按需读取。
3. 每次工具回包只返回本批接收/拒绝条目、计数增量、剩余预算和下一动作；检索原始结果仍按原策略保存在权威证据存储，不重复回灌已接收资料。compact 必须可解析并保留 ID/回执，不以截断字符串冒充有效 JSON。
4. 复用当前每批 4、最多 4 批、接受上限 8 的冻结合同，明确既有来源复用、新来源与 locator 修订的计费口径；原始尝试与 retry 共用逻辑任务剩余预算，retry 不获得一份全新无限预算。批次上限与检索查询数不同，查询/locator 补验也必须通过现有执行预算限制。
5. 一旦达到任务收集目标且完整门通过，现有服务端收口立即结束该阶段的继续检索调度。达到预算但仍有缺口时记录 `needs_review` 和精确缺口；没有必要为了凑满 8 条继续搜索。
6. 对 SCI-011 的预算前置诊断核对：压缩是否启用、阈值、调用时机和压缩后大小。优先消除重复输入；预算不足以再搜索并完成结构化写回时停止新检索，通过现有 stage reconcile 保留已接收事实和可恢复终态。单轮 runtime 失败与业务阶段完成分开记录，只有完整门已满足且提交可验证时才认定业务完成。
7. retry 先读当前 run 的完整 readiness：完整且已提交则重放收口；缺少明确条目则只补缺口；预算失败复用现有 fresh session，但仅注入紧凑任务快照。保留 `retryOfSessionId`、attempt 与原始失败代码，不把 `context_budget_exhausted` 泛化成只有 `failed_runtime`。

**验收**：目录 URI 不进入查询；retry 不重跑全部冻结查询；零模型收口路径不发起搜索；预算耗尽仍有明确任务终态；新会话不携带前轮工具历史。回归 `test_finding_attempt_query_memory.py`、`test_source_collection_stage_session_replay.py`、`test_source_collection_stage_writeback_prompt_contracts.py` 和问题理解上下文测试。

**测量目标（验收指标，不改科研通过门）**：用 SCI-011 脱敏重放样本记录上下文分块大小；finding 初始工具上下文不超过 12k 估算 tokens、普通批次回包不超过 2k；预算提前量由实际模型硬限减去最大允许回包及终态所需输入确定，不硬编码全模型统一窗口。真实新题 finding 累计输入以低于原始尝试 661,266 的一半为目标；必须报告整阶段累计用量和单次最大输入，不能拿最后一条 93,930 token 回执当重试累计成本。来源质量不足时不为达成本指标假报完成。

### R3：恢复前端选择、等待依赖与实时状态

**依赖**：R1 的状态语义；可先编写选择入口复现测试，再统一接入修复后的状态。

**Owner/文件**：`web/src/routes/teams/research-workflow/{HypothesisFirstNodeInspector.tsx,useHypothesisFirstChain.ts,hypothesisFirstNextAction.ts,hypothesisFirstStateV2Adapter.ts}`；`research_runtime/{hypothesis_first_state_v2,command_service}.py` 与必要的调度条件代码。

1. Inspector 按所选节点区分假说生成、假说选择、知识节点和正式执行动作，移除 `formalRuntime` 对全部节点的覆盖。选择列表使用已有组件和 canonical action；不通过删除后端 scope/版本判断换取按钮可点。
2. “当前任务”与“所选节点”可以不同；已满足前置条件的人工动作仍可操作，未满足时给出具体依赖及跳转。失效候选/重复提交/旧版本 action 由既有版本冲突处理提示刷新。
3. 正式节点依赖未完成时，不执行无效重试或模型调用；候选选择成功、评审完成、知识交接接受这些事件重新计算 readiness，并触发一次幂等推进。
4. 审查 SSE 与 React Query 的 team/question/run key 对应关系、会议终态事件与 invalidation；复用已有 4 秒有界轮询补漏。可见活动页面目标在事件后 5 秒内刷新，断线重连恢复，切换题目不显示旧题内容；不加并行常驻轮询器。
5. 第一阶段进度只统计第一阶段必需节点；若全流程概览保留第二阶段，清楚显示其锁定状态。修复当前 `1/12` 和“实验设计”对第一阶段完成范围造成的歧义。

**验收**：浏览器从生成纪要确认直接进入选择并提交；formal runtime 存在时选择仍可达；无需整页刷新看到 `0/4 → 发言完成 → 待确认`；前置未齐时零无效 dispatch。运行 `HypothesisFirstNodeInspector.test.tsx`、`useHypothesisFirstChain.test.tsx`、next-action/state-adapter 测试与 `test_hypothesis_first_state_v2.py`。可见 UI 使用 VUI，跑 VUI route/design contracts 和 `tsc -b`。

### R4：打通知识交接、补证与评审修订回路

**依赖**：R1、R2、R3。

**Owner/文件**：`research_runtime/{knowledge_sideflow_service,command_service,hypothesis_first_chain,hypothesis_first_state_v2}.py`、`source_collection/stage_reconcile.py`、Inspector 与 `NodeKnowledgeCollectionSection.tsx`、`web/src/api/hypothesisFirst.ts`。

1. 用既有 `handoff_collection` / `resolve_human_task` / `absorb_knowledge_result` 覆盖两类实际使用的父子运行入口；确认知识入库 succeeded → 子输出物化 → 操作者接受交接 → 父运行吸收的对应关系。相同交接重复提交幂等，拒绝和重试有可见原因。
2. 父流程只消费当前 invocation 对应的子运行、当前输出 hash 和版本；错误 run、过期候选、旧知识包不得通过历史 fallback 代替。吸收成功后按既有合同开启后续评审/继续父节点，不依赖人工重新创建子运行。
3. claim 证据门阻断时先定位原因：缺证据走已有定向 evidence request；已被反证则走候选修订或放弃；数据缺失/物化失败走阶段恢复。前端将对应 canonical action 暴露在现有详情中，不能给操作者一个直接提高 confidence 的按钮。
4. 如现有动作缺少某一必要分支，仅补该分支的 service→DTO→domain API→VUI；不得让前端自行决定来源是否可信，或凭“打开知识包”记为已交接。

**验收**：子运行完成可通过 UI 接受并驱动父运行；重复接受不双写；拒绝保留原因；制造一次 evidence gap 后 UI 能定向补证并进入新版本评审；反证不能被强制批准绕过。回归 `test_knowledge_sideflow_run.py`、`test_research_workflow_knowledge_handoff_receipt_authority.py`、`test_research_workflow_hypothesis_first_chain.py` 和 HTTP/domain API contracts。

### R5：把候选草案变成可审查的高质量假说

**依赖**：R3、R4；与 R1/R2 共享候选数据时保持串行。

**Owner/文件**：`meeting_runtime.py`、`research_runtime/{hypothesis_first_chain,claim_belief_service}.py`、`core/research/workflow/contracts/hypothesis_quality.py` 及既有评审 runner。复用现有 rubric，不改变未到达的第二阶段实验合同。

1. 生成与修订上下文绑定问题范围/版本；并行生成草案若未见最终范围，在入选前核对并修订。本次无细胞 TX-TL 与活细胞约束冲突作为明确回归样本。
2. 复用候选/claim 结构区分已有事实、待检验预测与设计参数；具体数值必须有来源或被显式标为待验证假设，并说明为何选这个实验阈值。未经证据支持的“线性提升”不能作为既有事实，也不应机械删除所有可检验的函数关系预测。
3. 每个最终假说包含：问题与适用范围、机制、干预与对照、读出指标、预测方向或合理阈值、证伪条件、替代解释、支持与限制证据、可用资源/公开数据的验证路径。每个关键引用回到当前证据卡与原文定位。
4. 光控重写候选必须说明输入序列、基线、回切状态、观测时间和何种结果推翻哪一主张。定义不同或背景争论不能冒充对具体机制的实验证伪；四视角标签和高评分都不能代替内容审查。
5. 先做确定性的缺字段/范围/引用校验，再调用既有分级评审。搜索保持 Flash，提炼/整合/修订保持 Plus，关键评估保持 Max；从 frozen policy 与实际调用回执逐节点对账。未执行节点只能证明配置，不能宣称实际调用过该模型。
6. 对不能用当前资源验证的候选返回待澄清/修订，不能为“高质量完成”虚构菌株、设备、数据集或实验结果。沿用既有评审轮数预算，达限仍不收敛时输出有缺口的结果而不是强行通过。

**验收**：SCI-011 的范围冲突、无来源数值、证伪歧义均能被发现并进入可操作的修订路径；人工抽查最终假说逐项对上原文与机制。回归 `test_research_workflow_hypothesis_quality_contract.py`、meeting/review 对应测试；模型得分只作辅助，不作唯一完成标准。

### R6：第一阶段结果包与阶段边界

**依赖**：R4、R5。

**Owner/文件**：`research_runtime/{result_package_v2,result_package_system_adapter,hypothesis_first_state_v2}.py`、`question_result_package_adapter.py` 与现有题目档案/正式结果视图。

1. 复用现有结果包规范，汇集当前题目、运行、选定候选版本、问题理解 hash、证据/反证、知识交接、评审与修订轨迹、验证计划、限制和模型用量；读回重新核对 canonical hash。
2. 页面明确区分“候选已生成”“证据评审已收敛”“结果包已物化”“人工确认完成”。优先用既有题目档案承载结果核验；不因为缺少独立新页就断言缺少结果能力。
3. 第一阶段成功只依据自身合同；第二阶段模板就绪与实验节点不参与判断。单题完成不等于 125 题全部完成、不等于程序已发布，也不等于第二阶段激活；继续使用现有整体审批与 hash 匹配的真实 `applied` 发布回执边界。

**验收**：缺少任一必需当前产物不能显示完成；UI 可打开最终版本与来源；审批/发布状态可区别；阶段一完整时不报 `template_baseline_missing`，阶段二仍受原规则控制。回归 `test_challenge_cup_stage_one_v3_contract.py`、phase boundary/routes 及 result package tests。

### R7：历史现场处理与两类验收收口

**依赖**：R1–R6 的代码与合同测试通过。

1. 保存 SCI-011 原始两个 attempt 的失败事实，不覆盖旧会话或把旧失败改成成功。使用当前 run 的候选 ID、批次、search event、原 DOI/正确 DOI 形成只读处置清单。
2. 通过修复后的领域动作归并重复/错误候选并恢复现有任务；补证只针对缺口，不清空重跑。旧无效版本退出活跃消费，保留审计证据，不保留旧执行逻辑兼容分支。活数据写入前展示精确对象清单；原始证据删除和跨题清理不属于本方案。
3. 先用隔离的 SCI-011 事实样本跑故障恢复回归，再在前端核验 SCI-011 恢复路径；之后选择另一个无历史正式运行的问题做全新流程验收。恢复验收和冷启动验收各一条，不能互相替代。
4. 所有真实业务动作由前端完成：选择题目、范围确认（如合同要求）、候选选择、定向补证/修订、知识交接、最终核验。后台/文件/Ledger 仅只读对账，不手工伪造成功记录。
5. 真实验收前记录 frozen 模型、预算、题目和运行身份；同一根因再次失败立即停止付费重试并落盘。此轮规划不启动新运行，不延续此前已用完的单次重试额度。

**最终交付**：可复查的前端操作轨迹、关键页面证据、run/node/attempt 与回执 hash 对应表、来源抽查、候选修订前后、实际成本与延迟；更新问题清单的已修复/待验证/未解决状态。通过前不承诺任意科研题目都能产出高质量结果；证据不足但准确停在可处理缺口也是正确行为，不能伪装为成功案例。

## 5. 执行顺序和提交边界

关键路径：`R1 → R2 → R3 → R4 → R5 → R6 → R7`。每步的测试、文档、复用证据并入其功能提交；共享 `stage_writeback`、候选权威、`hypothesis_first_chain` 和 Inspector 均单 writer 串行。R3 的纯前端失败复现测试可以提前准备，不默认派子 Agent。

提交建议：来源写回一致性、检索预算恢复、前端动作与同步、知识/评审交接、质量与最终交付，按可独立验证的边界拆成约 5 个提交。R7 是运行验收结果，不作为虚构代码提交。不要修完一个按钮就宣称完整闭环。

各实现批次在任务 worktree 中完成；运行针对行为的 pytest/Vitest，主动审 diff；最终使用 selector 与 `task_closeout.py` 验证并快进合入本地 main。前端交付前必须通过 `tsc -b`、VUI route/design contracts；不重复执行输入与 HEAD 未变的全量测试。Launcher rebuild/restart 仅在代码闸通过且 active-work guard 允许时进行。

## 6. 风险、未决诊断与停止条件

- 当前已经证明写回次序错误；具体跨文件故障恢复能力须在 R1 用故障注入查明。优先预校验与已有幂等批次记录，不预先建设通用事务框架。
- 预算耗尽已实测，通用压缩器是否有缺陷尚未确认。R2 先量化输入分块和压缩诊断，不能直接把故障归咎于模型窗口太小。
- 正确 URL 与 DOI 的跨表示映射必须来自真实 provider 元数据或权威解析回执，不能放松为字符串猜测；R1 新校验若导致现有合法来源被拒绝，先修同源识别，不削弱校验。
- 原报告把状态完成、资料质量和某些静态缺口混在一起，本方案以 §1 校正后的事实为准；旧报告保留历史现场，不作为所有修复都必须新建能力的依据。
- 本次 `git fetch origin main` 遇到本地 `refs/agents/.../checkpoints/turn/0` 无效对象；只读 `ls-remote` 确认远端 main 仍为 `dd1acce0a`，当前本地已包含它。规划可继续；不删除该未知归属 ref，也不把远端同步异常混入产品修复。后续 push 前需独立检查该 Git 问题。
- 合入前目标 main 变动、文件 claim 重叠、实际需要改普通 Session 核心或出现批量数据迁移时，先定位具体影响；只停受影响步骤，不扩大写入。

## 7. 完成判据

| 维度 | 必须具备的证据 |
| --- | --- |
| 正确性 | 拒绝写回无未记录副作用；接收与失败语义一致；重复/中断恢复幂等 |
| 配置 | Flash/Plus/Max 按功能冻结，实际调用与冻结值一致；第一阶段不受第二阶段模板门阻断 |
| 效率 | 无 URI 污染；不重复整包搜索/上下文；报告累计成本、最大上下文、真实延迟与目标差距 |
| 操作 | 无后台补丁、无需整页刷新；前端可完成选择、补证、修订、知识交接和结果核验 |
| 质量 | 范围一致；预测与事实分开；来源/反证可追溯；证伪、替代解释、资源路径经内容审查 |
| 闭环 | SCI-011 可恢复与新题冷启动均有证据；最终产物/版本/hash 与 Ledger 一致；第一阶段和第二阶段边界明确 |

下一步建议：按 R1 开始修复来源写回与回执一致性，再顺序完成 R2–R7；实施中持续把新根因、改动和验证结果落盘。
