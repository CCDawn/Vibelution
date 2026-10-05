"""Human reading order, explicit semantic groups and progressive diagram detail.

The full reviewed graph is retained. A primary diagram only composes existing
paths through hidden implementation nodes; it never creates an inferred call.
"""

from copy import deepcopy


def node(label, subtitle, summary, role, owner, inputs, outputs, mechanism, boundaries, related):
    return dict(label=label, subtitle=subtitle, summary=summary, role=role,
                ownerPath=owner, inputs=inputs, outputs=outputs, mechanism=mechanism,
                boundaries=boundaries, relatedViews=related)


OVERVIEW = {
    'question': '操作界面、会话执行、模型、工具和数据记录怎样配合？',
    'entry': '从工作台提交一条消息，沿实线阅读请求与执行；下方是记录和回显。',
    'outcome': '得到 Agent 的执行结果；实时输出进入工作台，完整会话事件进入 Journal。',
    'category': 'foundation',
    'readingOrder': ['web', 'api', 'session', 'agent', 'llm', 'tools', 'journal', 'stream', 'desktop'],
    'relatedViews': ['session', 'startup', 'storage'],
    'nodes': {
        'desktop': node('启动与桌面控制', 'Electron main · Launcher',
            '管理窗口、所属后台进程与生命周期命令。', 'control', 'desktop/electron/src/lifecycle',
            ['启动、停止、重启等 Launcher 操作'], ['所属 Python 后台进程与就绪状态'],
            ['renderer 经 preload 的受限 IPC 调用主进程。', '主进程通过生命周期命令队列管理后台启动与健康阶段。'],
            ['桌面生命周期控制与普通业务 HTTP 请求是不同入口。'], ['startup']),
        'web': node('操作与结果呈现', 'React · VUI · Session stream',
            '提交操作，并把会话结果呈现在工作台。', 'entry', 'web/src/routes/chat',
            ['用户消息与页面操作', 'HTTP 返回与 Session 事件'], ['业务 API 请求与界面状态'],
            ['页面通过领域 API 和公共 fetchJson 发出请求。', '会话界面通过事件流接收增量，历史由持久记录恢复。'],
            ['页面投影不拥有会话执行和 transcript 的写入权威。'], ['http', 'session', 'stream']),
        'api': node('接收业务请求', 'FastAPI · /api routes',
            '校验请求，再委托对应领域服务。', 'entry', 'core/web/routes/sessions.py',
            ['经过公共传输层的 HTTP 请求'], ['领域服务调用与 HTTP 响应'],
            ['FastAPI 中间件处理来源与控制请求校验。', '会话消息入口委托 Session submit；其他领域有各自路由与服务。'],
            ['路由注册只是入口组织，不代表后台执行已完成。'], ['http', 'session']),
        'session': node('登记与调度消息', 'Session submit · Scheduler',
            '登记回合，并按会话顺序安排执行。', 'control', 'core/web/services/session',
            ['session_id、消息与回合上下文'], ['Journal 初始事件', '获准进入 worker 的回合'],
            ['接收服务校验消息，登记用户消息和初始回合事件。', '调度适配提交执行与释放回调；scheduler 控制会话串行和 Agent 并发槽。'],
            ['消息被接收与回合执行结束是不同阶段。'], ['session', 'storage']),
        'agent': node('执行 Agent 回合', 'Session worker · AgentRuntime',
            '准备上下文，驱动模型与工具多轮交互。', 'process', 'core/orchestration',
            ['Agent 快照与已登记的回合上下文'], ['assistant 结果、工具事件与回合状态'],
            ['worker 组装当前回合的身份、记忆、提示词和消息上下文。', '单轮 runner 复用现有 AgentRuntime，允许多次模型请求与工具交互。', 'worker 捕获 UI 输出，并统一结算完成或失败。'],
            ['Agent 单轮内部的模型循环与 Session 回合调度是不同层次。'], ['session', 'llm', 'tools']),
        'llm': node('调用模型', 'LLM adapter · Invocation',
            '解析模型与协议，发送请求并接收输出。', 'external', 'core/llm',
            ['本轮 messages、模型选择和获准工具 schema'], ['模型文本、tool_calls、流式片段与用量'],
            ['Agent 的 _invoke_llm 经回合适配层进入统一 invocation。', '模型 profile/provider 与协议能力决定实际 wire 请求和流式处理。'],
            ['源码存在模型接口不代表某个 Provider 当前可用。'], ['llm', 'tools']),
        'tools': node('执行受控工具', 'ToolLifecycleBridge · ToolExecutor',
            '校验模型提出的调用，并在授权后执行。', 'process', 'core/infrastructure/tool_executor.py',
            ['模型提出的 tool_calls 与本轮授权上下文'], ['工具结果、调用事件或拒绝结果'],
            ['请求前先物化模型可见的工具；模型返回后再次检查可见性。', '工具生命周期桥经执行回调进入 ToolExecutor，并做最终执行授权。'],
            ['模型提出调用不构成执行授权；要求审批时先等待决定。'], ['tools']),
        'journal': node('保存会话事件', 'Turn Journal · JSONL',
            '保存消息、工具事件与回合终态。', 'store', 'core/chat',
            ['用户消息、assistant 结果、工具与生命周期事件'], ['可恢复的会话事件序列'],
            ['接收阶段追加初始事件，持久化阶段追加最终结果和终态。', '会话目录用于列表和控制查询；完整 transcript 仍由 Journal 负责。'],
            ['Journal、会话目录、科研账本和个人记忆有各自职责。'], ['storage', 'stream']),
        'stream': node('推送实时输出', 'Capture · Publisher · SSE',
            '把执行中的增量输出推送到界面。', 'process', 'core/web/services/session',
            ['worker 捕获的 assistant 与工具 UI 事件'], ['订阅队列和 HTTP SSE 事件'],
            ['捕获层对直播输出进行批处理，并经 Session publisher 发布。', '前端订阅 Session SSE，断线和刷新仍需与持久历史对齐。'],
            ['直播 delta 不能独立代替完整会话历史。'], ['stream', 'storage']),
    },
}

