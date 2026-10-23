[← 上一部分](04-modules-and-learning.md) · [教程目录](README.md) · [下一部分 →](06-durable-systems.md)

# 配置、调度、授权、压缩与模型恢复

## 25. 核心机制精读入口：从目录到运行边界

第 25—41 章深入调度、取消、授权、协议恢复、文件回退与可靠性。先判断每段代码拥有哪项事实、失败怎样分类，再沿调用链阅读。

阅读每个机制时统一问六个问题：**入口是什么、输入带什么身份、谁允许修改什么状态、输出是什么、失败怎么收场、哪个测试能证明它。** 文中短代码“源码摘录”只用于解读真实语句；“教学伪代码”只画流程，不等于可调用的产品 API。

优先级标记：P0 表示普通对话运行就依赖的关键机制；P1 表示多任务/长期运行的重要机制；P2 表示特定高级业务依赖，不代表不重要。这个划分是阅读顺序，不是作者的缺陷评级。

| 精读主题 | 优先级 | 先看代码 |
| --- | --- | --- |
| Agent 配置身份与修订 | P0 | `agent_config_authority.py`、`agent_directory/repair_store.py` |
| Session 准入/调度/排队/停止 | P0 | `session/admission_lock.py`、`schedule.py`、`queued_turns.py`、`control.py` |
| 工具执行、审批、沙箱 | P0 | `tool_executor.py`、`tool_authorization_service.py`、`codex_cli_sandbox.py` |
| 上下文预算、压缩与稳定投影 | P0 | `context_assembler.py`、`microcompact.py`、`projection_stickiness.py` |
| 协议恢复、路由、用量 | P0 | `semantic_messages.py`、`provider_replay_state.py`、`resilience_policy.py` |
| 多模态、分支、文件回退 | P1 | `image_attachments.py`、`fork_session.py`、`file_change_ledger.py` |
| 后台任务、恢复、关机 | P1 | `runtime_task_registry.py`、`startup_recovery.py`、`lifecycle.py` |
| Ledger、进化、评估、感知 | P1/P2 | 工作流 Ledger、evolution services、agent_perception |
| 前端一致性、外部执行、诊断 | P0/P1 | URL selection、active-turn、CLI/CUA、trace/TTFT |

### 25.1 先更正：Agent 配置主数据并不等于 SQLite 配置表

沿实际写路径区分配置主数据、引用和历史快照：

```text
可编辑 Agent 主配置：workspace/agents/agents.json
    → Agent directory canonical mutation / save_state
    → canonical config identity（hash / revision / schema）
    → 会话目录中的 Agent 引用与不可变 compiled snapshot

编辑过程证据：agents/<id>/events/config_changes.jsonl
会话引用的配置快照：SQLite agent_config_revisions
一次 Turn 的执行参数：接受时冻结的历史快照
运行对象缓存：内存中的 AgentRuntime 条目
```

这几份内容不是“五个可以任选的真源”。主配置可编辑；编译快照供会话关联和审计；草稿事件记录编辑过程；Turn 参数描述当时执行条件；内存缓存负责效率。修改草稿不应悄悄改变运行配置，旧快照也不能反向覆盖用户新设置。

真实路径函数摘录：

```python
def registry_path(*, project_root: Path | None = None) -> Path:
    s = _service()
    with s.scoped_project_root(project_root):
        return s._workspace_path("agents", "agents.json")
```

第一行允许指定项目；scoped_project_root 绑定这次操作的根；最后通过工作区路由取得文件，避免不同实例读错同一份配置。SQLite 的 `agents`/`agent_config_revisions` 是目录控制面的一部分，不能据此称为可写 Agent 配置的替代主库。

