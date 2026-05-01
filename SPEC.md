# SPEC 开发流程规范 (Agent-Native)

**版本：** v4.0
**日期：** 2026-04-30
**读者：** AI Agent（本文档的读者和执行者均为 Agent，所有规则必须可被程序化执行）

---

## 1. 定位

Agent 每次苏醒后读取。定义：

- **每次开发统一必做清单**（不分任务大小）
- **对比上一次产出规则**
- **流程自分析与优化机制**

不包含任务分类、阶段工作流、Phase 状态表。

---

## 2. 每次开发必做

以下步骤**每次均执行**，不可跳过。小任务每步内容少，大任务每步内容多，但步骤相同。

```
[感知] git diff --stat 上次提交以来的变更
[感知] 读取 INDEX.md 上次修改日志
        → 是否有 [流程优化] 标记（如有，优先处理，见第3节）
        → 上次完成了什么
        → 本次目标是什么
[对比] 对比本次目标与上次产出（见第4节）
[决策] Core First 检查（见第5节）
[执行] 修改代码
[验证] python -m py_compile <修改文件>.py
        pytest tests/<相关测试>.py -v -x
        python tests/prompt_shooting.py --suite（若涉及 SOUL.md/AGENTS.md/SPEC_Agent.md/workspace/prompts/* 或工具变更）
[分析] 本次流程出现的问题（见第3节）
[记录] INDEX.md 修改日志追加一条
[交付] git commit
```

**步骤1或步骤2失败 → 禁止继续，禁止提交。**

---

## 3. 流程自分析与优化

每次验证完成后，Agent 必须执行以下分析。

### 3.1 问题捕获

| 情况 | 记录内容 |
|------|---------|
| 验证失败 | 失败步骤 + 失败原因（语法错误行号 / 测试失败用例名 / Core First 违规文件） |
| 执行受阻 | 阻塞点（依赖缺失 / 磁盘状态与 INDEX.md 不符 / 工具命令不可用） |
| 范围误判 | 实际修改文件数与预期偏差 > 3 个文件 |

### 3.2 问题分类

| 类别 | 触发条件 | 修复方向 |
|------|---------|---------|
| 流程缺陷 | 同一 SPEC 规则导致反复失败 | 修改 SPEC_Agent.md 对应规则 |
| 状态不同步 | `ls core/` 与 INDEX.md 描述不一致 | 更新 INDEX.md |
| 工具缺失 | 某命令不可用或执行超时 | 修复对应工具或提供替代 |
| 范围膨胀 | 修改文件数远超预估 | 下次拆分为多次提交 |

### 3.3 优化动作

```
若问题类别 = 流程缺陷
    → INDEX.md 修改日志追加 [流程优化] 具体问题描述
    → 下次 Agent 苏醒时，检查 INDEX.md 是否有 [流程优化] 标记
    → 若有，优先修改 SPEC_Agent.md 自身
    → 修改完成后 INDEX.md 追加 [流程优化完成]

若问题类别 = 其他
    → INDEX.md 修改日志追加问题摘要
    → 下次苏醒时对比是否有改善
```

---

## 4. 对比上一次

每次苏醒后，执行以下对比（步骤2 [感知] 的一部分）：

```
1. git log -1 --stat
   → 上次修改了哪些文件、每个文件变更行数
   → agent.py 行数变化（当前 818，每次必须记录）

2. 读取 INDEX.md 上次修改日志
   → 上次是否完成（有无未解决问题）
   → 是否有 [流程优化] 标记待处理
   → 本次目标与上次的关联（延续 or 新任务）

3. 如果有压缩记忆
   → 读取上次上下文（已修改的文件、关键决策、阻塞点）
```

---

## 5. Core First

Agent 在实现任何功能前，必须执行以下决策（不允许跳过）：

```
1. ls core/ → 了解目录结构
2. rg "function_name" core/ --type py → 搜索相似功能
3.
   ├─ 有 → import 使用，agent.py 仅写调用代码（<10行）
   └─ 无 → 在 core/ 对应子目录创建/修改
            ├─ 创建 core/{category}/xxx.py
            ├─ 在 core/{category}/__init__.py 导出
            ├─ 文件头 docstring（功能 + 参数 + 返回值）
            └─ agent.py 导入使用
```

### agent.py 硬性约束

`agent.py` 当前 818 行，目标 <500。

| 允许 | 禁止 |
|------|------|
| `think_and_act()` 核心循环 | 业务逻辑（任务分类、优先级计算） |
| `run_loop()` 主循环入口 | 工具执行逻辑 |
| `_invoke_llm()` LLM 调用 | 复杂条件判断 |
| 必要的初始化与状态管理 | 未封装的功能逻辑 |

每次修改 agent.py 后，必须在 INDEX.md 修改日志记录新行数。

---

## 6. 质量门控

### 每次修改后执行

```
python -m py_compile <修改的文件>.py
pytest tests/<相关测试>.py -v -x
python tests/prompt_shooting.py --suite  （若涉及 SOUL.md/AGENTS.md/SPEC_Agent.md/workspace/prompts/* 或工具变更）
git diff --stat
```

### 自动化检查