# Columns are semantic responsibility groups, not array-index positions.
GROUPS = {
    'startup': [('界面控制入口', ['ui', 'ipc']), ('桌面主进程', ['main', 'queue']), ('后台启动与就绪', ['process', 'health', 'routes'])],
    'http': [('页面与传输', ['router', 'transport']), ('请求处理', ['guard', 'routes']), ('启动时准备', ['lifecycle', 'bootstrap'])],
    'session': [('接收与登记', ['http', 'submit']), ('排队与并发', ['schedule', 'scheduler']), ('回合执行', ['worker', 'context', 'turn']), ('结果与事件记录', ['persist', 'journal'])],
    'stream': [('执行中的输出', ['capture', 'publish']), ('订阅与传输', ['subscribe', 'sse']), ('完整结果记录', ['persist', 'journal'])],
    'llm': [('上下文与回合', ['context', 'turn']), ('Agent 调用', ['agent', 'adapter']), ('请求组成与发送', ['tools', 'invoke'])],
    'tools': [('请求前：选择工具', ['defs', 'policy', 'materialize']), ('返回后：检查调用', ['visible', 'lifecycle', 'executor']), ('执行前：授权与审批', ['auth', 'approval', 'decision'])],
    'teams': [('界面与消息入口', ['panel', 'api', 'route']), ('团队与投递', ['team', 'bus', 'kernel']), ('独立团队数据', ['store'])],
    'research': [('创建与固定定义', ['create', 'definition']), ('命令与事务', ['command', 'ledger']), ('持久化调度', ['graph', 'adapter', 'checkpoint']), ('实际执行与回放', ['ports', 'replay'])],
    'knowledge': [('查询入口', ['tool', 'unified', 'rag']), ('正式知识检索', ['canonical', 'acl']), ('排序与派生索引', ['rank', 'index'])],
    'knowledge-write': [('正式知识的审核', ['proposal', 'review', 'ingest']), ('正式条目与派生索引', ['items', 'sync', 'index']), ('独立的个人记忆', ['episodic', 'filememory'])],
    'self-evolution': [('启动与计划', ['start', 'observe', 'plan']), ('候选与审核', ['evolve', 'review', 'approve']), ('集成与独立运行记录', ['integrate', 'workrun'])],
    'supervised': [('基线与候选', ['start', 'baseline', 'candidate']), ('复测与同标准判断', ['rerun', 'judge']), ('审批与集成', ['decision', 'merge'])],
    'gym': [('评测与晋升门', ['eval', 'gate']), ('Gym 验证', ['episode']), ('独立的应用入口', ['promotion'])],
    'companion': [('人物专属入口', ['route', 'facade', 'plugin']), ('人物命令队列', ['mailbox', 'dispatch']), ('原生会话接入', ['submitter', 'native'])],
    'finance': [('页面与助手初始化', ['ui', 'route', 'setup']),
                ('Agent 资源与原生会话', ['agent', 'kb', 'session', 'workspace']),
                ('页面行情查询', ['marketClient', 'marketRoute', 'marketService', 'provider']),
                ('Agent 行情工具执行', ['toolLifecycle', 'toolDefinition', 'marketAdapter']),
                ('助手能力状态', ['projection'])],
    'storage': [('统一路径解析', ['paths', 'workspace', 'config']), ('会话事件与目录', ['journal', 'bridge', 'directory']), ('独立科研账本', ['ledger'])],
}

