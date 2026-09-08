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
