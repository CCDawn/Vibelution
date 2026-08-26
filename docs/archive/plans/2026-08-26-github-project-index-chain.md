# GitHub 成熟项目索引链路实施计划

## 目标与范围

让开发 Agent 在动手前能够稳定发现成熟项目，并把借鉴结论绑定到固定外部源码证据：搜索必须无写副作用，支持中英文能力词和多词查询，返回真实相关性分数；Agent 获得紧凑的调用提示；复用研究证据能够验证固定 commit 下的具体文件/blob。

不引入 GraphRAG、Qdrant、向量数据库、外部 reranker 或新的运行时依赖；不把 clone 正文、README 摘要或不可信外部指令返回给模型；不扩大现有 Agent 工具权限和 Knowledge ACL。

## 复用决策

- 本地：改造 `github_project_library_service` 与 `unified_knowledge_search_service`，保留 registry、generated INDEX、本地 clone locator 和统一搜索合并链路。
- Mem0：只借“metadata filter + 关键词/语义候选 + 可解释分数 + 可选 rerank”的接口分层；当前先实现无依赖 lexical/BM25 风格排序，不接向量库。
- Dify：只借 `capability + keywords` 查询与加权排序思路；许可证为带附加条件的自定义许可，不复制代码。
- Codex：借紧凑能力提示、字节预算和来源 provenance；只强化既有工具说明与 preferred 顺序，不注入项目正文。
- Promptfoo：借固定查询集、阈值和失败退出契约；以参数化 pytest 固定中英文召回、排序和无副作用行为。
- GraphRAG/Qdrant：当前库规模和问题类型不需要图索引或外部向量服务，明确延后。

## 推荐路径

1. 把 `list_github_projects()` 变成纯读取：缺库时返回空投影，查询不得创建目录、重写 registry 或刷新 INDEX 时间戳；初始化只留在 clone/fetch 等显式写路径。
2. 在项目卡片上实现无依赖混合 lexical 排序：registry 元数据为高权重，固定大小读取本地 clone 根 README 仅用于词频，不返回正文；做英文归一化、常见中英文能力别名、覆盖率与 BM25 风格分数，输出 `searchScore`、`matchedTerms`、`matchReason`。
3. 让统一搜索使用该分数，不再给每张 GitHub 卡片固定 `1.0`；特殊 GitHub 工具返回同一排序信息，并明确提示“先按 2–4 个能力关键词搜索，再读取固定 SHA 的本地 clone”。
4. 调整默认会话 Agent 的 preferred 顺序，使现有专用搜索入口靠近本地代码检索入口；不新增任何 allowed tool。固定研究角色继续通过既有 `unified_memory_search_tool` 感知项目卡片。
5. 将复用研究证据升级为源码引用合同：`--source-ref projectId:path#symbol` 在记录时验证 candidate、固定 commit 和 repo 内相对路径，解析该 commit 下的 Git blob SHA；manifest 复核时再次验证 commit/path/blob，阻止“只有自述、没有外部源码位置”的证据通过。

## 保护边界

- README 只在本地进程内做有界 token 化，不作为 Prompt、摘要、excerpt 或知识正文；路径必须位于已登记 clone 内。
- 查询只读；缓存仅在进程内，以文件 stat 为失效依据，不写磁盘。
- registry 旧 schema 和缺少扩展字段的现有项目继续可读。
- 复用证据保留已有候选 SHA、许可证和 clean-clone 校验；新增 source ref 不能绕过许可证限制。
- 本任务只修改索引、工具提示、默认 preferred 顺序、证据合同及相关测试，不修改 UI、Launcher、真实 operator config 或活跃 project memory。

## 验证与成功证据

- RED：新增测试先证明多词/中文查询零命中、卡片固定 `1.0`、搜索会改 registry/INDEX、source ref 缺失或漂移未被拒绝。
- GREEN：固定查询集覆盖 `agent memory`、`workflow orchestration`、`document parsing`、`知识库检索` 等能力词；关键候选进入 Top 5，分数有区分且带解释字段。
- 无副作用：查询前后 registry/INDEX 内容与 `mtime_ns` 不变；缺失库查询不创建目录。
- 统一链路：专用工具与 `unified_memory_search_tool` 都返回按相关性排序的项目卡片。
- 证据：合法 source ref 记录 commit/path/blob/symbol；路径越界、文件不存在、candidate 不匹配或 blob 漂移均失败。
- 跑影响面 selector、聚焦 pytest、工具 `prompt_debugger`、diff check 和 claim-bound closeout；合入前记录本任务 Mem0/Codex/Promptfoo/GraphRAG 固定源码引用。

## 模式

`COMPACT_PLAN`，单 owner 串行实施。检索行为和证据合同使用紧凑 BDD/TDD；工具文案、preferred 顺序和兼容性适配使用轻量实现。
