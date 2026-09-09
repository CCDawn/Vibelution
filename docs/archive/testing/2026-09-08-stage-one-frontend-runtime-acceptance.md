# 第一阶段新版真实前端运行时验收

目标：在修复提交 `8d781c8f98b2926273159b9e5c933cc014ba241e` 真实加载后，从真实前端完成一次挑战杯第一阶段闭环（候选、评审、资料寻找、不可达来源补源、原文提炼、证据关系、知识入库、交接、假说收敛、结果包），边定位、边修复、边复验。业务推进全部通过前端按钮/表单/确认完成；API、日志、账本仅作辅助核验。

## 环境与版本事实

| 项目 | 值 |
| --- | --- |
| 工作区 | `C:\Users\Administrator\Desktop\Vibelution`（main `8d781c8f9`，clean） |
| 任务 worktree | `.worktrees/stage-one-frontend-acceptance`，分支 `codex/stage-one-frontend-acceptance` |
| 实例 | `bcabd5ca`（`scripts/agent_log_context.py --project .` 解析） |
| 验收页 | `http://127.0.0.1:8000/teams?teamId=research-team&researchView=workflow&workflowId=challenge-cup-research&questionId=SCI-009&...` |

## A. 新版加载前提的解决（2026-09-08 23:50–00:10 本地 / 15:50–16:10Z）

- 接手时后端运行 `fdf3e0d5760b2201e46be15816cbee3d83c8f578`（2026-09-08T13:38:05Z 启动），`/api/runtime/code-freshness` 判 `backend_behind`（落后 5 提交）；前端构建 current。
- 归属核实：评审房 `room-challenge-14f86137071fa65fec89e6e1`（`SCI-009 | sci-009-cc4f71303`，config.source=challenge_workflow，workflowRunId=run-1a77f2262372，questionId=SCI-009）确认为本次验收产生的旧自动流程；22→23 轮，仍在失败循环（r3-a15 尝试，最新轮 16:04Z 再启）。其他题目房间均为 failed/ready，无他人活跃任务；work_runs（chat_room_round/chat_turn）活跃 0。
- 前端停止操作（真实按钮）：工作台 → 假说设计节点面板 →「取消当前正式运行」→ 确认弹窗「确认执行」。第一次提交遇到状态版本冲突（界面提示“状态已更新，请重新确认”，期间新开 round-20260908-160402）；重新点击后生效。
- 结果：run `run-1a77f2262372` 状态 `cancelled`（16:04:52Z）；评审房最后一轮 `stopped`，房间 `ready`，20 秒观察无新轮；界面提示「正式会议已由服务端执行边界终止，未生成或晋升纪要」。
- Launcher restart（`VibelutionLauncher.exe --project <root> restart`，exit 0）。重启后 backend health：head `8d781c8f98b2926273159b9e5c933cc014ba241e`，pid 47404，16:06:45Z 启动；code-freshness 判 `current`（backend behind=false，frontend stale=false）。

## B. 新版前端闭环验收

### B.0 清理旧链与重建起点（16:10–16:21Z）

- 发现：重启后 R0 预正式评审被自动重驱——新房间 `room-hf-review-f122c25bb1b322d5eb405554`（config.source=hypothesis_first_candidate_review.v1，kind=preformal_candidate_review，无 workflowRunId），round-20260908-161025 于 16:10:25Z 运行。正式 run 已取消但 R0 评审仍被重驱（r3-a17）。前端经 `/chat?room=...` 会话页「停止」按钮停止该轮，房间转 ready。
- 为获得完全新版本的闭环证据，经前端「更多操作 → 重置本题运行」清理本题假说闭环工作记录（影响预览：候选假说 3、假说选择 1、生成或评审讨论 42、评审轮次 15、资料搜集请求 21、资料搜集运行 21），输入题号确认。重置后当前任务回到「生成候选假说 · 待确认」。
- 观察：重置后唯一可用命令为 `create_stage_one_run`（state-v2：phase=generation，formalRuntime=run-1a77f2262372/cancelled，allowedActions 仅 create_stage_one_run enabled）。这与 run 创建服务语义一致：`create_stage_one_run` 是 origin 级入口，创建正式 run 时自动打开 R0 生成会并自动 start 入口节点。
- 前端点击「创建第一阶段运行」：新 run `run-332a539909a6` 创建（16:21:32Z），旧 cancelled run 保留历史；run 进入 running，currentTask=problem_understanding；新 R0 生成房 `room-challenge-18452edf6a7ac392d55`（SCI-009 | 候选生成）running，generation meeting `hf-candgen-cdbc9f498d8ef387-r0`。

### B.1 R0 候选生成 → 选择 → 评审 → 收敛

- 16:21:33Z run 创建后自动开 R0 生成会 `hf-candgen-cdbc9f498d8ef387-r0`（房 `room-challenge-18452edf6a7ac392d55a95a4`）。
- 16:22–16:33 两轮（开幕 + 批评与修订）完成后 generation outcome=succeeded，产出 3 份 R0 探索草稿（sci-009-cc37e629e / c0958359d / ce0d8c43d，recordKind=hypothesis_exploratory_draft）。注意：R0 产出是草稿而非可选候选（candidateAuthority=exploratory_draft），候选须待知识搜集后的 R1 接地生成；state-v2 candidates=0 是该设计的预期读数，不是缺陷。
- problem_understanding 在新代码下 succeeded（16:2x–16:3x）。

### B.2 知识搜集子链

- 16:4xZ 前端假说设计节点「发起知识搜集」：knowledge invocation `kinv-65ff1f391aa24a82a5819eabd88bf011` 创建子 run `run-1ca97605acf3`（source_finding → …）。
- source_finding 第 1 次成功：注册 6 篇候选论文（Science/Palgrave/ScienceDirect×3/Nature，8 条 dprec 记录）。
- source_extraction 第 1 次被 `required_artifact_missing: source_extraction requires ['evidence_card_batch']` 阻塞。根因（辅助核验）：6 个来源全部付费墙不可达；提取器（session-20260909-004717-003871）对每个候选判 `needs_more_info`，缺陷记录「无法抓取全文，摘要为搜集阶段元数据而非原文验证」「缺少逐字引文锚点」，writeback closureSummary advanceOutcome=partial / artifactStatus=evidence_gap / blockedCount=6。提取器诚实拒绝以摘要伪造证据卡——符合不降门槛要求；该报错文本即 `retry_node.py` 设计的补源恢复入口（rerun target=source_finding）。
- 17:0xZ 前端知识节点「高级操作 → 返回资料寻找补源」：source_finding attempt 2 dispatching→running。补源搜索由失败抓取回执驱动，查询明确瞄准开放获取渠道（site:core.ac.uk、eprints.whiterose.ac.uk/orca.open.ac.uk、pmc.ncbi.nlm.nih.gov、mdpi.com）——与「成功抓取未清旧失败/失败回执驱动补源」修复一致。
- （观察中：补源第 2 次寻找 → 新一轮提炼）




### B.3 缺陷①：续跑 turn 模型回执断流 → 节点终态阻塞（已修复，待加载复验）

- 现象：source_finding attempt 2（补源）turn 于 17:14:03Z 因 context_budget_exhausted 暂停（needs_continue），编排层 `_submit_agent_turn_continuation` 提交「继续」（metadata.sourceSurface=team_workflow_agent_turn_continuation + continuationOfTurnId，不带 kind）。续跑 turn 17:14:03–17:19:27Z 正常完成并产出成果（补源 stage task stagetask-20260908170108-811dfb1f completed，注册 8 篇可及来源、排除 6 条无效 locator），但该 turn 期间模型调用回执（challenge_model_invocation_receipt）零落盘（上一条 17:13:10Z 后断流）。adapter_dispatch act-09390e92 失败：完成依赖在 (formalNodeRunId, sessionId, turnId) 作用域内找不到任何回执 → attempt 终态阻塞 `agent_completion_dependency_pending`（requiresOperator）。知识子链卡死：a2 恒 running，source_extraction 旧 attempt stale/blocked。
- 根因（`core/web/services/session/worker.py::_model_invocation_receipt_context`）：续跑 turn 的用户消息 metadata 继承 stage-task 元数据但**不含 researchProjectId**（submit 层设计如此，身份归 task 记录），且 task 记录 turn 仍钉在已暂停的旧 turn id——旧实现对两个差异都直接 `return None`，导致 stream_capture 收不到回执上下文，回执静默不落盘。回执看门狗只管「已落盘回执的送达」，管不到「上下文被拒后根本没落盘」。
- 修复（本任务分支）：① `sourceCollectionStageTaskId == taskId` 时允许 metadata 缺 researchProjectId，改从权威 task 记录读回并校验一致；② turn id 门放宽一条精确通道：`stored_turn_id == metadata.continuationOfTurnId`（即本 task 已暂停 turn 的编排续跑）放行，其他 turn id 仍严格拒绝。注释写明缘由：续跑跑在同一 task/session 但新 turn id，若不落回执，完成依赖永远找不到最终 turn 作用域的回执并把节点判终态失败。
- 回归：`tests/test_session_worker.py` 新增 `test_receipt_context_accepts_continuation_turn_of_stage_task`（含 turn-9 陌生续跑拒绝、无续跑声明拒绝两个反例）；`test_session_worker.py` 38 过 + 相关 4 套（continuation/completion_dependency/receipt_persistence/research_project_agent_tasks）92 过。
- 恢复路径（修复加载后）：a2 attempt 无 sweep 自愈、reconcile 不救 adapter_dispatch；经 state-v2 可用 offer `start_node source_extraction`（「启动 资料提炼」）对已注册 8 篇可及来源直接续链。

### B.4 缺陷②：终局阻塞 attempt 的僵尸预算预留锁死阶段准入（已修复，待加载复验）