FOCUS = {
    'startup': ['ui', 'main', 'process', 'routes'],
    'http': ['router', 'transport', 'guard', 'routes'],
    'session': ['submit', 'scheduler', 'worker', 'persist', 'journal'],
    'stream': ['capture', 'publish', 'subscribe', 'sse'],
    'llm': ['context', 'turn', 'agent', 'invoke'],
    'teams': ['panel', 'team', 'bus', 'kernel'],
    'research': ['command', 'ledger', 'graph', 'adapter', 'ports'],
    'knowledge': ['tool', 'unified', 'canonical', 'rank', 'index'],
    'self-evolution': ['start', 'observe', 'evolve', 'review', 'approve', 'integrate'],
    'supervised': ['baseline', 'candidate', 'rerun', 'decision', 'merge'],
    'companion': ['route', 'mailbox', 'dispatch', 'submitter', 'native'],
    'finance': ['ui', 'setup', 'session', 'workspace', 'marketService', 'provider'],
}

FOCUS_LABELS = {
    ('startup', 'ui', 'main'): '受限 IPC',
    ('startup', 'main', 'process'): '生命周期队列',
    ('startup', 'process', 'routes'): '分阶段就绪',
    ('session', 'submit', 'scheduler'): '提交调度',
    ('llm', 'agent', 'invoke'): '适配模型请求',
    ('teams', 'panel', 'team'): '消息 API',
    ('knowledge', 'unified', 'canonical'): 'RAG 模式',
    ('self-evolution', 'observe', 'evolve'): '计划后构建候选',
    ('supervised', 'rerun', 'decision'): 'Judge 复评',
    ('companion', 'route', 'mailbox'): '人物插件接收',
    ('finance', 'ui', 'setup'): '初始化助手',
    ('finance', 'workspace', 'marketService'): '页面行情查询',
}

LABELS = {
    'overview': '运行主线：消息与回合', 'startup': '启动与桌面控制', 'http': '页面请求如何到达服务',
    'session': '一条消息的执行过程', 'stream': '实时输出与历史记录', 'llm': 'Agent 如何调用模型',
    'tools': '工具如何获得执行权限', 'teams': '团队如何投递消息', 'research': '科研工作流如何运行',
    'knowledge': '怎样检索知识与记忆', 'knowledge-write': '知识与记忆怎样写入',
    'self-evolution': '自主进化的审核与集成', 'supervised': '监督进化的评测与批准',
    'gym': 'Gym 的评测与晋升', 'companion': '人物消息如何进入 Session',
    'finance': '金融研究与公开行情', 'storage': '数据在哪里，谁是权威',
}


def composed_edges(view, focus):
    """Compose only existing directed paths, preserving their source evidence."""
    visible = set(focus)
    adjacency = {}
    for edge in view['edges']:
        adjacency.setdefault(edge['from'], []).append(edge)
    edges = []
    for source in focus:
        def walk(at, path, seen):
            for edge in adjacency.get(at, []):
                dest = edge['to']
                if dest in seen:
                    continue
                chain = path + [edge]
                if dest in visible:
                    if len(chain) == 1:
                        edges.append(deepcopy(edge))
                    else:
                        refs = [r for part in chain for r in part['refs']]
                        edges.append(dict(id=f"{view['id']}-focus-{source}-{dest}-{len(edges)}",
                            **{'from': source, 'to': dest},
                            label=FOCUS_LABELS.get((view['id'], source, dest), '经实现步骤'),
                            detail='；'.join(part['detail'] for part in chain), refs=refs,
                            via=[part['to'] for part in chain[:-1]],
                            pathEdges=[part['id'] for part in chain],
                            relationKind='composed_path'))
                else:
                    walk(dest, chain, seen | {dest})
        walk(source, [], {source})
    return edges


