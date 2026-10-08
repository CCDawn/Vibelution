# 团队 / 角色统一格式契约（Unified Team Format）

> 状态：现行规范（机器门禁见 §5）。本文件是四套团队体系（通用 / 科研 / 进化 / 金融）收敛成员行、角色声明与模型引用格式的唯一基准；金融团队阶段 3 迁移以此为准。
> 权威顺序见 [README.md](README.md)；本文不复制全局红线，只定义格式契约本身。

## 1. 定位与权威链

统一格式的字段权威全部来自现有实现，本文只把它们固化为可复核契约，不引入第二实现：

| 记录 | 权威实现（字段来源） | 说明 |
| --- | --- | --- |
| 成员行 | `core/web/services/team/canvas_normalize.py` `_normalize_members` | 写入侧唯一规范化出口；`team_projection._members_to_api` 是只读响应投影 |
| 模型投影 | `core/web/services/team/team_projection.py` `_member_model_summary` | 从 agents.json `llmBindings` 经 `agent_dialogue_model_id` 只读投影 |
| 角色声明 | `core/web/services/team/role_definition_service.py`（角色文件层，见 §5） | 声明式角色字段集：一角色一文件，`team_format.validate_role_definition` 是加载门禁 |
| Agent 实例 | `workspace/agents/agents.json` | `agentId`/`agentCode`/`displayName`/`roleKey`/`llmBindings`/`promptTemplateId` 等的唯一权威 |
| 角色绑定 | `core/web/services/team_workflow/research_runtime/team_role_source.py` | roleKey→agentId 解析 + fail-cold 运行快照；Team `members` 是唯一绑定源，canvas 是投影 |

## 2. 团队清单（Team Manifest）

团队 = 清单记录 + 成员行数组。存储层必需字段：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `teamId` | string | 非空 |
| `name` | string | 非空 |
| `purpose` | string | 可为空 |
| `status` | string | `active` / `archived`（`team_constants.TEAM_STATUSES`） |
| `linkedChatRoomId` | string | 可为空（创建后链接） |
| `members` | list | 成员行数组，≤120 行，`agentId` 不得重复 |

## 3. 成员行（Member Row）Schema

`_normalize_members` 输出的恰好 8 个字段，是成员行的完整权威形状：

| 字段 | 类型 | 约束 |
| --- | --- | --- |
| `memberId` | string | 非空，≤96 字符 |
| `agentId` | string | 非空；必须存在于 agents.json |
| `agentCode` | string | 来自 Agent 实例 |
| `agentName` | string | 来自 Agent `displayName` |
| `role` | string | 单行 |
| `purpose` | string | ≤4 行 |
| `responsibilities` | string[] | ≤8 条 |
| `agentStatus` | string | 规范化写入只产 `active`；`archived` 仅为归档未修复行保留 |

成员行内**不得出现模型字段**。API 响应层（`_members_to_api`）可为每行附加只读 `model` 摘要（`{dialogueModelId, configured}`），它仅存在于响应，不入库、不参与校验器的存储层契约。

## 4. 模型 / 提示词引用语义（agents.json 唯一权威）

- 模型配置权威在 `workspace/agents/agents.json` 的 `llmBindings`（槽位：`dialogue`/`mentalModel`/`summary`/`subagentPlanning`/`subagentExecution`/`vision`，见 `core/llm/agent_runtime.py` `AGENT_LLM_SLOTS`）；提示词权威是同一记录的 `promptTemplateId`。10-03 模型配置 SSOT 链已落成，任何团队/角色格式不得制造第二源。
- 团队与角色记录里只允许**引用**，不允许**字面值**：
  - 禁止出现内嵌解析值字段：`model`、`modelId`、`model_id`、`dialogueModelId`、`llm`、`llmBindings`、`provider`、`prompt`、`promptText`、`systemPrompt`。
  - 角色声明可选字段 `modelRef`：值必须是 llmBindings 槽位名（引用"去 agents.json 哪个槽位取模型"），不能是具体模型名（如 `qwen3.5-9b` 属字面值，拒绝）。
- 成员行不带模型：展示层需要时由 `_member_model_summary` 在响应时实时投影。

## 5. 角色声明（Role Definition）与角色文件层

结构化字段集以 `ROLE_DEFINITION_FIELDS` 为完整形态：

```
roleKey          非空 string
role             非空 string（角色显示名）
purpose          非空 string
responsibilities 非空 string[]
agentName        非空 string（建议实例化的 Agent 显示名）
personaProfile   personality / communicationStyle / background / identityNotes / expertise[]
taskProfile      mission / responsibilities / preferredTasks / avoidTasks /
                 successCriteria / constraints / deliverables
toolPolicy       allowedTools[] / preferredTools[] / writeScopes[]
modelRef?        可选；llmBindings 槽位引用（见 §4）
```

### 5.1 存储布局（workspace 级共享角色库）