- 现象：缺陷①修复加载后，前端 start_node `source_extraction`（run `run-1ca97605acf3`，runVersion 3）被 `budget_safety_limit_reached: stage token limit exceeded` 拒绝（adapter_execution_exception），retry_node 同样被拒——知识搜集阶段（默认限额 2,000,000 tokens）无法启动任何后续节点。
- 根因（`completion_dependency.py::defer_completion` unavailable 终局分支）：a2 的续跑 turn 真实发生（settled_json 记录 usage 1,066,138 tokens）但回执缺失，该分支走 `fail_outbox` + `apply_node_run_block(update_attempt=False)` 终局，**不做任何预算补偿**——a2 的预算预留（`reservation-{node_run_id}`，status='reserved'，estimatedTokens=1,480,468）永不 settle/void，而 `_stage_admitted_tokens` 对 status='reserved' 按全额预估计入。1,480,468（a2 预留）+ 519,532（a1 settled）= 2,000,000 恰好顶满阶段限额，一个终局阻塞的僵尸 attempt 永久锁死整个阶段的准入。对照：`adapter_dispatch_worker.py` 的通用失败分支（execute_exception/execute_failed/verify_exception/verify_blocked）都有 `void_unused_reservation` 补偿，唯独 deferred 分支缺失；且 deferred 分支即使回执确实用了 token，void 也不对——正确做法是把预留 settle 成已观测 usage。
- 修复（本任务分支，三处）：① `budget_authority_adapter.py` 新增 `compensate_terminal_attempt_reservation_in_uow`：按观测 usage settle（复用 `settle_budget_authority_in_uow` 的幂等合并），从未使用的预留按 `void_budget_reservation` 体例置 voided（reason/correlationId/terminal），终态 receipt 幂等 no-op；② `defer_completion` unavailable 分支在 `apply_node_run_block` 之后同一事务内调用该补偿（fail_outbox 未成功则不补偿），成功后记录 `completion_dependency.reservation_compensated` 场景事件；③ `command_service._handle_reconcile_run` 对存量僵尸 run 增加运营商恢复路径：running attempt + failed adapter_dispatch（last_problem code=agent_completion_dependency_pending）→ 同一 reconcile 事务内补偿预留，`run_blocked` 事件 payload 新增 `compensatedReservations`。
- 测试：`tests/test_completion_dependency_recovery.py` 新增 2 个（观测 usage → settled 且 1,066,138 不丢；无 usage → voided 且终态幂等）；`tests/test_reconcile_run_ledger_authority_recompute.py` 新增 1 个（reconcile 补偿 completion-pending 僵尸预留 + 非 completion-pending 反例不触碰）。
- 恢复计划（修复加载后）：前端知识节点「对账运行」（reconcile_run）触发③的补偿闭合 a2 僵尸预留（按 usage settle），阶段准入释放后再「启动 资料提炼」（start_node source_extraction）续链。
- 恢复路径更正：经前端核实，知识节点 offer 白名单不含 reconcile_run（仅 ensure/inspect），子 run 无任何对账入口，上述恢复计划不可操作；故将对账补偿扩展到主 run reconcile 的知识子 run 扫描（缺陷③，本次提交），操作路径=主 run 面板「对账运行」。

### B.5 缺陷④：补源后的 a3 提炼在抓取层 8/8 全败——PDF 不支持 + 同站 IdP 跳转被误停（已修复，待加载复验）

- 现象：缺陷①②③修复加载并经前端补源（注册 8 篇可及来源）后，a3 提炼 attempt 对全部 8 个候选执行 web_fetch 全败，failureCode 清单：`http_403`×2、`redirect_loop`×4、`unsupported_content_type_pdf`×1、`403`×1。开放获取仓库（edepot.wur.nl 等）全文就是 PDF，提炼层拿不到任何原文。
- 根因（`tools/web_search_tool.py`，两个工具层缺口，均真机复现定案）：
  1. `_read_response_text` 只放行 text/html/xml/json/javascript/xhtml，`application/pdf` 直接返回「不支持的内容类型」，开放仓库 PDF 全文永远无法进入提炼；venv 已有 `pypdf`。
  2. `_fetch_with_same_host_redirects` 只跟同 host 重定向：nature.com 文章 303 → `idp.nature.com/authorize`（设 cookie）→ 302 回跳原样文章 URL →（带 cookie）200。工具在跨 host 一跳停下并提示「请直接抓重定向后的 URL」，agent 照做又被 303 弹回 idp，形成指令级 A→B→A 死循环（生产 `redirect_loop`×4 即此）。httpx.Client 自带 cookie jar，同一 Client 内跟完三跳即 200（真机复现：`www.nature.com/articles/s41586-021-03819-2` 303 → idp → 回原 URL → 200 全文）。
- 修复：① `_read_response_text` 对 content-type 含 `pdf` 走新增 `_extract_pdf_text`：pypdf 逐页 `extract_text()`（页间 `\n\n`，局部 import，异常/空文本分别返回 `[错误] PDF 文本提取失败` / `[错误] PDF 无可提取文本（可能是扫描件）`），保留 `_WEB_FETCH_MAX_BYTES` 超限拒绝，硬上限前 200 页并在文末标注截断；`web_fetch` 对 PDF 输出改用 `[PDF 文本] {final_url}` 前缀并跳过 trafilatura（实测 `trafilatura.extract` 对纯文本输入返回 None，跳过以免二次加工失真）。② 重定向判定改按注册域（`_registrable_host`，含 co.uk/org.uk/ac.uk/gov.uk/com.au/net.au/org.au/co.jp/ne.jp/or.jp/com.cn/net.cn/org.cn/edu.cn 多段后缀表）：同注册域跳转（nature.com ↔ idp.nature.com）继续跟随并由同一 Client 自然携带 cookie；真正跨站（doi.org → link.springer.com）保留原「跨主机重定向，已按安全策略停止自动跟随」语义与文案。③ 环路保护：同一 URL 允许到达 2 次（IdP 预授权回跳常是原样 URL，中间跳设置的 cookie 使第二次请求落 200——若按「第二次出现即报错」会掐死目标场景本身，真机冒烟证实），第 3 次出现返回 `[错误] 重定向循环: {url}`；`_WEB_FETCH_MAX_REDIRECTS` 上限语义保留。函数更名 `_fetch_with_same_site_redirects`。
- 测试：`tests/test_web_search_tool.py` 新增 6 个（PDF 提取/超限拒绝/扫描件报错/同站 IdP 三跳回原 URL 200/跨站停止/重定向循环，含 `_registrable_host` 多段后缀单测，PDF fixture 由测试内最小 PDF 构造器现场生成）；`tests/test_research_search_tools.py` 的 `test_web_fetch_stops_cross_host_redirect` 目标改真跨站 URL（原 `example.com → other.example.com` 是同注册域，新语义下应跟随）。三套件 100 过。
- 真机冒烟：`edepot.wur.nl/577712` 实测为 >2MB 的 application/pdf，被保留的 2MB 字节上限按设计拒绝（该仓库大文件需走其他来源）；`www.orimi.com/pdf-test.pdf` 返回 `[PDF 文本]` 开头且含正文子串；`www.nature.com/articles/s41586-021-03819-2` 跟完 idp 三跳返回文章正文，无 redirect_loop。

### B.6 缺陷⑤：a5 重试复用已超限会话——interrupted 状态被拒于新会话重放门，retry 确定性死循环（已修复，待加载复验）

- 现象（时间线）：a4 提炼 turn 在 writeback 成功之后死于上下文硬上限前置闸（turn failed_runtime，summary 含 `context_budget_exhausted`；6/8 候选的 quotable text + quote 锚已由 writeback 写入 dprec 记录，数据未丢）。操作员经前端「重试 资料提炼」→ a5 创建新 stage task `stagetask-…194920`，但 `prepare_source_collection_stage_task_replay` 判定 reuse，仍绑定同一个已超限会话 `session-20260909-004717-003871`；a5 turn 链 3 级 continuation 全部被前置闸拒（无进展）→ `agent_turn_continuation_exhausted` → 新 stage task 状态落 interrupted（`stage_reconcile.py` 把 interrupted/stopped/stopped_by_user/needs_continue 归一为 interrupted），failure summary 明确含 `context_budget_exhausted`。
- 根因：`core/web/services/team_workflow/source_collection/stage_session_replay.py::prepare_source_collection_stage_task_replay` 的新会话重放逃生口条件是 `status == "failed" and _failed_on_context_budget_loop(current)`——continuation 耗尽/needs_continue 的 turn 会被归一成 interrupted，而 interrupted 状态永远进不了该逃生口，于是每次 retry 都复用中毒会话，确定性死循环（同一会话 a4/a5 连续两轮死于同一前置闸）。
- 修复：重放门改为 `status in {"failed", "interrupted"}` 且保留 `_failed_on_context_budget_loop` 证据匹配——interrupted 但 summary 携带 context_budget 标记的同样换新会话，无标记的 interrupted 仍走既有 reuse 语义。测试：`tests/test_source_collection_stage_session_replay.py` 新增 2 个（interrupted+context 标记 → `formal_retry_same_task` + `context_budget_retry_new_session`；interrupted 无标记 → `reuse`），该文件 14 过。
- 恢复计划：再点一次前端「重试 资料提炼」（a6）应命中 `formal_retry_same_task` 重放进新会话，并经 stage context 工具从 dprec 记录读取 6/8 候选的 quotable text + quote 锚产出证据卡，无需重新抓取。

#### B.6 补遗：auto_formal_retry 门同样缺 interrupted（缺陷⑤第二层）

- 73667e3f2 修复的是 idempotency 重放门；但 retry_node 实际走**前任务血缘门** `_AUTO_FORMAL_RETRY_STATUSES`（stage_session.py:20，原含 error/failed/incomplete/timed_out/timeout/blocked）。a5 任务落 interrupted → a6 重试仍复用超限会话（formalRetry=False、retryOfSessionId 空，已核账本）。
- 修复：auto_formal_retry 判定扩为 `status in 集合 OR (status=="interrupted" AND _failed_on_context_budget_loop(前任务))`——**带 context 标记的 interrupted** 才升格新会话 formal retry；无标记的 interrupted（读中断原地续作是既有设计语义，test_source_collection_extraction_resume_after_interrupted_reading_prioritizes_writeback 守护）保持 reuse。dprec 记录承载 quotable text/quote 锚，新会话可无损续作。
- 测试：test_interrupted_on_context_budget_loop_upgrades_to_formal_retry（正例/反例/None/集合不变式）；首版直接把 interrupted 加进集合被 closeout 影响选择器抓出回归后改为标记门。


### B.7 缺陷⑥：v3 上下文策略 trigger 高于窗口推导的 hard limit——压缩永不触发、前置闸死锁（已修复，已加载复验）

- 现象：a7/a8 两轮「重试 资料提炼」全部死在模型调用前的 `context_budget_exhausted` 前置闸（`_context_budget_preflight_guard`），会话被暂停-续跑梯子（3 级 continuation）耗尽后 `agent_turn_continuation_exhausted`。
- 根因：挑战杯 v3 冻结策略按 262,144 窗口推导 trigger=204,800 / hard=221,184；但运行模型 qwen3.7-plus 的窗口是 131,072，策略合并（`effective_agent_context_compression_policy`）把 effectiveTokenLimit 钳到 131,072 却不改 trigger——trigger(204,800) 永远达不到，压缩永不触发，粗估 139,554 tokens 一直堆到 hard limit 前被前置闸拦死。
- 修复（9191b21eb）：策略合并新增窗口不变量钳制——policyVersion≥3 时 trigger=min(trigger, effective−16,384)（退化取 effective）、target=min(target, int(effective×2/3))；只降不升，operator 更低值原样透传。新增 3 测试（131,072→trigger 114,688/target 87,381、operator 低值透传、未版本化 trigger≤effective）。
- 生产验证：a9 重试通过前置闸（粗估 139,554 > trigger 114,688 → 切精确估算 ≈3–4 万 < hard 131,072 → 模型真实调用）。

