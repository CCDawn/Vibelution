# Rust 部分替换试验（Pilot）

## 目标

在不重写 Python 编排面的前提下，用 **sidecar CLI（JSON in / JSON out）** 验证高 ROI 边界能否用 Rust 硬化。

## ROI 排序（试验优先级）

| 优先级 | 候选 | ROI 理由 | 风险 | 状态 |
| --- | --- | --- | --- | --- |
| **P0** | LLM usage / cache 归一（Anthropic total + hit rate） | 纯函数、行为对账清晰；修已知与主流不一致；可双实现 parity | 低 | **本轮 pilot** |
| P1 | 路径/工作区 containment（工具写路径是否逃逸 project root） | 安全边界、可单测、热路径 | 中 | 候选下一刀 |
| P2 | Runtime scene / 日志索引 prune（扩展现有 maintenance crate） | 已有 Rust maintenance 先例、IO 密集 | 中 | 已有 `vibelution-maintenance` |
| P3 | 进程/PTY supervisor | 价值高但 Windows 细节多 | 高 | 后置 |
| — | Chat projection / Teams SC / 全 FastAPI | ROI 差 | 极高 | 不做 |

## Pilot 0 设计：`vibelution-usage-normalize`

```text
Python core/llm/usage.py
    │  optional
    ▼
crates/vibelution-usage-normalize  (stdin JSON → stdout JSON)
```

- **输入**：provider raw usage 对象（OpenAI / Anthropic 字段混用）
- **输出**：`inputTokens`, `cachedInputTokens`, `cacheCreationInputTokens`, `uncachedInputTokens`, `cacheHitRate`, `engine`（`rust`|`python`）
- **正确性契约（Anthropic 原生）**：
  - `total_input = cache_read + cache_creation + input_tail`（当 `input_tokens` 仅为 tail 时）
  - `hit = cache_read / total_input`
  - 不得把 `min(read, tail)` 截断成假 100% hit
- **降级**：无二进制或子进程失败时，走 Python 参考实现（同算法）

## 成功标准

1. Python 单测：OpenAI 形 + Anthropic 原生形 + 中继 `prompt_tokens` 形
2. 若本机有 `cargo`：`cargo test` + 与 Python 输出逐字段一致
3. 默认不强制依赖 Rust 构建（CI 仍可只跑 Python）

## 非目标

- 不替换 FastAPI / agent 主循环
- 不引入 PyO3（本轮仅 CLI sidecar，安装与 ABI 成本更低）
