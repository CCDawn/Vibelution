# 挑战杯证据链接管基础设计

## 状态元数据

- **状态：** approved — 用户已于 2026-07-10 确认书面 spec，并同意将 `chat_room_service.py` 现有 owner 结果作为前置依赖
- **负责人：** `codex-challenge-cup-evidence-chain`
- **Claim：** `claim-6014f58cee98`
- **分支：** `codex/challenge-cup-evidence-chain`
- **Worktree：** `C:\Users\17533\Desktop\Vibelution-worktrees\challenge-cup-evidence-chain`
- **范围：** 无损保全并治理 root 中 12 个 Challenge Cup/研究 Agent 相关未提交改动，为后续单条完整科学证据链实施建立可信基线
- **替代关系：** 不替代既有挑战杯流程设计、技术实施方案或赛题对齐方案
- **实施方案：** 书面 spec 审阅通过后，在 `docs/superpowers/plans/` 生成独立实施计划
- **验证：** scoped patch 等价性、Python 编译、挑战杯编排测试、研究 Agent/Team/Knowledge/Tool 相邻测试、`git diff --check`
- **关闭条件：** 12 个继承改动完成语义拆分、验证和独立提交；root 原改动未被清理或覆盖；后续证据链实施范围可以从干净提交继续规划

## 目标

本阶段只解决接管可信度，不直接启动挑战杯 Agent、写正式知识、创建实验或修改运行数据。

用户可观察结果是：

1. root 中来源不明但已通过焦点验证的 12 个相关改动，被完整镜像到独立 worktree；
2. `core/web/services/chat_room_service.py` 及其 active claim 明确排除；
3. 镜像改动被拆成可解释、可验证、可独立回退的变更单元；
4. 后续“一条完整可验证科学假设链”不再建立在脏 root 或混合 diff 上；
5. 任何提交、合并、运行态写入和项目 memory 更新都有清楚的自然闸门。

## 已确认决策

用户选择方案 A：完整镜像 12 个 Challenge Cup/研究 Agent 相关脏文件到独立 worktree，同时保持 root 原样。

该选择排除了两条高风险路径：

- 不从 root 移走、reset、stash 或恢复未知来源改动；
- 不只保全 5 个 workflow 文件而让相邻研究 Agent 测试契约继续失去归属。

## 当前证据

- root 位于 `main`，挑战杯相关改动没有现成 task branch，也没有 guard claim 冲突。
- 12 个相关改动覆盖 workflow helper 拆分和研究 Agent 测试契约更新；另有 `chat_room_service.py` 改动属于其他 active claim。
- 隔离 worktree 已从当前 local `main` 创建，12 个文件已按 root scoped diff 镜像。
- 隔离 worktree 的 `tests/test_team_workflow_orchestration_service.py` 已复跑为 207 passed；相邻 7 个测试文件在隔离 worktree 运行到 202 passed 后，被 `test_team_detail_uses_lightweight_agent_references_for_member_repair` 的外部 `chat_room_service.py` 前置依赖阻断。
- 同一 lightweight team detail 测试在包含现有 owner participant-context 投影的 root 上 1 passed，根因已确认；本分支等待 owner 将该结果提交并进入 local `main`，不复制其未提交 hunk。
- 最新挑战杯运行轮没有 active source work run；因此本阶段不需要为了保全代码而干预运行态。

## 复用决策

复用结论为 **ADAPT**：

- 复用现有 `team_workflow` package、兼容 facade、`agent_role_tool_profile_service` 和项目原生测试；
- 复用 project memory guard 管理 claim，不创建第二套 ownership 记录；
- 复用现有 worktree 规范和 scoped Git 流程，不引入新脚本、依赖或补丁管理器；
- 只整理当前已存在的 diff，不借接管机会扩大为新的架构重写。

## 变更分区

### 分区 A：workflow helper 提取

拥有面：

- `core/web/services/team_workflow/source_collection_common.py`
- `core/web/services/team_workflow/source_collection_context.py`
- `core/web/services/team_workflow/source_collection_stage_tasks.py`
- `core/web/services/team_workflow_orchestration_service.py`
- `tests/test_team_workflow_orchestration_service.py`

设计意图：

- 把 source collection split module 所需的纯规范化、compact context 和 writeback contract 逻辑放回对应 package 模块；未拆分 orchestration callsite 继续使用 facade 中既有的兼容私有 helper，本阶段只验证两者行为等价，不扩大迁移；
- 保留 `team_workflow_orchestration_service.py` 兼容 facade，避免调用方和 API contract 漂移；
- `SCHEMA_VERSION` 仍由 facade 作为运行时事实源传入 helper，避免 split module 形成第二份版本事实；
- 本阶段不继续拆分其他 orchestration 逻辑。

### 分区 B：研究角色策略测试对齐

拥有面：

- `tests/test_agent_config_workspace_service.py`
- `tests/test_agent_lifecycle_create_delete.py`
- `tests/test_agent_membership_indexes.py`
- `tests/test_research_organization_service.py`
- `tests/test_team_knowledge_service.py`
- `tests/test_team_service.py`
- `tests/test_tool_registry_service.py`

设计意图：

- 测试从 `agent_role_tool_profile_service` 读取期望策略，不再复制完整工具数组；
- `promptTemplateId/defaultPromptTemplateId/promptTemplateCustomized` 的断言跟随当前真实所有权契约；
- Tool Registry 测试读取公开 `argsSchema`，不再扫描 `tools/Key_Tools.py` 源文本；
- 测试必须继续保护禁止工具、写入范围、mutation/network 边界和关键上下文/回写工具可见性，不能退化为只验证 helper 自己。

