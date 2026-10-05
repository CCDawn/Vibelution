"""Reviewed execution/data views. Each relation carries an actual source anchor."""


def add_domain_views(view):
    base = 'core/web/services/team_workflow/research_runtime/'
    svc = 'core/web/services/'
    view('teams','团队通信与 Agent Bus','团队成员消息、原生会话与正式研究工作流分开。送达事件不等于 Agent 已执行完毕。',[
        ('panel','Team 通信面板','收集团队消息并触发 mutation。','web/src/routes/teams/TeamCommunicationPanel.tsx','function TeamCommunicationPanel'),
        ('api','团队消息 API','POST /api/teams/{teamId}/messages。','web/src/api/projectAgentBus.ts','function sendTeamProjectBusMessage'),
        ('route','Team route','HTTP 入口委托团队服务。','core/web/routes/teams.py','def team_message_create('),
        ('team','团队服务','从 active member IDs 得收件人，附 teamId/teamName/source=team。',svc+'team/team_crud.py','def send_team_message('),
        ('bus','Project Agent Bus','构造并投递 Agent message event，追加事件 JSONL。',svc+'project_agent_bus_service.py','def send_project_agent_bus_message('),
        ('kernel','Agent Kernel 投递','通过 submit_agent_message_event 进入 Agent Kernel；后续唤醒受内核策略约束。',svc+'project_agent_bus_service.py','submit_agent_message_event('),
        ('store','团队 / 画布存储','teams.json 与每队 canvas.json；建立 direct sessions / linked chat room，不与 workflow ledger 合并。',svc+'team/team_crud.py','def create_team('),
    ],[
        ('panel','api','发送 mutation','面板经 useTeamShellMutations 调团队消息 API。','web/src/routes/teams/useTeamShellMutations.ts','sendTeamProjectBusMessage'),
        ('api','route','POST messages','领域 API 与团队消息 route 对应。','web/src/api/projectAgentBus.ts','function sendTeamProjectBusMessage'),
        ('route','team','委托服务','薄 HTTP route 委托 send_team_message。','core/web/routes/teams.py','def team_message_create('),
        ('team','bus','收件人 / 团队范围','团队服务冻结此次 active recipients。',svc+'team/team_crud.py','def send_team_message('),
        ('bus','kernel','投递事件','逐个提交 Agent message event 并记录事件。',svc+'project_agent_bus_service.py','submit_agent_message_event('),
    ])
    view('research','科研运行与持久化调度','当前 Stage-One 主图为 problem_understanding → hypothesis_design → result_package；知识 sideflow 是独立 child run。',[
        ('create','创建 Question Run','服务端生成输入并 pin definition / binding snapshots 与初始 checkpoint。',base+'run_creation.py','def create_question_run('),
        ('command','Workflow Command','验证 team、幂等键、runVersion、readiness，处理 start_node。',base+'command_service.py','class WorkflowCommandService:'),
        ('ledger','Ledger / Outbox','一次 UoW 提交 command、attempt、graph_dispatch outbox、event 和 run 状态。','core/research/workflow/ledger/store.py','class WorkflowLedgerStore:'),
        ('graph','GraphDispatchWorker','消费 outbox、恢复 LangGraph checkpoint；上游成功与 handoff 决定后继。',base+'graph_dispatch_worker.py','class GraphDispatchWorker:'),
        ('adapter','AdapterDispatchWorker','输入/预检/预算检查后调用领域 adapter，回读产物 hash/revision 验收。',base+'adapter_dispatch_worker.py','class AdapterDispatchWorker:'),
        ('ports','RealDomainPorts','特定 Agent task 与原生 Session 的真实执行边界。',base+'real_domain_ports.py','def create_agent_task('),
        ('checkpoint','Graph Checkpoint','checkpoints.sqlite 保存图执行位置；workflow-ledger.sqlite 保存业务运行与命令权威。',base+'runtime_factory.py','checkpoints.sqlite'),
        ('replay','Durable Event Replay','从已提交 workflow_events 读取持久历史，前端 snapshot hydration + event reducer。',base+'event_replay_service.py','workflow_events'),
        ('definition','Stage-One Definition','当前主图三节点，其他工作流定义独立保存；不把历史版本混入主图。','core/research/workflow/stage_one_definition.py','problem_understanding'),
    ],[
        ('create','definition','固定定义','创建运行固定 Stage-One 定义和输入，后续不读取漂移的团队配置代替快照。',base+'run_creation.py','def create_question_run('),
        ('command','ledger','事务提交','命令与 outbox/event 一起提交后才唤醒 worker。',base+'command_service.py','def _handle_start_node('),
        ('ledger','graph','graph_dispatch','Graph worker 消费已提交的调度项。',base+'graph_dispatch_worker.py','class GraphDispatchWorker:'),
        ('graph','checkpoint','恢复 / 保存','Graph worker 使用 checkpoint 恢复图位置。',base+'graph_dispatch_worker.py','def _handle('),
        ('graph','adapter','动作派发','图产生的领域动作由 adapter worker 处理。',base+'adapter_dispatch_worker.py','class AdapterDispatchWorker:'),
        ('adapter','ports','执行 / 回读验收','AgentActionAdapter 经真实 ports 执行并 verify。',base+'adapters/domain_adapters.py','class AgentActionAdapter'),
        ('ledger','replay','committed events','持久回放从 Ledger 已提交事件读取，SSE 不另建权威。',base+'event_replay_service.py','workflow_events'),
    ])
    view('self-evolution','自主进化与人工批准','observe → plan → evolve 跑到 review。用户批准后才走集成/清理；不混入监督 Judge 双评分链。',[
        ('start','启动自主运行','API 委托默认 orchestrator，创建 WorkRun 状态。',svc+'self_evolution_autonomous_loop_orchestrator.py','def start_autonomous_self_evolution('),
        ('observe','Observe','观察当前目标及证据。',svc+'self_evolution_autonomous_loop_runtime.py','def observe('),
        ('plan','Plan','生成受约束的修改计划。',svc+'self_evolution_autonomous_loop_runtime.py','def plan('),
        ('evolve','Evolve Candidate','创建隔离候选，按目标文件边界执行与验证。',svc+'self_evolution_autonomous_loop_runtime.py','def _evolve_candidate('),
        ('review','Awaiting Approval','run_until_review 保存状态并等用户批准；候选生成不等于生效。',svc+'self_evolution_autonomous_loop_service.py','def run_until_review('),
        ('approve','显式批准','approve 触发集成；拒绝路径不集成。',svc+'self_evolution_autonomous_loop_service.py','def approve('),
        ('integrate','集成与清理','orchestrator runtime hooks 执行集成和任务资源清理。',svc+'self_evolution_autonomous_loop_orchestrator.py','def integrate('),
        ('workrun','WorkRunStore','formal workspace 下 self_evolution/autonomous_loops/work_runs；独立于监督 worktree run。',svc+'self_evolution_autonomous_loop_orchestrator.py','def build_default_orchestrator('),
    ],[
        ('start','observe','run_until_review','服务按 observe/plan/evolve hooks 推进。',svc+'self_evolution_autonomous_loop_service.py','def run_until_review('),
        ('observe','plan','观察 → 计划','观察结果交给计划阶段。',svc+'self_evolution_autonomous_loop_service.py','def run_until_review('),
        ('plan','evolve','计划 → 候选','按计划构建候选并验证。',svc+'self_evolution_autonomous_loop_service.py','def run_until_review('),
        ('evolve','review','等待审核','候选推进至 awaiting_user_approval。',svc+'self_evolution_autonomous_loop_service.py','def run_until_review('),
        ('review','approve','用户决定','只有显式 approve 进入集成。',svc+'self_evolution_autonomous_loop_service.py','def approve('),
        ('approve','integrate','集成 hooks','批准调用 integrate，然后 cleanup。',svc+'self_evolution_autonomous_loop_service.py','def approve('),
    ])
    supervised = svc+'supervised_worktree_evolution_service.py'
    view('supervised','监督 Worktree 进化','基线与候选共享冻结 rubric / 同一 Judge，再经配置的审批路径进入集成。这里不把普通 benchmark/Gym 误画成同一执行器。',[
        ('start','监督运行入口','创建并启动监督 WorkRun；此时尚未创建候选 worktree。',supervised,'def start_supervised_worktree_run('),
        ('baseline','基线评测','执行 baseline，Judge 冻结 rubric 并给基线评分。',supervised,'def _execute_flow('),
        ('candidate','反思 / 候选修改','基线评测、Judge 评分和 reflection 后创建候选 worktree，再按白名单修改。',supervised,'def _execute_flow('),
        ('rerun','隔离复测 / 审计','clean-room rerun + workspace audit。',supervised,'def _execute_flow('),
        ('judge','同一 Judge 复评','用冻结 rubric 再次评分，避免评判标准漂移。',supervised,'def _execute_flow('),
        ('decision','最终审批','根据 approvalMode 由用户或独立审批 Agent 作最终决定；不是固定 human-only。',supervised,'def _execute_flow('),
        ('merge','合入候选','通过集成检查后 _merge_candidate，之后排队激活 runtime。',supervised,'def _merge_candidate('),
    ],[
        ('start','baseline','执行 flow','运行入口驱动监督流程。',supervised,'def run_supervised_worktree_flow('),
        ('baseline','candidate','基线 → 改进','基线证据用于 reflection 与候选修改。',supervised,'def _execute_flow('),
        ('candidate','rerun','候选复测','候选不能用修改前或未隔离的结果代替复测。',supervised,'def _execute_flow('),
        ('rerun','judge','同标准比较','隔离复测结果交同一 Judge。',supervised,'def _execute_flow('),
        ('judge','decision','质量决定','评分只是决策输入，不自动代表批准合入。',supervised,'def _execute_flow('),
        ('decision','merge','批准后集成','配置的审批路径通过后进入集成，候选通过评分本身不等于已批准。',supervised,'def _execute_flow('),
    ])
    view('gym','Benchmark 与 Gym 晋升','普通 benchmark evaluator 的晋升门；与监督 worktree 执行器分开理解。',[
        ('eval','监督 Benchmark','汇总 baseline/candidate cases 并形成评估结论。','core/evaluation/supervised_evolution.py','def run_supervised_evolution_session('),
        ('gate','PROMOTE 晋升门','仅晋升判定触发 promotion gate。','core/evaluation/supervised_evolution.py','def _apply_promotion_gate('),
        ('episode','Gym Episode','run_promotion_gate_episode 运行评测回合。','core/gym/runner.py','def run_promotion_gate_episode('),
        ('promotion','显式应用 / 激活','Gym proposal 后续应用与激活有独立接口；不是评测通过自动生效。','core/gym/promotion.py','def apply_gym_promotion_proposal('),
    ],[
        ('eval','gate','PROMOTE 才进入','非晋升结论不自动执行晋升。','core/evaluation/supervised_evolution.py','def _apply_promotion_gate('),
        ('gate','episode','运行 Episode','promotion gate 委托 Gym runner。','core/evaluation/supervised_evolution.py','runner = run_promotion_gate_episode'),
    ])
    view('companion','Companion 专属消息入口','Agent-scoped mailbox 只负责到达顺序与租约；原生 Journal、worker、SSE 仍是会话权威。',[
        ('route','人物专属 Route','life_conversation_message 接收人物对话消息。','core/web/routes/virtual_human_life.py','def life_conversation_message('),
        ('facade','人物 Web Facade','委托受信任插件的消息队列。',svc+'virtual_human_life_service.py','def queue_virtual_human_conversation_message('),
        ('plugin','插件 admission','人物 Agent 的 queue_conversation_message 接收待处理命令。','core/agent_plugins/virtual_human_life/service.py','def queue_conversation_message('),
        ('mailbox','Agent-scoped Mailbox','conversation/mailbox.json 保存命令、顺序和租约，不保存第二套 transcript。','core/agent_plugins/virtual_human_life/mailbox.py','def enqueue_mailbox_entry('),
        ('dispatch','Dispatcher / FIFO','按顺序领取租约，再调用 conversation submitter。','core/agent_plugins/virtual_human_life/service.py','def dispatch_conversation_mailbox_once('),
        ('submitter','原生提交适配','默认 submitter 调 submit_session_message_lightweight。',svc+'virtual_human_life_service.py','def _default_conversation_submitter('),
        ('native','原生 Session','进入同一个 Session submit/scheduler/worker/Journal/SSE 链。',svc+'session/submit.py','def submit_session_message_lightweight('),
    ],[
        ('route','facade','人物接口','route 委托 queue_virtual_human_conversation_message。','core/web/routes/virtual_human_life.py','def life_conversation_message('),
        ('facade','plugin','插件委托','Web facade 调受信插件服务。',svc+'virtual_human_life_service.py','def queue_virtual_human_conversation_message('),
        ('plugin','mailbox','排入命令','enqueue_mailbox_entry 保存到达顺序。','core/agent_plugins/virtual_human_life/service.py','enqueue_mailbox_entry('),
        ('mailbox','dispatch','领取租约','dispatcher 从 mailbox 领取可提交命令。','core/agent_plugins/virtual_human_life/service.py','claim_next_mailbox_entry('),
        ('dispatch','submitter','调用 submitter','插件通过可注入的 submitter 接入原生会话。',svc+'virtual_human_life_service.py','def _default_conversation_submitter('),
        ('submitter','native','lightweight submit','在原生接收边界之前适配，不另建会话执行器。',svc+'virtual_human_life_service.py','submit_session_message_lightweight('),
    ])
    finance = svc+'financial_assistant_service.py'
    view('finance','金融助手与公开行情研究','金融工作台复用 Agent、scoped knowledge 和原生 Session；公开行情由页面查询 API 与 Agent 只读工具两条路径读取。没有账户、持仓或交易能力。',[
        ('ui','FinanceRoute 入口','空列表且 entry plan=create 时自动 POST 建立助手；打开会话前校验 direct session 或 Agent 归属。','web/src/routes/FinanceRoute.tsx','function FinanceRoute'),
        ('workspace','FinanceResearchWorkspace','展示股票搜索、报价/K线、报告与历史；研究聊天嵌入 ChatCodingRoute 并复用原生 Session。','web/src/routes/finance/FinanceResearchWorkspace.tsx','export function FinanceResearchWorkspace('),
        ('route','金融助手 API','助手 GET/POST 保持独立；GET 仅投影，POST 执行 setup/旧配置升级。','core/web/routes/financial_assistant.py','def financial_assistant_create('),
        ('marketRoute','公开行情 API','GET 搜索与股票快照；校验代码/周期并映射未找到、无效请求和行情源失败。','core/web/routes/financial_assistant.py','def financial_market_search('),
        ('setup','幂等 Setup / 策略升级','新建时配置只读工具；旧助手仅在未自定义的默认策略上，经显式 POST 升级行情工具。',finance,'def create_financial_assistant('),
        ('agent','Agent Directory','设置 general Agent、financial_advisor 角色和 financial_assistant_v1 工具策略。',finance,'READ_TOOLS ='),
        ('kb','Scoped Knowledge','创建 per-Agent 知识库并限制读取范围；与公开行情源和普通 Session transcript 分开。',finance,'get_financial_knowledge_base('),
        ('session','原生 Direct Session','ensure_agent_direct_session 建立原生会话；工作台内嵌 ChatCodingRoute 负责普通 Session 生命周期。',finance,'ensure_agent_direct_session('),
        ('marketClient','前端行情 API 客户端','financialMarket API 提供股票搜索与快照 query keys，并经 fetchJson 调用后端。','web/src/api/financialMarket.ts','export function fetchFinancialStock('),
        ('marketService','公开行情服务','调用腾讯搜索、报价与前复权日/周/月 K线；报价缓存 30 秒，搜索/K线缓存 300 秒，K线可部分失败。','core/web/services/financial_market_service.py','def get_stock_snapshot('),
        ('provider','腾讯财经公开数据源','外部公开 A 股数据；行情可能延迟或缓存，不含账户、持仓、下单或分钟线。','core/web/services/financial_market_service.py','https://qt.gtimg.cn'),
        ('toolDefinition','Agent 行情工具注册','Key_Tools 注册 financial_market_snapshot_tool；只有当前 Agent 策略授权后才向模型开放。','tools/Key_Tools.py','def financial_market_snapshot_tool('),
        ('toolLifecycle','原生工具授权与执行','Agent tool call 进入 ToolLifecycleBridge；行情工具列入只读并发分类，ToolExecutor 仍做最终授权。','core/orchestration/tool_lifecycle.py','financial_market_snapshot_tool'),
        ('marketAdapter','行情工具适配器','校验股票代码、周期和数量，限制输出并清理 Provider 错误，再委托行情服务。','tools/financial_market_tools.py','def financial_market_snapshot_tool('),
        ('projection','助手能力投影','marketDataStatus=public_quotes 表示存在公开行情能力；marketToolStatus 单独表示工具授权状态。','core/web/services/financial_assistant_service.py','def _project('),
    ],[
        ('ui','route','助手列表 / 创建','前端 financialAssistant API 查询列表；空列表的 entry plan 可自动发起创建 POST。','web/src/api/financialAssistant.ts','export function listFinancialAssistants('),
        ('route','setup','POST setup','创建或恢复助手；旧策略升级只改动未自定义的只读默认值。','core/web/routes/financial_assistant.py','def financial_assistant_create('),
        ('setup','agent','设置角色与策略','建立 financial_advisor Agent 并配置允许的财报、证据、新闻及行情读取工具。',finance,'def create_financial_assistant('),
        ('setup','kb','绑定知识范围','创建 scoped KB 并配置 per-Agent 读取策略。',finance,'def create_financial_assistant('),
        ('setup','session','Provision Session','复用原生 Agent direct Session，不另建金融 transcript。',finance,'ensure_agent_direct_session('),
        ('route','projection','助手状态投影','list 纯读投影；创建结果也由同一 service 生成能力状态。',finance,'def _project('),
        ('projection','ui','返回助手状态','前端分别读取数据能力和 Agent 工具授权状态。','web/src/api/financialAssistant.ts','export type FinancialAssistant'),
        ('ui','workspace','选中并校验会话','FinanceRoute 仅把已匹配助手的 direct session 或归属已核验的会话交给工作台。','web/src/routes/FinanceRoute.tsx','return <FinanceResearchWorkspace'),
        ('workspace','session','复用原生聊天','工作台内嵌 ChatCodingRoute；新研究创建 Agent Session，不另建 turn/transcript 实现。','web/src/routes/finance/FinanceResearchWorkspace.tsx','const nativeWorkspace = useMemo'),
        ('workspace','marketClient','查股票与行情','股票选择驱动搜索和快照查询；研究输入可将当前快照作为 Agent 研究上下文。','web/src/routes/finance/FinanceResearchWorkspace.tsx','const market = useQuery'),
        ('marketClient','marketRoute','GET 搜索 / 快照','searchFinancialStocks 与 fetchFinancialStock 经公共 HTTP 客户端访问领域 endpoints。','web/src/api/financialMarket.ts','export function searchFinancialStocks('),
        ('marketRoute','marketService','委托行情服务','路由只校验请求并映射错误；数据解析、缓存及 Provider 调用归服务层。','core/web/routes/financial_assistant.py','def financial_market_stock('),
        ('marketService','provider','读取公开报价 / K线','腾讯端点提供报价、搜索与前复权日/周/月 K线；报价和 K线分别处理失败。','core/web/services/financial_market_service.py','def get_stock_snapshot('),
        ('agent','toolDefinition','策略允许模型使用','tool profile 只是允许范围；逐回合可见性与执行仍经过原生授权。',finance,'MARKET_TOOL ='),
        ('agent','toolLifecycle','模型提出工具调用','金融助手调用仍进入通用 Agent 工具循环，不由行情 UI 直接执行。','agent.py','def _invoke_llm('),
        ('toolLifecycle','toolDefinition','校验并分派 canonical tool','ToolLifecycleBridge 经 ToolExecutor 最终授权后，按注册表映射到工具封装。','core/orchestration/tool_lifecycle.py','def execute_tool('),
        ('toolDefinition','marketAdapter','封装调用 adapter','Key_Tools 将有界 LangChain tool 包装绑定到 financial_market_tools 实现。','tools/Key_Tools.py','from tools.financial_market_tools import financial_market_snapshot_tool'),
        ('marketAdapter','marketService','只读快照委托','工具仅发送股票代码、周期和数量；输出保留来源、数据时间和单位。','tools/financial_market_tools.py','def financial_market_snapshot_tool('),
    ])
    view('session','消息 → Agent 回合','提交、排队、执行、落账分开；同一会话串行，Agent 并发由 scheduler 控制。',[
        ('http','提交消息 API','Prefer: respond-async 可进入轻量响应分支；最终委托 Session submit。','core/web/routes/sessions.py','def session_submit_message('),
        ('submit','接收 / 登记','校验输入、准备上下文并追加初始回合与用户消息事件。','core/web/services/session/submit.py','def submit_session_message('),
        ('schedule','调度适配','把 context 与 submit/release 回调交给 SessionTurnScheduler。','core/web/services/session/schedule.py','def _schedule_session_turn('),
        ('scheduler','SessionTurnScheduler','按会话顺序与 Agent 并发槽决定何时执行回调。','core/web/services/session_turn_scheduler.py','class SessionTurnScheduler:'),
        ('worker','Session worker','载入 Agent 快照与上下文，运行本轮；统一处理完成与失败。','core/web/services/session/worker.py','def _run_session_turn_impl('),
        ('turn','单轮执行','复用 Agent runtime；单轮内部允许模型与工具多次交互。','core/orchestration/turn_runner.py','def run_existing_agent_single_turn('),
        ('persist','终态持久化','保存 assistant 结果和 turn 终态，结束不是仅停止 SSE。','core/web/services/session/persist.py','def _persist_session_turn_result('),
        ('journal','Turn Journal','追加式 transcript / tool / lifecycle 事件权威。','core/chat/turn_journal.py','def append_turn_event('),
        ('context','上下文组装','组装身份、记忆、提示词和本轮消息上下文。','core/orchestration/context_engine.py','def build_agent_context('),
    ],[
        ('http','submit','受理请求','HTTP route 根据 Prefer 选择轻量或普通 submit。','core/web/routes/sessions.py','def session_submit_message('),
        ('submit','schedule','提交 context','接收逻辑完成登记后排入执行调度。','core/web/services/session/submit.py','def submit_session_message('),
        ('schedule','scheduler','排队 / 并发槽','传入本轮 context 和执行、释放回调。','core/web/services/session/schedule.py','def _schedule_session_turn('),
        ('scheduler','worker','执行回调','获准后 _submit_scheduled_session_turn 经 executor/包装函数调 worker。','core/web/services/session/schedule.py','def _submit_scheduled_session_turn('),
        ('worker','context','准备上下文','worker 初始化当前 Agent 回合所需上下文。','core/web/services/session/worker.py','def _run_session_turn_impl('),
        ('context','turn','传入上下文','Session worker 将 context packet 派生的 blocks/history 传入单轮调用；ContextEngine 产出数据，调用者仍是 worker。','core/web/services/session/worker.py','def _run_session_continuation_loop('),
        ('worker','turn','执行本轮','worker 驱动已有 Agent 的单轮 runner。','core/web/services/session/worker.py','def _run_session_turn_impl('),
        ('worker','persist','结算结果','完成路径统一调用结果持久化。','core/web/services/session/worker.py','def _finish_session_turn_worker('),
        ('submit','journal','初始事件','初始 turn markers 与用户消息进入日志。','core/web/services/session/submit.py','def _append_initial_session_journal_markers('),
        ('persist','journal','assistant / terminal','将结果与终态写入回合日志，保持事件权威。','core/web/services/session/persist.py','def _persist_session_turn_result('),
    ])
    view('stream','实时输出与持久化','SSE 为直播，Journal 为记录。断线/页面刷新不应把直播 delta 当作完整历史。',[
        ('capture','流式捕获','捕获 assistant 和工具 UI 事件，批处理直播片段并记录。','core/web/services/session/stream_capture.py','def _capture_session_ui_stream('),
        ('publish','Delta 发布','发布 assistant delta，推动订阅者看到增量输出。','core/web/services/session/publish.py','def _publish_session_assistant_delta('),
        ('subscribe','事件订阅队列','异步流订阅 Session 事件。','core/web/services/session/publish.py','def stream_session_events_async('),
        ('sse','HTTP SSE','session_events 对外暴露事件流；不是 transcript 的写入权威。','core/web/routes/sessions.py','def session_events('),
        ('persist','最终结果','本轮结束后持久化最终 assistant 和状态。','core/web/services/session/persist.py','def _persist_session_turn_result('),
        ('journal','Journal 记录','终态与过程事件由追加接口保护。','core/chat/turn_journal.py','def append_turn_event('),
    ],[
        ('capture','publish','增量通知','捕获逻辑触发 assistant delta 对外发布。','core/web/services/session/stream_capture.py','def _capture_session_ui_stream('),
        ('publish','subscribe','广播事件','发布与订阅经 session 事件队列交接。','core/web/services/session/publish.py','def stream_session_events_async('),
        ('subscribe','sse','SSE 输出','路由消费异步 Session 事件流。','core/web/routes/sessions.py','def session_events('),
        ('persist','journal','最终落账','直播完成不取代结果持久化。','core/web/services/session/persist.py','def _persist_session_turn_result('),
    ])
    view('llm','模型调用与协议','模型选择与协议客户端分层。此图仅表示代码调用路径，不代表某个 Provider 当前可用。',[
        ('context','AgentContext','组装当前回合上下文。','core/orchestration/context_engine.py','def build_agent_context('),
        ('turn','回合 Runner','准备消息并驱动当前 Agent 实例。','core/orchestration/turn_runner.py','def run_existing_agent_single_turn('),
        ('agent','AgentRuntime','每轮模型请求进入 _invoke_llm。','agent.py','def _invoke_llm('),
        ('adapter','LLM 回合适配','集中适配 Agent 回合到模型 invocation。','core/orchestration/turn_llm_adapter.py','def invoke_agent_llm_turn('),
        ('invoke','模型 Invocation','经 LLMClient 按 profile/provider 解析协议和 wire；含流式与用量处理。','core/llm/invocation.py','def invoke_llm('),
        ('tools','本轮工具 Schema','只物化获准工具；具体执行仍有最终授权。','core/orchestration/tool_authorization_binding.py','def materialize_authorized_tools('),
    ],[
        ('context','turn','回合输入','worker 把组装后的上下文和消息历史交给单轮 runner；这条边表示数据传入，不表示 ContextEngine 直接调用 runner。','core/web/services/session/worker.py','def _run_session_continuation_loop('),
        ('turn','agent','运行回合','Runner 调用现有 Agent 的执行入口，Agent 内部进入模型调用。','core/orchestration/turn_runner.py','def run_existing_agent_single_turn('),
        ('agent','adapter','模型适配','Agent _invoke_llm 委托 invoke_agent_llm_turn。','agent.py','def _invoke_llm('),
        ('adapter','invoke','统一调用','适配器委托 invocation。','core/orchestration/turn_llm_adapter.py','def invoke_agent_llm_turn('),
        ('agent','tools','物化工具','Agent 经 _materialize_authorized_tools 获取本回合获准工具集合，随后将 schema 随请求传给模型。','agent.py','def _materialize_authorized_tools('),
    ])
    view('tools','工具可见性 → 执行授权','模型看见工具和工具真正获准执行是两个检查点；需要审批时等待用户决策。',[
        ('defs','候选工具集','构造面向模型的候选工具定义。','tools/Key_Tools.py','def create_llm_facing_tools('),
        ('policy','回合授权','根据 descriptor、ToolPolicy 与 turn grant 判定可见性。','core/orchestration/tool_authorization_binding.py','def resolve_turn_authorization('),
        ('materialize','获准工具物化','仅物化授权后的工具集合。','core/orchestration/tool_authorization_binding.py','def materialize_authorized_tools('),
        ('visible','调用可见性检查','模型返回 tool_calls 后拦截隐藏或幻觉工具。','agent.py','def _is_tool_visible_to_current_agent('),
        ('lifecycle','工具生命周期','拆批、执行与工具事件记录。','core/orchestration/tool_lifecycle.py','class ToolLifecycleBridge:'),
        ('executor','ToolExecutor','最终授权后才通过 tool map 调用实际工具函数。','core/infrastructure/tool_executor.py','class ToolExecutor:'),
        ('auth','执行前最终授权','检查 canonical execution authorization；可拒绝或进入审批。','core/authorization/tool_authorization_service.py','def authorize_tool_execution('),
        ('approval','等待用户审批','按需等待，拒绝不会执行工具。','core/web/services/session/tool_approvals.py','def authorize_or_wait('),
        ('decision','审批 API','用户决定唤醒对应的等待请求。','core/web/routes/sessions.py','def session_resolve_tool_approval('),
    ],[
        ('defs','policy','候选 → 判定','候选工具经回合授权选择。','core/orchestration/tool_authorization_binding.py','def resolve_turn_authorization('),
        ('policy','materialize','物化 allowed','只生成允许工具的模型绑定。','agent.py','def _materialize_authorized_tools('),
        ('visible','lifecycle','仅可见调用','可见性过滤后才进入工具生命周期；不把模型输出当授权。','agent.py','_is_tool_visible_to_current_agent('),
        ('lifecycle','executor','执行回调','ToolLifecycleBridge.execute_tool 调用执行回调。','core/orchestration/tool_lifecycle.py','def execute_tool('),
        ('executor','auth','canonical check','执行前调用 canonical 授权服务。','core/infrastructure/tool_executor.py','def _check_canonical_execution_authorization('),
        ('auth','approval','on_request','授权策略要求人工确认时进入等待。','core/authorization/tool_authorization_service.py','def authorize_tool_execution('),
        ('decision','approval','解决请求','审批 API 调用 resolve_tool_approval_request 唤醒等待者。','core/web/routes/sessions.py','def session_resolve_tool_approval('),
    ])
    view('knowledge','统一搜索与知识检索','检索是受权限约束的读取。RAG 返回有界上下文与引用，不自行注入 Agent prompt。',[
        ('tool','统一记忆搜索工具','要求 Agent identity，检查知识库读取策略与用户 Space allowlist。','tools/team_knowledge_tools.py','def unified_memory_search_tool('),
        ('unified','统一搜索服务','分派正式知识、个人记忆、项目/GitHub 与显式用户内容查询。','core/web/services/unified_knowledge_search_service.py','def search_unified_memory('),
        ('rag','RAG 检索','仅 rag 模式进入此分支，返回有长度上限的 contexts/citations。','core/web/services/rag_retrieval_service.py','def retrieve_rag_contexts('),
        ('canonical','Team Knowledge Search','正式知识条目的范围、来源、eligibility 与权限筛选。','core/web/services/team_knowledge/retrieval.py','def search_knowledge_items('),
        ('acl','知识权限','owner/base 范围按读取权限检查。','core/web/services/team_knowledge/permissions.py','def _require_permission('),
        ('rank','检索排序','精确/BM25 或 semantic/hybrid；hybrid 向量不可用可降级 BM25。','core/web/services/team_knowledge/semantic.py','def rank_candidates('),
        ('index','可重建向量索引','查询读取 canonical items 的派生索引，不是正式知识正文权威。','core/web/services/rag_vector_index_service.py','def _read_json('),
    ],[
        ('tool','unified','受控查询','校验主体与允许范围后调用统一搜索。','tools/team_knowledge_tools.py','def unified_memory_search_tool('),
        ('unified','rag','rag 模式','_rag_search 显式委托 RAG retrieval。','core/web/services/unified_knowledge_search_service.py','def _rag_search('),
        ('unified','canonical','其他知识模式','exact/semantic/hybrid/BM25/metadata 经正式知识查询。','core/web/services/unified_knowledge_search_service.py','def _knowledge_search_payloads('),
        ('rag','canonical','检索上下文','RAG 复用正式知识检索后组装引用。','core/web/services/rag_retrieval_service.py','def retrieve_rag_contexts('),
        ('canonical','acl','读权限','知识检索对 owner/base 权限与 item/source 范围进行检查。','core/web/services/team_knowledge/retrieval.py','def search_knowledge_items('),
        ('canonical','rank','排序候选','语义或混合模式应用 semantic 排序。','core/web/services/team_knowledge/retrieval.py','def search_knowledge_items('),
        ('rank','index','读取派生索引','排序消费已建立的 embedding 索引；非正文写入。','core/web/services/team_knowledge/semantic.py','def rank_candidates('),
    ])
    view('knowledge-write','正式知识与个人记忆','知识提案审核与直接来源审核是不同路径；个人记忆、文件记忆和知识库各有存储。',[
        ('proposal','精炼提案','提出 refinement proposal，尚未自动等同正式知识。','core/web/services/team_knowledge/governance.py','def create_refinement_proposal('),
        ('review','审核提案','审核接受/应用后产生批次与正式条目，并记录审计。','core/web/services/team_knowledge/governance.py','def review_refinement_proposal('),
        ('items','Owner-scoped 知识','知识库、来源、提案、items、batches 和 audit 在 owner 范围持久化。','core/web/services/team_knowledge/store.py','def _knowledge_root_for_owner('),
        ('sync','语义索引同步','reviewed item 同步到可重建向量索引。','core/web/services/team_knowledge/semantic.py','def sync_reviewed_item('),
        ('index','向量索引','索引写入与正式条目分开。','core/web/services/rag_vector_index_service.py','def write_index_record('),
        ('episodic','Agent 个人事件记忆','workspace/agents/{id}/events/episodic_events.jsonl，与会话 transcript 不同。','core/web/services/agent_directory/episodic_memory.py','def append_episodic_event('),
        ('filememory','文件记忆','独立的文件式 memory 工具持久化，不合并到 Journal。','tools/memory_tools.py','def _save_memory('),
        ('ingest','来源审核导入','knowledge_ingestion_tool 的 inbox_source_id 路径只有 accept 后才 ingest_on_accept；不是所有调用都直接写 items。','tools/team_knowledge_tools.py','def knowledge_ingestion_tool('),
    ],[
        ('proposal','review','待审提案','先记录提案，再由显式审核决定是否应用。','core/web/services/team_knowledge/governance.py','def review_refinement_proposal('),
        ('review','items','应用与审计','accepted/applied 后写 batches/items 与审计记录。','core/web/services/team_knowledge/governance.py','def review_refinement_proposal('),
        ('sync','index','写 embedding','对已审核条目建立派生向量索引。','core/web/services/team_knowledge/semantic.py','def sync_reviewed_item('),
        ('ingest','items','接受来源后导入','inbox 来源审核分支允许 source_document/authored；成功后尝试同步语义索引。','tools/team_knowledge_tools.py','def knowledge_ingestion_tool('),
    ])
    view('storage','数据与权威边界','这些节点表示不同的数据职责，不能互相代替。仅展示源码路径规则，未读取本机运行数据库。',[
        ('paths','项目 / 实例路径','ProjectStoragePaths 区分 project、instance、data、runtime、logs、memory 和 cache。','vibelution_storage.py','class ProjectStoragePaths:'),
        ('workspace','实例 workspace','workspace 从实例 data/workspace 派生；沙箱路径另有显式解析。','core/infrastructure/developer_sandbox.py','def formal_workspace_path('),
        ('journal','Turn Journal · JSONL','会话事件追加到 sessions/<token>/turn_journal.jsonl，终态写入受保护。','core/chat/turn_journal.py','def append_turn_event('),
        ('directory','会话目录 · SQLite','ConversationStore 提供目录和控制面存取，不替代完整 transcript。','core/chat/conversation_store/store.py','class ConversationStore:'),
        ('bridge','目录同步与终态投影','同步目录字段；列表查询再批量附加原生 turn 终态元数据，不改 transcript 权威。','core/web/services/session/directory_bridge.py','def _with_terminal_states('),
        ('config','Operator 配置','config/ 是实际配置代码库；配置文件路径由 resolve_config_path 决定。','config/paths.py','def resolve_config_path('),
        ('ledger','研究 Workflow Ledger','研究运行和命令/Outbox 使用专门账本；不是普通会话 transcript。','core/research/workflow/ledger/store.py','class WorkflowLedgerStore:'),
    ],[
        ('paths','workspace','解析工作区','formal_workspace_path 经统一存储路径规则返回工作区。','core/infrastructure/developer_sandbox.py','def formal_workspace_path('),
        ('workspace','journal','sessions / token','turn_journal_workspace_root 经 sandboxed_workspace_path 选择正式或隔离工作区，再定位每个会话日志。','core/chat/turn_journal.py','def turn_journal_workspace_root('),
        ('bridge','directory','同步与列表增强','同步可查询目录字段；读取时批量附加 lastTurnStatus、terminal turn id 和 terminalReason。','core/web/services/session/directory_bridge.py','def _with_terminal_states('),
    ])
