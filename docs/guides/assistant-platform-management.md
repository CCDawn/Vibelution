# Launcher 助理的平台管理边界

能力导航见 [runtime README 的能力表](../../core/assistant_runtime/README.md#platform-management)。运行版本的动作、参数与前置条件以 `personal_assistant_action_tool` 的 `index` / `describe` 为准；写入遵循 `personal_assistant_manage_tool` 的原生权限策略。`full_access` 可能自动批准，但不跳过目标授权、来源身份或并发校验。旧平台 adapter 清单和 API 文档都不能扩 Launcher 执行权限。

## 来源权威

| 管理面 | 来源与执行 owner | 不能替代它的证据 |
| --- | --- | --- |
| 全局模型 / provider | main 完整持久注册表租约、固定 native assistant root、原生元数据与 operator-config 事务 | `projects` 可调用列表、`--projects-file` 活动授权投影、单项目扫描、旧零引用结果 |
| 项目运行与管理 | 项目绑定的原生 SDK、当前 subject grant、业务 owner 与原始回执 | 助理巡检 checkpoint、缓存目录、外层管理意图状态 |
| 主项目 / 分支生命周期 | Electron main queue 或 branch instance supervisor、绑定原生 command 的结果 | Python 新执行器、默认全局 queue、进程树猜测、HTTP 断连 |
| 助理派遣 | 当前原生用户事件、有限目标授权、原生任务关联与 Session admission | 模型自述授权、目录 `active` 标记、旧事件文本 |

项目 scope 与真实 operator 身份分别校验。全局引用保护内部检查未开放业务访问的登记项目，只输出覆盖与计数，不授予这些项目的正文、Prompt 或任务权限。

## 模型 / provider 删除与停用

`configuration_references` 覆盖完整 stored registrations，包括 inactive、离线登记和 native assistant 自身。它绑定实际项目身份与已有存储，检查 formal/sandbox 的 Agent、room、Team、历史 Session compiled pin、活动 supervised 绑定及 operator 模型引用；sandbox workspace 必须配自己的 runtime。缺失、损坏、离线、绑定不明或实际引用解析失败均阻止零引用证明，未知不能显示为 `0`。

实际引用按原生大小写敏感 `llm.model_aliases` 链解析到 qualified model，不按 upstream 或显示名称合并。静态 alias 不算活动绑定，原生 unpin 不自动清除它；真正引用悬空 alias 时仍不可用。删除或 `enabled=false` 在执行时取得 main registry admission lease，持共享 reference writer fence 全量复核，并通过原生 operator-config 事务提交。先持久记录受影响 model/alias 的有限退休归属，排队旧绑定提交时再校验真实配置；alias 被清除也不能回落为未知 opaque ID 绕过。重新添加/绑定可用模型后遵循当前配置，未标记的历史 opaque ID 保持原 import 契约。

只读零计数没有写权或长期有效期。主进程缺少可信完整租约、配置变化或任一来源覆盖不全时，保留配置并报告不可用/未知。`provider_remove` 仍要求原生 provider 没有 pinned models。实现入口是 `configuration_control.py`、`configuration_references.py` 和 `model_reference_fence.py`。

私有配置通道丢失确认时，保留原配置进程与登记保护，只恢复同一代控制通道。只有原工作线程确认引用写锁与配置工作已结束，或原 Job 已完整退出，才能解除未知租约；临时完成记录不包含配置正文，也不替代业务回执。

## 运行巡检与未知操作

`runtime_list` / `runtime_get` 投影原生 Session Turn、runtime task、external task、Team、supervised、self-evolution、Research 元数据，携带 snapshot、分页与逐来源 coverage。`runtime_watch` / `patrol` 按有界页面观察失败、停滞和来源变化，再通过原生助理续接处理。观察范围受项目授权和可达性限制，不是所有登记项目的原子运行快照；checkpoint 不成为第二运行索引。空页、缺项或来源消失都不能证明任务结束或项目空闲。

控制使用对象当前返回的 `commands`、精确 owner 引用及 revision。`revisionCheck=preflight_only` 只代表预检，原生 owner 仍决定能否执行。`accepted`、`stopRequested`、`restart_queued`、外层管理 `completed` 均不等于业务终态，之后读取原对象核验。

`management_requests` 发现原请求引用；`management_receipt` / `management_reconcile` 按原 action/request ID 只读核对管理应答或原生结果，权限仍按原动作独立 scope。`requires_review` / `unavailable` 必须如实保留；确认管理应答不证明业务完成。超时、丢失确认或重启后继续查询原稳定 ID，不换 ID 重放。需要人工复核时报告证据和对象引用，不能无限轮询同一 unknown。

## Research 与知识库

`research_get` 需要 `operations:read`，读取 formal Research Ledger 的节点与人工任务元数据，不输出任务 Prompt。`research_command` 需要 `operations:control` 及原生审批，以精确 run/team/flow、revision CAS、稳定 request ID 执行 `retry_node`、`resolve_human_task` 或 `reconcile_run`。人工决策只选任务当前返回的选项，`revise` 绑定返回的 checkpoint；命令回执不代替运行终态。

Research 续页必须同时传原 `operation.revision` 为 `expected_revision`、原 `snapshot` 为 `expected_snapshot`。目录 snapshot 覆盖同一原生读取事务中的完整节点和待办元数据；worker 新增待办即使没有提升命令版本，也会使旧续页失效。不能将目录快照冒充命令 CAS 版本。

`knowledge_list` 使用独立 `knowledge:catalog:read`，按 owner type/ID/query 发现 Agent 库与当前 operator 可管理的系统 Team 库，返回公开名称、状态、owner、稳定 scoped ID 及 ACL fingerprint。它不读正文、不冒充 owner，也不 seed/hydrate/修复缺失权威；续页保持 `expected_digest`，`partial` / `unavailable` 不是空库或全量目录。旧 `team_knowledge_list` 保留兼容。ACL 操作用精确 `scopedKnowledgeBaseId` 重新读取当前 ACL/fingerprint；目录可见不授予正文或 ACL 写权，也不扩大默认 grant。

## 派遣授权与主体撤销

`delegation_goal_*` 将当前助理会话的原生用户来源绑定到目标 Agent、权限上限、任务额度和期限。`dispatch_derived` 可在该 envelope 内派遣拆分任务，每次仍受原生 manage 审批与目标项目权限限制。稳定 dispatch ID 不重复扣额度，也不能用新 ID 重派未知任务。目录 `active` 只代表未撤销且未过期，`sourceVerified=false` / `partial` 不证明当前可执行或目录完整；继续前验证原 goal。撤销 goal 只阻止新派工，已有任务继续查询原 `receipt`。

`authorization_status` 返回当前 scopes/revision。`authorization_reduce` 只移除非空真子集，清空访问必须明确 `authorization_revoke`；两者要求真实 operator control、原 capability、精确 `expected_scopes` / `expected_grant_revision`、稳定 request ID 与原生审批，不接受外部 subject/actor/force。scopes、revision、receipt 在同一原生 subject 记录中原子保存。撤销立即拒绝业务操作及新升级/降权，原凭据只可恢复本次撤销的原回执；历史证据和任务关联保留，旧升级回执不会恢复已移除权限。

## 生命周期与验收限制

`project_status` / `project_lifecycle` / `project_lifecycle_receipt` 定位已登记 physical root；主项目复用 canonical queue，分支 start/stop/restart 复用 branch instance supervisor 和原生 command owner，不再一律拒绝分支，也不开放任意 worktree/Git 命令。生命周期占用、active work、缺失身份、登记变化和退休未确认仍保留原生拒绝/未知语义。回执绑定 root、instance、command ID/source；恢复只读原结果，无 force、路径、URL、任意命令或进程树强杀入口。状态查询不能证明全项目空闲。

源码接通与局部回归不能替代最新安装包、真实模型、真实 main/branch 项目及退出恢复的联合现场验收。旧平台助理退休、数据交接与发布仍有各自验收条件。上述能力不放宽普通 Session 的权限、提交、Journal、worker、持久化或 SSE，也不创建第二套 transcript。