## 数据与状态流

```text
root 未提交 diff
  -> scoped patch 镜像
  -> 隔离 worktree
  -> 分区 A / 分区 B 语义审查
  -> 分区级验证
  -> 独立提交
  -> 后续证据链实施计划
```

root 只作为一次性来源快照，不是本分支的持续同步源。镜像完成后，新增改动只发生在 worktree；root 中后续变化不得自动覆盖本分支。

## 错误与冲突处理

- 如果 worktree diff 与初始 root scoped diff 不等价，停止提交并重新生成差异报告；不修正 root。
- 如果分区 A 测试失败，先判断是 helper 提取语义变化还是 facade 兼容缺口；不得通过删除行为断言来恢复绿色。
- 如果分区 B 测试失败，先核对生产事实源和当前角色策略；不得把旧硬编码数组重新引入测试。
- 如果 local `main` 在实施期间前进，不自动 rebase、merge 或覆盖；先完成当前分区提交，再单独评估同步风险。
- 如果 claim 冲突出现，停止写入冲突文件并报告 owner、scope 和建议 merge order。
- `chat_room_service.py` 始终不属于本 spec；其改动、测试和生命周期验证由现有 owner 负责。

## 验证设计

### 等价性与 Git 边界

- 对 12 个文件比较 root 与 worktree 的 scoped diff/patch identity；设计文档不参与比较。
- `git status --short --branch` 必须只显示当前分区文件和本 spec。
- `git diff --check` 必须通过。
- 设计文档先单独提交；12 个继承改动不得混入 spec commit。
- staging 必须逐文件进行，禁止 `git add .`。

### 分区 A

- `py -3 -m py_compile` 覆盖 4 个变更 Python 模块。
- `py -3 -m pytest tests/test_team_workflow_orchestration_service.py -q`。
- 重点保护 compact context、分页 continuation、writeback schema version、stage completion gate 和正式知识边界。

### 分区 B

- 运行 7 个相邻测试文件的完整集合。
- 核对研究协调、资料寻找、资料提炼、关系整理、资料入库、知识库管理员及 experiment/iteration 角色的 ToolPolicy 所有权。
- 保留禁止 `cli_tool`、`apply_patch_tool` 和越权 mutation/write scope 的断言。

### 本阶段不要求

- 不要求前端 build，因为本阶段没有前端文件；
- 不要求 Launcher refresh，因为本阶段不改变运行中的代码事实；
- 不要求挑战杯 HTML regeneration，因为本阶段不改变 workflow schema、运行数据或用户流程；
- 不把整仓测试作为提交前唯一门禁，但最终报告必须明确焦点范围和未运行部分。

## 保护边界

- 不编辑、暂存或提交 `core/web/services/chat_room_service.py`。
- 不清理 root、其他 worktree、branch、stash 或 `.claude/worktrees/**`。
- 不启动、继续、终止或修复挑战杯运行任务。
- 不写 CandidateStore、Team Knowledge、RAG、official graph、experiment plan 或 Research Loop。
- 不修改 `挑战杯/**`、项目 memory lane/overview、版本文件、远端分支或 PR；claim registry 只允许通过 guard 命令更新。
- 不把继承 diff 的测试通过解释为比赛级证据链已经完成。

## 后续证据链阶段入口

本阶段关闭后，下一份实施设计只覆盖一个代表性研究对象，目标链固定为：

```text
source_manifest
  -> paper_note
  -> neuro_mechanism
  -> mechanism_mapping
  -> algorithm_hypothesis
  -> review_record
  -> experiment_plan / smoke evidence
```

后续阶段必须同时满足：

- 每个关键结论有 `sourceRef/pageAnchor/citation/evidenceRef`；
- 至少一个反例或边界条件进入 review；
- 真实 Qwen/百炼调用证据登记到 official model evidence store，而不是只保留 CandidateStore 派生输出；
- baseline、metric、dataset、smokePlan 可执行且失败也有记录；
- 正式知识、RAG 和 official graph 仍经过既有 Steward 门禁。

## 风险与缓解

- **风险：镜像 diff 混入多个语义。** 通过分区 A/B 独立审查、验证和提交降低回退成本。
- **风险：测试只跟随实现而失去独立性。** 保留权限边界、禁止工具、关键可见工具和 facade 行为断言。
- **风险：main 前进导致基线变化。** 本 worktree 固定从创建时 local `main` 开始，后续同步单独审查。
- **风险：root 重复改动长期存在。** 本阶段只建立安全副本和 ownership；root 清理由原 owner 或后续明确授权处理。
- **风险：治理工作拖延比赛主线。** 只允许两个分区，不新增第三个重构分区；验证通过后立即进入单条证据链设计。

## 完成标准

本阶段只有在以下条件全部满足时才完成：

1. 12 个继承改动与 root 初始 scoped diff 等价；
2. 分区 A 和分区 B 的职责与文件边界明确；
3. 两个分区的焦点验证均通过；
4. 两个分区可独立提交或已有证据证明必须合并提交；
5. spec、branch、worktree、claim、验证命令和剩余风险均可追溯；
6. root、`chat_room_service.py`、运行数据、项目 memory 和远端均未被本阶段改变；
7. 后续单条证据链的输入、输出、证据门和正式知识边界已经明确。
