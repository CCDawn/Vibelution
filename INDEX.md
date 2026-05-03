# Vibelution 项目索引

**版本：** v7.0
**日期：** 2026-05-03
**用途：** AI Agent 执行任务的执行参数

---

## 项目结构

```
Vibelution/
├── agent.py                    # Agent 主程序 (~499行)
├── reset.py                    # 一键初始化脚本
├── config.toml                 # TOML 配置文件
├── core/                       # 核心模块（按功能分类）
│   ├── infrastructure/         # 基础设施
│   │   ├── agent_session.py    # Session 状态管理
│   │   ├── background_tasks.py # 后台任务管理
│   │   ├── cli_utils.py        # CLI 辅助工具
│   │   ├── cron_scheduler.py   # Cron 调度系统
│   │   ├── event_bus.py        # 事件总线
│   │   ├── llm_utils.py        # LLM 辅助工具
│   │   ├── model_discovery.py   # 模型动态发现
│   │   ├── security.py         # 安全模块
│   │   ├── state.py            # 状态管理
│   │   ├── test_gate.py        # 进化测试门
│   │   ├── tool_executor.py    # 工具执行器
│   │   ├── tool_result.py      # 工具结果处理
│   │   └── workspace_manager.py # 工作区管理
│   ├── logging/                # 日志系统
│   │   ├── logger.py           # 日志模块
│   │   ├── setup.py            # 日志设置
│   │   ├── tool_tracker.py     # 工具追踪器
│   │   ├── transcript_logger.py # 转录日志
│   │   └── unified_logger.py   # 统一日志
│   ├── orchestration/          # 任务编排
│   │   └── task_planner.py     # 任务计划器
│   ├── pet_system/             # 宠物系统 (10大子系统)
│   │   ├── pet_system.py
│   │   ├── models.py
│   │   ├── subsystems/         # 心跳/饥饿/健康/日记/梦境/基因/装扮/社交/声音/性格
│   │   └── utils/
│   ├── prompt_manager/         # 提示词管理
│   │   ├── builder.py          # 提示词构建器
│   │   ├── codebase_map_builder.py # 代码库地图
│   │   ├── prompt_manager.py   # 提示词管理器
│   │   ├── section_cache.py    # 章节缓存
│   │   ├── sections.py         # 章节工厂
│   │   ├── task_analyzer.py    # 任务分析器
│   │   └── types.py            # 类型定义
│   ├── restarter_manager/       # 重启管理
│   │   └── restarter.py
│   ├── ui/                     # 用户界面
│   │   ├── ascii_art.py        # ASCII 艺术
│   │   ├── cli_ui.py           # CLI UI
│   │   ├── interactive_cli.py  # 交互式 CLI
│   │   ├── theme.py            # 主题配置
│   │   └── token_display.py    # Token 显示
│   └── core_prompt/            # 核心提示词
│       ├── SOUL.md             # 身份定义 (v4.1)
│       └── SPEC.md             # 开发流程规范 (v4.5)
├── tools/                      # 工具集
│   ├── agent_tools.py          # 子代理工具
│   ├── code_analysis_tools.py  # 代码分析工具
│   ├── codebase_analyzer.py    # 代码库分析器
│   ├── key_info_extractor.py   # 关键信息提取
│   ├── Key_Tools.py            # LangChain 工具包装
│   ├── memory_tools.py         # 记忆管理
│   ├── rebirth_tools.py        # 重生工具
│   ├── search_tools.py         # 搜索工具
│   ├── shell_tools.py          # Shell 工具
│   ├── state_broadcaster.py    # 状态广播
│   ├── token_manager.py        # Token 管理
│   └── web_search_tool.py      # 网络搜索
├── tests/                      # 测试套件 (22个测试文件)
└── workspace/                   # 工作区
    ├── prompts/
    │   ├── DYNAMIC.md          # 动态任务描述
    │   ├── IDENTITY.md         # 身份定义
    │   └── USER.md             # 用户环境
    └── memory/archives/        # 压缩记忆存档
```

