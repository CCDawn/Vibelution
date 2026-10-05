"""Reviewed architecture semantics; source anchors are validated by build_atlas.

Inventory grouping is navigational. Only make_views describes reviewed execution
relationships. Update these descriptions after reviewing changed source evidence.
"""

REVIEWED_COMMIT = 'd0fa8febe0ece9600b261bfad6dd5ada0f0a68b3'

DOMAIN_ROWS = [
 ('desktop','桌面与生命周期','Electron 主进程、Launcher、Runtime Manager、实例与进程管理。','#5b67c7'),
 ('frontend','工作台与 VUI','React 路由、交互状态、会话呈现、领域 API、VUI 与静态资源。','#427d9d'),
 ('gateway','Web 入口与协议','FastAPI、路由注册、中间件、控制令牌、服务入口与投影。','#417f86'),
 ('session','Agent 与会话','Agent 档案、Session 接收与调度、Journal、流式事件和会话目录。','#3b8275'),
 ('intelligence','模型与单轮执行','模型协议、上下文、提示词、编排、单轮执行与心理模型。','#7b68a1'),
 ('tools','工具与权限','工具注册与执行、授权、MCP、外部 Agent 与受控能力。','#ac773a'),
 ('research','团队与科研','团队、组织、群聊、研究工作流、实验、证据与运行账本。','#617f48'),
 ('knowledge','记忆与知识','知识库、检索、记忆图谱、内容治理与来源。','#4b8396'),
 ('evolution','进化与评测','自主与监督进化、候选、Gym、评测与人工审核。','#9b667d'),
 ('companions','虚拟人与专业插件','Agent-scoped 插件、人物生活、桌面宠物和金融助手。','#b46f58'),
 ('platform','配置与基础设施','配置代码、路径解析、工作区、日志、诊断和公共基础设施。','#77778a'),
 ('engineering','测试与工程','测试、构建、发布、开发脚本、CI 与仓库维护。','#6e7c87'),
 ('docs','文档与资源','现行规范、ADR、开发指南及展示资源；只索引文件路径。','#85806e'),
 ('experiments','实验与演示','实验程序和演示材料；不自动视为产品运行链路。','#997548'),
 ('archive','历史材料','归档、历史计划与旧记录；不能作为当前行为权威。','#8b8b8b'),
]
DOMAINS = [dict(zip(('id','label','description','color'), row)) for row in DOMAIN_ROWS]


def domain_for(path):
    if path == 'config.toml': return 'archive'
    if path.startswith(('docs/archive/', 'docs/plans/')): return 'archive'
    if path.startswith(('experiments/', '挑战杯/', 'web/preview/')): return 'experiments'
    if path.startswith(('tests/', '.github/', '.githooks/', 'scripts/')) or '.test.' in path: return 'engineering'
    if path.startswith(('docs/', 'assets/')): return 'docs'
    if path.startswith(('desktop/', 'core/launcher/', 'core/runtime_manager/', 'core/restarter_manager/')): return 'desktop'
    if path.startswith('web/'): return 'frontend'
    if path.startswith(('core/agent_plugins/', 'core/pet_system/')): return 'companions'
    if path.startswith(('tools/', 'core/authorization/', 'core/external_agent/', 'core/agent_protocol/')): return 'tools'
    if path.startswith(('core/evaluation/', 'core/gym/')): return 'evolution'
    if path.startswith(('core/research/', 'core/chatroom/')): return 'research'
    if path.startswith(('core/chat/', 'core/agent_kernel/')): return 'session'
    if path.startswith(('core/orchestration/', 'core/llm/', 'core/context/', 'core/prompt_manager/', 'core/core_prompt/', 'mental_model/', 'prompts/')) or path == 'agent.py': return 'intelligence'
    if path.startswith('core/web/services/') or path.startswith('core/web/routes/'):
        name = path.split('/')[3]
        for prefixes, domain in [
            (('virtual_human','financial','agent_plugin','pet'), 'companions'),
            (('team_knowledge','knowledge','rag_','memory','unified_knowledge','github_project','user_content'), 'knowledge'),
            (('team','research','challenge','chat_room','source_collection','hypothesis','experiment','data_processing'), 'research'),
            (('evolution','self_evolution','supervised','chat_review'), 'evolution'),
            (('session','conversation','agent_','project_agent_bus'), 'session'),
            (('external_agent','cli_agent','tool','skill','computer_use'), 'tools'),
            (('launcher','runtime_manager','reset'), 'desktop'),
            (('config','provider','model','theme','log','diagnostic','runtime_scene','git','workspace','file','usage'), 'platform')]:
            if name.startswith(prefixes): return domain
        return 'gateway'
    if path.startswith('core/web/'): return 'gateway'
    if path.startswith(('config/', 'core/infrastructure/', 'core/workspace/', 'core/logging/', 'core/diagnostics/', 'core/ui/', 'core/code_context_graph/')) or path == 'vibelution_storage.py': return 'platform'
    if path.endswith(('.md', '.txt', '.json', '.yaml', '.yml', '.toml')): return 'docs'
    return 'engineering'