def apply_reading(views):
    from runtime_details import DETAILS as runtime
    from domain_details import DETAILS as domain
    details = {'overview': OVERVIEW, **runtime, **domain}
    for view in views:
        vid = view['id']
        info = details[vid]
        ids = {n['id'] for n in view['nodes']}
        assert set(info['nodes']) == ids, (vid, 'narrative coverage')
        assert set(info['readingOrder']) == ids, (vid, 'reading order')
        view.update({k: deepcopy(v) for k, v in info.items() if k != 'nodes'})
        view['label'] = LABELS[vid]
        view['description'] = info['question']
        for current in view['nodes']:
            current['sourceLabel'] = current['label']
            current.update(deepcopy(info['nodes'][current['id']]))
            current['description'] = current['summary']
            current['step'] = info['readingOrder'].index(current['id']) + 1
        if vid == 'overview':
            positions = {'desktop': (32, 84), 'web': (32, 304), 'api': (344, 304),
                         'session': (656, 304), 'agent': (968, 304),
                         'llm': (1280, 112), 'tools': (1280, 456),
                         'journal': (656, 604), 'stream': (344, 604)}
            for current in view['nodes']:
                current['x'], current['y'] = positions[current['id']]
                current['step'] = None
            view['zones'] = [
                dict(label='桌面入口与界面', x=8, y=40, w=292, h=416),
                dict(label='请求与回合执行', x=320, y=248, w=916, h=208),
                dict(label='模型与受控工具', x=1256, y=40, w=292, h=572),
                dict(label='记录与回显', x=320, y=548, w=604, h=208),
            ]
        else:
            groups = GROUPS[vid]
            grouped = [nid for _, members in groups for nid in members]
            assert len(grouped) == len(ids) and set(grouped) == ids, (vid, 'responsibility groups')
            view['zones'] = []
            by_id = {n['id']: n for n in view['nodes']}
            for col, (label, members) in enumerate(groups):
                for row, nid in enumerate(members):
                    by_id[nid].update(x=32 + col * 336, y=112 + row * 216)
                view['zones'].append(dict(label=label, x=8 + col * 336, y=48,
                    w=292, h=8 + len(members) * 216))
        focus = FOCUS.get(vid)
        if focus:
            view['focusNodes'] = focus
            view['focusEdges'] = composed_edges(view, focus)
            # Longer stories turn at the right edge instead of shrinking six
            # cards onto one row. Sequence numbers and arrows retain the order.
            columns = 3 if len(focus) > 4 else len(focus)
            view['focusPositions'] = {}
            for index, nid in enumerate(focus):
                row, column = divmod(index, columns)
                if row % 2:
                    column = columns - 1 - column
                view['focusPositions'][nid] = dict(x=32 + column * 336, y=112 + row * 288)
            view['focusZones'] = []
            if vid == 'finance':
                # Setup assigns an Agent tool policy; it does not synchronously
                # read market data. Keep that later execution branch in the
                # full implementation instead of composing it into setup.
                view['focusEdges'] = [
                    edge for edge in view['focusEdges']
                    if (edge['from'], edge['to']) != ('setup', 'marketService')
                ]
                # Parallel branches read left-to-right. A snake layout made
                # shared routed segments look like market -> Session calls.
                view['focusPositions'] = {
                    nid: dict(x=32 + (index % 3) * 336, y=112 + (index // 3) * 288)
                    for index, nid in enumerate(focus)
                }
                view['focusZones'] = [
                    dict(label='助手初始化与原生会话', x=8, y=48, w=964, h=208),
                    dict(label='研究工作台与公开行情', x=8, y=336, w=964, h=208),
                ]
            hidden = ids - set(focus)
            view['hiddenImplementation'] = [n for n in info['readingOrder'] if n in hidden]
        else:
            view['focusNodes'] = []
            view['focusEdges'] = []
            view['hiddenImplementation'] = []
