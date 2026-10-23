# 受版本控制目录的职责地图

[返回教程目录](README.md)

此表按教程源码快照列出 Git 跟踪文件的父目录，不包括依赖安装目录、用户工作区和运行缓存。摘要按模块职责或路径组织生成；未独立确认的子目录明确标为导航线索，不代表已逐文件审计。

| 目录 | 职责/阅读线索 |
| --- | --- |
| [.cursor/](../../../.cursor/) | Cursor 开发辅助配置；不是产品后端 |
| [.cursor/skills/](../../../.cursor/skills/) | 编辑器/开发 Agent 的技能目录 |
| [.cursor/skills/vibelution-continuous-optimization-loop/](../../../.cursor/skills/vibelution-continuous-optimization-loop/) | Vibelution 持续优化开发流程技能材料 |
| [.githooks/](../../../.githooks/) | Git 操作钩子和本地协作/集成约束 |
| [.github/](../../../.github/) | GitHub 仓库协作、工作流与 Issue 配置 |
| [.github/ISSUE_TEMPLATE/](../../../.github/ISSUE_TEMPLATE/) | 提交缺陷和需求时使用的表单模板 |
| [.github/workflows/](../../../.github/workflows/) | GitHub Actions 自动检查/构建/发布流程 |
| [.vibelution/](../../../.vibelution/) | 项目专用受版本控制元配置；不等于用户正式业务数据 |
| [assets/](../../../assets/) | 项目静态资源集合；子目录按实际资源分工 |
| [assets/agent-avatars/](../../../assets/agent-avatars/) | 项目静态素材子集：agent-avatars，不是后端服务 |
| [assets/icons/](../../../assets/icons/) | 项目静态素材子集：icons，不是后端服务 |
| [assets/team-bundles/](../../../assets/team-bundles/) | 项目静态素材子集：team-bundles，不是后端服务 |
| [assets/theme_backgrounds/](../../../assets/theme_backgrounds/) | 项目静态素材子集：theme_backgrounds，不是后端服务 |
| [config/](../../../config/) | Python 配置结构、加载、公共接口、Provider 与安全策略代码 |
| [core/](../../../core/) | Python 运行时、领域、Web 和基础设施核心 |
| [core/agent_kernel/](../../../core/agent_kernel/) | 应用级 Agent 事件→任务→执行→结果、消息投递与 JSONL 领域记录 |
| [core/agent_plugins/](../../../core/agent_plugins/) | 按 Agent 显式绑定的第一方业务插件 |
| [core/agent_plugins/personal_affairs/](../../../core/agent_plugins/personal_affairs/) | 待办、日程、目标等个人事务领域 |
| [core/agent_plugins/virtual_human_life/](../../../core/agent_plugins/virtual_human_life/) | 虚拟人生活、关系、日程、主动消息、证据和记忆领域 |
| [core/agent_plugins/virtual_human_life/prompts/](../../../core/agent_plugins/virtual_human_life/prompts/) | 虚拟人受限 Prompt Pack 模板；不是模型权重 |
| [core/agent_protocol/](../../../core/agent_protocol/) | Agent 协议/方向/操作/适配器绑定与路由解析、准入契约 |
| [core/authorization/](../../../core/authorization/) | 工具策略模型、可见性/执行授权与协作模式边界 |
| [core/chat/](../../../core/chat/) | 对话 Journal、ledger、分支、压缩、历史投影和上下文基础 |
| [core/chat/conversation_store/](../../../core/chat/conversation_store/) | Agent/Session SQLite 目录控制面、schema、读写协调与迁移 |
| [core/chatroom/](../../../core/chatroom/) | 群聊调度、上下文、检查点、存储与时间线 |
| [core/code_context_graph/](../../../core/code_context_graph/) | 代码结构/上下文图相关服务；不是正式知识向量库 |
| [core/context/](../../../core/context/) | 通用上下文章节、易变性、Skill 上下文契约 |
| [core/core_prompt/](../../../core/core_prompt/) | 受保护核心提示词和角色模板 |
| [core/core_prompt/roles/](../../../core/core_prompt/roles/) | 角色专项提示词材料 |
| [core/diagnostics/](../../../core/diagnostics/) | 运行异常、诊断与证据辅助 |
| [core/evaluation/](../../../core/evaluation/) | 评估、聊天数据捕获、切分与评测组织 |
| [core/evaluation/bundles/](../../../core/evaluation/bundles/) | 评测数据/契约的 bundle 定义与材料 |
| [core/external_agent/](../../../core/external_agent/) | 官方 SDK MCP stdio 网关、loopback client 与固定外部调用契约 |
| [core/gym/](../../../core/gym/) | Agent 能力评测/训练场景的组织模块 |
| [core/infrastructure/](../../../core/infrastructure/) | 文件/进程/锁/安全/工作区/工具/Git 等共享底层设施 |
| [core/infrastructure/codex_sandbox/](../../../core/infrastructure/codex_sandbox/) | Codex 沙箱相关的环境、策略与执行适配 |
| [core/launcher/](../../../core/launcher/) | Python 侧 Launcher 准备、路径、新鲜度、维护与兼容桥；桌面主控制在 Electron |
| [core/llm/](../../../core/llm/) | 模型绑定、协议、请求/流式规范化、重试/恢复、用量与缓存 |
| [core/llm/provider_discovery/](../../../core/llm/provider_discovery/) | Provider 能力和模型发现相关适配 |
| [core/llm/wire/](../../../core/llm/wire/) | Chat Completions、Responses、Anthropic 等具体 wire 编解码 |
| [core/logging/](../../../core/logging/) | 日志初始化、统一 logger 与运行日志支持 |
| [core/orchestration/](../../../core/orchestration/) | Agent 单轮上下文、模型适配、工具生命周期、结果分类与子任务 |
| [core/pet_system/](../../../core/pet_system/) | Python 宠物状态、成长/行为等领域；与浏览器模型 renderer 分层 |
| [core/pet_system/subsystems/](../../../core/pet_system/subsystems/) | 宠物领域的各子系统 |
| [core/pet_system/utils/](../../../core/pet_system/utils/) | 宠物存储等通用辅助 |
| [core/prompt_manager/](../../../core/prompt_manager/) | 系统 Prompt 章节、核心快照、能力/预算裁决、代码库地图与缓存 |
| [core/research/](../../../core/research/) | 题目、实验、证据、评分、知识与正式科研运行领域 |
| [core/research/competition/](../../../core/research/competition/) | 竞赛/挑战杯相关领域逻辑 |
| [core/research/competition/data/](../../../core/research/competition/data/) | 竞赛领域使用的固定数据材料 |
| [core/research/evidence/](../../../core/research/evidence/) | 研究证据模型与验证辅助 |
| [core/research/evidence_adapters/](../../../core/research/evidence_adapters/) | 外部/领域证据到统一研究契约的适配 |
| [core/research/experiment_adapters/](../../../core/research/experiment_adapters/) | 实验运行的具体适配器 |
| [core/research/operator_optimization/](../../../core/research/operator_optimization/) | 算子优化研究领域与实验组织 |
| [core/research/third_party/](../../../core/research/third_party/) | 研究相关第三方组件适配/引用；注意许可和实际调用边界 |
| [core/research/workflow/](../../../core/research/workflow/) | 科研工作流定义、状态、预算、命令与运行时契约 |
| [core/research/workflow/contracts/](../../../core/research/workflow/contracts/) | 工作流输入、产物、handoff 等强类型契约 |
| [core/research/workflow/definitions/](../../../core/research/workflow/definitions/) | 固定工作流/阶段/节点定义 |
| [core/research/workflow/ledger/](../../../core/research/workflow/ledger/) | SQLite Workflow Ledger、事务、正式运行事实与回执 |
| [core/research/workflow/migration/](../../../core/research/workflow/migration/) | 研究工作流持久化升级/迁移辅助 |
| [core/restarter_manager/](../../../core/restarter_manager/) | 专门的重启/重生管理机制；不等于前端刷新 |
| [core/runtime_manager/](../../../core/runtime_manager/) | 实例、WorkRun、进程身份、命令/重启协调与运行管理 |
| [core/ui/](../../../core/ui/) | Python 终端 UI 和 chat-state 兼容访问；不是 React 页面 |
| [core/web/](../../../core/web/) | FastAPI 应用、生命周期、中间件、路由与业务服务 |
| [core/web/middleware/](../../../core/web/middleware/) | 请求计时/运行证据、路由就绪等待等 HTTP 中间件 |
| [core/web/routes/](../../../core/web/routes/) | HTTP 路由、Pydantic DTO 和异常/状态码映射 |
| [core/web/routes/team_workflows/](../../../core/web/routes/team_workflows/) | 团队科研工作流分模块 HTTP route，统一 router 导出 |
| [core/web/services/](../../../core/web/services/) | 稳定业务 facade 与分领域实现包 |
| [core/web/services/agent_directory/](../../../core/web/services/agent_directory/) | Agent 配置/目录、策略、生命周期、个人记忆和初始资源 |
| [core/web/services/agent_directory/presets/](../../../core/web/services/agent_directory/presets/) | 首次安装公开角色/Agent 预设目录 |
| [core/web/services/agent_directory/presets/assets/](../../../core/web/services/agent_directory/presets/assets/) | 公开 Agent 预设携带的头像等静态资源 |
| [core/web/services/agent_perception/](../../../core/web/services/agent_perception/) | 按操作者配置的感知来源、有界读取与原生后台任务 |
| [core/web/services/external_agent/](../../../core/web/services/external_agent/) | 受管 MCP 网关的资格、任务归属、lease、审批、取消与状态投影 |
| [core/web/services/financial_backtest/](../../../core/web/services/financial_backtest/) | 历史 AI 决策、回测执行/恢复和导出 |
| [core/web/services/financial_jobs/](../../../core/web/services/financial_jobs/) | 金融任务批次和研究日程 |
| [core/web/services/financial_market/](../../../core/web/services/financial_market/) | 市场报价/K线/筛选及来源、时间、单位校验 |
| [core/web/services/financial_paper/](../../../core/web/services/financial_paper/) | 模拟交易账本；不是券商实盘接口 |
| [core/web/services/financial_preferences/](../../../core/web/services/financial_preferences/) | 金融 Agent 用户偏好，复用个人记忆 |
| [core/web/services/financial_rebalance/](../../../core/web/services/financial_rebalance/) | 目标配置、风险校验和受控模拟调仓 |
| [core/web/services/financial_report/](../../../core/web/services/financial_report/) | 从归属正确的已完成 Turn 导出金融报告与证据 |
| [core/web/services/financial_research/](../../../core/web/services/financial_research/) | 股票/主题研究和只读筛选投影 |
| [core/web/services/financial_team/](../../../core/web/services/financial_team/) | 多分析员的原生协作与汇总 |
| [core/web/services/memory/](../../../core/web/services/memory/) | 记忆管理的领域辅助；检索/清理 facade 在 services 同级 |
| [core/web/services/personal_assistant_platform_api/](../../../core/web/services/personal_assistant_platform_api/) | 个人助理允许访问的受控内部平台 API 子集 |
| [core/web/services/personal_assistant_project/](../../../core/web/services/personal_assistant_project/) | 个人助理的项目范围有界只读查询 |
| [core/web/services/runtime_scene/](../../../core/web/services/runtime_scene/) | 运行场景事件、诊断包、索引和读取投影 |
| [core/web/services/session/](../../../core/web/services/session/) | 消息准入/调度/worker/持久化/投影/SSE 等热路径实现 |
| [core/web/services/team/](../../../core/web/services/team/) | 团队成员、角色、组织、画布与关联会话业务 |
| [core/web/services/team/role_definitions/](../../../core/web/services/team/role_definitions/) | 团队角色定义/模板 |
| [core/web/services/team_knowledge/](../../../core/web/services/team_knowledge/) | 正式知识、Owner、ACL、来源/审核/修订/生命周期与检索 |
| [core/web/services/team_workflow/](../../../core/web/services/team_workflow/) | 团队科研/通用工作流编排与业务适配 |
| [core/web/services/team_workflow/experiment_api/](../../../core/web/services/team_workflow/experiment_api/) | 实验计划、冻结、基线与执行 API 的业务切片 |
| [core/web/services/team_workflow/generic/](../../../core/web/services/team_workflow/generic/) | 用户定义顺序流程、原生 Session 执行、回执与可选恢复 |
| [core/web/services/team_workflow/operator_optimization/](../../../core/web/services/team_workflow/operator_optimization/) | 团队算子优化任务的服务编排 |
| [core/web/services/team_workflow/research_runtime/](../../../core/web/services/team_workflow/research_runtime/) | 正式科研运行时：命令、graph/adapter worker、read-back、receipt/handoff |
| [core/web/services/team_workflow/research_runtime/adapters/](../../../core/web/services/team_workflow/research_runtime/adapters/) | 研究运行时到真实领域操作的适配 |
| [core/web/services/team_workflow/research_runtime/command_offers/](../../../core/web/services/team_workflow/research_runtime/command_offers/) | 正式工作流可用命令/操作的投影与构造 |
| [core/web/services/team_workflow/research_runtime/readiness/](../../../core/web/services/team_workflow/research_runtime/readiness/) | 节点运行条件、绑定、预算与产物等可执行性判定 |
| [core/web/services/team_workflow/source_collection/](../../../core/web/services/team_workflow/source_collection/) | 来源搜索、候选、阶段任务、写回、核对和持久化 |
| [desktop/](../../../desktop/) | 桌面宿主与原生运行支持 |
| [desktop/electron/](../../../desktop/electron/) | Electron 工程：依赖、构建、main/preload、生命周期与测试 |
| [desktop/electron/native/](../../../desktop/electron/native/) | Electron 使用的本地原生扩展 |
| [desktop/electron/native/workbench-job/](../../../desktop/electron/native/workbench-job/) | C 实现 Windows Job Object 进程树归属与回收 |
| [desktop/electron/scripts/](../../../desktop/electron/scripts/) | 桌面编译/打包、原生组件与 provenance 准备脚本 |
| [desktop/electron/src/](../../../desktop/electron/src/) | Electron TypeScript 主进程、preload 与桌面模块 |
| [desktop/electron/src/cli/](../../../desktop/electron/src/cli/) | 桌面命令行动作解析与转发 |
| [desktop/electron/src/debugging/](../../../desktop/electron/src/debugging/) | 只绑定 loopback 的动态桌面调试发现 |
| [desktop/electron/src/launch/](../../../desktop/electron/src/launch/) | 桌面启动设置、launch profile 和环境路径 |
| [desktop/electron/src/lifecycle/](../../../desktop/electron/src/lifecycle/) | 实例状态、registry、准入、构建新鲜度、延迟重启与生命周期投影 |
| [desktop/electron/src/lifecycle/__fixtures__/](../../../desktop/electron/src/lifecycle/__fixtures__/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：__fixtures__ |
| [desktop/electron/src/lifecycle/mainLine/](../../../desktop/electron/src/lifecycle/mainLine/) | main 工作台启停/重启命令排队和证据 |
| [desktop/electron/src/notifications/](../../../desktop/electron/src/notifications/) | 会话/审批/个人提醒等桌面通知 |
| [desktop/electron/src/packaging/](../../../desktop/electron/src/packaging/) | 前端 bundle 与桌面包的来源/版本元数据 |
| [desktop/electron/src/process/](../../../desktop/electron/src/process/) | 后端/子进程、安全 spawn、健康探测、归属、新鲜度与回收 |
| [desktop/electron/src/protocol/](../../../desktop/electron/src/protocol/) | IPC、deep link、Launcher 请求/回执与受限 HTTP 桥 |
| [desktop/electron/src/runtime/](../../../desktop/electron/src/runtime/) | 桌面运行期通用保护，如 broken-pipe guard |
| [desktop/electron/src/scripts/](../../../desktop/electron/src/scripts/) | 写 launch profile/provenance 等内部构建入口 |
| [desktop/electron/src/security/](../../../desktop/electron/src/security/) | IPC sender、URL、外链与路径安全策略 |
| [desktop/electron/src/shutdown/](../../../desktop/electron/src/shutdown/) | 活动任务判断、退出协调和桌面壳退出 |
| [desktop/electron/src/smoke/](../../../desktop/electron/src/smoke/) | 桌面 smoke 场景与退出验证 |
| [desktop/electron/src/state/](../../../desktop/electron/src/state/) | 桌面状态/会话镜像等本地状态组织 |
| [desktop/electron/src/tray/](../../../desktop/electron/src/tray/) | 系统托盘菜单与产品入口 |
| [desktop/electron/src/windows/](../../../desktop/electron/src/windows/) | BrowserWindow、窗口角色、标题、桌宠拖动等 |
| [desktop/electron/tests/](../../../desktop/electron/tests/) | 桌面单测、契约、原生进程管理与构建测试 |
| [docs/](../../../docs/) | 文档总入口，需区分现行指南与历史 archive |
| [docs/adr/](../../../docs/adr/) | 架构决策记录：为什么采用某项设计 |
| [docs/agents/](../../../docs/agents/) | 开发/运行 Agent 的操作、授权、事实源与职责契约 |
| [docs/architecture/](../../../docs/architecture/) | 架构专题说明 |
| [docs/archive/](../../../docs/archive/) | 历史计划、旧规范和实现记录，只作背景而非现行权威 |
| [docs/archive/frontend/](../../../docs/archive/frontend/) | 历史文档归档（frontend）；只作背景，不代表现行实现已启用 |
| [docs/archive/guides/](../../../docs/archive/guides/) | 历史文档归档（guides）；只作背景，不代表现行实现已启用 |
| [docs/archive/ops/](../../../docs/archive/ops/) | 历史文档归档（ops）；只作背景，不代表现行实现已启用 |
| [docs/archive/ops-config/](../../../docs/archive/ops-config/) | 历史文档归档（ops-config）；只作背景，不代表现行实现已启用 |
| [docs/archive/ops/2026-05/](../../../docs/archive/ops/2026-05/) | 历史文档归档（ops/2026-05）；只作背景，不代表现行实现已启用 |
| [docs/archive/ops/efficiency-baselines/](../../../docs/archive/ops/efficiency-baselines/) | 历史文档归档（ops/efficiency-baselines）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/](../../../docs/archive/plans/) | 历史文档归档（plans）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-05/](../../../docs/archive/plans/2026-05/) | 历史文档归档（plans/2026-05）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-06-07/](../../../docs/archive/plans/2026-06-07/) | 历史文档归档（plans/2026-06-07）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-08/](../../../docs/archive/plans/2026-08/) | 历史文档归档（plans/2026-08）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-08-09/](../../../docs/archive/plans/2026-08-09/) | 历史文档归档（plans/2026-08-09）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-08-10/](../../../docs/archive/plans/2026-08-10/) | 历史文档归档（plans/2026-08-10）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-08-11/](../../../docs/archive/plans/2026-08-11/) | 历史文档归档（plans/2026-08-11）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-08-15/](../../../docs/archive/plans/2026-08-15/) | 历史文档归档（plans/2026-08-15）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-09/](../../../docs/archive/plans/2026-09/) | 历史文档归档（plans/2026-09）；只作背景，不代表现行实现已启用 |
| [docs/archive/plans/2026-10/](../../../docs/archive/plans/2026-10/) | 历史文档归档（plans/2026-10）；只作背景，不代表现行实现已启用 |
| [docs/archive/product/](../../../docs/archive/product/) | 历史文档归档（product）；只作背景，不代表现行实现已启用 |
| [docs/archive/superpowers/](../../../docs/archive/superpowers/) | 历史文档归档（superpowers）；只作背景，不代表现行实现已启用 |
| [docs/archive/superpowers/evidence/](../../../docs/archive/superpowers/evidence/) | 历史文档归档（superpowers/evidence）；只作背景，不代表现行实现已启用 |
| [docs/archive/superpowers/evidence/2026-07-24-vui-wave2/](../../../docs/archive/superpowers/evidence/2026-07-24-vui-wave2/) | 历史文档归档（superpowers/evidence/2026-07-24-vui-wave2）；只作背景，不代表现行实现已启用 |
| [docs/archive/superpowers/plans/](../../../docs/archive/superpowers/plans/) | 历史文档归档（superpowers/plans）；只作背景，不代表现行实现已启用 |
| [docs/archive/superpowers/specs/](../../../docs/archive/superpowers/specs/) | 历史文档归档（superpowers/specs）；只作背景，不代表现行实现已启用 |
| [docs/archive/testing/](../../../docs/archive/testing/) | 历史文档归档（testing）；只作背景，不代表现行实现已启用 |
| [docs/assets/](../../../docs/assets/) | 文档截图、示意图、演示与素材，不是业务执行代码 |
| [docs/assets/readme/](../../../docs/assets/readme/) | 文档用截图/演示/设计素材，按 readme 分类 |
| [docs/assets/readme/showcase/](../../../docs/assets/readme/showcase/) | 文档用截图/演示/设计素材，按 readme/showcase 分类 |
| [docs/guides/](../../../docs/guides/) | 安装、调试、开发、首轮对话等操作教程 |
| [docs/ops/](../../../docs/ops/) | 操作者运维文档 |
| [docs/ops/config/](../../../docs/ops/config/) | 模型、Provider、协议、工具、插件等操作者配置说明 |
| [docs/plans/](../../../docs/plans/) | 白名单在研计划；计划不等于已经上线的实现 |
| [docs/prds/](../../../docs/prds/) | 产品需求文档 |
| [docs/product/](../../../docs/product/) | 产品设计登记与界面规范 |
| [docs/release/](../../../docs/release/) | 发布流程与版本相关说明 |
| [docs/research/](../../../docs/research/) | 研究专题与说明材料 |
| [docs/security/](../../../docs/security/) | 安全边界/专题说明 |
| [docs/standards/](../../../docs/standards/) | 开发、测试、文档等现行工程规范 |
| [docs/testing/](../../../docs/testing/) | 测试流程和验收说明 |
| [experiments/](../../../experiments/) | 专项研究实验，按任务选择运行，不是聊天服务必经路径 |
| [experiments/challenge_cup_gpu_operator/](../../../experiments/challenge_cup_gpu_operator/) | 挑战杯 GPU 算子相关实验 |
| [experiments/challenge_cup_gpu_operator/fixtures/](../../../experiments/challenge_cup_gpu_operator/fixtures/) | 挑战杯 GPU 算子相关实验的专项子目录：fixtures |
| [experiments/challenge_cup_neural_spike/](../../../experiments/challenge_cup_neural_spike/) | 神经脉冲相关研究实验 |
| [experiments/challenge_cup_neural_spike/fixtures/](../../../experiments/challenge_cup_neural_spike/fixtures/) | 神经脉冲相关研究实验的专项子目录：fixtures |
| [experiments/challenge_cup_predictive_coding/](../../../experiments/challenge_cup_predictive_coding/) | 预测编码相关实验 |
| [experiments/challenge_cup_spike_coding/](../../../experiments/challenge_cup_spike_coding/) | 脉冲编码相关实验 |
| [prompts/](../../../prompts/) | 专项任务 Prompt 模板 |
| [prompts/research/](../../../prompts/research/) | 研究任务提示词模板 |
| [schemas/](../../../schemas/) | JSON Schema 数据与产物契约 |
| [scripts/](../../../scripts/) | 安装/启动/诊断/构建/迁移/协作/验证的脚本入口 |
| [scripts/challenge_cup/](../../../scripts/challenge_cup/) | 挑战杯研究专项脚本 |
| [scripts/windows_launcher_entry/](../../../scripts/windows_launcher_entry/) | 官方 Windows 无控制台 C# 启动 shim 的源码与构建/同步 |
| [tests/](../../../tests/) | Python 后端单元/集成/契约与端到端辅助 |
| [tests/_support/](../../../tests/_support/) | 测试专用共享支持模块，非产品运行模块 |
| [tests/_support/team_workflow/](../../../tests/_support/team_workflow/) | 团队工作流测试辅助 |
| [tests/e2e/](../../../tests/e2e/) | 端到端测试与本机运行辅助 |
| [tests/e2e/helpers/](../../../tests/e2e/helpers/) | 端到端测试公共工具 |
| [tests/e2e/mock_llm/](../../../tests/e2e/mock_llm/) | 可控模型模拟服务；不代表真实 Provider 能力 |
| [tests/e2e/mock_llm/scenarios/](../../../tests/e2e/mock_llm/scenarios/) | 模型模拟场景和预设响应 |
| [tests/e2e/mock_llm/scenarios/fixtures/](../../../tests/e2e/mock_llm/scenarios/fixtures/) | 后端测试专用子集：e2e/mock_llm/scenarios/fixtures；按同目录文件识别具体场景 |
| [tests/fixtures/](../../../tests/fixtures/) | 后端测试用固定输入、合同样本和资源 |
| [tests/fixtures/challenge_cup/](../../../tests/fixtures/challenge_cup/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：challenge_cup |
| [tests/fixtures/config/](../../../tests/fixtures/config/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：config |
| [tests/fixtures/conversation_chain/](../../../tests/fixtures/conversation_chain/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：conversation_chain |
| [tests/fixtures/launcher/](../../../tests/fixtures/launcher/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：launcher |
| [tests/fixtures/tool_authorization/](../../../tests/fixtures/tool_authorization/) | 测试 fixture：固定输入/协议样本或资源；不是正式运行数据。主题：tool_authorization |
| [tests/helpers/](../../../tests/helpers/) | 测试帮助函数 |
| [tools/](../../../tools/) | Agent 工具实现、Key_Tools 注册与领域工具包装 |
| [web/](../../../web/) | React/TypeScript 工作台工程、Vite 构建、预览、静态资源与测试 |
| [web/live2d/](../../../web/live2d/) | Live2D 运行源码/构建资产来源与 manifest 指纹链 |
| [web/preview/](../../../web/preview/) | 设计样机/对照预览集合；不自动进入正式产品路由 |
| [web/preview/agent-config-layout/](../../../web/preview/agent-config-layout/) | Agent 配置布局设计样机/对照预览，不自动成为生产路由 |
| [web/preview/aligned-workspaces/](../../../web/preview/aligned-workspaces/) | 对齐工作区设计样机/对照预览，不自动成为生产路由 |
| [web/preview/assistant-compact-window/](../../../web/preview/assistant-compact-window/) | 助理紧凑窗口设计样机/对照预览，不自动成为生产路由 |
| [web/preview/assistant-overview/](../../../web/preview/assistant-overview/) | 助理概览设计样机/对照预览，不自动成为生产路由 |
| [web/preview/chat-stream-core/](../../../web/preview/chat-stream-core/) | 聊天流与过程核心设计样机/对照预览，不自动成为生产路由 |
| [web/preview/chat-stream-core/docs/](../../../web/preview/chat-stream-core/docs/) | 聊天流与过程核心设计样机/对照预览；docs 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/docs/screenshots/](../../../web/preview/chat-stream-core/docs/screenshots/) | 聊天流与过程核心设计样机/对照预览；docs/screenshots 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/](../../../web/preview/chat-stream-core/src/) | 聊天流与过程核心设计样机/对照预览；src 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/current/](../../../web/preview/chat-stream-core/src/current/) | 聊天流与过程核心设计样机/对照预览；src/current 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/mock/](../../../web/preview/chat-stream-core/src/mock/) | 聊天流与过程核心设计样机/对照预览；src/mock 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/next/](../../../web/preview/chat-stream-core/src/next/) | 聊天流与过程核心设计样机/对照预览；src/next 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/panels/](../../../web/preview/chat-stream-core/src/panels/) | 聊天流与过程核心设计样机/对照预览；src/panels 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/runtime/](../../../web/preview/chat-stream-core/src/runtime/) | 聊天流与过程核心设计样机/对照预览；src/runtime 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/chat-stream-core/src/shared/](../../../web/preview/chat-stream-core/src/shared/) | 聊天流与过程核心设计样机/对照预览；src/shared 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/codex-rail-toolbar/](../../../web/preview/codex-rail-toolbar/) | 消息侧栏工具条设计样机/对照预览，不自动成为生产路由 |
| [web/preview/companion-life-immersion/](../../../web/preview/companion-life-immersion/) | 人物生活沉浸式界面设计样机/对照预览，不自动成为生产路由 |
| [web/preview/companion-ui-alignment/](../../../web/preview/companion-ui-alignment/) | 人物界面对齐设计样机/对照预览，不自动成为生产路由 |
| [web/preview/composer-model-parameters/](../../../web/preview/composer-model-parameters/) | 输入区模型参数设计样机/对照预览，不自动成为生产路由 |
| [web/preview/finance-conversation/](../../../web/preview/finance-conversation/) | 金融对话设计样机/对照预览，不自动成为生产路由 |
| [web/preview/finance-desktop-tabs/](../../../web/preview/finance-desktop-tabs/) | 金融桌面标签设计样机/对照预览，不自动成为生产路由 |
| [web/preview/finance-investment-plan/](../../../web/preview/finance-investment-plan/) | 金融投资计划设计样机/对照预览，不自动成为生产路由 |
| [web/preview/finance-ui-repair/](../../../web/preview/finance-ui-repair/) | 金融界面修整设计样机/对照预览，不自动成为生产路由 |
| [web/preview/frontend-ux-polish/](../../../web/preview/frontend-ux-polish/) | 前端体验细节设计样机/对照预览，不自动成为生产路由 |
| [web/preview/generic-team-workspace/](../../../web/preview/generic-team-workspace/) | 通用团队流程工作区设计样机/对照预览，不自动成为生产路由 |
| [web/preview/launcher-update/](../../../web/preview/launcher-update/) | 启动器更新设计样机/对照预览，不自动成为生产路由 |
| [web/preview/live-token-gauge/](../../../web/preview/live-token-gauge/) | 实时 token 仪表设计样机/对照预览，不自动成为生产路由 |
| [web/preview/memory-reader/](../../../web/preview/memory-reader/) | 记忆阅读器设计样机/对照预览，不自动成为生产路由 |
| [web/preview/platform-knowledge-map/](../../../web/preview/platform-knowledge-map/) | 平台知识地图设计样机/对照预览，不自动成为生产路由 |
| [web/preview/team-chat/](../../../web/preview/team-chat/) | 团队群聊设计样机/对照预览，不自动成为生产路由 |
| [web/preview/team-chat/src/](../../../web/preview/team-chat/src/) | 团队群聊设计样机/对照预览；src 为该样机的源码/资料子集，不自动成为生产路由 |
| [web/preview/tools-management/](../../../web/preview/tools-management/) | 工具管理设计样机/对照预览，不自动成为生产路由 |
| [web/probes/](../../../web/probes/) | 前端专门诊断与探测材料 |
| [web/public/](../../../web/public/) | 原样提供给浏览器的公共静态资源 |
| [web/public/desktop-pet/](../../../web/public/desktop-pet/) | 桌宠运行时/角色静态资源 |
| [web/public/desktop-pet/live2d/](../../../web/public/desktop-pet/live2d/) | Live2D Core、Shaders 与角色资源 |
| [web/public/desktop-pet/live2d/Core/](../../../web/public/desktop-pet/live2d/Core/) | Live2D 底层运行资源，注意第三方许可 |
| [web/public/desktop-pet/live2d/Shaders/](../../../web/public/desktop-pet/live2d/Shaders/) | Live2D 渲染 shader 资源 |
| [web/public/desktop-pet/live2d/XiaoLuo/](../../../web/public/desktop-pet/live2d/XiaoLuo/) | XiaoLuo 角色模型/配置资源 |
| [web/public/desktop-pet/live2d/XiaoLuo/motions/](../../../web/public/desktop-pet/live2d/XiaoLuo/motions/) | 角色动作资源 |
| [web/public/desktop-pet/live2d/XiaoLuo/motions/tap/](../../../web/public/desktop-pet/live2d/XiaoLuo/motions/tap/) | 点击触发的动作资源 |
| [web/public/desktop-pet/live2d/XiaoLuo/physics/](../../../web/public/desktop-pet/live2d/XiaoLuo/physics/) | 角色物理参数资源 |
| [web/public/desktop-pet/live2d/XiaoLuo/textures/](../../../web/public/desktop-pet/live2d/XiaoLuo/textures/) | 角色贴图资源 |
| [web/public/desktop-pet/whale-rig/](../../../web/public/desktop-pet/whale-rig/) | 鲸鱼形象骨架/表现相关静态资源，不是用户数据目录 |
| [web/public/desktop-pet/whale-rig/lib/](../../../web/public/desktop-pet/whale-rig/lib/) | 鲸鱼表现使用的浏览器库文件 |
| [web/scripts/](../../../web/scripts/) | 前端并行构建、预算、资源指纹、视觉 token 等辅助脚本 |
| [web/src/](../../../web/src/) | 正式前端源代码与同目录测试 |
| [web/src/agent-thread/](../../../web/src/agent-thread/) | Agent 线程/消息表现与结构适配 |
| [web/src/api/](../../../web/src/api/) | 按领域封装 HTTP/IPC 调用、控制 token、query keys 与 DTO |
| [web/src/api/research-workflow/](../../../web/src/api/research-workflow/) | 正式科研工作流通信接口的模块化实现 |
| [web/src/api/types/](../../../web/src/api/types/) | 按业务域划分的 TypeScript DTO，不是数据库表声明 |
| [web/src/api/types/research-workflow/](../../../web/src/api/types/research-workflow/) | 科研工作流前后端数据契约 |
| [web/src/app/](../../../web/src/app/) | 全局 Provider、Router、页面壳、导航、桌面桥与遥测 |
| [web/src/components/](../../../web/src/components/) | 共用显示、交互、编辑器、布局、预览与 VUI 组件 |
| [web/src/components/conversation/](../../../web/src/components/conversation/) | 消息输入/展示、TurnItems/cells、过程行、附件与聊天布局 |
| [web/src/components/editor/](../../../web/src/components/editor/) | 编辑器组件与代码编辑辅助 |
| [web/src/components/layout/](../../../web/src/components/layout/) | 共用布局/面板组织 |
| [web/src/components/preview/](../../../web/src/components/preview/) | 文件、内容或产物预览组件 |
| [web/src/components/vui/](../../../web/src/components/vui/) | 项目公开 V* UI API、组件实现与设计契约 |
| [web/src/components/vui/aesthetic/](../../../web/src/components/vui/aesthetic/) | 装饰/视觉表现类 VUI 组件 |
| [web/src/components/vui/designs/](../../../web/src/components/vui/designs/) | VUI 设计规范和登记文档，不是另一套组件代码 |
| [web/src/components/vui/designs/aesthetic/](../../../web/src/components/vui/designs/aesthetic/) | VUI 的 aesthetic 类组件设计规范/登记文档 |
| [web/src/components/vui/designs/display/](../../../web/src/components/vui/designs/display/) | VUI 的 display 类组件设计规范/登记文档 |
| [web/src/components/vui/designs/forms/](../../../web/src/components/vui/designs/forms/) | VUI 的 forms 类组件设计规范/登记文档 |
| [web/src/components/vui/designs/layout/](../../../web/src/components/vui/designs/layout/) | VUI 的 layout 类组件设计规范/登记文档 |
| [web/src/components/vui/designs/primitives/](../../../web/src/components/vui/designs/primitives/) | VUI 的 primitives 类组件设计规范/登记文档 |
| [web/src/components/vui/designs/product/](../../../web/src/components/vui/designs/product/) | VUI 的 product 类组件设计规范/登记文档 |
| [web/src/components/vui/display/](../../../web/src/components/vui/display/) | 信息显示类 VUI 组件 |
| [web/src/components/vui/forms/](../../../web/src/components/vui/forms/) | 表单输入/选择等 VUI 组件 |
| [web/src/components/vui/layout/](../../../web/src/components/vui/layout/) | 页面 recipe、分栏和容器布局 VUI |
| [web/src/components/vui/lib/](../../../web/src/components/vui/lib/) | VUI 共享的无业务辅助 |
| [web/src/components/vui/primitives/](../../../web/src/components/vui/primitives/) | 基础原子 VUI 控件 |
| [web/src/components/vui/product/](../../../web/src/components/vui/product/) | 产品领域 VUI 组合组件 |
| [web/src/components/vui/product/agent-management/](../../../web/src/components/vui/product/agent-management/) | Agent 管理领域组合组件 |
| [web/src/components/vui/product/memory/](../../../web/src/components/vui/product/memory/) | 记忆/知识图等产品组件 |
| [web/src/components/vui/product/team-management/](../../../web/src/components/vui/product/team-management/) | 团队管理组合组件 |
| [web/src/components/vui/product/workbench-shell/](../../../web/src/components/vui/product/workbench-shell/) | 工作台壳/导航等组合组件 |
| [web/src/components/vui/product/workflow/](../../../web/src/components/vui/product/workflow/) | 流程/图画布等产品组件及公开边界 |
| [web/src/components/vui/renderers/](../../../web/src/components/vui/renderers/) | UI 底层 renderer 边界；业务页面不要直连私有实现 |
| [web/src/components/vui/renderers/shadcn/](../../../web/src/components/vui/renderers/shadcn/) | 基于 shadcn/Radix 思想的实际交互/DOM 组件实现 |
| [web/src/components/vui/renderers/shadcn/memory/](../../../web/src/components/vui/renderers/shadcn/memory/) | 记忆/图谱组件的底层渲染 |
| [web/src/components/vui/renderers/shadcn/workflow/](../../../web/src/components/vui/renderers/shadcn/workflow/) | 流程图组件的底层渲染/交互 |
| [web/src/components/vui/renderers/shared/](../../../web/src/components/vui/renderers/shared/) | renderer 共用辅助 |
| [web/src/design/](../../../web/src/design/) | 设计 token、基础/页面样式、视觉预览和截图材料 |
| [web/src/design/challenge-cup-single-action-preview/](../../../web/src/design/challenge-cup-single-action-preview/) | 设计验证/预览/截图材料：challenge-cup-single-action-preview；正式接入以 router/组件引用为准 |
| [web/src/design/challenge-research-usability/](../../../web/src/design/challenge-research-usability/) | 设计验证/预览/截图材料：challenge-research-usability；正式接入以 router/组件引用为准 |
| [web/src/design/composer-followup-queue-preview-shots/](../../../web/src/design/composer-followup-queue-preview-shots/) | 设计验证/预览/截图材料：composer-followup-queue-preview-shots；正式接入以 router/组件引用为准 |
| [web/src/design/research-process-workspace-preview-shots/](../../../web/src/design/research-process-workspace-preview-shots/) | 设计验证/预览/截图材料：research-process-workspace-preview-shots；正式接入以 router/组件引用为准 |
| [web/src/design/route-css/](../../../web/src/design/route-css/) | 按页面拆分的设计样式 |
| [web/src/design/team-node-inspector-preview-shots/](../../../web/src/design/team-node-inspector-preview-shots/) | 设计验证/预览/截图材料：team-node-inspector-preview-shots；正式接入以 router/组件引用为准 |
| [web/src/design/vui-component-preview/](../../../web/src/design/vui-component-preview/) | VUI 组件目录预览应用 |
| [web/src/design/vui-component-preview/catalog/](../../../web/src/design/vui-component-preview/catalog/) | 按领域组织的 VUI 组件示例与预览登记 |
| [web/src/i18n/](../../../web/src/i18n/) | 国际化与中英文文本资源 |
| [web/src/i18n/domains/](../../../web/src/i18n/domains/) | 按业务领域分组的翻译资源 |
| [web/src/logs/](../../../web/src/logs/) | 前端日志展示/诊断辅助 |
| [web/src/routes/](../../../web/src/routes/) | 业务页面及页面级 hooks/模型/样式/测试 |
| [web/src/routes/agent-create/](../../../web/src/routes/agent-create/) | 创建 Agent 的向导与页面切片 |
| [web/src/routes/agent-plugins/](../../../web/src/routes/agent-plugins/) | Agent 插件配置页面 |
| [web/src/routes/agentPerception/](../../../web/src/routes/agentPerception/) | Agent 感知配置与运行投影页面 |
| [web/src/routes/agents/](../../../web/src/routes/agents/) | Agent 管理页面内部组件和逻辑 |
| [web/src/routes/auxConversations/](../../../web/src/routes/auxConversations/) | 辅助会话视图；刻意避免 Windows AUX 保留名 |
| [web/src/routes/chat/](../../../web/src/routes/chat/) | 聊天工作台、提交/流、选中态、缓存/活动层与工作区 |
| [web/src/routes/companions/](../../../web/src/routes/companions/) | 人物大厅/房间、生活、外观编辑、模型与场景布局 |
| [web/src/routes/companions/assets/](../../../web/src/routes/companions/assets/) | 人物页面专用静态素材 |
| [web/src/routes/companions/assets/scenes/](../../../web/src/routes/companions/assets/scenes/) | 人物房间背景场景素材 |
| [web/src/routes/config/](../../../web/src/routes/config/) | 模型/Provider/主题等操作者配置页面切片 |
| [web/src/routes/config/__snapshots__/](../../../web/src/routes/config/__snapshots__/) | 自动化测试快照基准，用于比较输出/页面契约 |
| [web/src/routes/desktopPet/](../../../web/src/routes/desktopPet/) | 桌宠/桌面浮窗相关前端页面与运行支持 |
| [web/src/routes/evolution/](../../../web/src/routes/evolution/) | 自进化/监督进化等页面与交互 |
| [web/src/routes/finance/](../../../web/src/routes/finance/) | 金融研究/行情/模拟/回测/报告等页面 |
| [web/src/routes/memory/](../../../web/src/routes/memory/) | 记忆、知识管理和阅读/图谱页面切片 |
| [web/src/routes/personalAssistant/](../../../web/src/routes/personalAssistant/) | 个人助理页面、事务、分派/状态等 |
| [web/src/routes/shared/](../../../web/src/routes/shared/) | 多个业务页面共用的 hooks/投影/组件 |
| [web/src/routes/teams/](../../../web/src/routes/teams/) | 团队、画布、工作流、科研与来源采集页面 |
| [web/src/routes/teams/challenge-cup/](../../../web/src/routes/teams/challenge-cup/) | 挑战杯团队专项界面 |
| [web/src/routes/teams/generic/](../../../web/src/routes/teams/generic/) | 用户定义通用团队工作流页面 |
| [web/src/routes/teams/research-projects/](../../../web/src/routes/teams/research-projects/) | 研究项目组织与管理界面 |
| [web/src/routes/teams/research-workflow/](../../../web/src/routes/teams/research-workflow/) | 正式科研节点、状态与运行证据界面 |
| [web/src/routes/teams/source-collection/](../../../web/src/routes/teams/source-collection/) | 研究来源采集、候选、阶段任务界面 |
| [web/src/routes/teams/source-collection/ui/](../../../web/src/routes/teams/source-collection/ui/) | 来源采集页面内的显示组件 |
| [web/src/shortcuts/](../../../web/src/shortcuts/) | 键盘快捷键模型、绑定、冲突和处理 |
| [web/src/store/](../../../web/src/store/) | 客户端共享 UI 状态；不是持久业务事实源 |
| [web/src/vendor/](../../../web/src/vendor/) | 本地维护的第三方适配/补丁代码 |
| [web/src/visual-regression/](../../../web/src/visual-regression/) | 视觉回归用 token/场景等支持 |