### B.8 缺陷⑦：formal retry 终态门缺 interrupted——a8 被拒「前任务不在终态」（已修复，已加载复验）

- 现象：缺陷⑤第二层修复后 a8 仍失败，报「Formal retry requires the previous task to be in a terminal state」。
- 根因：`stage_reconcile` 把 stopped/stopped_by_user/needs_continue 归一成 interrupted 后，`TERMINAL_TASK_STATUSES`（research_project_agent_sessions.py）不含 interrupted——每个 marker 门升级的 context-budget 重试都在会话创建处被拒。
- 修复（919d2b856）：TERMINAL_TASK_STATUSES 增补 interrupted（附归一化口径注释）；新增 test_formal_retry_accepts_normalized_interrupted_previous_task。
- 生产验证：a9 formal retry 会话创建成功（attempt 2、retryOfSessionId 回填）。

### B.9 a9 资料提炼成功：22 次抓取、10 次写回、零预算命中（缺陷④⑤⑥⑦链路闭合实证）

- 时间线：a9 会话通过缺陷⑥的钳制闸 + 缺陷⑦的终态门，21:47:26 完成 source_extraction。
- 量级：22 次 web_fetch、10 次写回、预算零命中；dprec 记录承载 6/8 候选的 quotable text + quote 锚。
- 产出：candidate_store 21 条 source_manifest 候选——6 keep / 15 needs_more_info，15 条带真实锚 id（不复述具体锚内容，避免报告携带无界原文）。

### B.10 缺陷⑧：预算阻塞事件在知识子 run 上——异常收件箱零信号、一键补预算 CTA 不可达（已修复，真实前端复验）

- 现象：evidence_relations 被 `budget_precheck_insufficient` 阻塞（consumed 2,726,303 > limit 2,000,000，suggested 262,347），但异常收件箱对 SCI-009 返回 0 项——运维台看不到阻塞、也没有恢复入口；`调整上限` 只作用于新建/续跑 run，活 run 无解。
- 根因（两层，都在 hypothesis_first.py）：`_collect_budget_precheck_blocks` 只回放 formal run 尾部，而阻塞事件挂在 knowledge sideflow 子 run（run-1ca97605acf3）的事件流上；`_resolve_run_version` 只列 challenge-cup-research 的 run，子 run 属 challenge-cup-knowledge-sideflow，补预算端点必 404。
- 修复（02a1a3135）：formal 尾部顺带解析 `knowledge_invocation_created.childRunId`（生产账本实证 formal seq10 就有），逐子 run fail-soft 回放尾部并给 block 标记子 run id；版本解析 miss 后回退 sideflow listing。route contract +2 测试（11 过）。
- 生产复验（真实前端按钮链）：重启后收件箱出现 budget_exhausted 项（scope=子 run/evidence_relations）+「一键补预算」CTA（两段式误触防护）；arm→「确认补预算」→ `extend_budget` 命令落库（cmd-f7705a8cfb…，accepted，runVersion 10→11，幂等键 inbox-extend-budget:…:2000000:262347）→ `budget_settled` 上限 2,000,000→2,262,347。前端随后「重试 证据关系」正确 POST 到子 run（retry_node a2/v11）——被 412 拒绝，暴露缺陷⑨。
- 附带环境事实：Launcher exe 经 git-bash/cmd 转义调用会静默失败（native-launcher-entry.log `native_entry.failed 路径中具有非法字符`），须用 PowerShell 干净引号；`/api/runtime/code-freshness` 可判定 `backend_behind`（本次曾因 closeout 全量选择器耗时导致「重启早于合入」，靠该端点发现并二次重启）。

### B.11 缺陷⑨：补预算基线公式忽略超支——上限提到 2,262,347 仍低于已消耗 2,726,303（已修复，真实前端两轮复验）

- 现象：缺陷⑧补预算落库后，「重试 证据关系」仍 412 `node_not_ready / budget_safety_limit_reached / stage_tokens_limit_reached`。
- 根因：CTA（`extend_budget_action`）与端点都写死 `new = limit + suggested`；但本阶段消耗已超上限 726,303（准入只在节点边界拦，末节点跑过头），准入公式是 `consumed + estimated > limit`——剩余仍为 0。正确基线：`max(limit, consumed) + suggested` = 2,988,650（恰留 262,347 余量）。
- 连带：幂等键含 limit:suggested 而非新总额，修公式后会与已执行旧命令同键、幂等重放不加预算，必须改含新总额。
- 修复（在途）：action/端点/请求模型（+stageConsumedTokens 字段）/前端透传四处同源修正 + 测试更新；落地后按 CTA→重试→evidence_relations 执行继续验收。


#### B.11 复验结果（38ab5f18c 合入并 rebuild-and-start 后）

- CTA 新总额正确：收件箱渲染「+262,347 tokens · 新上限 2,988,650」，hint 如实表述「基准 2,726,303 + 262,347；含已消耗 2,726,303」。
- 第一轮真实点击（arm→确认补预算）：`extend_budget` 落库 cmd-0caf16c113…（键 `inbox-extend-budget:…knowledge_collection:2988650`，v11→12），上限→2,988,650。
- 前端「重试 证据关系」从 412 变 **202 accepted**（cmd-be7355a343…，retry_node a2/v12→13）：节点真实执行（execution_anchor_bound + artifact_verified + handoff ho-be23f2d99fb…，node_succeeded），子 run blocked→running→执行完成。
- 后继 knowledge_ingestion 再次预算阻塞（消耗 2,837,952/参考 262,347/建议 +111,649）→ 收件箱自动出现新项且公式正确（max(2,988,650, 2,837,952)+111,649=3,100,299）；第二轮 CTA 点击落库 cmd-652cb45cb4…（键 …:3100299，v13→14），上限→3,100,299。**自续环成立：每轮阻塞都有一键补预算 + 重试出口。**
- 噪声观察（未修）：evidence_relations 成功后其陈旧阻塞项仍留在收件箱并渲染可点 CTA；点击会以 `idempotency_conflict`（同键不同请求）失败。操作员需按节点核对当前状态，建议后续对已成功节点的阻塞项做消解或标注。

### B.12 缺陷⑩：预算先挡的交错使「重跑上游」合同出口永久不可达（已定案，修复中）

- 现象：补足预算后「重试 知识入库」被 412 拒（blockers=evidence_graph_incomplete——关系图有 1 条 missingLink：source_relation_mapper 断言了指向不存在候选 `…-9143d4d6` 的 contradicts_scale_claim 边，同秒真实候选为 `…-9143d85a`；随机 id 笔误无法被标题/别名语义端点解析修复，merger fail-closed 降级为 missingLink——门禁本身工作正常）。同时「重试 证据关系」按钮 disabled（toast `retry_not_available`），操作员互锁无解。
- 根因：`sync_run_blocked` 对已 blocked 的 run 直接 return——阻塞原因一经写入永不刷新。run 的 blocked_problem 停留在旧的 `budget_precheck_insufficient`；而 `succeeded_node_rerun_target`（重跑 evidence_relations 的合同出口，注释明确覆盖本场景）只认 `auto_advance_not_ready/evidence_graph_incomplete` 形状；命令级拒绝（NodeNotReadyError）按设计零写入。三段共同构成：预算先挡 → 补预算 → 真实阻塞（图缺口）永远写不进投影 → 重跑出口永不出现。
- 修复（在途）：拒绝路径 best-effort 刷新已 blocked run 的 blocked_problem 为当前真实 blockers（auto_advance_not_ready + blocker codes，与 worker 的 not-ready 写法同形）；不建 attempt、不 bump 版本、不写事件、幂等。

#### B.12 复验结果（4bb3adf2d 合入并重启后）

- 前端点「重试 知识入库」：命令被 412 拒（预期），但拒绝路径刷新了投影——run 的 blocked_problem 从陈旧 `budget_precheck_insufficient` 更新为 `auto_advance_not_ready / evidence_graph_incomplete`，「重试 证据关系」按钮随即变为「**重跑 证据关系**」且可点（`succeeded_node_rerun` 合同出口首次可达）。
- 点击「重跑 证据关系」→ retry_node a3 **202 accepted**（evidence_relations 真实重跑）。但重跑产物重新并入时，`source_relation_mapper` 再次断言同一条指向不存在候选 `…-9143d4d6` 的 contradicts 边（讲者读取候选店内自己上一版图并复述——自回声），missingLink 仍为 1；豁免（缺陷⑪）成为合同内的唯一收口面。

### B.13 缺陷⑫：知识子 run 卡 reconciliation_required——「对账运行」不级联、子 run 无任何对账操作面（已定案，修复中）

- 现象：a3 重跑与 worker 已排队的 knowledge_ingestion-a2 graph_dispatch 竞速，dispatch 提交时发现执行回执身份失配（expected `(act-aa29dfbd…, nr-…-knowledge_ingestion-a2)`，got `(act-e4b7c78…, nr-…-evidence_relations-a3)`），子 run run-1ca97605acf3 被标记 `reconciliation_required`（v15，graph_dispatch_invalid），outbox `act-8ec85658…` 终态 failed。此后整条 sideflow 冻结：知识入库/交接全停。
- 现有操作面核查：formal run 面板「对账运行」是对账唯一前端入口；知识子 run 的节点 offer 白名单只含 ensure/inspect——**子 run 没有任何对账入口**（grep 全仓确认）。真实前端点「对账运行」：`reconcile_formal_run` 200 受理，formal 落 v5 blocked（`knowledge_package_not_materialized` + `hypothesis_round_unconverged`），但子 run 纹丝不动仍 reconciliation_required v15。
- 根因：`_handle_reconcile_run`（command_service.py）只对 `request.run_id` 做 ledger 权威重规划（superseded→stale、复活 failed graph_dispatch、落位 run 状态）；对知识子 run 仅做 `_compensate_completion_pending_reservations` 预留补偿——复活 SQL 的 `WHERE run_id = ?` 永远指父 run，子 run 的 failed dispatch 无人复活。
- 修复（在途，codex/fix-reconcile-cascade-child-runs）：把单 run 重规划核心抽成复用 helper，父 run 对账落位后对 `reconciliation_required` 的知识子 run 在**同一事务**内做同构重规划（`KNOWLEDGE_SIDEFLOW_NODE_IDS` 节点序、同样的 auto_advance_not_ready 排除、同款落位阶梯 lands_blocked→BLOCKED / 有活→RUNNING / 零活→保持）+ 子 run 版本递增与 reconciled 事件；blocked/终态子 run 不动。

### B.14 缺陷⑬：收件箱陈旧预算项渲染可点 CTA——点击 409、误点风险（已修复，2fa079183）

