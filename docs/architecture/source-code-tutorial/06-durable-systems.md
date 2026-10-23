[← 上一部分](05-runtime-deep-dive.md) · [教程目录](README.md) · [下一部分 →](07-engineering-and-reading.md)

# 附件、回退、后台任务与持久化工作流

## 31. 图片、文档、拖入引用：多模态输入的完整链

### 31.1 三种输入不能混成一个字符串

| 输入 | 处理模块 | 实际进入模型的内容 |
| --- | --- | --- |
| 图片附件 | `image_attachments.py`、`image_model_variant.py` | 受模型能力约束的图像内容块及文字说明 |
| 文本/PDF 文档 | `document_attachments.py` | 提取的有界文本与不可信内容标记 |
| 文件/消息/知识/会话引用 | conversation_references、turn_diagnostics 等 | 验证权限和归属后的受控片段/定位 |

上传成功只证明字节进入受控存储，不证明模型支持视觉，也不证明文件已经成为正式知识或 RAG 索引。

### 31.2 图片原图、页面预览、模型输入是三份不同投影

`image_attachments.py` 维护图片 artifact、类型/大小/路径约束、能力记录及模型输入；桌面可引用用户声明的本地文件，但读取后仍经过常规校验。页面预览可以用原始 artifact，不代表 Provider 实际收到同样字节。

`build_model_image_variant()` 构造模型输入变体：按策略处理 EXIF、缩放、JPEG 重编码和透明背景。当前策略期望最长边 2000px 内、base64 不超过约 5 MiB，并有逐级缩放质量阶梯。

**实现边界必须读完整：**最后一档即使仍超预算也可能使用；预处理异常按 fail-open 合同返回原字节。因此不能把这些目标参数宣传为所有图片都无条件满足的硬上限。原图不被覆盖，变体是可失效的 sibling cache。

