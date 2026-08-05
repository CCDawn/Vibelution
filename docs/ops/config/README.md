# Operator 配置文档

面向 **人类运维 + 后续 Agent** 的配置真源说明。
实现校验以 `config/models.py` 为准；运行时协议以 `core/llm/PROTOCOL.md` 为准。

## 权威顺序

1. 用户当前明确要求
2. 本目录文档（配置语义）
3. `config/models.py` 字段校验
4. `core/llm/PROTOCOL.md`（协议/缓存运行时）
5. 历史 plan / 截图 / 口头习惯（**无权威**）

## 活跃配置在哪里

| 角色 | 路径 |
| --- | --- |
| **运行时真源** | `%USERPROFILE%\Documents\Vibelution\config\config.toml` |
| 元数据 | 同目录 `config.meta.json` |
| 覆盖 | 环境变量 `VIBELUTION_CONFIG_PATH` / `VIBELUTION_CONFIG_HOME` |
| 仓库根 config | **legacy/template only**，集成时禁止当输入真源 |

启动后用 Launcher / 诊断面板确认解析路径，不要假设固定用户名。

## 配置结构总览

```toml
[llm]                 # schema_version、providers、profiles、角色绑定
[agent]               # Agent 行为相关
[evolution]           # 自进化
[launcher]            # Launcher 控制面
[runtime]             # 运行时能力
[workbench]           # 窗口模式/尺寸/位置
[git]                 # 提交文案模型等
[ui]                  # UI 偏好
[user_profile]       # 用户资料
```

`llm` 是最复杂、最容易配错的子系统：Provider → 钉选模型 → Profile → 协议/Wire → Prompt Cache。

## 禁止事项（Agent 红线）

- 不要改仓库根 `config.toml` 当「生产配置」。
- 不要把密钥明文写进 git 跟踪文件；用 `credential_ref = "env:XXX"`。
- 不要为了「能跑」随手 `prompt_cache.mode = "disabled"` 然后宣称缓存正常。
- 不要混用：`profile.transport`（仅 `chat_completions`|`responses`）与 `WireProtocol`（含 `anthropic_messages` 等）。
- 不要假设 Anthropic 已走完整原生 REST Messages 实现：当前 wire 是 **LiteLLM 兼容 OpenAI 形 body**（见 PROTOCOL.md）。

## 相关

- 索引：[INDEX.md](./INDEX.md)
- 协议运行时：[../../core/llm/PROTOCOL.md](../../../core/llm/PROTOCOL.md)
- 开发标准配置条款：`docs/standards/development-standard.md` § 配置/Launcher