- 现象（B.11 复验中实录）：evidence_relations 补预算重试成功后，其旧 `budget_precheck_blocked` 事件仍留在 tail 窗口里，收件箱继续渲染该项的可点「一键补预算」CTA；点击以 `idempotency_conflict`（同键不同请求）409 失败。且当 knowledge_ingestion 随后被阻时两项同屏，arm→确认流程须靠肉眼分辨新旧项，误点陈旧项即 409。
- 根因：`_collect_budget_precheck_blocks` 无差别收集 tail 里全部 precheck 事件，不判节点是否已越过阻塞。
- 修复（2fa079183）：派生层按账本真实事件判时效——同节点更新 attempt 的 `node_starting`、经 nodeRunId→nodeId 归属的 `node_succeeded`、同 run 异节点的新 precheck（构造上仅在本节点成功后才触发）、`run_succeeded` 四类证据任一出现即判陈旧丢弃；同节点多块去重保最新；每 run tail 独立过滤保住 ⑧ 的子 run 信号；无法归属的成功保持可见（fail-visible）。+4 测试（16 全绿）。
- 价值：补预算→重试→成功的自续环每转一圈不再遗留幽灵 CTA，操作员见到的每一项都是当前真阻塞。

### B.15 缺陷⑫修复与⑪豁免面（合入后复验在 B.16 记录）

- ⑫ 修复（72f1af139）：`_handle_reconcile_run` 抽出 `_apply_ledger_reconcile_for_run` 复用核心；父落态后同事务级联 `reconciliation_required` 子 run（`KNOWLEDGE_SIDEFLOW_NODE_IDS` 重排、同款 auto_advance_not_ready 排除、同款落位梯 lands_blocked→BLOCKED/有活→RUNNING/零活→保持、子 run 版本递增 + reconciled run_blocked 事件含 parentRunId）。+5 测试（16 全绿，含幂等与 readiness 裁决保护）。
- ⑪（19ae6ffad→rebase）：`evidence_graph_waiver` 服务 + `POST /api/research/workflow-runs/{run_id}/evidence-graph/missing-links/waive`（服务端 428 闭合 confirmed/理由≥8 字、404 族、operator scope、幂等 no-op 不改写审计）；写入走 knowledge_kernel 正规候选店面（同锁同 `sourceCollectionRunId` 权威 scope）；`missingLinkCount` 冻结、`waiverCount` 按读侧同口径重算——**门禁不放宽，只登记人工接受**；图工作台「缺口」行清单 + 豁免两段式交互（理由输入→确认），成功后 refetch。后端 18 测试 + 面板 5 测试绿；首版因 VUI 边界门（本地类常量/内联视觉串）打回返工，类串迁入兄弟 `.styles.ts` 后过门。

### B.16 缺陷⑭：对账级联复活「已成功 attempt 绑定的死 dispatch」+ 僵尸 running attempt——reconcile 死循环（现场定案，修复中）

- 复验环境：⑪⑫⑬ 合入（9e1946382/00ca5099b、72f1af139、2fa079183），rebuild-and-start，code-freshness=current。真实前端链：团队 → 选 SCI-009 → 继续运行 → formal 面板「对账运行」。
- ⑫ 级联**半程生效**：子 run 事件 seq94 = `reconciled run_blocked {reconciled:true, revivedDispatchCount:1, activeWorkFound:true, reconciledStatus:"running", parentRunId:"run-332a539909a6"}`（复活 + 落位 + 事件 + 父唤醒全部按设计工作）；但 seq95 worker 重放该 dispatch 再次终态失败——**同一 `graph_dispatch_invalid` 回执身份失配**（expected ingestion-a2 时代前沿 vs got evidence_relations-a3），子 run 又被打回 reconciliation_required。对账→复活→重撞→再对账 = 死循环。
- 两层耦合根因（live ledger 证据）：
  1. 子 run 唯一 failed graph_dispatch（act-8ec85658）绑定的 attempt `evidence_relations-a3` 状态 **succeeded**（其兄弟 graph/adapter dispatch 均成功）——它是重跑竞速窗口遗留的重复后继 dispatch，期望前沿被 a3 重跑本身作废，重放永不可能过回执检查；现复活 SQL 只排除 blocked+auto_advance_not_ready，不排除 succeeded/stale。
  2. `source_finding-a2` attempt 状态 **running** 僵尸（其 adapter dispatch 早已终态 failed `agent_completion_dependency_pending`，无任何 pending/leased dispatch 能再驱动它），却永久撑起 `has_active_work` 并让 plan 无法落 lands_blocked——落位梯永远走 RUNNING。
- 修复方向（codex/fix-reconcile-zombie-attempts）：`_apply_ledger_reconcile_for_run` 内先做僵尸 attempt 终局化（starting/dispatching/running 且无 pending/leased dispatch → failed 带 reconciliation 审计问题；waiting_human 与有活 dispatch 的不动），再 plan→supersede→复活；复活排除扩展到 succeeded/stale 绑定（failed 绑定保持可复活，保住 checkpoint_node_mismatch 修复形状）。
- 预期修复后子 run 诚实落位 BLOCKED（最深真实阻塞 = knowledge_ingestion-a1 的预算问题，预算上限已两次提高、重试可通过准入），随后走 重试知识入库 → readiness（图缺口）→ 豁免 → 执行链。

#### B.16 续：⑭ 复验 + ⑮ 定案与复验（reconcile 死循环全闭合）

- ⑭ 复验（fe06b9420 合入重启后第二次「对账运行」）：三层全部生效——僵尸 source_finding-a2 终局化为 failed（`agent_completion_dependency_pending` 真实原因逐字保留）、绑定已成功 attempt 的问题 dispatch（act-8ec85658）不再复活、搁浅预算预留被同事务补偿（formal evt13-15 reconciled 记录 compensatedReservations 含子 run）。但子 run 仍无落位：`plan_ledger_authority` 按设计只让 readiness 裁决 authored 落位，唯一存活的 ingestion-a1 是预算类事件性阻塞 → 级联走「零工作 continue」= 缺陷⑮。
- ⑮ 修复（2075ef49c）：级联零工作分支对子 run 专属扩展——重查 post-supersede 尝试，存在存活 blocked attempt 时落 BLOCKED（problem_json 逐字复制、空则哨兵兜底、事件带 `landing: surviving_blocker` 判别符）；真零工作与父 run 行为不变（父 run 事件性阻塞形状有回归测试钉死 reconcile_no_active_work）。
- ⑮ 前端复验（第三次「对账运行」，真实按钮）：子 run run-1ca97605acf3 落位 **blocked v17**，active_node=knowledge_ingestion，blocked_problem=预算阻塞 verbatim，evt96 `{"reconciled":true, "revivedDispatchCount":0, "reconciledStatus":"blocked", "landing":"surviving_blocker", "parentRunId":"run-332a539909a6"}`。UI 投影随即翻转为「知识搜集失败；可按剩余预算重试」。**reconcile 死循环四层（⑫⑭⑮）+ 预算自续环（⑧⑨⑬）全部闭合。**

### B.17 缺陷⑯：cancel 清理队列残留任务在启动排空时崩溃后端——runtime 无法拉起（P0，事故定案，修复中）

- 事故：⑮ 复验后 ~09:44 后端进程死亡，Launcher start/restart 均 bridge_failed exit 3 无法拉起；前端「后端 离线 / Failed to fetch」。
- 根因（backend.stderr 五连 traceback + 账本交叉）：`cancel_run_cleanup._handle → _finalize_budget_receipts → finalize_cancelled_run_budget_receipts` 对 run-20f4bcdf8c84 硬断言 `status=='cancelled'`，而该 run 早在 09-05 已从 cancelled 归档为 **archived**（run_archived evt13 archivedFromStatus=cancelled）→ `BudgetAuthorityError` 未捕获穿透 → 进程崩溃；每次启动排空清理队列即重演 = 崩溃环，后端起不来。
- 影响面：全部运行时验证被硬阻塞（本 run 数据完好：formal blocked v8 / child blocked v17，账本无损）。
- 修复方向（codex/fix-cancel-cleanup-crash-loop）：(1) finalize 接受 archived-from-cancelled（归档来源权威判定，其余终态保持 fail-loud）；(2) 清理 handler 每任务异常隔离 + 有界重试/停驻，毒条目不得杀进程；(3) 排查四天前陈旧任务为何仍在队列被 re-arm，补完成标记幂等性。

### B.18 缺陷⑰：豁免操作面无存活挂载点——standalone 工作台退役后豁免 UI 成死代码（审计定案，修复中）

- 双路独立审计交叉定案：⑪ 交付的豁免面板（TeamSourceCollectionGraphWorkspacePanel 的缺口行）唯一挂载链在已退役的「资料搜集 standalone 工作台」——`researchWorkspaceModel.ts:94-122,238-251` 将 `source_collection/knowledge_collection` 视图规范化回工作流画布；挑战杯画布「证据关系」tab 用的是只读 `EvidenceGraphView`（无 missingLink 渲染），research-workflow 目录 grep missingLink 零命中。操作员在本路由内对 evidence_graph_incomplete 无任何豁免出口。
- 账本核验：唯一 candidate_graph 记录 scope = 子 run 的 SC 权威（dprun-…c0caf640），含 1 条未豁免缺口（contradicts_scale_claim → 不存在候选 …-9143d4d6，自回声边）；formal 与 child 快照的 `sourceCollectionRunId` 指向**不同** SC run——豁免面必须传**子 sideflow run id**（run-1ca97605acf3），传 URL 的 formal runId 必 404 graph_not_found。
- 修复（codex/fix-canvas-waiver-surface）：抽取缺口豁免 section 为共享组件，挂载到画布知识节点检查器的证据视图；child run id 从收集中 childRun 投影取权威值；两段式确认与 ⑪ 交互一致；VUI 边界（兄弟 .styles.ts）+ 三道机器门 + tsc 全过。

### B.19 剩余链路静态审计结论（交接后全自动解阻；R1 收敛硬门清单）

- **交接接受→父 run 解阻全自动**：handoff accept（RESOLVE_HUMAN_TASK decision=accept，需已物化包 receipt）→ 子 run terminal close → `record_knowledge_sideflow_child_success`（无包证据则 invocation FAILED fail-closed）→ outbox `knowledge_result_available` → `absorb_knowledge_result` 写父 run 幂等事件（父 blocked 不影响，仅拒 archived/cancelled）→ readiness recheck 自动 START_NODE 到 hypothesis_design（幂等键 knowledge-ready:{invocationId}；CAS 冲突 advisory skip，靠 sweep 补位）。后端停摆期间积压、恢复后 durable outbox 补跑。
- **handoff 隐性前置**：knowledge_handoff 自身 readiness 要求 Knowledge Store 已写回 draft 知识包且审计完成（否则 `knowledge_package_not_reviewable`，无 pending human task、offer 不可用）——ingestion 成功≠立即可交接。
- **R1 收敛硬门**（hypothesis_design readiness = accepted 知识包 + pendingCollectionCount==0 + hypothesisConverged）：收敛要求 latest 评审轮 closed + 质量非 failed + **claim belief 五态门**（无 contradicted/disputed）+ metaReview/人工裁决 accepted + 无 pending 搜集请求；HARD_ROUND_LIMIT=3 触发 budgetExhausted 时有 auto-adjudication 兜底。死局族：每轮新增 evidence request 未交接（循环搜集）、claim gate rejected 终态（需人工修订 claim/证据）、会议未关闭。
- **结果包段**：protocol_freeze/smoke_gate/candidate_promotion 三道 HUMAN 门 + stage-one 结果核验（packaging_ready 且无未决 HumanTask）；stop/rollback governance 反而放行 packaging；version_lineage_invalid 与非 promote governance 是无出口形态。
- 风险排序：⑰豁免不可达（已立项）> 知识包写回/审计未完成 > 后端停摆积压（⑯修复即解）> accept 时包 receipt 缺失无自动重试 > claim rejected 终态。