---

## 版本信息

| 文件 | 版本 | 更新日期 |
|------|------|----------|
| INDEX.md | v7.0 | 2026-05-03 |
| SOUL.md | v4.1 | 2026-04-30 |
| SPEC.md | v4.5 | 2026-04-30 |

---

## 核心约束

| 约束 | 限制 | 当前状态 |
|------|------|----------|
| agent.py 行数 | ≤ 500 行 | ✅ 499 行 |
| Core First 规范 | 必须执行 | ✅ 已建立 |
| 测试覆盖率 | 全部核心模块 | ✅ 22 测试文件 |

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

| 测试文件 | 状态 | 覆盖 |
|----------|------|------|
| test_code_analysis_tools.py | ✅ | 75 tests |
| test_event_bus.py | ✅ | 80 tests |
| test_key_info_extractor.py | ✅ | 16 tests |
| test_memory.py | ✅ | 9 tests |
| test_memory_tools.py | ✅ | 20 tests |
| test_model_discovery.py | ✅ | 27 tests |
| test_prompt_manager.py | ✅ | 49 tests |
| test_restarter.py | ✅ | 56 tests |
| test_runner.py | ✅ | 7 tests |
| test_search_tools.py | ✅ | 61 tests |
| test_security.py | ✅ | 21 tests |
| test_shell_tools.py | ✅ | 70 tests |
| test_state.py | ✅ | 68 tests |
| test_task_planner.py | ✅ | 71 tests |
| test_token_manager.py | ✅ | 82 tests |
| test_tool_executor.py | ✅ | 23 tests |
| test_tool_result.py | ✅ | 14 tests |
| test_tool_tracker.py | ✅ | 30 tests |
| test_workspace_manager.py | ✅ | 46 tests |
| **总计** | **20/22** | **824 tests** |

---

## 待处理任务追踪表

| # | 优先级 | 任务描述 | 状态 |
|---|--------|----------|------|
| 1 | P0 | 修复 INDEX.md 表格格式问题 | ✅ 已完成 |
| 2 | P0 | 验证 agent.py ≤500 行约束 | ✅ 已完成 |
| 3 | P1 | 补充 test_model_discovery.py (已有 27 tests) | 📋 待办 |
| 4 | P1 | 补充 test_key_info_extractor.py (已有 16 tests) | 📋 待办 |
| 5 | P1 | 补充 test_tool_tracker.py (已有 30 tests) | 📋 待办 |
| 6 | P1 | 补充 test_security.py (已有 21 tests) | 📋 待办 |
| 7 | P2 | 清理 tools/backups/ 历史备份 | 📋 待办 |
| 8 | P2 | 优化 prompt_manager/builder.py 代码 | 📋 待办 |

---

## 关键文件路径

| 文件 | 用途 |
|------|------|
| `core/core_prompt/SOUL.md` | 身份定义 (56 行) |
| `core/core_prompt/SPEC.md` | 开发流程规范 (294 行) |
| `workspace/prompts/DYNAMIC.md` | 动态任务描述 |
| `workspace/prompts/IDENTITY.md` | 身份定义 |
| `workspace/prompts/USER.md` | 用户环境 |

---

## 健康检查

- [x] Core First 规范已建立
- [x] 索引联动已规范化
- [x] 测试套件完整 (20/22 文件)
- [x] agent.py 行数 ≤ 500 (当前 499)
- [x] INDEX.md 格式已修复

---

## 修改日志

| 版本 | 日期 | 变更 |
|------|------|------|
| v7.0 | 2026-05-03 | 重建 INDEX.md，修复损坏的表格格式；记录 v7.0 版本信息；清理冗余内容；建立清晰的待处理任务追踪表 |
| v6.9 | 2026-04-30 | 补充缺失的测试用例；完善 prompt_manager 模块 |
| v6.8 | 2026-04-29 | 完成 Core First 规范建立；agent.py 代码迁移完成 |