| 存储 | 位置 | 说明 |
| --- | --- | --- |
| registry | `workspace/agent_config/role_definitions.json` | 每角色一行：`roleKey` / `sourcePath` / `status` / `metadata{builtin, builtinContentVersion, updatedAt}`；**不存角色内容**，md 文件是唯一内容权威 |
| 角色文件 | `workspace/roles/<roleKey>.md` | frontmatter（YAML 子集）放上述结构化字段，markdown 正文放 persona/task 叙述（operator 可读可编辑，不参与结构化校验） |
| builtin 角色文件 | `core/web/services/team/role_definitions/*.md` | 随产品发布；当前为 dev-team 四角色（`dev_team_planner` / `dev_team_developer_a` / `dev_team_developer_b` / `dev_team_reviewer`） |

### 5.2 加载与 repair 语义

- 加载器：`role_definition_service`（`get_role_definition` / `load_role_definitions` / `list_role_definitions` / `repair_role_definitions`）。每次加载都过 `team_format.validate_role_definition` 门禁；畸形文件 **fail-closed**，报错带文件路径与 issue code，不得物化残缺角色。
- repair 照抄 prompt 模板 registry 语义：workspace 缺文件时从 builtin 内容 seed；`builtinContentVersion` 升级时**覆盖**对应 builtin 条目的 workspace 文件；用户新建/编辑的非 builtin 条目永不覆盖。
- `sourcePath` 只允许 `workspace/roles/<roleKey>.md` 且必须落在路由后的 workspace 内（防目录逃逸，与 prompt 模板 sourcePath 守卫同源）；角色正文属 operator_controlled 信任级（与 prompt 模板角色提示词同源），**不得进入 knowledge / 不可信通道**。
- 无文件监听：沿用 stat 签名 + 显式失效 + metadata 版本 + repair 的既有模式；dev-team 模板实例化时从角色文件层读取（`team_template_service.DEV_TEAM_ROLE_KEYS` 顺序即成员行/画布节点顺序），`workspace/agents/agents.json` 仍是运行时模型与提示词唯一权威，instantiate 单向物化。
- 系统托管团队由 team spec 的 managed 标记声明（批次2 落地）。

## 6. 四体系收敛路线

| 体系 | 现状 | 收敛动作 |
| --- | --- | --- |
| 通用（自定义/模板团队） | **已合规**：`team_crud` + `_normalize_members` 就是格式权威 | 保持；格式变更必须先改本文与门禁测试 |
| 科研（挑战杯） | `bootstrap_challenge_cup_research_team` 仍直接写 3 字段成员行，未走 `_normalize_members`。组织同步已不再写成员 | 挑战杯收尾已停止，不沿这条启动路径补字段。新增系统团队必须复用 `_normalize_members` |
| 进化（Gym/自进化） | `ensure_evolution_system_teams` 的成员行经 `_normalize_members` 落成 8 字段 | 保持；不另建成员存储。角色声明仍不在本行展开 |
| 金融 | 阶段 3 迁移目标 | 迁移时以本文为格式基准：成员行 8 字段、角色走角色文件层字段集、模型只留 agents.json 引用 |
| 开发团队模板 | 唯一可新建模板。实例化走 `create_team`，成员行经 `_normalize_members`；角色声明从角色文件层读取（§5） | 保持。医疗问诊与妇幼数字健康模板已移除，不再作为格式先例 |

## 7. 禁止事项

1. **新增第二处成员存储**：Team `members` 是唯一成员与角色绑定权威；canvas、workflow 快照、projection 都只是投影或冻结副本，不得反写或成为第二写入者。
2. **角色/团队记录内嵌模型或提示词字面值**：模型与提示词权威永久保持在 agents.json（见 §4）；禁止在成员行、角色声明、团队清单里写入解析后的模型 id 或提示词正文。
3. **绕过 `_normalize_members` 造成员行**：新体系接入统一格式必须复用同一规范化出口或与其逐字段对齐，并以 `tests/test_team_format_contract.py` 契约测试证明。

## 8. 校验器与门禁

- 校验模块：`core/web/services/team/team_format.py`（纯函数、零写入）
  - `validate_team_record(team, *, known_agent_ids=None)`：团队清单 + 成员行形状 + `agentId` 存在性（`known_agent_ids` 缺省时只读读取 Agent 目录）。
  - `validate_role_definition(role)`：角色声明字段集 + 模型必须是槽位引用（`modelRef`）而非字面值；角色文件层加载器（`role_definition_service`）是其唯一生产调用方，每次读文件都过此门禁。
  - 返回 `{valid, summary:{errorCount,warningCount,issueCount}, issues:[{severity,code,message,path}]}`。
- 契约测试：`tests/test_team_format_contract.py`（`_normalize_members` / 角色文件层黄金形状、`_member_model_summary` 引用解析语义、畸形样本拒绝）；角色文件层行为测试：`tests/test_role_definition_service.py`（seed / 版本升级 / 用户条目保留 / 逃逸拒绝 / fail-closed）。
- 修改成员行或角色字段集时，必须同步修改：`canvas_normalize._normalize_members`（或角色文件层字段与 `role_definitions/*.md` builtin 内容并升级 `BUILTIN_ROLE_CONTENT_VERSION`）→ 本文 schema 表 → `team_format.py` 常量 → 契约测试，四者一致方可合入。