### B.20 缺陷⑯复验（崩溃环闭合）+ 缺陷⑱：hypothesis 恢复清扫 O(N²) 重读饿死后端（py-spy 定案，修复中）

- ⑯ 复验（34da1731a 合入重启）：后端拉起、毒条目（archived-from-cancelled 的 run-20f4bcdf8c84）清理失败不再杀进程（stderr 出现带 runId/actionId 上下文的受控失败日志而非穿透 traceback），Layer 1 状态血缘判定 + Layer 2 有界停驻（8 次 attempt 上限）按设计工作。
- ⑰ 合入（8af04ceb9）：豁免 section 抽共享组件挂载画布知识节点「证据关系」tab（EvidenceGraphView 下方）；child run id 从 run 级 invocation badges 线程传入并注释禁止替换为 formal URL runId；25 前端测试 + tsc 0 错全过。待 rebuild 生效。
- 缺陷⑱现场：后端进程在启动排空阶段 HTTP 全超时；py-spy 实锤唯一活跃线程 `vibelution-workflow-hypothesis-recovery`（active+gil）在 `auto_redrive_fenced_review_meeting → _fenced_review_redrive_plan → _records → read_jsonl_tolerant` 反复全量重读 6.4MB/9127 行团队链 JSONL（每次 1–2s），GIL 独占饿死 asyncio。**非死循环**：JSONL 3 分钟 +3.6KB（redrive 记录持续落盘），是 O(N²) 慢排空——重启积压的围栏评审会议逐个 redrive、每个都重读全量。
- ⑱修复方向（codex/fix-recovery-sweep-reparse）：清扫单趟只读一次 records 并向下传参；`_records` 加 mtime+size 键缓存（append 后自然失效）；逐会议间让出；redrive 决策逻辑零改动。
- 环境事实：期间另一会话两次推进 main（desktop-ui-corrections 5fb9e522c、stage-one-feedback-fixes 25e660c22），各收口均已 rebase 适配，无冲突；doc worktree 二次注册时命中陈旧 active 协调记录（claim_overlap），已 complete 释放后重注册。

### B.21 缺陷⑰豁免链真实前端走通 + 新缺陷⑲/⑳/㉑ 定案（09-09 上午）

- **⑰ 豁免操作面真实验证通过**（rebuild-and-start 加载 8f93c5010 后）：CDP 驱动真实工作台，路由 `?…&node=ksf_evidence_relations&panel=evidence`（知识子流程画布节点 + 证据面板，URL 会把 sideflow workflowId 规范化回 formal，须以 ksf_ 前缀节点 + panel=evidence 挂载）呈现「知识子流程证据」区：缺口行（contradicts_scale_claim …905-bcb5daab → …904-9143d4d6）+ 豁免按钮 + 理由输入（≥8 字客户端门）+ 确认豁免两段式。提交后 UI 即显「已豁免 · 已登记豁免：缺口保留计数，但不再阻塞知识入库就绪门」；服务端复核 candidate store：missingLinks[0].waiver 审计三要素齐全（by=local-control-operator / at / 完整 justification），missingLinkCount 冻结不放宽——契约与 ⑪ 设计一致。豁免后 run 级 blocker 从 evidence/budget 族变为 `handoff_not_accepted`，证据门确实不再拦。
- **缺陷⑲：⑱ 修复后 sweep 换热点继续饿死（定案，修复中）**：⑱ 合入重启后 60 秒健康检查通过、3 分钟后 HTTP 再次全超时；py-spy 三连采显示同一 `hypothesis-recovery` 线程栈持续移动（非死锁）但热点从 JSONL 解析转移到 **state-v2 投影读链**：`project_hypothesis_first_state_v2 → _scope_records → get_snapshot → _read_bundle → _discussion_inputs_from_run → list_meeting_rounds`（全团队每会议逐记录 deepcopy）与 `completed_latest_bound_round_source_messages → get_chat_room_detail → _participant_refresh_indexes`（每次 detail 读全量 store load + 签名构建逐会话 touch journal + 写侧对账）。量化结构（只读审计定案）：sweep 每 30 秒一轮、每轮每题 9 步、无时长上限；每轮全量深拷贝 ≥ Q×(1+2R) 次（Q=有链记录题目数、R=有活跃 run 的题目数），数十会议 × 胖记录 = 每轮数千次深拷贝单线程抢 GIL。期间后端进程 44344 消失**非崩溃**——另一会话 11:34 以新 main 头 f06893821 正常重启（Launcher 日志无 traceback，新进程 36448 verdict=current）。修复（codex/fix-sweep-read-starvation-19，三件套）：list_meeting_rounds 增加 (文件游标, status 过滤) 键深拷贝 memo + read_only 共享路径（内部 6 个只读调用方切换，路由层保持隔离拷贝）；sweep 增加墙钟预算（VIBELUTION_AUTO_ADVANCE_SWEEP_BUDGET_MS 默认 5s，超预算本轮停开新题、下轮游标续扫）；chat_room_service 签名改文件签名 + 只读链路改非对账 detail 读。pass 级投影缓存（审计 Option 3）本轮明确排除防风险叠加。
- **缺陷⑳：auto-gate ready handoff 无人接受 → 下游重试永久 412（定案，修复中）**：豁免后点「重试 知识入库」→ POST 412 `node_not_ready`，blockers=[{code: handoff_not_accepted, detail: "Handoff ho-f67bc7db… 状态为 ready"}]。账本铁证：同 edge `evidence_relations->knowledge_ingestion` 两条 handoff——a2 版已被 graph-worker 自动接受（10:03），a3 版（gate_kind=auto、输入快照 hash 与 a2 完全相同）offered 后**永远停在 ready**。根因：唯一 auto-accept 执行者是 graph_dispatch_worker 的成功收尾 mutate（from 节点 succeeded 时 pending→ready→accepted 一气呵成），而 a3 的成功走 receipt 写回/重试路径（10:33 事件三连 artifact_verified/execution_anchor_bound/node_succeeded），不经过该收尾；readiness 又要求最新 handoff 已接受。「对账运行」产品按钮实测不接（点击后零新事件、handoff 仍 ready）——形成无产品出口的结构死锁。修复（codex/fix-autogate-handoff-acceptor-20）：`_apply_ledger_reconcile_for_run` 新增轻量 pass——`status=ready AND gate_kind=auto AND from attempt succeeded` 的 handoff 幂等置 accepted（by reconcile，事件风格与 worker 一致）；human gate 与 from 未成功的严格不碰。修复后「对账运行」按钮即可自愈此类残留。
- **缺陷㉑：命令 offer 被 412/拒绝时前端零反馈（定案，修复中）**：`useResearchWorkflowCommand` hook 已 setCommandError 并 rethrow，但 KnowledgeChildNodeInspector 的 submit 包装只有 try/finally，commandError 无任何渲染位（formal 侧 ResearchProcessNodeInspector 亦无）——操作员点击后 UI 毫无变化，不知道按钮为何无效（本次 412 靠抓 POST 响应才定位）。修复（codex/fix-command-error-surfacing-21）：检查器渲染结构化错误面（blockers[].title/detail 中文原文），VUI 错误面组件 + styles 边界 + 前端契约门。
- 链路位置：豁免已闭环；当前卡点=⑳（handoff 接受后即可重试入库 → 知识包写回 → 交接人工门 → formal 自动解阻）。

### B.22 ⑳-b/㉒/㉓ 三连修复与交接链闭环（09-09 下午，R1 接地生成启动）