源码定位：[core/web/services/agent_directory/ops_residual.py · registry_path](../../../core/web/services/agent_directory/ops_residual.py#L1918)；[core/web/services/agent_directory/repair_store.py · save_state](../../../core/web/services/agent_directory/repair_store.py#L2803)；[core/web/services/agent_config_authority.py](../../../core/web/services/agent_config_authority.py)；[core/web/services/agent_config_change_service.py](../../../core/web/services/agent_config_change_service.py)。

### 25.2 configHash、configRevision、schemaVersion 分别防什么

- **schemaVersion**：这份配置按哪个结构解释，不是模型版本。
- **configHash**：canonical payload 的内容身份；无关显示/缓存字段不应任意污染这个身份。
- **configRevision**：配置变更谱系/CAS 的版本号；只重新读一遍不能随便增加版本。
- **permissionPreset**：映射成实际沙箱和审批策略；不能只按 UI 标签猜执行能力。

`save_state()` 对已建立身份的 Agent 规范化、计算身份、检查异常缩减、原子保存并使缓存失效；它明确不自行推进 revision，修订推进由正式 mutation API 拥有。`load_state()` 使用“路径、存在性、mtime_ns、size”等签名验证缓存，返回独立副本，避免调用者直接改到共享缓存对象。

**运行缓存退休也是核心。** `session/agent_runtime_retirement.py` 处理旧 runtime 的引用与退休。Agent 配置变化后，不能一边关闭旧对象，一边让正在使用它的任务继续调用已经关闭的资源。

源码定位：[core/web/services/agent_config_authority.py · canonical_agent_config_payload](../../../core/web/services/agent_config_authority.py#L83)；[core/web/services/agent_config_authority.py · materialize_agent_config_identity](../../../core/web/services/agent_config_authority.py#L158)；[core/web/services/session/agent_runtime_retirement.py](../../../core/web/services/session/agent_runtime_retirement.py)。

自测：为什么 configHash 一样不一定代表草稿事件相同？为什么刷新配置页面不应增加 configRevision？为什么不能在 SQLite 快照表里 UPDATE 一行来“改 Agent”？

## 26. Session 运行控制：准入、排队、调度与停止

### 26.1 需要经过三种“门”

```text
请求到达
  → Session admission：允许这轮进入吗？是否重复/忙/只读？
  → Scheduler/executor：何时有执行槽和线程？
  → Provider route gate：何时允许发模型请求？
```

前者管业务一致性，中间管本地运行资源，后者管模型路由并发。三者不可合并为一个“running=true”。任务已被接受但还没得到线程，和已经连上模型但在等待输出，是两种等待。

`SessionAdmissionLock` 同时保护同一项目/会话的跨进程准入；它与 Journal 的追加锁不同。追加锁保证一行不被两个写者写坏，准入锁保证“检查是否空闲→打开 Turn→调度”的组合不会同时被两个后台接受。

教学伪代码：

```python
with session_admission_lock:
    check_submission_identity()
    check_no_conflicting_live_turn()
    freeze_turn_parameters()
    append_acceptance_events()
    schedule_turn()
```

源码定位：[core/web/services/session/admission_lock.py · SessionAdmissionLock](../../../core/web/services/session/admission_lock.py#L29)；[core/web/services/session/submit.py · submit_session_message](../../../core/web/services/session/submit.py#L1395)；[core/web/services/session/schedule.py · _schedule_session_turn](../../../core/web/services/session/schedule.py#L111)。

### 26.2 schedule 为什么不是直接 Thread(target=run)

`schedule.py` 适配现有 SessionTurnScheduler、执行器交接、外部 Agent/Session 槽位预约和释放。跨服务的群聊/外部任务也要声明自己占用了谁，不能绕开主调度偷偷同时执行同一任务。

`_submit_scheduled_session_turn()` 先登记 executor watchdog，再交给 executor：空闲线程可能立即拿到任务，若先 submit 后登记，worker 已启动却查不到登记，会造成误报或遗留状态。主动消息在正式准入竞争中让位给用户任务时，可以释放临时槽位后重新排到后面。

源码定位：[core/web/services/session/schedule.py · _submit_scheduled_session_turn](../../../core/web/services/session/schedule.py#L119)；[core/web/services/session/schedule.py · reserve_session_execution_slot](../../../core/web/services/session/schedule.py#L75)。

### 26.3 Queue 与 Guide 是两种交付方式

`queued_turns.py` 保存已接受但需要以后执行的输入，支持编辑、删除、重排、暂停和 drain；它保存可恢复的附件 metadata 与模型参数，不只是浏览器里的待发送数组。当前普通排队用户消息有上限，具体见常量。

`turn_steer.py` 记录 guide/queue 的准入事件。Guide 试图进入正在执行的 Turn；如果它写入时原 Turn 恰好终结，系统不能直接丢掉输入，而是保留同一 steerId，记录 delivery_changed 并转入 queue。后续提升为新用户消息时再记录 promoted。

```text
guide admitted ──当前 Turn 仍开放──→ 本轮引导
       └────写入输给终态竞争────→ delivery_changed → queue → promoted
```

steer 元事件本身不是第二份模型可见正文；真正的 user-message 投影仍是唯一对话内容入口。队列的 queued/starting/blocked 等操作状态也不等同于 Turn 的 completed/failed/interrupted。

源码定位：[core/web/services/session/queued_turns.py · enqueue_session_queued_turn](../../../core/web/services/session/queued_turns.py#L197)；[core/web/services/session/turn_steer.py](../../../core/web/services/session/turn_steer.py)。

### 26.4 为什么排队项需要 claim 与恢复

drain 先认领一行，再尝试提交。如果进程在认领后崩溃，行可能停在 starting；直接忽略会永远不执行，直接重放又可能重复执行。因此有过期认领识别、幂等 dispatch 身份、busy 竞争处理和有限自续排机制。要从已有准入/Journal 证据判断结果，不是发现 starting 就立即再开一个任务。

### 26.5 停止按钮首先发“停止意图”

`request_stop_session_turn(session_id, expected_turn_id, fast_ack, cascade)` 的关键顺序是：校验当前 Turn 身份→先通知 controller→处理级联/排队状态→由 worker 在取消或协作检查点收口。

`fast_ack` 让 HTTP 快速确认停止请求，避免先构建很大的历史 detail 导致按钮很久没反应。它不等于进程已经物理退出。默认 cascade 会处理该会话的活动后代任务，并封住迟到结果通知，避免停止后又被子任务唤醒。

源码定位：[core/web/services/session/control.py · request_stop_session_turn](../../../core/web/services/session/control.py#L45)。

练习：画出“已接受→等执行槽→正在调模型→等待工具审批→请求停止→实际终结”的状态线，分别标明哪些状态属于 HTTP、scheduler、controller、Journal，而不是凭 UI 一个绿圈推断全部事实。

## 27. ToolExecutor、审批与权限：把“工具可调用”拆开

### 27.1 execute 的真实输入输出

真实签名与返回约定：

```python
def execute(self, tool_name: str, tool_args: dict,
            *, tool_call_id: str = "") -> tuple:
    # 返回 (result, action)
    # action 可以表达 restart、hibernated、tool_budget_exhausted 等控制意图。
```

它不只是 `func(**args)`。入口解析参数、读取当前 Agent/Session/Turn 身份、绑定 callId、检查 canonical authorization，再处理工具能力/参数/运行约束、执行、超时取消、结果分类与事件。`(result, action)` 中 action 还会影响上层生命周期，因此不能只把 result 字串拿出来后忽略另一半。

源码定位：[core/infrastructure/tool_executor.py · ToolExecutor](../../../core/infrastructure/tool_executor.py#L678)；[core/infrastructure/tool_executor.py · execute](../../../core/infrastructure/tool_executor.py#L872)；[core/orchestration/tool_lifecycle.py](../../../core/orchestration/tool_lifecycle.py)。

### 27.2 权限不是只看 allowedTools 列表

`evaluate_tool_policy()` 是纯、确定性的 deny-first 策略评估器，输入包括 Agent policy、工具描述、Turn grant 等；宿主安装本轮执行授权上下文。真正执行时 `authorize_tool_execution()` 复核：

1. 是否有当前 Agent 身份与可信决策；
2. callId 是否存在；
3. 决策是否属于这个 Agent、Turn；
4. configRevision/configHash/permissionPreset 是否匹配冻结配置；
5. 工具是否在 executable_tools；
6. 插件、委派、协作模式、额度和审批等额外约束。

源码中拒绝码例如 missing_decision、missing_call_id、agent_mismatch、turn_mismatch、agent_config_mismatch、tool_not_executable。它们不是所有情况都应该显示成“模型出错”。

源码定位：[core/authorization/tool_policy_evaluator.py · evaluate_tool_policy](../../../core/authorization/tool_policy_evaluator.py#L148)；[core/authorization/tool_authorization_service.py · install_execution_authorization](../../../core/authorization/tool_authorization_service.py#L680)；[core/authorization/tool_authorization_service.py · authorize_tool_execution](../../../core/authorization/tool_authorization_service.py#L781)。

### 27.3 必须看实际分支，不能被旧注释误导

该授权模块开头还有 “Shadow-mode” 历史表述，但实际 Agent 执行路径有 enforced 决策和明确拒绝。反过来也不能写成“每个调用永远都 fail-closed”：函数对没有 runtime_agent_id 的宿主 system_context 返回 `allowed=True, enforced=False`。

这说明安全边界还依赖**谁能够建立可信 runtime context、哪条入口可以调用宿主能力**。不能把 system_context 当用户请求可任意选择的权限档，也不能只读一句 docstring 就宣称系统已经全面强制或全面未强制。

### 27.4 一次性、会话、长期授权不同

`session/tool_approvals.py` 协调 live Turn 的审批。accept 是本次；acceptForSession 等有进程/会话范围；acceptAlways 的持久 grants 写入所属 Agent ToolPolicy。部分桌面/CUA 动作明确固定逐次审批，不能由“本会话一直允许”扩大权限。

审批绑定工具/参数等身份。等待审批时应响应取消；用户拒绝与模型参数错误是不同业务结果。计划模式也是实际约束：`session/collaboration_mode.py` 持久保存状态，`core/authorization/collaboration_mode.py` 在工具调用前做模式判定，而非只在 Prompt 里说“先别改”。

源码定位：[core/web/services/session/tool_approvals.py](../../../core/web/services/session/tool_approvals.py)；[core/authorization/collaboration_mode.py](../../../core/authorization/collaboration_mode.py)。

### 27.5 超时不代表线程被杀掉

Python Future 超时通常只是等待方停止等，并不保证执行线程停止。项目用 `tool_execution_scope.py`、协作取消事件、owned executor 和迟到结果 reconciliation 跟踪仍存活的执行；对子进程工具还要回收进程树。

因此某个工具显示 timeout，不应立即假设外部写操作没有发生。重试具有副作用的动作前，需要核对真实结果和幂等性。

源码定位：[core/infrastructure/tool_execution_scope.py](../../../core/infrastructure/tool_execution_scope.py)；[core/infrastructure/tool_executor.py · _attach_abandoned_future_reconciliation](../../../core/infrastructure/tool_executor.py#L104)；[core/infrastructure/owned_executor.py](../../../core/infrastructure/owned_executor.py)。

## 28. 沙箱、文件路径、进程与出站 URL

### 28.1 权限预设如何变成执行参数

`permission_runtime_contract()` 当前把 request_approval/auto_review 映射到 workspace_write 与 on_request；区别在审批方。full_access 对应 danger_full_access 与不请求该层审批。**这些是本项目受配置控制的执行合同，不是本教程在建议开启全权限。**

模型调用 `exec_command` 时不应自行决定 Windows/Linux 或替换沙箱 backend；宿主从冻结 runtimePermissions 解析，再由 `codex_cli_sandbox.py` 和 `codex_sandbox/` 适配平台。

源码定位：[core/web/services/agent_config_authority.py · permission_runtime_contract](../../../core/web/services/agent_config_authority.py#L59)；[core/infrastructure/codex_cli_sandbox.py](../../../core/infrastructure/codex_cli_sandbox.py)。

### 28.2 为什么要分 resolver、shell、environment、process

| 模块 | 输入/输出职责 | 守住的边界 |
| --- | --- | --- |
| resolver | 环境配置、PATH → 本机 Codex 可执行文件 | 显式路径错误时失败，不偷偷换未知可执行文件 |
| shell | 平台、命令、沙箱模式 → argv | shell 引号与参数属于代码语义，不能随意拼接 |
| environment | 父环境 → 清理后的子环境/临时目录 | 默认剥离 Provider/API/token/secret/SSH 等凭据环境项 |
| process | argv/运行参数 → 子进程及退出 | 无可见控制台、进程组/树回收 |

本机命令运行失败有时是缺少可验证沙箱，不是缺少 Python。Windows 离线 shell 隔离未通过验证时存在明确拒绝路径；不能为了让工具“跑起来”就删除拒绝条件。

源码定位：[core/infrastructure/codex_sandbox/resolver.py](../../../core/infrastructure/codex_sandbox/resolver.py)；[core/infrastructure/codex_sandbox/shell.py](../../../core/infrastructure/codex_sandbox/shell.py)；[core/infrastructure/codex_sandbox/environment.py](../../../core/infrastructure/codex_sandbox/environment.py)；[core/infrastructure/codex_sandbox/process.py](../../../core/infrastructure/codex_sandbox/process.py)。

### 28.3 可信路径不等于字符串 startswith

路径约束需要处理绝对路径、`..`、盘符、符号链接/重解析点与最终解析后的包含性。`path_containment.py`、developer_sandbox、附件 store 和各领域 loader 负责各自边界。`F:/work2` 在字面上以 `F:/work` 开头，却不是它的子目录，就是简单 startswith 的反例。

不要把“开发 worktree 隔离”和“操作系统沙箱隔离”混为一谈：前者分离 Git checkout，后者限制进程可访问资源；它们可以同时使用，互不替代。

源码定位：[core/infrastructure/path_containment.py](../../../core/infrastructure/path_containment.py)；[core/infrastructure/developer_sandbox.py](../../../core/infrastructure/developer_sandbox.py)。

### 28.4 进程树必须有 owner

`OwnedProcess` 在 Windows 使用 Job，先以挂起方式创建、分配 Job 再恢复；POSIX 使用独立进程会话。这样父程序退出后，不能只因为根 PID 已死就判断所有后代都结束。

`OwnedThreadPoolExecutor` 也记录 admission 关闭、Future、仍活着的 worker 和失败。`closed=True` 的定义需要考虑实际存活资源，而不是简单调用一次 shutdown 后改一个布尔值。

源码定位：[core/infrastructure/owned_process.py · OwnedProcess](../../../core/infrastructure/owned_process.py#L15)；[core/infrastructure/owned_executor.py · OwnedThreadPoolExecutor](../../../core/infrastructure/owned_executor.py#L11)；[core/infrastructure/windows_process_job.py](../../../core/infrastructure/windows_process_job.py)。

### 28.5 URL guard 的作用与局限

`url_guard.py` 对模型可控的出站 URL 做字面目标校验，包括 localhost、私网/特殊 IP、IPv4-mapped/NAT64 等情况；模块明确不做 DNS preflight，避免某些网络下提前解析阻塞。重定向逐跳检查等责任仍在具体 fetch 入口。

所以正确结论是“有明确的 URL 出口策略与分层职责”，不能只因为引入该文件就声称所有 DNS rebinding/重定向问题已经被统一彻底解决。它与前端调用本机 FastAPI 的 control token 也不是同一道门。

源码定位：[core/infrastructure/url_guard.py](../../../core/infrastructure/url_guard.py)；[tools/web_search_tool.py · web_fetch](../../../tools/web_search_tool.py#L1087)。

## 29. 长上下文的四层治理：预算、结果限长、微压缩、摘要

### 29.1 先数清几种不同预算

模型上下文窗口、一次输出上限、Prompt 各章节预算、工具结果字符预算、每 Turn 工具调用次数、研究工作流 token/call reservation 是不同限制。一个输入窗口很大的模型仍可能被很低的输出上限截断；工具只调用三次也可能读回几万行文本。

`context_input_metering.py`、`context_assembler.py`、Prompt assembly resolver、`tool_result_budget.py` 分别在不同边界计量/裁决，不能把 UI 上一个数字理解为所有预算的同一总开关。

### 29.2 工具结果先做有界展示，不等于删除原始事实

`tool_result_budget.py` 对已声明预算的工具应用 truncate 或 artifact 策略，区分模型可见长度与 inline 长度；未声明工具保持既有行为。artifact 策略把完整输出保存成受控产物，并返回预览/引用；落盘失败有明确降级与审计，而不是把成功工具伪报为业务失败。

需要区分“业务工具结果是否成功”“完整输出是否保留”“模型这次实际看到了多少”。这正是一个命令成功，但 AI 只看到日志末尾的常见原因。

源码定位：[core/infrastructure/tool_result_budget.py](../../../core/infrastructure/tool_result_budget.py)；[core/infrastructure/tool_result_artifact.py](../../../core/infrastructure/tool_result_artifact.py)；[core/chat/tool_result_replacement.py](../../../core/chat/tool_result_replacement.py)。

### 29.3 Micro-compaction 的真实算法

`microcompact.py` 不是再次调用模型写摘要，而是读时投影：在接近全压缩阈值的区间，把较老、允许的只读工具结果换成稳定的引用/预览占位，保留近期工具组。错误、多媒体、未完成 tool pairing 等不应随意清除；节省太少时可回滚这次投影。

触发线的源码核心语句：

```python
return max(0, min(int(full * 0.9), full - 2000))
```

full 是全压缩触发 token 线；窗口过小时结果可能为 0，从而停用该层。当前默认保留最近 5 个工具组，且工具调用 ID 与结果配对不变。不要把“组”误写成“最近 5 行聊天”。

清除的工作集文件可以按有界契约重新注入提醒；原 Journal 没有因此被删。模型输入变短与原始历史丢失是两件事。

源码定位：[core/chat/microcompact.py · micro_compact_trigger_tokens](../../../core/chat/microcompact.py#L98)；[core/chat/microcompact.py](../../../core/chat/microcompact.py)。

### 29.4 为什么压缩还牵涉 Provider cache

假设某次请求中间一段工具结果被压缩，下一次又恢复成原文，即使信息相近，前缀字节也变了，会破坏精确前缀缓存。`projection_stickiness.py` 因此把已使用的压缩形式按 toolCallId/原文 hash 锁住，后续稳定重建。

锁以 Journal 的 out-of-band 事件保存，本身不送给模型；旧正文不被覆盖。它解决的是“模型输入投影稳定性”，不是把过期正文永久当新内容，也不是分布式数据库锁。

源码定位：[core/chat/projection_stickiness.py](../../../core/chat/projection_stickiness.py)；[core/chat/microcompact_anchor.py · estimate_tokens_with_anchor](../../../core/chat/microcompact_anchor.py#L212)。

### 29.5 全摘要压缩需要可追溯检查点

`turn_compression.py` 编排更重的上下文压缩，`context_compression_ledger.py` 记录压缩尝试、覆盖范围和 checkpoint。回放时先从账本取得事实，再应用范围明确的摘要投影，而不是随便把前一半消息删掉。

摘要可能失败、丢细节或超预算，因此要保留决定、错误、恢复引用等约束。`llm_summary_breaker.py` 等还处理摘要调用的失效治理。摘要后的文本不是新的客观证据来源；需要精确细节时仍应重新读取原始历史/文件。

源码定位：[core/orchestration/turn_compression.py](../../../core/orchestration/turn_compression.py)；[core/chat/context_compression_ledger.py · append_context_compression_checkpoint](../../../core/chat/context_compression_ledger.py#L183)；[core/orchestration/llm_summary_breaker.py](../../../core/orchestration/llm_summary_breaker.py)。

练习：分别解释“工具输出被截断”“只读结果被微压缩”“历史被摘要”“UI 只加载最后一页”的区别，指出哪一种会修改模型输入、哪一种只影响显示，以及能从哪里找回原始依据。

## 30. 模型协议与恢复：不是 catch Exception 后再试一次

### 30.1 统一语义模型与 wire 解耦

`semantic_messages.py` 使用不可变数据结构表达 InvocationScope、内容、生成设置等；InvocationScope 含 session_id、turn_id、invocation_id、iteration，用来把同一 Turn 的多次调用区分开。`semantic_projector.py` 转成统一语义请求，`wire/registry.py` 按明确路由选择编解码器。

```text
Agent 语义消息/工具结果
  → immutable request + invocation scope
  → resolved route（Provider/endpoint/model/wire/adapter）
  → encode request → transport → decode stream/outcome
  → canonical text/reasoning/tool calls/usage
```

“接口兼容 OpenAI”不意味着任意模型都支持相同 reasoning、缓存、工具和 response-id 语义。协议的具体差异必须留在明确适配边界，而不是撒在每个聊天页面里。

源码定位：[core/llm/semantic_messages.py · InvocationScope](../../../core/llm/semantic_messages.py#L27)；[core/llm/semantic_projector.py](../../../core/llm/semantic_projector.py)；[core/llm/wire/registry.py](../../../core/llm/wire/registry.py)。

### 30.2 ProviderReplayState 为什么不直接塞给下一个模型

某些服务返回不透明的 reasoning/replay items、response_id 或待完成调用标识。`ProviderReplayState` 将其绑定 issuer、provider_id、endpoint_fingerprint、model_id、wire_protocol，并限制条数/字节。

其兼容检查的关键语句：

```python
for field_name, value in expected.items():
    if getattr(self, field_name) != value:
        raise ReplayStateMismatchError(
            f"provider replay route identity mismatch: {field_name}")
```

因此切换 Provider/endpoint/model 后，不能复用另一条路由的不透明状态。`safe_summary()` 只暴露身份、计数和是否存在 response id，避免把不透明内容泄漏到普通日志。

源码定位：[core/llm/provider_replay_state.py · ProviderReplayState](../../../core/llm/provider_replay_state.py#L45)；[core/llm/provider_replay_state.py · require_compatible](../../../core/llm/provider_replay_state.py#L83)。

### 30.3 四级恢复阶梯

当前 `resilience_policy.py` 明确定义顺序：

```text
TRANSPORT_RETRY → DEGRADED_RETRY → FALLBACK_SWITCH → TURN_TERMINAL
```

| 阶段 | 处理什么 | 不能误解成 |
| --- | --- | --- |
| Transport retry | 同路径可重试的连接/传输失败，受 profile 预算约束 | 所有异常都盲重放，包括已产生副作用的流 |
| Degraded retry | 有限改变请求形状，如关流或关工具 | 悄悄把 Agent 永久改成另一套能力 |
| Fallback switch | 受声明约束的备路由切换，当前有单跳等限制 | 在所有模型之间无限循环碰碰运气 |
| Terminal | 压缩、失败/停止或明确收口等分类 | 永远把空结果当成功 |

`recovery.py` 决定动作词汇，`client.py` 执行传输预算，`turn_llm_adapter.py` 执行本轮降级/备路由。跨 Turn 的 stuck 检测和续跑是 worker 另一层，不属于同一个重试循环。

源码定位：[core/llm/resilience_policy.py](../../../core/llm/resilience_policy.py)；[core/llm/recovery.py · plan_recovery](../../../core/llm/recovery.py#L65)；[core/orchestration/turn_llm_adapter.py](../../../core/orchestration/turn_llm_adapter.py)；[core/web/services/session/turn_stuck_analyzer.py](../../../core/web/services/session/turn_stuck_analyzer.py)。

### 30.4 空回答、思考泄漏、工具格式泄漏

`answer_channel_guard.py` 处理部分内部格式进入可见回答的异常：先尝试保守的无损解析；无法恢复有效答案时分类为错误，进入已有降级路径；重复泄漏仍要带标记与可见告知，不能声称“所有泄漏一律已清洗干净”。

`legacy_xml_tool_decoder.py` 是特定兼容解析层；只有可识别、符合规则的结构才能成为 tool call。不能把用户普通文本里出现 `<tool...>` 就当命令执行。`wire/provider_control_content.py` 更有严格路由限定，并非对所有模型全文做通用正则删除。

源码定位：[core/llm/answer_channel_guard.py](../../../core/llm/answer_channel_guard.py)；[core/llm/legacy_xml_tool_decoder.py](../../../core/llm/legacy_xml_tool_decoder.py)；[core/llm/wire/provider_control_content.py](../../../core/llm/wire/provider_control_content.py)。

### 30.5 路由 gate 与流式 deadline

`client.py` 的每路由 BoundedSemaphore 管并发，gate 等待有预算；流还有 idle chunk deadline 和 total deadline。一直没有新输出与持续输出但总时长过长是不同故障。取消时还要关闭流并归还槽位，否则一个卡住的连接可能让后续请求都排队。共享客户端还可能有独立 request-slot 等待；当前实现把这层等待也纳入有界预算，不应把排队耗时全解释成 Provider 推理耗时。

学习检查：某次耗时 60 秒，其中 40 秒在等 route gate，不能说模型推理花了 60 秒；下一章的 usage 与第 37 章的 TTFT 会继续解释如何证明。

---

[← 上一部分](04-modules-and-learning.md) · [教程目录](README.md) · [下一部分 →](06-durable-systems.md)
