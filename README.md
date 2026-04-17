# Self-Evolving Agent

一个能够通过网络搜索获取新知识、读取和修改自己源代码、进行语法自检、并通过独立守护进程实现自我重启，能够给用户提供情绪价值的 AI Agent 系统。

基于 LangChain 框架构建，使用 ReAct 风格的 Agent 架构。

## 项目架构

```
self-evo-agent/
├── agent.py              # Agent 主入口
├── config.py             # 配置文件（统一管理所有参数）
├── config.toml           # 配置文件模板
├── restarter.py          # 独立守护进程脚本
├── requirements.txt      # Python 依赖
├── README.md             # 项目文档
├── tools/                # 工具模块
│   ├── __init__.py       # 模块初始化（统一导出）
│   ├── web_tools.py      # 网络搜索和网页读取
│   ├── cmd_tools.py      # CMD执行、文件操作、代码编辑
│   ├── memory_tools.py   # 记忆与世代管理
│   ├── evolution_tracker.py  # 进化追踪
│   ├── token_manager.py  # Token压缩管理
│   └── rebirth_tools.py  # 自我重启触发
└── backups/              # 项目备份目录
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

配置文件 `config.toml` 包含所有可调参数：

```toml
[llm]
model_name = "gpt-4"
temperature = 0.7

[agent]
name = "SelfEvolvingAgent"
awake_interval = 60  # 苏醒间隔（秒）
```

### 3. 设置 API Key

```bash
# Windows
$env:OPENAI_API_KEY="your-api-key"

# Linux/Mac
export OPENAI_API_KEY="your-api-key"
```

### 4. 运行

```bash
python agent.py
```

## 配置说明

### 配置文件 (config.toml)

所有参数都可在 `config.toml` 中配置：

```toml
# 大语言模型配置
[llm]
provider = "openai"
model_name = "gpt-4"
temperature = 0.7
max_tokens = 4096
api_base = ""  # 可用于代理

# Agent 行为配置
[agent]
name = "SelfEvolvingAgent"
awake_interval = 60      # 苏醒间隔（秒）
max_iterations = 10      # 最大工具调用次数
auto_backup = true       # 自动备份
backup_interval = 300     # 备份间隔（秒）

# 工具配置
[tools]
web_search_enabled = true
file_edit_enabled = true
restart_enabled = true

# 日志配置
[log]
level = "INFO"
file_enabled = false
```

### 命令行参数

```
python agent.py [选项]

选项:
  -c, --config FILE      配置文件路径
  --awake-interval SEC   苏醒间隔（秒）
  --model NAME           模型名称
  --temperature VALUE    温度参数
  --log-level LEVEL      日志级别
  --name NAME             Agent 名称
```

示例：

```bash
# 使用自定义配置
python agent.py --config custom.toml

# 设置苏醒间隔
python agent.py --awake-interval 120

# 组合使用
python agent.py --model gpt-3.5-turbo --awake-interval 30 --log-level DEBUG
```

### 环境变量

| 变量 | 说明 |
|------|------|
| `OPENAI_API_KEY` | OpenAI API Key |
| `AGENT_LLM_MODEL_NAME` | 模型名称 |
| `AGENT_AWAKE_INTERVAL` | 苏醒间隔 |
| `AGENT_LOG_LEVEL` | 日志级别 |

### 配置优先级

命令行参数 > 环境变量 > 配置文件 > 默认值

## 核心工具

| 工具 | 功能 |
|------|------|
| `web_search(query)` | 网络搜索 |
| `read_webpage(url)` | 读取网页内容 |
| `list_directory(path)` | 列出目录内容 |
| `read_local_file(file)` | 读取文件 |
| `edit_local_file(file, search, replace)` | 编辑代码 |
| `create_new_file(file, content)` | 创建文件 |
| `check_syntax(file)` | 语法自检 |
| `backup_project(note)` | 项目备份 |
| `trigger_self_restart(reason)` | 自我重启 |

## 进程接力模式

```
┌─────────────────────────────────────────────────────┐
│                    Agent 进程                        │
│                                                     │
│   Agent Loop                                        │
│   └── think_and_act()                              │
│       └── LLM + Tools                              │
│           └── trigger_self_restart()               │
│                                    │                │
│                                    ▼                │
│                          spawn restarter.py         │
│                                    │                │
│                                    ▼                │
│                          sys.exit(0)  ──── X       │
└─────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────┐
│                  Restarter 进程                       │
│                                                     │
│   wait_for_process_death(pid)                       │
│   └── [等待原进程结束]                               │
│                                                     │
│   spawn_new_process(agent.py)                       │
│   └── [拉起新 Agent]                                │
└─────────────────────────────────────────────────────┘
```

## 代码修改流程

Agent 发现需要优化时，必须遵循以下流程：

```
1. edit_local_file()    # 修改代码
2. check_syntax()       # 语法自检
3. trigger_self_restart()  # 重启应用
```

## License

MIT