- **⑳-b 生产验证通过**（ed17dd34c 合入重启后）：前端「对账运行」按钮（正式节点检查器 reconcile_formal_run）触发 reconcile 级联接受 blocked 子 run 的孤儿 auto-gate handoff；本次实测 ho-f67bc7db… 由 `{"actorType":"system","actorId":"reconcile"}` 接受，父 run_blocked 事件 payload 带 childAutoAcceptedHandoffIds 审计键。知识入库重试（retry_node v17→v18）受理，a2 派发且预算未拦。
- **缺陷㉒：knowledge_ingestion 写回 FileNotFoundError 的真根因是 Windows MAX_PATH（定案+修复+生产验证，1f699915f）**：a2 的 25 轮会话里首次写回失败，agent 转述的「knowledge_ingestion_materialize.lock directory missing」是幻觉文案（该字符串代码库零命中）；turn_journal seq15 原始错误为 errno 2 打在 `<runDirectory>/knowledge_ingestion_materialize.lock`。量化定案：活数据 runDir=233 字符 + fe1c4f60c 起的 35 字符锁名 = **270 > 260**，本机 `LongPathsEnabled=0`；`inter_process_lock` 的 `mkdir(parent, exist_ok=True)` 因父目录已存在静默成功，掩盖到 `open(lock_path,"a+b")` 才炸。修复：storage_durability.inter_process_lock 对盘符绝对、≥248 字符的锁路径加 `\?\` 扩展长度前缀（短路径字节不变），一次覆盖 append_jsonl_locked/回执注册表/链 scope 锁/入库物化全部调用点；回归测试以 270 字符深目录复现。重启后前端「重试 知识入库」→ a3 running→**succeeded**，锁修复生产生效。
- **交接链真实闭环（前端按钮 + 产品自动化策略）**：a3 成功后 knowledge_handoff-a1 一度被 `run_reconciliation_required` 拒（retry 先置 reconciliation_required，节点 start 先拦）→「对账运行」清态→「重试 知识包交接」→ human task 创建（a2=waiting_human，面板出现 接受/拒绝/要求修订 三操作）→ **T8 operator automation policy 自动接受**（decision reason：source review accepted + knowledge review approved）→ 子 run knowledge_result_published → 父 run **knowledge_result_absorbed**（dedupKey=knowledge-result:kinv-…；invocation 行 status=completed/handoff_state=accepted/package_content_hash=3c55e860…）。此前双 blocker 中的 knowledge_package_not_materialized 消失。
- **缺陷㉓：stage-one 运行被 3.0.0 版本硬比对双拒（定案+修复+生效验证，b298a12a2）**：吸收后链路停在 `hypothesis_round_unconverged`（尚无闭环评审轮），重试节点 412；state-v2 的 open_generation 动作不出现，自动推进 sweep 对本题静默 no-op。根因：stage-one 运行钉定义 `3.1.0-stage-one`（stage_one_definition.STAGE_ONE_SCHEMA_VERSION），而 `build_stage_one_grounded_generation_context`（research_project_hypothesis_context.py）与 `knowledge_sideflow_trigger.on_node_succeeded` 都硬比对全局 `SCHEMA_VERSION="3.0.0"`——前者令 stageOneGroundedContextReady 恒 False（open_generation 永不启用），后者令问题理解成功后的自动侧流触发恒 not_canonical（09-08 侧流能开是前端「发起知识搜集」按钮路径掩盖）。诊断用 sqlite 只读 stub（get_run/list_knowledge_invocations_for_parent/list_knowledge_delivery_event_payloads）直接跑生产 loader 复现 blocked；知识包权威 loader 本身（load_knowledge_package_payload→candidate store→hash 复算）单测全通，排除包存储问题。修复：两处门接受 `(SCHEMA_VERSION, STAGE_ONE_SCHEMA_VERSION)`；两条回归测试（register_or_resolve 钉 stage-one 定义 → context ready / trigger submitted）。合入重启后 state-v2 立即恢复 open-stage-one-generation enabled，30 秒内 sweep 自动开会 **R1 接地生成会议 hf-candgen-cdbc9f498d8ef387-r1**（chat 侧栏「正在进行·候选假说生成讨论开幕」可见），链路进入接地候选生成阶段。
- 环境事实：两次重启均经 Launcher restart 指令完成（15:2x/16:0x），health routesReady；本节所有操作经真实工作台按钮或产品自身 sweep/automation 策略完成，无直接数据改动。

### B.23 评审两轮闭环 + 二代 sideflow PU 谱系缺陷（㉓+1）定案修复（09-09 傍晚，R3 评审进行中）

- **链路推进全景（全部真实 UI/产品自动化路径）**：R1 接地生成 r1 会议 09:09 由操作员关账（5 候选 → 假说选择 3 个）；三路配对评审（decision_gate）中两路 system:auto-approve:review-digest 关账、第三路 awaiting_approval 后随收敛面 3/3 确认消化；「补充证据」步骤 6 个资料请求全部完成（画布节点详情：资料搜集 6/6，第 6 个在重启后收口）→ 自动交接 → **下一轮（R3）评审会议自动开幕**（顶部横幅「假说评审会议开幕 hf-review-hsel-…-d5cbe1f954-r3」）。假说收敛门进入等待人工（接受/拒绝/发起下一轮按钮就位，待 R3 收口后裁决）。
- **缺陷㉓+1：补证子 run source_finding blocked "Finding stage canonical problem-understanding artifact is missing."（定案+修复+合入，282a667e3）**：现场 run-5a890f660097（kinv-8637，05:04 创建）6 秒即败。证据链：PU artifact 实际存在且 scope 完全匹配（problem_understanding.jsonl 末行 = run-332a539909a6 / dprun-…-2cd75f2c / nr-…-problem_understanding-a1，团队店 17 行全量核对）；失败 run 的 input_snapshot 却是 `parentRunId=run-1ca97605acf3`（首个 sideflow run）+ `sourceCollectionRunId=dprun-…-5c2930e5`（第三个搜集 run）。根因：`_problem_understanding_authority_scope`（stage_session.py）只上溯**一跳**并假定父即 formal run——修复/补证类子 run 挂在 sideflow 父下，解析出 (wf=sideflow-run, sc=c0caf640) 查店必然 0 条。修复：链式上溯至第一个非 sideflow 祖先（formal run），逐跳校验 team/question/project、seen 集防环，无 workflow_id 视为 formal（兼容既有契约）；回归测试二代链解析到 formal 祖先 + 环谱系拒绝，problem-context/lineage/sideflow-run 三套 44 绿。17:47 Launcher restart 加载。
- **补证闭环归因修正（避免重复烧预算的关键判断）**：6 个资料请求与知识回灌**实际经 run-1ca97605acf3 链完成**（ingestion-a3 succeeded 15:32 → handoff-a2 accepted → 父 run knowledge_result_absorbed 15:42，与 B.22 记录同源）；run-5a890f660097 是 05:04 触发的悬空孤儿（账本仅 run_created/knowledge_invocation_created 两事件，无任何下游等待），**明确不重试**——重试只会重复搜集与评审预算。knowledge_invocations 中历史 child_created/pending 孤儿多个（09-06 起），属该触发路径常态。
- **遗留（非本轮阻塞）**：run-1ca97605acf3 在 handoff_accepted 后由 graph dispatch 续走时命中确定性 resume 错误（期望 knowledge_ingestion-a2 回执、线程停在 evidence_relations-a3），状态 reconciliation_required；其业务使命（知识吸收）已完成，仅在 R3 再发 EVIDENCE_REQUEST、新补证子 run 挂其下时才可能形成阻塞，届时以「对账运行」（reconcile pass，⑳-b 已验证其级联接受能力）清理。CDP 事实：URL 直带 sideflow runId 会被前端规范化重置（「正在切换题目」），sideflow 视图须走画布 ksf_ 前缀节点入口。

### B.24 ㉓+2 纪要死锁实弹修复 + 预存红归属定案 + 收敛门机制全解 + 好候选重选启动（09-09 晚）

- **㉓+2（-rN 后缀候选引用绑定）实战闭环验证**：f5102d3289be40b3-d5cbe1f954-r3 纪要死锁现场（draft evidenceRequests=0 + validationErrors=[candidate_ref_unbound: sci-009-cbf2d6930-r3]）——approve 只重验已存草稿（approve_meeting_digest 对 draft.evidenceRequests 逐条重跑 validate_evidence_request_draft，13426-13432），旧 prepare 已把请求丢进 validationErrors，单纯确认永远 awaiting_approval。真实 UI 路径解锁：**退回重新整理**（decision=rejected → 服务端同稿重备）→ 新 draft 3 请求全部绑定 sci-009-cbf2d6930、零 validationErrors（修复前后同一 transcript 对照，㉓+2 生效铁证）→ **确认候选纪要** → r3 closed 12:28:27Z，请求 hfcr-005f1724 随即 handed_off。旧选择被 system:auto-advance:gate-blocked 记录 rejected 收口（预算 3/3 耗尽，12:38:16Z）。
- **预存红 test_approve_review_digest_rejects_mixed_source_type_contract 归属定案（非 e97a09c32 回归）**：main 上与 ㉓+2 无关地红。根因双层：① 该测试用 `_build_runtime`+`_seed_parent_run` 播种 formal run，fan-out 评审房因此带 workflow_discussion_scope.v1 → `_uses_structured_meeting_message` 判真 → 结构化 JSON 消息契约生效；② 自由标记 fixture 文本不再可摄取（message failed "not valid JSON"→ 全军覆没 → discussion_has_no_completed_messages → draft blocked）。而该测试要覆盖的**消费侧**拒绝（draft validationErrors + approve 关账拒绝）只存在于 preformal 房间路径（preformal_candidate_review_scope.v1）；**生产侧**同类枚举拒绝已有专属覆盖（tests/test_meeting_message_payload.py：test_meeting_rejects_requests_that_collection_cannot_consume 参数化 search_sourceTypes_invalid + test_native_schema_rejects_unknown_source_type_and_matches_ingestion）。修复 21a0a9b5d：移除 runtime harness 使房间回 preformal、fixture 回自由标记（结构化分支全部还原），31/31 绿；与姊妹测试 test_approve_review_digest_without_keywords_stays_open 口径一致。诊断中确认结构化 payload 契约细节：disagreements[]/actionItems[] 必须为对象（issue/positions/unresolvedReason、ownerRoleId/action/dueGate），risks/knowledgeCandidates 为字符串数组。
- **收敛门机制全解（chain_state :15186-15194，决定后续所有操作）**：`converged = 最新轮 closed ∧ 无 rejected 裁决 ∧ qualityStatus != failed ∧ (metaReview.accepted ∨ 人工裁决 accepted) ∧ 无 pending 搜集请求(run 域) ∧ (本轮无新证据请求 ∨ 人工裁决 accepted)`。关键推论：**凡本轮又产证据请求的轮次（迄今每轮都产），metaReview 接受也不够，必须人工裁决 accept**；而 claim 绑定物化（hypothesis 角色）只发生在人工 accept（_apply_human_acceptance_for_recommended_candidate + _materialize_recommended_candidate_claim_bindings 是唯一写入方）→ 缺一不可的两步：好轮收口 + 人工接受。pending 请求为 run 域过滤（formal readiness 传 workflowRunId），09-03/09-04 三个跨代 straggler（pending/failed）不拦本 run。hypothesis_design 阻塞详情中的 knowledge_package_not_materialized 是旧 attempt 的陈旧 problem 文案（kinv-65ff 15:42 已 accepted），下次 auto-advance 评估会消散。
- **好候选重选（当前进行中）**：五轮质量失败全部只挂在 sci-009-c020177fe（falsifier_targets_mechanism + scope_consistent 两项；cbf2d6930/c38102c57 5/5 全过，剔除科学上成立）。20:40 真实 UI 重选 hsel-56523bf700465ade = cbf2d6930 + c38102c57（勾选框 0/4，label 点击切换 React 状态），记录选择并开启评审 → 两房间 d5cbe1f954-r1 / 383aa49a73-r1 开跑，新选择预算 3 全新、pendingCollectionCount=0。预期序列：房间收口 quality-passed → 纪要确认 → 收敛面板人工裁决（理由 ≥ 必填 + 接受当前收敛结果）→ claim 物化 → converged → hypothesis_design 解锁。watcher 在岗监控两房间状态。
- **操作效率注记**：工作台页面会被应用导航重置回 chat 视图，CDP 会话需重挂 URL；「正在读取当前任务」骨架在 sweep 高负载时可挂 60s+，以 store 直读（meeting_rounds.jsonl / ledger 只读 URI）为准。

### B.25 双链深夜推进：SCI-009 收敛落地→打包五缺一→backfill 上线追踪；SCI-014 提炼复活与 completionResume 唤醒缺口（09-09 深夜–09-10 凌晨）

- **SCI-009 好候选重选走完全程并收敛**：B.24 重选（hsel-56523bf700465ade = cbf2d6930 + c38102c57）两房间评审连夜推进，共 10 个 closed 轮次，最终收敛轮 d-5b7c4802e0d5 于 09-09 14:55:06Z 关账且 metaReview accepted。随后真实 UI 点「结果打包」，readiness 门五件套（problem_understanding / hypothesis_set / dimension_reviews / stage1_research_plan / competition_alignment）判 **dimension_reviews 缺失**——run-332a539909a6 的 workflow_artifacts/dimension_reviews.jsonl 至今 0 条。
- **缺陷㉓+3：dimension_reviews 权威 write-once 无补写出口（已修 04528d75a）**：首写只发生在首轮生成路径 `_generate_hypothesis_round`（hypothesis_first_chain.py:12550 `materialize_dimension_reviews_authority`）；内容寻址的轮次复用永不重跑该函数，凡首写失败或旧构建产出的轮次永远缺权威 → stage-one readiness 永久卡 result_package_incomplete。修复：`auto_backfill_missing_round_authorities` 作为 sweep step zero-six 每题无条件执行——对 missing 的 reusable 轮次重放 `regenerate_hypothesis_round` 物化整套权威（零评审调用），带 fan-in 组同一性守卫（status=ready 且 meeting 集合相等才放行），失败 fail-closed 记 blocker、绝不伪造权威。
- **缺陷㉓+10：场景事件流不可检索=观测盲区（登记，未修）**：无 active-runtime-scene.json 时 `record_runtime_scene_event` 静默返回 None（record.py:2728 的 quietly 包装吞掉一切）；launcher state.json 的 runtimeSceneDir 为空、logs/runtime_scenes 只剩 08-21 旧快照 → sweep 全部 skip/fail 事件无落点。叠加应用层 logger 的 INFO 不进 backend.stdout（仅 uvicorn access log 可见），sweep 内部行为完全不可观测，本节取证只能靠只读复算+账本快照。修复方向：无活跃场景时降级写 per-team 有界滚动文件，sweep 关键 skip/fail 补 logger.warning。
- **缺陷㉓+4：source_collection_context_tool 30s 超时双杀提炼（已修 373448854）**：该工具装配 25 候选 × 记录原文块的受限快照，是有界重查询；通用 30s 工具预算在并行负载下必然截断——09-09 23:33–23:41 首次卡死与 17:18Z 重驱超时同根因（agent 第二次自行缩小请求自愈）。修复：`_timeout_map` 提到 90s（对齐 writeback 180s / research_knowledge_request 90s 重查询档），带镜像单测。
- **缺陷㉓+5：五工具描述含硬认知标记=closeout 阻断（已修 8abfa920f）**：`test_llm_facing_tool_descriptions_are_capability_contracts` 在 main 上预存红——Key_Tools.py 与 virtual_human_life_tools.py 五处描述含「必须」。改写为中性约束词（查询需服务于/仅可为/需先 propose 等），语义与运行时消息不动，245 相关测试绿。
- **SCI-014 提炼僵尸的 composer 续写恢复配方（operator 级恢复手段，记档）**：run-50d3e53c54de source_extraction a1 自 15:40Z 起僵死 running。产品会话面板显示「可继续」并渲染续写指引——经 composer 给阶段任务会话发明确续写指令（先 source_collection_context_tool 读最新 quotableSources 与修正要求 → 为每条 claims/keyFindings 补逐字 quote、sourceRef、来源内定位锚 → source_collection_stage_writeback_tool 回写 completed）→ agent 穿过 30s 超时自行缩小请求完成提炼，任务权威 8/8 completed 且 completionGate passed（01:23 回写）。配方有效前提=阶段任务会话可续写；记为平台恢复手段。
- **缺陷㉓+6：completionResume 僵死无系统/UI 出口（修复中）**：节点级唤醒死锁解剖——defer_completion 写 completionResume 游标；`wake_receipt_completion`（completion_dependency.py:132）要求 outbox 存在 adapter_dispatch(pending|failed) 行才可重挂唤醒，而 run-50d3e53c54de 从未产生该行 → 唤醒在结构上永不可能；消费路径（agent_turn_completion.py:1188 起 completion_resume 非空 → 重读 turn 终态 → source_collection 家族 `_stage_task_work_already_complete` 判任务权威 completed 即 reconcilable）只在 action 重执行时跑到；前端「重试」被 retry_not_available 锁死（attempt running 永不再判）。修复方向：对 completion_pending 且阶段任务权威已 completed 的 run 自动 redrive（复用 :1188 消费路径）。
- **缺陷㉓+7：exe start 转发间歇 exit 3（登记）**：exe start 对 live shell 转发两次失败（native_action.bridge_failed exitCode=3 forward_to_live_shell）；恢复手段=直接驱动 Launcher UI（a11y 点主实例行「停止」/「打开窗口」）。
- **缺陷㉓+8：env 无投递通道（登记+手册）**：workbenchBackend.ts:1361 的 extraEnv 参数无任何 caller（死钩子）；Electron 壳长期存活，backend 继承壳 env，exe start 只转发不重建。VIBELUTION_HF_ROUND_LIMIT=2 等运行时开关必须整壳冷启：托盘「退出壳并停止全部任务」→ 验 electron/pythonw 全归零 → 带内联 env 的 exe start（vibelution_env_restart.ps1 已备）。
- **缺陷㉓+11/㉓+12（登记）**：inspect_knowledge_collection 无可见效果且前端 onOffer(...).catch(()=>undefined) 吞错；直链 runId+node 的面板卡「正在读取」。慢命令 POST 60–150s 仅 isPending 无进度反馈（既有）。
- **重启与验证计划（进行中）**：修复合入后整壳冷启带 VIBELUTION_HF_ROUND_LIMIT=2；行为验证=state-v2 的 roundBudget（selections/latest 探针对两种上下文均 403，弃用）；双链恢复=SCI-009 backfill 物化后真实 UI 重试结果打包 → 人工门（若浮现）→ 结果核验；SCI-014 extraction 节点唤醒 → 证据关系 → 知识入库 → 知识包交接（UI 人工确认）→ absorbed → hypothesis_design 解锁 → 接地 R1。B 线父 run 预检：除知识链+R1 外无其他 blocker。
- **最终数字（待补）**：

- **缺陷㉓+6 修复合入（ff1c8c6d3，已亲审）**：`redrive_authority_complete_completions` 挂 AdapterDispatchWorker 修复 tick（常驻维护循环，runtime_factory.py:170 链），SQL 枚举 blocked+agent_completion_dependency_pending 的 run；前置只读校验（source_collection family + `_stage_task_work_already_complete` + 游标 turn 已 terminal）全过才在单事务内重挂 failed 行（与 wake_receipt_completion 同构：requeue + 解除 blocked + node_completion_resumed 事件，redrive 标记），幂等。修正早前判断：failed adapter_dispatch 行其实存在（envelope id ≠ payload actionId 属设计），真死因是回执随产它的进程死亡永远无法送达。配套回执门唯一放宽：resume 到已过 completionGate 的完成工作时缺失回执记结构化 warning 场景事件（默认参数关闭，fresh 路径零改动）。亲跑 8 新用例 + 122 相关回归全绿。run-50d3e53c54de 将在下个维护 tick 被自动收口。
- **缺陷㉓+3 追加定案（3a4487413，已亲审）：backfill 静默两层根因 + 系统性契约漂移**：生产数据沙箱 dry-run 证实——① 重放入口在 dedup 前解析真实评审 runners，正式轮的 server-owned receipt authority 遇配置不可解析即被 formal fence 拒绝（修复：`replay_only` 贯穿 generate/regenerate，dedup 未中即抛结构化 ReplayMiss，绝不退化为烧预算新生成；replay 路径跳过 runner 解析）；② 穿透后写入器对真实数据确定性 fail-closed：`inputSnapshotHash` 在现架构无真实来源（唯一成功记录来自已退役旧 live-node 物化器）、评审行证据引用为裸 candidate-* 非 canonical——**当前链路生成的任何评审轮都无法首写 dimension_reviews**，属独立系统性缺陷（㉓+13，修复派发中）。同时为 backfill 全部 skip/fail 路径补 logger.warning（scene sink 生产不可用时日志是唯一落点）。85 测试亲跑全绿。
- **缺陷㉓+13：dimension_reviews 写入器与数据生产链系统性契约漂移（修复中）**：SCI-091 存量成功记录（2 条）显示目标形态=双哈希（inputHash/inputSnapshotHash 各 64-hex）+ canonical typed refs（hypothesis_selection:/meeting_round:/collection_request:/hypothesis_candidate:）。修复方向：轮次生成时计算并持久化有权威定义的快照哈希（确定性、可复算），存量轮裸 candidate 引用若能经纯函数映射到真实候选店对象则 backfill 合法救活，任何一环缺失保持 fail-closed。此缺陷同时挡 SCI-009 打包与 SCI-014 未来收敛，是两条链的共同 P0。

### B.25 续：round-limit 杠杆改走代码默认值合入；退出壳三缺陷族定案；completionResume 生产实弹验证成功（09-10 晨）

- **缺陷㉓+13 修复合入（f732499e8，已亲审）**：dimension_reviews 写入器输入绑定改为推导式——`inputSnapshotHash` 由轮次权威输入确定性推导，评审行证据引用由裸 `candidate-*` 映射为 canonical typed refs，fail-closed 写入器从此可接受链上轮次。回归绿；行为验证待 SCI-009 backfill 物化后重试结果打包。
- **环境投递路线废弃 + round-limit-2 改代码默认值合入（88c4349dd）**：㉓+8 的 env 冷启路线在实践中被证明不可达（退出壳无合成输入可用的正门，见㉓+14/㉓+15），遂改走更干净的同效路径：`_HARD_ROUND_LIMIT_DEFAULT` 3→2（`hypothesis_first_chain.py:50`，带恢复注释），env 钳制语义原样复用（窗口变 [1,2]，env=3 按设计回落 2）。三个场景测试套件以 autouse monkeypatch 钉住历史 3 轮边界契约（test_challenge_review_budget_consistency / test_hypothesis_first_state_v2 / test_research_workflow_hypothesis_first_chain，含 `fixed at 3` 消息级断言与 5 轮 legacy link 场景），env-resolution 测试改为对 `_HARD_ROUND_LIMIT_DEFAULT==2` 断言。聚焦 427 测试绿；LOCAL_ONLY 复用证据记录；closeout 合入 main，验收结束后须恢复 3 并同步改回三处 pin 注释。
- **缺陷㉓+14：托盘菜单 IPC 门控设计=单点死锁（登记，未修）**：`desktopTray.ts` 的 `tray.on("click")` 与 `tray.on("right-click")` 均 preventDefault 后走 `refreshMenu(true)`——await `listInstances()`/`getFreshness()`（Promise.allSettled）之后才 `tray.popUpContextMenu(menu)`。该 IPC 一挂，托盘菜单永久不可用，且产品内无第二退出壳入口：web/queue 车道刻意不近似（workbench_controller 注释明示 close_workbench+stopManager 不转发）、窗口关闭永不退壳（window-all-closed 保活）、CLI 无 shutdown 命令、`app.relaunch()` 继承同进程 env。修复方向：refresh 失败/超时回退 `tray.setContextMenu` 静态菜单（退出项直连 requestDesktopShellExit），IPC 门控只影响动态实例子菜单。
- **缺陷㉓+15：批准的桌面壳退出零执行（登记，未修）**：经 CDP（壳 `--local-debugging`，`localDebugging.ts:32` 对本壳常开；launcher 页 preload 暴露 `window.vibelutionLauncher.requestDesktopShellExit()`，即托盘退出项同一函数，`assertTrustedIpcSender` 校验通过）调用返回 `{allowed:true, reason:"no_active_work", stopPythonLauncher:true}`，但 runApproved 零效果：`electron.runtime.stop_requested` 等事件零落盘（recordElectronSupervisorEvent 全被 `.catch(()=>undefined)` 吞=㉓+16 观测缺陷）、`main_line_intent.json` 未写、后端持续服务、壳存活；15s 外预算/8s 步预算的可观察效果均未出现。eval 以决策对象先行返回而内层 IIFE 裸奔的结构（requestDesktopShellExit → desktopLifecycleCoordinator.request → executeShutdownAuthorizationBoundary）使该缺陷无法从外部判定成败。
- **缺陷㉓+16：Electron supervisor 事件通道静默失效（登记，未修）**：recordElectronSupervisorEvent 在本实例从未写入任何 `electron.*` 事件（events.jsonl 全量 grep=0），launcherBootstrap 上下文失败被无条件吞掉，㉓+15 的取证只能靠运行时文件复算。修复方向：bootstrap 缺失时降级写 launcher 控制面日志并至少 console.warn 一次。
- **缺陷㉓+17：lifecycle intents 无跨壳孤儿回收（登记，未修）**：lifecycle.sqlite3 中 `request_app_exit` executing 自 09-09 16:43Z（上一壳实例死亡中断，永不停靠）、`restart_after_apply` executing 自 08-28（12 天）无人收割；inbox 中 16:43Z 的 close_workbench 命令（cmd_20260909T164304Z）永不消费。壳重启不清理前任 executing intents，新请求与僵尸记录共存。
- **运维发现（本机输入注入边界，手册级）**：SendInput/UIA Invoke/Win+B 组合均无法驱动 Win11 托盘按钮与任务栏 XAML 表面（SystemTray.NormalButton 不响应注入；CUA raw 被拒或无效；仅时钟 flyout 偶尔可达）；UIA 枚举可得精确 rect——托盘条 y=1380，Vibelution 按钮 (1802,1380,40x60)，完整地图（Tailscale 1722 / ZCode 1762 / OneDrive 1842 / 安全中心 1922 / 电源 2387 / 时钟 2427 / 显示桌面 2545）。托盘流程在本环境不可交付=㉓+14 的实际放大器。`vibelution://launcher/focus` 深链可靠唤出隐藏 Launcher 窗口；`Start-Process 'vibelution://launcher/focus'` 可用，exe 带 URL 参数调用无效。
- **completionResume 生产实弹验证成功（㉓+6 修复 ff1c8c6d3 行为证明）**：21:38:47Z restart（accepted，14s 结算）→ 新后端 pid 32212 于 05:38:54 起 → 44 秒后 session-20260910-053938-521648 创建（source=agent_inbox，leases=worktree_write+memory_write）→ run-50d3e53c54de 的 source_extraction agent 真实复活，live_output stage=model_thinking，思考内容正是「沿用现有 checklist、分批 writeback、以 coverageSummary/completionGate 为准、修复 danglingEdgeCount=1」——僵尸提炼被系统自动唤醒，与 ㉓+6 设计路径（AdapterDispatchWorker tick 重挂 failed 行 → node_completion_resumed）一致。chat_turn work_run 快照呈 needs_continue 每 ~6 分钟自续（auto-continue 机制），期间 active-work guard 生效：21:42:09Z 第二次 restart 被正确拒绝（active_work_blocked，290ms，「有进行中的任务，无法重启 Vibelution」）。运维推论：**回驱工作运行中不得 restart**；后端换代码窗口=人工门间隙（gate 态不占 active work）。
- **当前时序事实（下一步 restart 的依据）**：本窗口 merge（88c4349dd 检出 05:39:50）晚于后端进程启动（05:38:54）56 秒——活后端仍在旧代码（roundBudget=3）；active run 为 source_collection 阶段（不消耗评审轮），budget 2 将在下一 restart 窗口生效并由 state-v2 roundBudget 行为验证。

