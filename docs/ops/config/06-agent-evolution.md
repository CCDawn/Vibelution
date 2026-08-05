# 06 · Agent 与 Evolution

## `[agent]`

与 Agent 运行策略、工具面相关的产品配置。具体键以当前 `config.toml` 与 `config/models.py` 中 Agent 相关模型为准。

### Agent 配置时注意

- Agent **对话模型**来自 LLM profile 绑定，不在 `[agent]` 里写死 model 字符串。
- 工具是否对模型可见取决于 **工具注册 + 授权**，不单看配置开关。
- 改 Agent 行为后：相关 session 重启或新开对话；必要时 Launcher refresh。

### 推荐排查

1. Agent 目录 / registry 中的 `agentId`、模式（chat / evolution）
2. 绑定的 LLM profile 与 `prompt_cache`
3. 工具策略 `toolPolicy`（maxCallsPerTurn 等）
4. runtime status 注入：`runtimeStatus.enabled`（Status Bar；已放消息尾部）

## `[evolution]`

```toml
[evolution]
intake_mode = "auto"   # 示例：以实际枚举为准
```

自进化、监督进化相关开关。改动属 **HIGH_RISK** 范畴时走开发标准完整流程。

### Agent 清单

- [ ] 未把密钥写进 agent 元数据
- [ ] evolution 模式与工具授权匹配
- [ ] 对话 profile 的 protocol/cache 已按 04/05 配置
