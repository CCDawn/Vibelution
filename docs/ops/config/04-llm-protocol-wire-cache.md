# 04 · 协议 / Wire / Prompt Cache

运行时权威细节：[core/llm/PROTOCOL.md](../../../core/llm/PROTOCOL.md)。

## 三层不要混

| 层 | 配置从哪来 | 例子 |
| --- | --- | --- |
| **ModelProtocol** | profile.`protocol` 或 provider.api/kind 推断 | `deepseek_reasoning` `openai_chat_tools` |
| **WireProtocol** | provider.protocols / kind / api / endpoint | `chat_completions` `responses` `anthropic_messages` |
| **profile.transport** | profile 字段 | **仅** `chat_completions` \| `responses` |

`profile.transport` ≠ 完整 Wire 枚举。

## ModelProtocol 速查

| protocol | 对话链 | 要点 |
| --- | --- | --- |
| `openai_chat_tools` | tool_chat | 标准 tools |
| `openai_responses` / `relay_responses` | responses_agent | Responses wire |
| `deepseek_reasoning` | reasoning_chat | reasoning 回传；tool_choice 常 omit |
| `anthropic_chat` / `anthropic_thinking` | tool_chat / reasoning | thinking 参数；wire=anthropic_messages |
| `qwen_openai_compat` | tool_chat | 多 system 折叠 |
| `qwen_thinking_no_prefill` | reasoning_chat | 禁止 assistant prefill |
| `basic_chat_no_tools` | basic_chat | 无 tools |
| `minimax_chat` / `xiaomi_mimo_*` / `llamacpp_*` | 见 PROTOCOL | 兼容差异 |

解析：`core/llm/protocol_resolver.py`。

## Wire 与能否调用

| Wire | 可调用 | 说明 |
| --- | --- | --- |
| `chat_completions` | 是 | 主路径 |
| `responses` | 是 | OpenAI/relay |
| `anthropic_messages` | 是* | LiteLLM 兼容 body，非完整手写 REST |
| `gemini_generate_content` | 是* | 同上 |

\* 见 PROTOCOL.md「Cleared / Residual debt」。

## Prompt Cache 配置

### mode

| mode | 含义 | 适用 |
| --- | --- | --- |
| `disabled` | 去掉 cache_control，不注 key | 调试 |
| `automatic` | 按厂商策略自动 | **默认推荐**（DeepSeek/OpenAI/Anthropic） |
| `explicit_cache_control` | 消息块打 `cache_control` | Qwen / Anthropic 精细控制 |
| `unsupported` | 模型声明不支持；带 control 会拒发 | 特殊模型 |

### 厂商策略（automatic）

| 厂商 | strategy | 请求里会出现 |
| --- | --- | --- |
| DeepSeek | `deepseek_automatic` | **无** key；靠前缀字节匹配 |
| OpenAI / relay / responses | `openai_automatic_key` | `prompt_cache_key`（+ retention） |
| Anthropic | `anthropic_automatic_top_level` | 顶层 `cache_control: {type: ephemeral}` |
| Qwen 等兼容 | `qwen_automatic_key` 等 | 可能被端点忽略 |

### 厂商策略（explicit_cache_control）

| 厂商 | 行为 |
| --- | --- |
| Qwen | 在可选 history 文本块加 ephemeral |
| Anthropic | system + 稳定 history 文本块加 ephemeral |
| 其它 | 通用 explicit（有限） |

### key / retention

- `key`：一般 **留空**，运行时用 session partition（`chat-agent-static-…`）生成。
- `retention`：`in_memory` | `24h` | 空=默认；OpenAI 代际差异见 PROTOCOL.md。

## 缓存要命中，配置之外还要满足

1. **前缀从第 0 token 起相同**（DeepSeek 官网要求）。
2. 系统/Agent 静态前缀稳定。
3. **Turn Status Bar 在消息末尾**（代码已修；勿再改回 user 前）。
4. 工具结果可以追加；**不要在 user 前每步重写可变 system 块**。

## 错误对照

| 日志/现象 | 配置侧 |
| --- | --- |
| `unsupported_wire_protocol` | wire adapter 缺失（现已注册四类）；检查 `protocols.allowed` |
| `prompt_cache_unsupported` | mode=unsupported 却带了 cache_control |
| cache hit 死钉 ~5k | 前缀被中段 volatile 切断（非 mode 写错） |
| Claude 无 cache 字段 | mode 非 automatic/explicit；或走了错误 strategy |

## Agent 最小正确模板

**DeepSeek：**

```toml
[llm.profiles.X.prompt_cache]
mode = "automatic"
```

**OpenAI：**

```toml
[llm.profiles.X]
transport = "chat_completions"  # 或 responses
[llm.profiles.X.prompt_cache]
mode = "automatic"
```

**Anthropic：**

```toml
[llm.providers.anthropic_main]
kind = "anthropic"
driver = "anthropic"
[llm.profiles.X.prompt_cache]
mode = "automatic"   # 顶层 cache_control
# 或 mode = "explicit_cache_control"
```
