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