### B.25 续二：㉓+13 修复实弹验证翻案——canonicalizer 无法解析 claim 级引用=回填永久 blocked（09-10 晨）

- **缺陷㉓+18（f732499e8 的残留层，本轮定案）**：后端 05:55:28 重启加载 3a4487413+f732499e8 后，backfill sweep（30s 节拍）对 SCI-009 每 30s 实跑一轮，backend.stderr.log 留下 89 条 auto_backfill_round_authorities 记录——不再是静默，但结果全部 fail-closed：`authority_still_blocked blockers=['dimension_review_evidence_ref_invalid','dimension_review_evidence_refs_missing']`（SCI-013/020/024/034/046 另叠加 nodeRunId/workflowRunId/workflow_authority_missing 绑定级缺口，非同族）。根因（只读复算定案）：评审行 evidence_refs 是 reflection LLM 铸造的 claim 级 id（如 `candidate-20260908171716-ce855d14`），而 canonicalize 的解析谓词只按 `ClaimEvidenceStore.list(candidate_id=citation)` 查——该 id 既非证据卡 candidateId（= `sci-009-*` 假说 id 或部分 origin id）也非 claimId（= `claim-<hash>` 格式），永远解析不到 → 裸引用原样透传 → writer 判 invalid；另有整行零引用（_refs_missing）。10 个 closed 轮中 3 个另被 fan_in_group_moved 组同一性守卫跳过（设计行为）。生成路径（hypothesis_rounds.py:939）落盘前走同一 canonicalize，故该缺陷同时封锁存量回放与新轮首写——修复面收敛到 `dimension_reviews_input_binding.canonicalize_dimension_review_evidence` 一处。
- **㉓+18 修复合入（3d5251a32，已亲审）**：行级两层投影——① 可解析引用保留、不可解析裸引用剪枝出 evidence_refs（原引用全量保留在新行字段 citationRefs + report.unresolvedRefs，落盘 artifact 因 writer 六字段重建不含原始引用，审计链=存储轮原始行+authority 结果报告）；② 解析后零引用的行回退到该行 hypothesis 自身证据卡批次引用（卡→sourceCollectionRunId→evidence_batch_ref_for_run，与唯一存量成功记录 SCI-091 的 source_candidate_batch:// 粒度同构）；假说无卡 → 行保持空、writer 继续 fail-closed（契约保留）。幂等：canonical 行直通不增字段。
- **SCI-009 画布全量事实（收敛已完成，仅差打包）**：假说收敛门=人工确认·已完成（假说集已收敛）；假说选择=人工确认·已完成（2 候选）；假说评审「2 轮有效评审 · 3 次失败重试 · 最近第 2 轮」=roundBudget=2 的直接 UI 行为证据（88c4349dd 生效）；资料补充 26 请求·当前步骤已完成。结果核验 0/1 已阻塞的唯一 blocker=result_package_incomplete=dimension_reviews 缺失。闭环序列：修复合入→安静窗重启→回填物化（workflow_artifacts/dimension_reviews.jsonl 出现 run-332a539909a6 行）→真实 UI「重试 结果打包」→结果核验。
- **运维事实补充**：05:55:28 restart #3 后活后端 pid 35716（web_workbench.py）已含 round-limit-2；重启后工作活跃（sessions 每 ~30s 新建，05:39 会话完成 danglingEdge 修复后续跑）——确认「回驱工作运行中不得 restart」，换代码窗口须等人工门间隙。跨题噪声：工作台「正在进行」横幅显示的 hsel-165019c4 评审会属 SCI-056（09-04 选择），非 SCI-009 新预算消耗。