LABELS = {
 'core/web/services/session': ('Session 生命周期','接收、调度、worker、持久化、投影与 SSE 发布；展开查看子模块。'),
 'core/chat': ('会话账本与目录','Turn Journal 与会话数据结构；目录投影不替代 transcript。'),
 'core/chat/conversation_store': ('ConversationStore','SQLite 会话目录与控制信息。'),
 'core/web/services/agent_directory': ('Agent 档案与记忆','Agent 配置、身份、生命周期、模型选择与个人记忆。'),
 'core/web/services/team_workflow': ('团队工作流','来源搜集、研究运行、实验、产物及阶段编排。'),
 'core/web/services/team_workflow/research_runtime': ('研究运行控制','研究任务、讨论、回执、预算、恢复与执行边界。'),
 'core/web/services/team_workflow/operator_optimization': ('算子优化','算子候选、计划、基线、讨论和决策权威。'),
 'core/research': ('科研核心','研究定义、状态、证据与工作流执行。'),
 'core/web/services/team_knowledge': ('团队知识治理','知识内容、来源、ACL、生命周期与可检索状态。'),
 'core/llm': ('模型协议与客户端','模型解析、协议能力、请求构建、流式调用与用量。'),
 'core/orchestration': ('Agent 单轮编排','上下文组装、工具生命周期、轮次执行与停止条件。'),
 'core/prompt_manager': ('提示词管理','核心身份、角色模板与会话快照装配；不嵌入提示词正文。'),
 'core/authorization': ('授权策略','工具与调用主体的权限边界。'),
 'tools': ('Agent 工具入口','工具目录、封装与注册；具体能力需结合授权策略。'),
 'core/gym': ('Gym 评测','评测用例、任务环境、反馈和候选验证。'),
 'core/evaluation': ('评估核心','评估逻辑与指标处理。'),
 'desktop/electron/src': ('Electron 主进程与桥接','窗口、IPC、桌面事件及 Launcher 控制入口。'),
 'desktop/electron/src/lifecycle': ('实例生命周期','实例状态、准入、恢复与关闭事务。'),
 'desktop/electron/src/process': ('后台进程管理','工作台进程启动、健康确认与所属进程回收。'),
 'web/src/app': ('工作台页面壳','路由、窗口入口、导航、初始化与遥测。'),
 'web/src/components/vui': ('VUI 产品 API','产品统一组件与布局 API；renderer 负责具体交互。'),
 'web/src/components/vui/renderers/shadcn': ('shadcn / Radix renderer','VUI 交互实现层；业务路由经 VUI 产品 API 使用。'),
 'web/src/routes/chat': ('会话工作台','composer、提交、订阅、会话视图与状态。'),
 'web/src/routes/teams': ('团队工作台','团队、研究画布、实验及知识呈现。'),
 'config': ('配置代码库','配置 schema、Provider、模型、事务与实际配置路径解析。'),
 'core/infrastructure': ('共享基础设施','安全、文件系统、工具执行、事件及工作区能力。'),
 'core/agent_plugins/virtual_human_life': ('虚拟人生活插件','人物状态、mailbox 与主动消息；按 Agent 插件绑定隔离。'),
 'core/runtime_manager': ('Runtime Manager','工作运行、后台协调与兼容控制路径。'),
}


def describe_module(path, domain):
    if path in LABELS: return LABELS[path]
    name = path.rsplit('/', 1)[-1]
    return (name, f'{next(d["label"] for d in DOMAINS if d["id"] == domain)}中的源码/资源单元。查看文件符号和关联流程了解实际职责。')