源码定位：[core/web/services/session/image_attachments.py](../../../core/web/services/session/image_attachments.py)；[core/web/services/session/image_model_variant.py · build_model_image_variant](../../../core/web/services/session/image_model_variant.py#L53)。

### 31.3 文档是“有界提取”，不是运行文件

当前文档链接受白名单文本扩展和 PDF，源码常量限定大小/数量，PDF 走文本提取。HTML 附件按文本处理，不应因为上传的是 `.html` 就直接作为可信活动页面运行；PDF 扫描图片也不能保证仅靠文字抽取就有内容。

提取后有每文件/每 Turn 的字符预算，截断需要告知。截断的是此次模型输入投影，不是原附件字节；如果模型需要后面的段落，应该通过受控读取或知识入库后分页获取，而不是假设它已经完整看过。

源码定位：[core/web/services/session/document_attachments.py](../../../core/web/services/session/document_attachments.py)。

### 31.4 引用解析先验身份，再取内容

`conversation_references.py` 处理 knowledge_item、knowledge_base、file、message；Session-kind 引用走现有诊断/引用管线。知识库引用可触发现有受管检索，单个知识项有内容预算，来源消息要验证存在性，文件读取须处于受控 artifact/路径边界。

外部文本被放入 fenced untrusted-data block；若文本本身带有用于包围数据的 fence literal，会被替换，避免提前闭合围栏。**这是提示词隔离措施，不是证明 Prompt injection 已被数学上消灭。** 真正执行仍需要工具权限和 ACL。

源码定位：[core/web/services/session/conversation_references.py](../../../core/web/services/session/conversation_references.py)；[tools/session_reference_tools.py](../../../tools/session_reference_tools.py)。

## 32. 对话分支、Fork 与文件回退：三个不同的“回到过去”

### 32.1 Head 切换改的是正在看的对话路径

`conversation_branches.py` 从 Journal 的 parent chain/head 推导分支图；`branch_head.py::switch_session_head()` 在准入保护下检查可写性和活动任务，再追加 head_select 标记并发布新的 detail。

```text
同一 Journal： A → B → C
                  └→ C′
head=C 或 C′：选择不同可见路径，不是删除另一分支。
```

前端不应自行重建一个与后端不同的分支真相；它根据后端 nodeId/branch/turnItems 展示。分支与普通数组下标不同，旧消息插入后下标会变，稳定 node/event ID 更可靠。

编辑重提与 regenerate 的 `_resubmit_session_user_message()` 实际追加 branch_rebase，再写新一轮输入。某些旧 docstring 仍写 truncate，但这里要区分“截断当前活动投影”与“物理删掉 Journal 后半文件”。当前普通路径保留其他分支；不能仅凭历史描述认定在做物理覆写。

源码定位：[core/chat/conversation_branches.py](../../../core/chat/conversation_branches.py)；[core/web/services/session/branch_head.py · switch_session_head](../../../core/web/services/session/branch_head.py#L25)；[core/web/services/session/submit.py · _resubmit_session_user_message](../../../core/web/services/session/submit.py#L2474)。

### 32.2 Fork 创建另一个 Session

`fork_session.py` 从一个节点派生新 Session，可选 visible_path 或 with_branches。源 Journal 不改；新 Journal 重新映射 sessionId 和序号，保留必要事件/Turn 关联，并处理不能留下悬空 open Turn 的尾部结构。

这与“在原 Session 内切换 head”不同，也不等于 Git worktree。一个是对话路径复制，一个是代码 checkout 隔离。

源码定位：[core/web/services/session/fork_session.py](../../../core/web/services/session/fork_session.py)。

### 32.3 文件 rewind 需要修改前的真实字节

`file_change_ledger.py` 为接入的写工具记录第一次修改前的 pre-image 和完成写入后的 after-image，按 Session/Turn 保存：

```text
sessions/<session>/file_history/<turn>/
  pre.jsonl       # 同一路径第一次修改前的状态
  after.jsonl     # 完成写入后的状态
  audit.jsonl     # 回退结果与幂等标记
  images/<sha256>.bin
```

`capture_pre_write()` 必须在真正写文件前执行；对于本轮新建文件，要保存“原来不存在”的哨兵，而不是伪造一个空文件。否则回退时无法区分该删除新文件，还是恢复一个原有空文件。

源码定位：[core/chat/file_change_ledger.py · capture_pre_write](../../../core/chat/file_change_ledger.py#L324)；[core/chat/file_change_ledger.py · capture_post_write](../../../core/chat/file_change_ledger.py#L362)；[tools/shell_tools.py](../../../tools/shell_tools.py)。

### 32.4 为什么一定要 preview 和 conflict 检测

若 Agent 写完后用户又编辑了同一文件，直接用 pre-image 覆盖会抹掉用户修改。`preview_turn_rewind()` 分类 safe、checkpoint_missing、external_modified 等；strict 默认拒绝带不安全项的批次，force 的语义也不是任意覆盖所有文件，而是按实现处理安全文件并报告跳过项。

回退重复请求要重放已有审计结果，不应第二次又触碰磁盘。捕获 checkpoint 本身是 fail-open：记录失败不能让本来成功的写工具失败，因此某些写入可能没有回退证据。更不能承诺所有 shell/第三方工具改的文件都自动有此账本。

**边界：它不回滚云 API、已发送消息、任意数据库事务或一切外部副作用，也不能因为对话 head 切回去就默认这些副作用消失。**

源码定位：[core/chat/file_change_ledger.py · preview_turn_rewind](../../../core/chat/file_change_ledger.py#L583)；[core/chat/file_change_ledger.py · apply_turn_rewind](../../../core/chat/file_change_ledger.py#L650)；[core/web/services/session/rewind.py](../../../core/web/services/session/rewind.py)。

## 33. 后台任务、迟到结果与重启恢复

### 33.1 RuntimeTaskStore 不是又一套聊天正文库

`runtime_task_registry.py` 为长于当前等待窗口的 CLI Agent、child_session、research_task 保存 typed snapshot、状态、来源会话、branchGeneration、pendingMessages 和活动索引。它记录任务生命周期，而正文仍各归原生 Session 或对应执行来源。

活动任务 `_index.json` 让 sweeper 不必每秒扫完所有历史文件；周期 reconcile 修复“快照写成功、索引没来得及更新”的漂移。读写锁顺序固定 task-file→index，反过来可能形成死锁。

源码定位：[core/web/services/runtime_task_registry.py · RuntimeTaskStore](../../../core/web/services/runtime_task_registry.py#L301)；[core/web/services/runtime_task_query_service.py](../../../core/web/services/runtime_task_query_service.py)。

### 33.2 branchGeneration 防止旧世界的结果污染新世界

任务注册时捕获来源 Session 的 branch generation。执行会推进该代次的操作后，迟到的完成通知必须与当前代次比较；例如当前 `switch_session_head()` 中明确调用 `advance_session_branch_generation()`。失配就阻止旧通知进入新上下文。文件 rewind 是另外的路径，不能仅凭“回退”这个名称就断言所有回退 API 都推进同一代次。

这里的“丢弃”是阻止通知进入不再匹配的当前 Session，不等于删除历史任务和它已经发生的外部副作用。并非每次切换页面都会改变 branchGeneration，也不能把它理解成浏览器标签页编号。

### 33.3 转后台与停止不是一回事

`runtime_task_auto_background.py` 的 sweeper 达到阈值后标记后台并按既有队列通知，任务继续运行；默认未配置/非正阈值时该功能关闭。不能看到代码有 daemon 就说当前所有任务都已自动转后台。

`request_stop` 在 registry 中记录 stop intent，执行方仍要观察并停止。query service 只是读投影/薄委托，不会凭界面点一次就保证所有外部进程已退出。

源码定位：[core/web/services/runtime_task_auto_background.py](../../../core/web/services/runtime_task_auto_background.py)；[core/web/services/runtime_task_query_service.py](../../../core/web/services/runtime_task_query_service.py)。

### 33.4 Session 启动恢复：保守续接原任务

`startup_recovery.py` 在后端重启后检查持久 WorkRun/Journal 中未收口的任务，根据 session_recovery 开关和每条恢复链预算决定是否提交 `hot_restart_resume`，恢复原写入意图和 per-turn 模型选择，并记录 recovery 状态行。排队输入另行触发 drain。

它明确跳过 Companion 会话，避免侵入人物私有投递链；感知后台任务也有自己的许可代次和恢复政策。不能把“有自动恢复代码”写成“任何任务重启后都会原地继续且保证不重做工具”。内存 socket、Future、外部提交状态都需要重新证明。

源码定位：[core/web/services/session/startup_recovery.py](../../../core/web/services/session/startup_recovery.py)；[core/web/services/session/journal_bridge.py](../../../core/web/services/session/journal_bridge.py)。

## 34. 持久化与工作流可靠性：崩溃点应该怎么分析

### 34.1 不同故障用不同存储策略

| 状态 | 常用机制 | 防什么 | 不能替代什么 |
| --- | --- | --- | --- |
| 一条 JSONL 事件 | sidecar 锁、追加、flush/fsync、容忍残尾 | 并发写坏行、断电/中断后的部分行 | 多文件事务 |
| 一份 JSON 快照 | 临时文件、replace、锁、重试 | 文件只写一半、Windows 临时占用 | 外部业务操作的原子性 |
| SQLite 多行 | 明确事务、schema 与单写协调 | 关联行部分成功、写锁竞争 | 云端服务副作用 |
| 工作流派发 | transactional Outbox + lease + 幂等 adapter | 提交与派发之间崩溃、重复派发 | 不支持幂等的外部 API 的 exactly-once |

### 34.2 atomic_write_text 也有选项语义

`atomic_io.py` 默认先临时文件再替换，受 per-target sidecar lock 与重试保护。若替换持续失败，部分调用允许 fallback 为原地写；需要严格 all-or-nothing 的调用应使用 `strict_replace=True`。

因此不能只看到函数名 atomic 就断言所有调用路径永远是同样的严格原子替换。应继续检查调用者传参、失败回退与恢复规则。

源码定位：[core/infrastructure/atomic_io.py · atomic_write_text](../../../core/infrastructure/atomic_io.py#L25)；[core/infrastructure/file_lock.py · cross_process_file_lock](../../../core/infrastructure/file_lock.py#L64)。

### 34.3 Workflow Ledger 的 Outbox lease

`ledger/outbox.py::lease_ready_actions()` 在单写者的 BEGIN IMMEDIATE 事务里认领动作，写 owner、期限、尝试等；超时 lease 可以被重新认领。Adapter 仍必须使用稳定幂等键，防止重复调用外部副作用。

教学时间线：

```text
事务提交节点状态 + Outbox
  → worker lease
  → 调用 domain adapter
  → 回读并验证领域产物/模型回执
  → transaction 提交 receipt/handoff、ack
```

若崩在“领域写回成功、ack 前”，重启后可能再次处理该动作。正确 adapter 应识别原来的 dispatch/task/产物，而不是再调用一次昂贵模型或重新下发副作用。这里是有条件的重复安全，不是天然 exactly-once。

源码定位：[core/research/workflow/ledger/outbox.py · lease_ready_actions](../../../core/research/workflow/ledger/outbox.py#L20)；[core/research/workflow/ledger/store.py · WorkflowLedgerStore](../../../core/research/workflow/ledger/store.py#L25)；[core/web/services/team_workflow/research_runtime/adapter_dispatch_worker.py](../../../core/web/services/team_workflow/research_runtime/adapter_dispatch_worker.py)。

### 34.4 Checkpoint、Session Journal、Receipt 不能互相冒充

`checkpoint_store.py` 使用 LangGraph SqliteSaver 保存恢复位置与受控绑定；Workflow Ledger 管节点进度；领域 store 管业务产物；Model Invocation Receipt Registry 保存真实模型调用回执；Session Journal 管 Turn。

例如 checkpoint 已经过某节点，不代表对应报告文件的归属/hash 已通过；Session completed 也不代表某项知识审核已经成功。`model_invocation_receipt_registry.py` 的不可变回执进一步防止拿别的题目、别的节点/尝试的模型证据替代本次结果。

源码定位：[core/research/workflow/checkpoint_store.py](../../../core/research/workflow/checkpoint_store.py)；[core/web/services/team_workflow/research_runtime/model_invocation_receipt_registry.py](../../../core/web/services/team_workflow/research_runtime/model_invocation_receipt_registry.py)；[core/web/services/team_workflow/research_runtime/readiness](../../../core/web/services/team_workflow/research_runtime/readiness)。

### 34.5 用“崩溃点表”练习可靠性

| 崩溃位置 | 你该找的事实 | 禁止直接作的推断 |
| --- | --- | --- |
| HTTP 超时前后 | 幂等 key、Journal 准入回执 | 没收到响应就必定没执行 |
| queue starting 后 | claim/dispatch 与已接受 Turn | 直接复制该行重新启动 |
| 工具 timeout 后 | live Future/进程、领域回读 | 工具外部副作用肯定没有发生 |
| Outbox 调用后、ack 前 | stable dispatch、领域产物、receipt | 从头新建模型任务 |
| 关闭窗口中途 | owner、工作进程、Journal 终态 | 窗口没了就所有任务都停了 |
| JSON 快照写后、索引写前 | canonical snapshot 与 reconcile | 索引缺失就删除快照 |

## 35. 自进化、评估与数据集：核心闭环不是“自己改自己”

### 35.1 三条链应分别读

1. **聊天样本治理**：chat_segmenter / dataset_capture / review_queue / case_lifecycle 管候选、审核、正负数据集。
2. **监督进化/候选验证**：控制 run、隔离 worktree、harness、证据校验和候选集成。
3. **自主进化/有限 campaign**：观察、计划、执行、独立验收及有限持续调度，带授权范围与停止条件。

聊天里把一条已完成回答勾成 include/exclude，调用 `session/message_curation.py`，走已有评审队列和正负样本生命周期；它不表示模型权重已被在线训练。项目中的“进化”不少是代码/Prompt/候选工作流的治理，不应直接宣称基础模型参数在本机自动更新。

源码定位：[core/web/services/session/message_curation.py](../../../core/web/services/session/message_curation.py)；[core/evaluation/chat_review_queue.py](../../../core/evaluation/chat_review_queue.py)；[core/evaluation/chat_case_lifecycle.py](../../../core/evaluation/chat_case_lifecycle.py)；[core/web/services/evolution_services.md](../../../core/web/services/evolution_services.md)。

### 35.2 Candidate 的代码边界

候选在隔离 worktree/harness 执行；目标文件合同限制计划与实际改动。测试、评估、审批、Git 集成和运行激活分别有 owner；页面投影不能改 baseline。`supervised_candidate_integration_service.py` 和 promotion lane 处理受管晋级，并检查 expected head 等条件。

“候选测试通过”≠“已合入 main”≠“Launcher 已启动新版本”≠“新版本实际服务正确”。每个等号都需要独立证据。

源码定位：[core/web/services/supervised_candidate_integration_service.py](../../../core/web/services/supervised_candidate_integration_service.py)；[core/web/services/evolution_promotion_lane.py](../../../core/web/services/evolution_promotion_lane.py)；[core/web/services/self_evolution_candidate_target_contract.py](../../../core/web/services/self_evolution_candidate_target_contract.py)。

### 35.3 自动本地集成必须是有界委托

当前 localIntegration 可显式指定 acknowledge、准确 allowedFiles、Team 与有效期；观察、执行、验收角色有独立身份约束。授权存于这次运行，不是给该 Agent 永久新增管理员能力；验收还要有独立只读工具证据，不能只返回一个 PASS JSON。

campaign 复用正式角色绑定和有限轮数/期限，不应无限续签授权或自动部署。历史默认、可选开关和本机当前状态要区分。

源码定位：[core/web/services/self_evolution_local_integration.py](../../../core/web/services/self_evolution_local_integration.py)；[core/web/services/self_evolution_campaign_service.py](../../../core/web/services/self_evolution_campaign_service.py)；[core/web/services/self_evolution_campaign_binding.py](../../../core/web/services/self_evolution_campaign_binding.py)。

## 36. 感知与插件扩展：比“给 Agent 多加一个 Prompt”更严格

### 36.1 PerceptionPolicy 决定何时可以发现哪些资料

`agent_perception/` 控制个人、团队、知识库、本地项目等来源的 off/manual/auto、task/update/background 触发、可读范围、后台额度和通知。它不授予额外 ACL，也不提供知识写权限。

worker 建立可信 trigger/Agent/Session/Turn 上下文；手动意图从原始用户消息按规则解析，文档正文、检索结果和模型自述不能伪造用户指令来放大读取范围。运行读取会与现有 MemoryPolicy、Owner ACL 取交集。

源码定位：[core/web/services/agent_perception/README.md](../../../core/web/services/agent_perception/README.md)；[core/web/services/agent_perception/policy.py](../../../core/web/services/agent_perception/policy.py)；[core/web/services/agent_perception/runtime.py](../../../core/web/services/agent_perception/runtime.py)。

### 36.2 后台感知是带 permit 的原生任务

启用后台主题/配额后，runtime 预留日额度，创建隐藏原生 Session/Turn，并在 LLM 输入、工具与来源读取处限制额度。后台 permit 绑定进程启动身份/生命周期代次；完整重启后旧许可不会无条件重建并重放任务。

知识更新通知主要是 metadata 变化扫描，不等于自动把原文塞进 Agent 对话。关闭感知也不代表文件/命令工具失去所有读取能力；那些仍归原有 ToolPolicy 和文件沙箱。

### 36.3 插件通过窄接口接入核心

`AgentPluginRuntimeExtension` 规定 build_prompt_segments、filter_tool_names、tool_execution_denial、archive prepare/rollback/purge、proactive freshness/cancel/finalize 等 hooks。普通核心依赖接口，不直接耦合某个人物插件。

归档具有 prepare/rollback/commit 语义，避免目录改一半、插件数据残留一半；主动消息用 binding revision/delivery token 判断旧回调是否仍有效，防止插件禁用后旧计时器继续投递。

这个注册面明确是**受信的第一方窄扩展**，不是可以随便安装任意第三方 Python 插件的通用市场。

源码定位：[core/agent_plugins/runtime_extensions.py · AgentPluginRuntimeExtension](../../../core/agent_plugins/runtime_extensions.py#L14)；[core/agent_plugins/runtime_extensions.py · installed_runtime_extensions](../../../core/agent_plugins/runtime_extensions.py#L82)；[core/agent_plugins/virtual_human_life/runtime_extension.py](../../../core/agent_plugins/virtual_human_life/runtime_extension.py)。

---

[← 上一部分](05-runtime-deep-dive.md) · [教程目录](README.md) · [下一部分 →](07-engineering-and-reading.md)
