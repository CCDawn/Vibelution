"""Reviewed project-level wiki pages and cross-domain relationships.

The wiki is a curated navigation layer over the source inventory. Its links
describe only relationships with a concrete source anchor; directory
membership and static imports are not treated as runtime edges.
"""


def make_wiki(ref):
    """Build the architecture wiki using the caller's fixed-source ref resolver."""

    groups = [
        {
            'id': 'runtime-entry',
            'label': '运行入口',
            'description': '桌面生命周期、工作台页面与 Web 服务入口。',
            'role': 'runtime',
            'domainIds': ['desktop', 'frontend', 'gateway'],
        },
        {
            'id': 'agent-execution',
            'label': 'Agent 执行与平台',
            'description': 'Session 调度、Agent 单轮、受控工具与共享运行基础。',
            'role': 'runtime',
            'domainIds': ['session', 'intelligence', 'tools', 'platform'],
        },
        {
            'id': 'runtime-capabilities',
            'label': '业务能力',
            'description': '团队科研、知识治理、进化评测与 Companion 专业能力。',
            'role': 'runtime',
            'domainIds': ['research', 'knowledge', 'evolution', 'companions'],
        },
        {
            'id': 'engineering-support',
            'label': '工程支撑',
            'description': '验证、仓库维护与当前开发规范，为运行能力提供支撑。',
            'role': 'support',
            'domainIds': ['engineering', 'docs'],
        },
        {
            'id': 'reference-material',
            'label': '参考材料',
            'description': '实验演示与历史记录；它们不代表当前产品运行权威。',
            'role': 'reference',
            'domainIds': ['experiments', 'archive'],
        },
    ]

    def entry(label, note, path, anchor):
        return {'label': label, 'note': note, 'ref': ref(path, anchor)}

    def page(
        domain_id,
        title,
        summary,
        responsibilities,
        boundaries,
        entries,
        scenarios=(),
        related=(),
    ):
        return {
            'id': domain_id,
            'title': title,
            'summary': summary,
            'responsibilities': responsibilities,
            'boundaries': boundaries,
            'entryPoints': entries,
            'scenarioIds': list(scenarios),
            'relatedDomainIds': list(related),
        }

    pages = [
        page(
            'desktop', '桌面与生命周期',
            'Electron 主进程、Launcher 控制与工作台进程生命周期。',
            [
                'Electron 主进程管理窗口、IPC、实例状态与受控的启动、停止和恢复。',
                'Launcher 控制经过 preload 暴露的 IPC；主线操作进入生命周期队列，分支实例操作核对 registry 与真实进程身份。',
                'Workbench backend 按工作区启动；进程健康、API 就绪和页面可用是不同阶段。',
            ],
            [
                '桌面生命周期拥有进程和窗口控制；业务 HTTP 请求仍由前端与 Web 服务处理。',
                '端口和实例身份应从当前运行实例解析，源码默认值不能证明现场状态。',
                '分支 start 只有实例代次、命令、进程身份和端口复核一致才返回复用；缓存 alive 不能确认启动成功。',
            ],
            [
                entry('Electron 主进程', 'Launcher IPC 与主进程控制入口。',
                      'desktop/electron/src/main.ts', 'ipcMain.handle(IPC_CHANNELS.launcherInvoke'),
                entry('Workbench backend', '创建并监督归属当前 workspace 的后台进程。',
                      'desktop/electron/src/process/workbenchBackend.ts', 'export function spawnWorkbenchBackend('),
                entry('生命周期队列', '串行化主线启动、停止和恢复命令。',
                      'desktop/electron/src/lifecycle/mainLine/commandQueue.ts', 'export function createMainLineCommandQueue('),
                entry('分支实例复用核验', '核对 registry、进程身份与端口，决定复用、启动或等待核对。',
                      'desktop/electron/src/lifecycle/isolatedInstanceRegistryHost.ts', 'export async function inspectIsolatedStartReuse('),
            ],
            ['startup', 'storage'], ['frontend', 'gateway', 'platform'],
        ),
        page(
            'frontend', '工作台与 VUI',
            'React 路由、VUI 产品组件、领域 API、会话呈现与前端状态。',
            [
                '路由和页面组织会话、团队、研究、知识、金融助手等工作台。',
                '领域 API 通过公共 HTTP 客户端传输，并将请求状态投影到页面。',
                'Session event stream 将服务端实时事件转换为会话视图更新。',
            ],
            [
                'Launcher 生命周期控制走 preload IPC；它与普通 JSON/HTTP 领域 API 分开。',
                '页面状态与 SSE 增量不是会话 transcript 的持久化权威。',
            ],
            [
                entry('路由入口', 'React Router 将路径映射到懒加载工作台页面。',
                      'web/src/app/router.tsx', 'createBrowserRouter(['),
                entry('领域 HTTP 客户端', '公共 fetchJson 处理工作台领域请求。',
                      'web/src/api/client.ts', 'export async function fetchJson<'),
                entry('会话事件流', 'Session SSE 订阅把事件交给页面消费。',
                      'web/src/routes/chat/sessionEventStream.ts', 'export function createSessionEventStream('),
            ],
            ['overview', 'http', 'stream', 'finance', 'companion'],
            ['desktop', 'gateway', 'session', 'companions'],
        ),
        page(
            'gateway', 'Web 入口与协议',
            'FastAPI 应用、中间件、路由注册、控制边界和生命周期入口。',
            [
                '应用工厂建立 FastAPI 实例并连接服务生命周期与路由 bootstrap。',
                '控制中间件约束请求来源；路由注册器把领域 API 挂到统一 /api 前缀。',
                'HTTP route 保持薄层，将领域行为委托给 service。',
            ],
            [
                '局部路由装饰器路径还需叠加 router prefix 与 /api 才是完整 API 路径。',
                '路由层不是 Agent Session、Journal 或领域数据的第二写入权威。',
            ],
            [
                entry('应用工厂', 'FastAPI 和分阶段 route bootstrap 的入口。',
                      'core/web/app.py', 'def create_app('),
                entry('路由模块注册', '按稳定次序加载并挂载领域 router。',
                      'core/web/router_registry.py', 'def import_web_route_modules('),
                entry('控制请求边界', '中间件执行 Web 控制来源校验。',
                      'core/web/control.py', 'class WebControlGuardMiddleware('),
            ],
            ['startup', 'http', 'overview', 'session'],
            ['desktop', 'frontend', 'session', 'platform'],
        ),
        page(
            'session', 'Agent 与会话',
            'Session 接收、调度、worker、Journal、持久化、投影和 SSE 发布。',
            [
                '提交层登记用户输入并交给调度器；scheduler 管理会话串行与 Agent 并发槽。',
                'worker 驱动单轮 Agent continuation loop，并把模型与工具事件捕获为 Turn 结果。',
                'Turn Journal 保存事件权威；会话目录 SQLite 提供可查询目录与控制信息。',
                'SSE publisher 发布增量；完成或失败后由持久化路径结算终态。',
            ],
            [
                'ConversationStore 是目录和控制面，不取代 Turn Journal transcript。',
                'SSE 是实时投递，不是完整历史；断线后需要从持久化记录恢复。',
            ],
            [
                entry('Session 消息入口', 'HTTP route 将提交委托给 Session 服务。',
                      'core/web/routes/sessions.py', 'def session_submit_message('),
                entry('调度入口', '排队和并发控制进入 Session scheduler。',
                      'core/web/services/session/schedule.py', 'def _schedule_session_turn('),
                entry('Agent continuation loop', 'worker 构建上下文后驱动当前 Agent 回合。',
                      'core/web/services/session/worker.py', 'result = _run_session_continuation_loop('),
                entry('Turn Journal', '会话事件以追加记录方式写入 Journal。',
                      'core/chat/turn_journal.py', 'def append_turn_event('),
            ],
            ['overview', 'session', 'stream', 'companion', 'research', 'storage'],
            ['gateway', 'intelligence', 'tools', 'knowledge', 'companions', 'research'],
        ),
        page(
            'intelligence', '模型与单轮执行',
            'Agent 上下文、提示装配、模型协议适配与单轮执行循环。',
            [
                'Agent runner 组合身份、上下文、历史消息、工具策略和停止条件。',
                '统一 LLM invocation 选择模型协议并处理调用结果和流式响应。',
                '模型发出的工具调用交由工具生命周期桥接器执行与回写。',
            ],
            [
                '模型路由和协议客户端描述源码路径，不证明某个 Provider 当前可用。',
                '可见工具集合与工具执行授权分开检查，模型输出本身不构成授权。',
            ],
            [
                entry('Agent 模型调用', 'Agent 将一轮请求交给模型调用适配。',
                      'agent.py', 'def _invoke_llm('),
                entry('统一 LLM invocation', '集中解析请求、协议和模型响应。',
                      'core/llm/invocation.py', 'def invoke_llm('),
                entry('工具生命周期桥接', '单轮执行将工具调用交给受控执行回调。',
                      'core/orchestration/tool_lifecycle.py', 'def execute_tool('),
            ],
            ['overview', 'session', 'llm', 'tools'],
            ['session', 'tools', 'knowledge', 'platform'],
        ),
        page(
            'tools', '工具与权限',
            '工具目录、Agent 工具策略、授权检查、受控执行和 MCP/外部能力。',
            [
                '注册表与 Agent 策略决定工具是否可见；生命周期桥接器解释模型调用并回写结果。',
                'ToolExecutor 在执行边界检查最终权限并运行具体能力。',
                '知识、研究和行情等工具通过适配层调用其领域 service。',
            ],
            [
                'Agent 配置中的工具 profile 不是最终的逐次执行授权。',
                'MCP、外部 Agent 和本地工具都必须受各自受控边界约束。',
            ],
            [
                entry('工具生命周期桥接', '承接 canonical tool call、执行授权与结果回写。',
                      'core/orchestration/tool_lifecycle.py', 'def execute_tool('),
                entry('最终执行器', '受控运行已通过调用链检查的工具。',
                      'core/infrastructure/tool_executor.py', 'class ToolExecutor:'),
                entry('知识检索工具', 'Agent 工具通过统一知识搜索 service 获取有界结果。',
                      'tools/team_knowledge_tools.py', 'def unified_memory_search_tool('),
                entry('行情快照工具', '只读工具验证输入后委托公开行情服务。',
                      'tools/financial_market_tools.py', 'def financial_market_snapshot_tool('),
            ],
            ['overview', 'tools', 'llm', 'knowledge', 'finance'],
            ['intelligence', 'knowledge', 'companions', 'platform'],
        ),
        page(
            'research', '团队与科研',
            '团队协作、研究运行、Stage 工作流、实验、证据与 Workflow Ledger。',
            [
                '团队工作台组织成员、来源、问题、假设、实验和结果包。',
                'Research runtime 创建和恢复运行，适配器把 Agent 工作交给原生 Session。',
                'Workflow Ledger、运行状态和 artifact receipt 记录科研事务，不替代普通聊天账本。',
            ],
            [
                '研究 run、命令和 outbox 有自己的状态与账本，不是普通 Session transcript。',
                '群聊投递或工具回执只表示消息/动作交付，不代表 Agent 工作已完成。',
            ],
            [
                entry('研究运行创建', '创建 workflow run 并设置运行初始状态。',
                      'core/web/services/team_workflow/research_runtime/run_creation.py', 'def create_run('),
                entry('研究 Workflow Ledger', '科研工作流的事件与状态持久化入口。',
                      'core/research/workflow/ledger/store.py', 'class WorkflowLedgerStore:'),
                entry('Session 适配器', '研究域端口将 Agent 任务提交到原生 Session。',
                      'core/web/services/team_workflow/research_runtime/real_domain_ports.py', 'started = submit_session_message('),
            ],
            ['teams', 'research', 'knowledge', 'storage'],
            ['session', 'knowledge', 'gateway', 'tools'],
        ),
        page(
            'knowledge', '记忆与知识',
            '知识库、统一检索、来源治理、ACL、个人记忆与研究知识记录。',
            [
                'Team Knowledge 管理知识条目、来源、权限、生命周期和检索候选。',
                '统一搜索工具按当前知识范围返回有界检索结果与引用。',
                '研究知识、个人记忆、文件记忆和正式知识库分别保留自己的来源与写入路径。',
            ],
            [
                '检索能力受调用主体和知识 ACL 约束，结果不会自行越权写入 Agent 上下文。',
                '知识提案审核、来源审核与个人记忆写入不是同一条事务。',
            ],
            [
                entry('知识条目检索', '执行带搜索模式和权限边界的知识候选查询。',
                      'core/web/services/team_knowledge/retrieval.py', 'def search_knowledge_items('),
                entry('Agent 知识搜索工具', '工具适配统一知识搜索 service 并投影引用。',
                      'tools/team_knowledge_tools.py', 'payload = unified_knowledge_search_service.search_unified_memory('),
                entry('研究知识查询', '研究 Agent 使用独立只读研究知识工具。',
                      'tools/research_knowledge_tools.py', 'def research_knowledge_query_tool('),
            ],
            ['knowledge', 'knowledge-write', 'research', 'storage'],
            ['tools', 'research', 'intelligence', 'platform'],
        ),
        page(
            'evolution', '进化与评测',
            '自主进化、监督候选、评测 rubric、Gym 验证和审批后的晋升。',
            [
                '自主进化沿 observe、plan、evolve 到待审核状态，再由人类审批后集成。',
                '监督进化在冻结 rubric 下评估基线与候选，并依配置审批路径处理结果。',
                'Gym 运行、候选归档和晋升应用分别记录执行、决策与激活状态。',
            ],
            [
                '普通 benchmark、Gym promotion gate 和监督 worktree 执行器不是同一个 evaluator。',
                '候选得分或待审状态本身不会自动成为当前产品实现。',
            ],
            [
                entry('自主进化状态', '读取自主进化事务与审计事件。',
                      'core/web/services/self_evolution_service.py', 'def list_self_evolution_transactions('),
                entry('监督晋升门', '对监督候选应用晋升检查逻辑。',
                      'core/evaluation/supervised_evolution.py', 'def _apply_promotion_gate('),
                entry('Gym 晋升应用', '把通过验证的 Gym proposal 应用到候选状态。',
                      'core/gym/promotion.py', 'def apply_gym_promotion_proposal('),
            ],
            ['self-evolution', 'supervised', 'gym', 'storage'],
            ['research', 'engineering', 'platform'],
        ),
        page(
            'companions', '虚拟人与专业插件',
            'Agent-scoped 虚拟人生活插件、桌面宠物和金融研究助手。',
            [
                '虚拟人以 Agent-scoped 插件提供人物状态、主动消息与到达顺序 mailbox。',
                '金融助手复用 Agent、scoped knowledge 与原生 direct Session，并提供公开行情搜索和快照。',
                '桌面宠物和专业入口通过各自适配层连接已有工作台能力。',
            ],
            [
                'Companion mailbox 只管理到达顺序与租约，不保存第二份 transcript；原生 Session Journal、worker 与 SSE 仍是会话权威。',
                '行情可能延迟，缓存可返回先前观测；当前能力不读取账户、持仓或订单。',
            ],
            [
                entry('虚拟人到达适配', '主动消息最终委托原生 Session proactive submit。',
                      'core/web/services/virtual_human_life_service.py', 'return submit_session_proactive_turn(**payload)'),
                entry('金融助手行情路由', '公开股票搜索与快照 API。',
                      'core/web/routes/financial_assistant.py', 'def financial_market_stock('),
                entry('公开行情服务', '缓存和 Provider 处理集中在行情服务。',
                      'core/web/services/financial_market_service.py', 'def get_stock_snapshot('),
                entry('金融研究工作台', 'Finance workspace 复用原生聊天与研究 UI。',
                      'web/src/routes/finance/FinanceResearchWorkspace.tsx', 'const nativeWorkspace = useMemo'),
            ],
            ['companion', 'finance', 'session', 'storage'],
            ['session', 'knowledge', 'tools', 'frontend'],
        ),
        page(
            'platform', '配置与基础设施',
            '配置 schema、路径解析、沙箱工作区、安全文件系统、日志与诊断。',
            [
                '配置代码定义配置结构、Provider/model 目录和安全更新流程。',
                '路径 resolver 选择实际配置、数据和工作区位置；sandbox 区分正式路径与隔离路径。',
                '共享基础设施提供文件、事件、工具执行和诊断能力。',
            ],
            [
                '仓库根 config/ 是活配置代码；根 config.toml 是 legacy/template 材料。',
                '路径规则说明源码如何解析位置，不证明本机当前实例使用哪个实际目录。',
            ],
            [
                entry('配置路径权威', '解析实际 operator config 文件路径。',
                      'config/paths.py', 'def resolve_config_path('),
                entry('工作区路径策略', '将工作区操作路由到正式或隔离位置。',
                      'core/infrastructure/developer_sandbox.py', 'def route_workspace_path('),
                entry('正式工作区解析', '根据项目根与相对路径解析正式 workspace。',
                      'core/infrastructure/developer_sandbox.py', 'def formal_workspace_path('),
            ],
            ['startup', 'storage', 'overview'],
            ['desktop', 'gateway', 'session', 'intelligence', 'tools'],
        ),
        page(
            'engineering', '测试与工程',
            '测试选择、任务说明、closeout、构建、发布脚本和 CI 仓库维护。',
            [
                '测试选择器按改动影响面生成相关验证计划；匹配结果不等同完整覆盖率。',
                '任务脚本和 closeout 规则记录开发证据、验证决定与集成收口。',
                '构建、打包和 CI 自动化支撑产品与文档的工程维护。',
            ],
            [
                '测试或静态构建通过不能单独证明运行时、浏览器、部署或用户可见验收。',
                '这里描述仓库工程入口，不把测试资产视为产品运行时模块。',
            ],
            [
                entry('测试影响面选择', '按改动文件构建测试执行计划。',
                      'tests/select_tests.py', 'def build_execution_plan('),
                entry('任务 closeout', '整理任务验证和集成收尾决策。',
                      'scripts/task_closeout.py', 'def main('),
                entry('任务 brief', '本地生成任务上下文和 owning-surface 信息。',
                      'scripts/task_brief.py', 'def build_brief('),
            ],
            [], ['platform', 'docs', 'evolution'],
        ),
        page(
            'docs', '文档与开发规范',
            '现行开发标准、操作指南、ADR、架构说明和仓库内资源索引。',
            [
                '开发规范和指南描述当前规则、入口与操作契约。',
                'ADR 记录已定架构决策，README 为模块级导航和边界补充。',
                '页面仅提供受版本控制的文档路径，供开发者继续打开阅读。',
            ],
            [
                '历史目录与计划不覆盖当前标准；旧文档不得自动当作现行行为证据。',
                '本页不嵌入文档正文或配置内容。',
            ],
            [
                entry('开发标准', '当前规范文件入口；正文按需查看。',
                      'docs/standards/README.md', None),
                entry('开发指南索引', '当前流程和操作指南入口；正文按需查看。',
                      'docs/guides/README.md', None),
                entry('架构地图说明', '查看本离线架构地图的范围和更新方式。',
                      'docs/architecture/README.md', None),
            ],
            [], ['engineering', 'platform'],
        ),
        page(
            'experiments', '实验与演示',
            '隔离的实验程序、演示和实验依赖资料，可用于了解探索性工作。',
            [
                '实验材料可能用于试验算法、研究工作流或演示运行方式。',
                '入口只定位已跟踪的实验路径，便于开发者自行判断是否相关。',
            ],
            [
                '实验目录不自动属于产品启动、依赖或生产调用链。',
                '只索引路径，不读取或嵌入实验文档、fixture 与配置正文。',
            ],
            [
                entry('Spike Coding 实验', '实验目录路径；不代表产品集成。',
                      'experiments/challenge_cup_spike_coding/README.md', None),
                entry('Predictive Coding 实验', '演示/依赖路径；正文不进入架构快照。',
                      'experiments/challenge_cup_predictive_coding/requirements-cpu.lock', None),
            ],
            [], ['engineering', 'research'],
        ),
        page(
            'archive', '历史材料',
            '归档计划、历史审查与旧模板材料，用于追溯背景，不代表当前实现。',
            [
                '保留历史方案、治理审查和阶段记录的可定位路径。',
                '开发者可在需要追溯决策沿革时单独打开对应原文。',
            ],
            [
                '归档材料不是现行规则、运行证据或当前架构行为权威。',
                '根 config.toml 属旧模板材料；当前配置代码位于 config/。',
                '只索引路径，不读取归档文档或配置值。',
            ],
            [
                entry('历史归档索引', '归档路径入口；需与现行规范区分。',
                      'docs/archive/README.md', None),
                entry('历史工作区治理记录', '归档材料路径；不作为当前开发规范。',
                      'docs/archive/ops/2026-05/2026-05-19-worktree-ownership-audit.md', None),
            ],
            [], ['docs', 'experiments'],
        ),
    ]

    relationships = [
        {
            'id': 'desktop-starts-gateway',
            'from': 'desktop', 'to': 'gateway',
            'kind': 'lifecycle',
            'label': '启动工作台服务进程',
            'detail': 'Electron backend 管理器按 workspace 启动 Workbench 后台；FastAPI 与页面路由就绪仍分阶段判断。',
            'refs': [ref('desktop/electron/src/process/workbenchBackend.ts', 'export function spawnWorkbenchBackend(')],
        },
        {
            'id': 'frontend-http-gateway',
            'from': 'frontend', 'to': 'gateway',
            'kind': 'request',
            'label': '领域 HTTP 请求',
            'detail': '工作台 API 经公共 fetchJson 发起 HTTP 请求；Launcher 控制走独立 IPC 通道。',
            'refs': [ref('web/src/api/client.ts', 'export async function fetchJson<')],
        },
        {
            'id': 'gateway-session-submit',
            'from': 'gateway', 'to': 'session',
            'kind': 'request',
            'label': '提交 Session 消息',
            'detail': 'Session route 接收消息并委托 Session submit/scheduling 路径。',
            'refs': [ref('core/web/routes/sessions.py', 'def session_submit_message(')],
        },
        {
            'id': 'session-agent-turn',
            'from': 'session', 'to': 'intelligence',
            'kind': 'execution',
            'label': 'worker 驱动 Agent 回合',
            'detail': 'Session worker 构造本轮上下文并调用 continuation loop；Agent 轮次中可进行模型和工具交互。',
            'refs': [ref('core/web/services/session/worker.py', 'result = _run_session_continuation_loop(')],
        },
        {
            'id': 'agent-authorized-tools',
            'from': 'intelligence', 'to': 'tools',
            'kind': 'capability',
            'label': '请求受控工具执行',
            'detail': '模型提出的调用经 ToolLifecycleBridge 和最终执行器；策略可见性不取代执行时授权。',
            'refs': [ref('core/orchestration/tool_lifecycle.py', 'def execute_tool(')],
        },
        {
            'id': 'tools-knowledge-retrieval',
            'from': 'tools', 'to': 'knowledge',
            'kind': 'data',
            'label': '调用统一知识检索',
            'detail': 'Agent 知识工具委托统一知识搜索服务，并将受约束的检索结果和引用返回给调用方。',
            'refs': [ref('tools/team_knowledge_tools.py', 'payload = unified_knowledge_search_service.search_unified_memory(')],
        },
        {
            'id': 'research-native-session',
            'from': 'research', 'to': 'session',
            'kind': 'execution',
            'label': '研究任务复用原生 Session',
            'detail': '研究域适配器将 Agent 工作提交到 Session 服务；研究 Workflow Ledger 仍记录研究事务。',
            'refs': [ref('core/web/services/team_workflow/research_runtime/real_domain_ports.py', 'started = submit_session_message(')],
        },
        {
            'id': 'companion-native-session',
            'from': 'companions', 'to': 'session',
            'kind': 'execution',
            'label': 'Companion mailbox 交付原生 Session',
            'detail': '虚拟人服务将已出队消息交给原生 Session proactive submit；mailbox 不建立第二份 transcript。',
            'refs': [ref('core/web/services/virtual_human_life_service.py', 'return submit_session_proactive_turn(**payload)')],
        },
        {
            'id': 'market-tool-market-service',
            'from': 'tools', 'to': 'companions',
            'kind': 'data',
            'label': '行情工具读取公开快照',
            'detail': 'Agent 行情工具验证代码、周期和数量后调用行情服务；公开报价可能延迟或命中缓存，不读取账户或订单。',
            'refs': [ref('tools/financial_market_tools.py', 'snapshot = market.get_stock_snapshot(symbol, period)')],
        },
    ]

    return {'schemaVersion': 1, 'groups': groups, 'pages': pages, 'relationships': relationships}
