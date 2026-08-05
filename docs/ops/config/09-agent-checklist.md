# 09 · Agent 配置自检清单

每次改配置交付前过一遍。

## A. 路径与权威

- [ ] 改的是 `Documents\Vibelution\config\config.toml`（或 `VIBELUTION_CONFIG_PATH`）
- [ ] 未把生产配置写进仓库根
- [ ] 密钥仅为 `credential_ref = "env:…"`

## B. Provider

- [ ] `kind` / `driver` / `base_url` 与厂商一致（见 05）
- [ ] `credential_ref` 环境变量在运行进程可见
- [ ] 至少一个 `models.*.upstream_id`

## C. Profile

- [ ] `provider_id` + `model` 匹配钉选
- [ ] `transport` ∈ {`chat_completions`,`responses`}
- [ ] `contract` 与是否 tools/reasoning 一致
- [ ] 角色绑定指向该 profile

## D. 协议与缓存（调用 + 省钱）

- [ ] 需要缓存时 `prompt_cache.mode` 不是 `disabled`
- [ ] DeepSeek → `automatic`（不写 OpenAI key）
- [ ] OpenAI → `automatic`
- [ ] Anthropic → `automatic`（顶层 cache_control）或 `explicit_cache_control`
- [ ] Qwen 兼容 → 优先 `explicit_cache_control`
- [ ] 未把 wire 名误填进 `transport`

## E. 验证命令 / 证据

```text
# 配置校验失败会在启动/加载时暴露；协议可用：
# - 日志 event: conversation.turn.prompt_cache_partition_bound
# - llm.stream.succeeded 的 cachedInputTokens / prompt_cache_hit_tokens
# - 错误：unsupported_wire_protocol / prompt_cache_unsupported / payload_protocol_error
```

- [ ] 启动后能完成至少一轮对话
- [ ] 多轮 tool 时 DeepSeek 的 cached 不再永久钉死在静态头（Status Bar 已在尾部）
- [ ] 需要时 Launcher restart 已执行

## F. 文档

- [ ] 新厂商菜谱已补进 [05](./05-llm-vendor-recipes.md)（若新增厂商）
- [ ] 协议行为变更已核对 [PROTOCOL.md](../../../core/llm/PROTOCOL.md)

## 快速失败对照

| 失败 | 打开 |
| --- | --- |
| 密钥/401 | 02 + env |
| 协议/payload 拒发 | 04 |
| wire 不支持 | 04 + PROTOCOL.md |
| cache 为 0 | 04 + 05 + 前缀是否被 volatile 切断 |
| 前端起不来 | 非 config：`tsc -b` preflight |