```
[ ] 新文件 snake_case，新类 PascalCase，新函数 snake_case
[ ] 公开函数有类型注解
[ ] 新模块有 docstring（功能 + 参数 + 返回值）
[ ] 无 pass/... 空壳模块
[ ] 配置值来自 config.toml（禁止硬编码路径/密钥）
[ ] 若修改 agent.py：新行数 <= 修改前
[ ] 若添加/修改工具：通过 prompt_shooting.py 打靶测试
```

---

## 7. INDEX.md 联动

| 变更类型 | INDEX.md 更新 |
|----------|--------------|
| 任何变更 | 修改日志追加一条 |
| 修改 agent.py | 修改日志记录新行数 |
| 流程缺陷 | 修改日志标注 `[流程优化] 问题描述` |
| 流程优化完成 | 修改日志标注 `[流程优化完成]` |

---

## 8. 提示词系统架构

### 核心文件

| 文件 | 职责 | 约束 |
|------|------|------|
| `core/core_prompt/SOUL.md` | 身份、铁律、思维格式 | <120行，禁止写入 SOP |
| `core/core_prompt/AGENTS.md` | SOP 操作流程、协议 | <500行，禁止写入身份信息 |
| `requirement/SPEC/SPEC_Agent.md` | 开发流程规范（本文件） | Agent 每次苏醒后读取 |
| `workspace/prompts/DYNAMIC.md` | 本世代任务描述 | Agent 自行维护 |
| `workspace/prompts/IDENTITY.md` | 身份定义 | 动态 |
| `workspace/prompts/USER.md` | 用户环境 | 动态 |

### 组件优先级

```
SOUL(10) → TASK_CHECKLIST(20) → CODEBASE_MAP(30) → DYNAMIC(40) →
IDENTITY(50) → AGENTS(60) → SPEC(65) → USER(70) →
MEMORY(80) → current_rules(85) → TOOLS_INDEX(90) → ENV_INFO(100)
```

### 响应解析标签

| 标签 | 提取内容 | 处理位置 |
|------|---------|---------|
| `<think>` | 思考过程 | UI、日志 |
| `<plan>` | 任务计划 | `core/task_planner.py` || `<active_components>` | 组件切换 | `core/prompt_manager/prompt_manager.py` |
| `<tool_call>` | 工具调用 | 工具执行层 |

---

## 9. Git 提交规范

### 格式

```
<type>: <简短描述>

INDEX: v{version}
```

type: `feat` / `fix` / `refactor` / `docs` / `test`

### 规则

- 每次提交必须包含 `INDEX: v{version}` 行
- 提交信息写"做了什么"，不写"怎么做"

---

## 10. 磁盘状态快照

实际存在的 `core/` 子目录（以 `ls core/` 为准，不依赖 INDEX.md 描述）：

```
core/
├── core_prompt/        SOUL.md + AGENTS.md
├── evolution/          自我进化引擎
├── infrastructure/     工具执行、注册、状态、事件、安全
├── logging/            记录器、转录、追踪
├── orchestration/      LLM、记忆、任务、压缩、解析
├── pet_system/         10大子系统
├── prompt_manager/     构建、组件、分析、代码库地图
├── restarter_manager/  重启守护进程
└── ui/                 CLI、ASCII艺术、主题
```

---

## 11. 工具变更与提示词打靶

### 11.1 触发条件

添加新工具或修改现有工具时（包括 `tools/` 和 `core/` 下的所有工具），**必须**执行提示词打靶测试，验证模型能够正确理解并调用该工具。

### 11.2 执行方式

```bash
# 方式一：使用 prompt_shooting.py（推荐）
python tests/prompt_shooting.py --tool <工具名>

# 方式二：运行内置测试用例集
python tests/prompt_shooting.py --suite
```

### 11.3 验证标准

工具打靶通过需满足：
- 模型能识别工具名称和用途
- 模型能正确解析工具参数
- 模型在适当场景下主动调用该工具
- 无幻觉调用（不该调用时不调用）

### 11.4 测试框架职责

| 组件 | 职责 |
|------|------|
| `prompt_shooting.py` | 提示词打靶测试：验证模型对工具的理解和调用 |
| `test_runner.py` | 单元/集成测试运行器：验证代码正确性 |
| `simulate_lifecycle.py` | 生命周期验证：不调用大模型，验证防断裂机制 |
| `conftest.py` | pytest 配置：单例重置、隔离工作空间、共享 fixtures |

---

## 变更记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-04-18 | v1.0 | 初始版本 |
| 2026-04-19 | v1.2 | Core First、INDEX.md 联动、签收机制 |
| 2026-04-30 | v2.0 | 合并优化方案；双轨流程；增量联动；两文一表 |
| 2026-04-30 | v3.0 | Agent-Native 重写：按修改范围分类；确定性决策树；世代级规划；删除人类时间单位 |
| 2026-04-30 | v4.0 | 删除任务分类/工作流分支/Phase 状态表；统一为每次必做清单；新增对比上一次规则；新增流程自分析与优化闭环 |
| 2026-04-30 | v4.1 | 新增第11节"工具变更与提示词打靶"要求；更新磁盘状态快照；创建 prompt_shooting.py 测试框架 |