def make_views(ref):
    views = []
    def view(vid, title, desc, nodes, edges):
        # Reading layouts are applied below after the reviewed graph is built.
        ns = []
        for i, (nid, label, detail, path, anchor) in enumerate(nodes):
            ns.append({'id': nid, 'label': label, 'detail': detail,
                       'refs': [ref(path, anchor)], 'x': (i % 3) * 350 + 40, 'y': (i // 3) * 205 + 60})
        es = []
        for i, (a,b,label,detail,path,anchor) in enumerate(edges):
            es.append({'id': f'{vid}-edge-{i}', 'from':a,'to':b,'label':label,'detail':detail,'refs':[ref(path,anchor)]})
        views.append({'id':vid,'label':title,'description':desc,'nodes':ns,'edges':es})

    view('overview','系统如何运转','从工作台发出消息，经 Session 调度 Agent 执行；模型、工具、实时输出与会话记录各有职责。',[
        ('desktop','Electron / Launcher','桌面主进程拥有窗口、IPC 与生命周期控制。','desktop/electron/src/main.ts','ipcMain.handle(IPC_CHANNELS.launcherInvoke'),
        ('web','React 工作台','路由加载业务页面，经领域 API 发起请求。','web/src/app/router.tsx','createBrowserRouter(['),
        ('api','FastAPI 服务入口','控制来源校验、健康端点、路由注册和静态前端。','core/web/app.py','def create_app('),
        ('session','Session 调度','会话接收与登记后，把回合交给 scheduler 和 worker。','core/web/services/session/schedule.py','def _schedule_session_turn('),
        ('agent','Agent 回合执行','worker 驱动 Agent 单轮 runner；单轮可发生多次模型和工具交互。','core/web/services/session/worker.py','def _run_session_turn_impl('),
        ('llm','模型调用','统一 invocation 解析模型与协议并处理返回。','core/llm/invocation.py','def invoke_llm('),
        ('tools','受控工具执行','工具可见性和真正执行的授权分别检查。','core/infrastructure/tool_executor.py','class ToolExecutor:'),
        ('journal','会话事件记录','用户消息、assistant 结果、工具与生命周期事件写入 Journal。','core/chat/turn_journal.py','def append_turn_event('),
        ('stream','实时输出','worker 捕获 UI 事件，Session publisher 将增量交给 SSE 订阅者。','core/web/services/session/stream_capture.py','def _capture_session_ui_stream('),
    ],[
        ('desktop','api','启动后台','Electron 创建所属工作台后台进程；健康和页面可用是不同阶段。','desktop/electron/src/process/workbenchBackend.ts','export function spawnWorkbenchBackend('),
        ('web','api','JSON / HTTP','工作台领域 API 通过公共 fetchJson 传输；Launcher 控制另走 IPC。','web/src/api/client.ts','export async function fetchJson<'),
        ('api','session','提交消息','Session route 将消息委托接收服务，随后进入调度。','core/web/routes/sessions.py','def session_submit_message('),
        ('session','agent','调度回合','scheduler 获得执行槽后回调 worker 执行本轮。','core/web/services/session/schedule.py','def _submit_scheduled_session_turn('),
        ('agent','llm','请求模型','Agent 的模型调用集中委托 LLM 回合适配与 invocation。','agent.py','def _invoke_llm('),
        ('agent','tools','执行调用','ToolLifecycleBridge 将模型提出的工具调用交给执行回调；授权通过后才执行。','core/orchestration/tool_lifecycle.py','def execute_tool('),
        ('session','journal','登记 / 结算','接收阶段登记用户消息；worker 完成或失败后走持久化，写最终结果与终态。','core/web/services/session/persist.py','def _persist_session_turn_result('),
        ('agent','stream','捕获增量','Session worker 的 UI 捕获层收集 assistant 和工具事件，再经 publish 发送。','core/web/services/session/stream_capture.py','def _capture_session_ui_stream('),
        ('stream','web','SSE 回显','前端 Session 事件通道订阅事件并更新会话呈现。','web/src/routes/chat/sessionEventStream.ts','export function createSessionEventStream('),
    ])
    view('startup','启动与桌面控制','Launcher IPC → Electron 控制队列 → 工作台进程 → 分阶段就绪。具体端口由运行实例解析，不把默认端口当现场事实。',[
        ('ui','Launcher UI','Launcher API 首先识别 IPC 桥。','web/src/api/launcher.ts','export function hasLauncherIpcBridge('),
        ('ipc','preload IPC','renderer 通过 launcherInvoke 调用主进程。','desktop/electron/src/preload.ts','ipcRenderer.invoke(IPC_CHANNELS.launcherInvoke'),
        ('main','Electron main','主进程接收 Launcher 操作并进入生命周期实现。','desktop/electron/src/main.ts','ipcMain.handle(IPC_CHANNELS.launcherInvoke'),
        ('queue','生命周期命令队列','主线命令排队、合并与关闭退避。','desktop/electron/src/lifecycle/mainLine/commandQueue.ts','export function createMainLineCommandQueue('),
        ('process','工作台 Python 进程','按 workspaceRoot 启动；Windows 后台进程隐藏控制台。','desktop/electron/src/process/workbenchBackend.ts','export function spawnWorkbenchBackend('),
        ('health','FastAPI 健康入口','第一阶段建立中间件与 health；不等于所有业务路由已就绪。','core/web/app.py','def create_app('),
        ('routes','API / SPA 就绪','第二阶段挂载 API 与固定前端发布目录，失败不偷换前端。','core/web/route_bootstrap.py','def _mark_routes_ready('),
    ],[
        ('ui','ipc','桥接','Launcher 控制走受限 IPC。','web/src/api/launcher.ts','export function hasLauncherIpcBridge('),
        ('ipc','main','launcher:invoke','IPC 通道由 preload 暴露给 renderer。','desktop/electron/src/preload.ts','ipcRenderer.invoke(IPC_CHANNELS.launcherInvoke'),
        ('main','queue','排队执行','主进程调用 runWorkbenchLifecycle，内部使用 mainLine 命令队列。','desktop/electron/src/process/workbenchLifecycle.ts','return queue.submit({'),
        ('queue','process','生命周期启动','生命周期执行最终创建所属后台进程；队列控制串行操作。','desktop/electron/src/process/workbenchBackend.ts','const spawned = spawnWorkbenchBackend('),
        ('process','health','启动入口','工作台脚本启动 FastAPI 应用。','desktop/electron/src/process/workbenchBackend.ts','WEB_WORKBENCH_SCRIPT ='),
        ('health','routes','后台挂载','两阶段 bootstrap：早期 health 与完整业务 readiness 分离。','core/web/app.py','from .route_bootstrap import ensure_web_routes_registered'),
    ])
    view('http','页面到后端','通用 HTTP 请求路径与控制边界；具体业务执行请切换领域流程。',[
        ('router','页面路由','React Router 把 URL 映射到业务工作台；页面采用 lazy 加载。','web/src/app/router.tsx','createBrowserRouter(['),
        ('transport','领域 API / fetchJson','业务命名 API 经公共 HTTP 传输；DTO 与 query keys 分开维护。','web/src/api/client.ts','export async function fetchJson<'),
        ('guard','控制请求校验','服务端校验来源、控制令牌等；图不暴露实际令牌。','core/web/control.py','class WebControlGuardMiddleware('),
        ('bootstrap','路由注册','模块按稳定次序单线程导入，避免循环 import 的锁问题。','core/web/router_registry.py','def import_web_route_modules('),
        ('routes','/api 业务入口','注册表挂载领域路由；装饰器的局部 URL 需要加前缀。','core/web/router_registry.py','def register_web_routers_from_modules('),
        ('lifecycle','后台生命周期','启动恢复、后台工作与退出由 lifespan 管理。','core/web/app.py','lifespan=web_workbench_lifespan'),
    ],[
        ('router','transport','页面发起请求','以 Chat composer 提交为例：页面动作进入 submitSessionMessage，再经 fetchJson；Launcher 控制另走 IPC。','web/src/api/chat.ts','export function submitSessionMessage('),
        ('transport','guard','HTTP 请求','请求进入中间件链，拒绝不可信控制来源。','core/web/app.py','app.add_middleware(WebControlGuardMiddleware)'),
        ('guard','routes','受控分发','通过控制校验后按注册的路由处理。','core/web/control.py','class WebControlGuardMiddleware('),
        ('bootstrap','routes','include_router','所有注册业务模块统一添加 /api。','core/web/router_registry.py','app.include_router(module.router, prefix="/api")'),
        ('lifecycle','bootstrap','分阶段启动','lifespan 和 route bootstrap 分工管理就绪。','core/web/app.py','from .route_bootstrap import ensure_web_routes_registered'),
    ])
    # Additional reviewed domain flows are appended below by the source audit.
    from flows import add_domain_views
    add_domain_views(view)
    from reading_layout import apply_reading
    apply_reading(views)
    order = ['overview','startup','http','session','stream','llm','tools','teams','research','knowledge','knowledge-write','self-evolution','supervised','gym','companion','finance','storage']
    views.sort(key=lambda item: order.index(item['id']))
    return views
