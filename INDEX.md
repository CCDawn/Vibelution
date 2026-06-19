# Vibelution 项目索引

**版本：** v7.3
**日期：** 2026-06-19
**用途：** AI Agent 执行任务的执行参数（结构说明已与仓库同步）

---

## 项目结构

```
Vibelution/
├── agent.py                    # Agent 主入口与主循环编排（当前约 2.5k 行，持续收敛中）
├── config/                     # 配置模型库、provider、runtime defaults 与 public config 同步
├── core/                       # 核心模块（按功能分类）
│   ├── chat/                   # Chat session、结果格式、任务状态
│   ├── chatroom/               # 多 Agent 协作 chat room
│   ├── code_context_graph/     # 项目代码上下文图与索引
│   ├── core_prompt/            # 核心提示词（身份与规范）
│   │   ├── SOUL.md             # 身份定义
│   │   ├── MENTAL_SOUL.md      # 心智模型说明
│   │   ├── COMMON.md           # 通用准则
│   │   └── SPEC.md             # 开发流程规范
│   ├── evaluation/             # 监督进化、dataset registry、dashboard、chat case review
│   ├── gym/                    # proposal lifecycle、advisory baseline、promotion 记录
│   ├── infrastructure/         # session、tool executor、git memory、security、workspace 等
│   ├── llm/                    # LLM payload builder、路由、protocol 解析
│   ├── logging/                # transcript、tool tracker、runtime scene 日志
│   ├── orchestration/          # 模式策略、委托、输出边界、回合收束
│   ├── pet_system/             # 长期陪伴体子系统
│   ├── prompt_manager/         # prompt 组装、任务分析、代码库地图
│   ├── research/               # 研究流程与知识组织
│   ├── restarter_manager/      # 重启管理
│   ├── runtime_manager/        # Web workbench 与运行进程生命周期
│   ├── ui/                     # CLI 主题、Workbench、Token 显示
│   ├── web/                    # FastAPI app、routes、services
│   └── workspace/              # 工作区分析与产物管理
├── tools/                      # Agent 可见工具（约 27 个 *_tools.py 模块）
├── tests/                      # Python 测试套件（以 pytest 收集为准）
├── web/                        # React + Vite 前端工程
├── docs/                       # 文档索引、当前计划、操作记录、归档
│   ├── README.md               # 文档入口与归档边界
│   ├── plans/                  # 当前或近当前计划
│   └── archive/                # 历史计划与归档说明
├── workspace/                  # 本地运行态产物、evaluation 数据和日志（gitignored）
├── scripts/                    # launcher、web_workbench、doctor、prune_logs 等
└── .docs/project-memory/       # 项目记忆与多页 HTML 状态面
```

---

## 版本信息

| 文件 | 版本 | 更新日期 |
|------|------|----------|
| INDEX.md | v7.3 | 2026-06-19 |
| SOUL.md | v4.1 | 2026-04-30 |
| SPEC.md | v4.5 | 2026-04-30 |

---

## 核心约束

| 约束 | 限制 | 当前状态 |
|------|------|----------|
| agent.py 体量 | 优先将新逻辑放入 `core/`，入口保持黏合与循环 | ⚠️ 约 2.5k 行；近期偏运维稳定性，结构收敛节奏放缓 |
| Core First 规范 | 必须执行 | ✅ 已建立 |
| 测试 | 变更后跑相关 `pytest`；全量见下 | ✅ `tests/` 下逾 140 个测试文件 |
| 单文件红线 | core/web/services 与前端 route 控制在 ~2k 行内 | ⚠️ session_service.py 约 1.3w 行、ChatCodingRoute.tsx 约 6.4k 行需拆 |

---

## 开发流程 (SPEC.md)

每次任务执行流程：

```
[感知] git diff --stat 上次变更
[感知] 读取 INDEX.md 修改日志
[对比] 对比本次目标与上次产出
[决策] Core First 检查
[执行] 修改代码
[验证] py_compile + pytest + prompt_debugger
[分析] 流程自分析与优化
[记录] INDEX.md 修改日志追加
[交付] git commit
```

### Core First 检查清单

```
1. ls core/ → 了解目录结构
2. rg "function_name" core/ --type py → 搜索相似功能
3. 有 → import 使用，agent.py 仅写调用代码 (<10行)
   无 → 在 core/ 对应子目录创建/修改
```

---

## 测试状态

勿在此手工维护用例个数（易与仓库漂移）。在已激活的 **项目 `.venv`** 下执行：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ --collect-only -q
```

全量运行（同上，需 venv 以满足 `environment_smoke`）：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

---

## 待处理任务追踪表

| # | 优先级 | 任务描述 | 状态 |
|---|--------|----------|------|
| 1 | P0 | 拆分 `core/web/services/session_service.py`（~1.3w 行）按域抽出 | 📋 待办 |
| 2 | P0 | 拆分 `web/src/routes/ChatCodingRoute.tsx`（~6.4k 行） | 📋 待办 |
| 3 | P1 | 给 `log_info/` / `.runtime/` / `backups/` 落地本地 retention 策略 | 📋 进行中 |
| 4 | P1 | 生产环境锁定 Python 3.11–3.12 并文档化 CI 镜像 | 📋 待办 |
| 5 | P2 | 把 `挑战杯/` 子项目归位（拆 submodule 或挪到 docs/） | 📋 待办 |
| 6 | P2 | 优化 `core/prompt_manager/builder.py` 可读性 | 📋 待办 |

---

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `core/core_prompt/SOUL.md` | 身份定义 |
| `core/core_prompt/SPEC.md` | 开发流程规范 |
| `core/core_prompt/COMMON.md` | 通用准则 |
| `core/core_prompt/MENTAL_SOUL.md` | 心智模型说明 |
| `DEVELOPMENT_STANDARD.md` | 当前开发与协作标准 |
| `docs/README.md` | 当前文档入口与归档边界 |
| `tests/README.md` | 测试入口与验证说明 |
| `挑战杯/research_team_flow_design.html` | 挑战杯科研流程 HTML 入口 |

---

## 健康检查

- [x] Core First 规范已建立
- [x] 索引与 README 已与当前目录树对齐（持续随提交更新）
- [x] 测试套件：`tests/` 下逾 140 文件（以本地收集为准）
- [ ] agent.py 体量偏大，按任务表继续收敛
- [ ] 超大单文件（session_service.py / ChatCodingRoute.tsx）尚未拆分

---

## 修改日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v7.3 | 2026-06-19 | 增加 docs 入口；将 2026-05 历史计划归档到 docs/archive/plans/2026-05；刷新 README/INDEX 文档边界 |
| v7.2 | 2026-06-05 | 补齐缺失子目录（chatroom/code_context_graph/llm/research/workspace）；修正 agent.py 行数；重排 P0/P1 待办，新增单文件红线约束与日志 retention 项 |
| v7.1 | 2026-05-21 | 删除重复的根目录 reset.py，Reset 入口统一到 Web 工作台白名单清理动作面 |
| v7.0 | 2026-05-11 | 同步项目结构（orchestration、infrastructure、ui）；修正 agent.py 体量与测试说明；移除过时的 ≤500 行与手工用例计数表 |
| v7.0 | 2026-05-03 | 重建 INDEX.md，修复损坏的表格格式；记录 v7.0 版本信息；清理冗余内容；建立清晰的待处理任务追踪表 |
| v6.9 | 2026-04-30 | 补充缺失的测试用例；完善 prompt_manager 模块 |
| v6.8 | 2026-04-29 | 完成 Core First 规范建立；agent.py 代码迁移完成 |
