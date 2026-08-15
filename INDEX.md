# Vibelution 项目索引

**用途：** 仓库目录地图。
**权威：** 根 [`AGENTS.md`](AGENTS.md) → [`docs/README.md`](docs/README.md) → [`docs/standards/`](docs/standards/README.md)。本文件不定义流程、不维护待办、不记录行数。

项目记忆：运行 `python scripts/migrate_project_storage.py inventory`，读取 `activePaths.memory` 下的 `INDEX.md`。`.docs/project-memory/` 只是迁移前只读兼容路径，禁止当作现行规范或新写入目标。

---

## 项目结构

```text
Vibelution/
├── AGENTS.md                   # Agent 红线与路由入口
├── agent.py                    # Agent composition root（新逻辑进 core/）
├── config/                     # 配置模型库、provider、runtime defaults
├── core/                       # 运行时核心（chat / llm / orchestration / web / …）
├── desktop/                    # Electron Launcher 控制面
├── tools/                      # Agent 可见工具（*_tools.py）
├── tests/                      # pytest；命令见 tests/README.md
├── web/                        # React + Vite 工作台
├── docs/                       # 文档地图：standards / guides / adr / archive
│   ├── README.md               # 现行 vs 历史
│   └── plans/                  # 白名单在研草案（非正式规范）
├── scripts/                    # launcher、doctor、migrate_project_storage 等
├── workspace/                  # 本地运行态产物（gitignored）
└── .worktrees/                 # 任务 worktree 池（gitignored）
```

---

## 从这里打开

| 需求 | 打开 |
| --- | --- |
| Agent 红线 / 工作分级 | [`AGENTS.md`](AGENTS.md) |
| 文档地图 | [`docs/README.md`](docs/README.md) |
| 开发标准 | [`docs/standards/development-standard.md`](docs/standards/development-standard.md) |
| 任务路由 | [`docs/guides/README.md`](docs/guides/README.md) |
| Web services | [`core/web/services/README.md`](core/web/services/README.md) |
| 测试 | [`tests/README.md`](tests/README.md) |
| Operator 配置 | [`docs/ops/config/INDEX.md`](docs/ops/config/INDEX.md) |
| 身份 / 通用纪律（运行时 Prompt，不扩权） | [`core/core_prompt/SOUL.md`](core/core_prompt/SOUL.md) · [`COMMON.md`](core/core_prompt/COMMON.md) |