### B.25 续三：双修复实弹验证全线贯通——回填物化+relations 重驱+知识包自动交接；㉓+20 打包证据域定案（09-10 晨）

- **㉓+18 生产验证（restart 06:34:47 加载 3d5251a32+6746151b9 后 90s 内）**：dimension_reviews.jsonl 2→7 行——SCI-009 run-332a539909a6 四条权威（含决定轮 hround-5b7c4802e0d5）+SCI-003 一条（顺带修复）+两条 SCI-091 存量。链上轮次首次通过 fail-closed 写入器物化。三个 fan_in_group_moved 轮仍按组同一性守卫跳过（设计行为）。
- **㉓+19 生产验证（B 线证据关系重驱全链）**：真实 UI 知识子流程面板（「重试 证据关系」）第一次点击在面板加载中触发 `retry_not_available`（运维注记：面板「加载知识节点」完成前 offer 未就绪，须等待后重试）；第二次点击 retry_node accepted（06:47:47，run-50d3e53c54de evidence_relations）→ 同会话（session-20260910-053938，completionResume 唤醒的那个）重驱回合 ~4 分钟完成「全新干净写回」（全部真实 candidateId/themeId + 4 个 canonical claimEvidenceId）→ 任务 completed（22:51:33Z），新图 candidate-graph-…225109 dangling=0/missing=0 → **知识入库 completed**（22:58:32Z，6 条 approved 候选过治理门禁写入正式知识项：SPRITAM FDA 批准/Nature Reviews 2024 综述/荷兰实施案例等）→ **知识包交接由 system:auto-advance:knowledge-handoff 按运营自动化策略自动 accept**（07:00:24，「source review accepted + knowledge review approved」）→ sideflow run-50d3e53c54de 整体 **succeeded**。诚实注记：本实例由重试+干净写回解锁（晋升代码属纵深防御，生产未走到该分支，单测已锁定其行为）；㉓+6 completionResume 修复的会话在重驱中再次担任执行载体。
- **SCI-014 当前态**：正式 run-1b64401aa16a 阻塞因子 knowledge_package_not_materialized 应随交接消散，剩 hypothesis_round_unconverged——B 线假说评审轮将在 roundBudget=2 下自动推进（画布已显示「2 轮有效评审」为 A 线同口径证据）。
- **缺陷㉓+20（打包证据域，修复在途）**：真实 UI「重试 结果打包」命令 accepted（06:43:29）后打包尝试执行、仍报 `canonical artifact is missing: evidence_card_batch` 并持久化为 run 阻塞问题。只读复算定案：formal run input_snapshot.sourceCollectionRunId=dprun-20260908162239665012-2cd75f2c（早期搜集 run）名下 0 张 claim-evidence 卡；SCI-009 的 104 张卡分布在 6 个后续搜集 run（26 次资料请求跨 run 积累，设计行为）；`_load_scoped_evidence` 严格单 authority 域 → 永远 None。修复方向=从 materialized dimension_reviews 的 evidence_refs（evidence_card_batch://<dprun>）推导评审实际引用的 run 集合并聚合读取，孤儿门以 hypothesis_set 候选作第二权威来源，两处都找不到仍 fail-closed。
