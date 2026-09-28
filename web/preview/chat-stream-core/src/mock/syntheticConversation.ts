/**
 * Deterministic synthetic long conversation for the A/B compare view.
 * Seeded PRNG (mulberry32) keeps every run byte-identical: no Math.random,
 * no dates, no network. >= 500 messages mixing user / assistant / tool rows
 * with code blocks, tables, long tool output and Chinese prose.
 */

export type PreviewMessageRole = "user" | "assistant" | "tool";

export type PreviewMessage = {
  id: string;
  role: PreviewMessageRole;
  /** Short header label, e.g. "用户" / "助手" / "工具 · run_tests". */
  roleLabel: string;
  content: string;
};

function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const TOPICS = [
  "虚拟化列表", "流式渲染", "序列投影", "滚动锚定", "markdown 解析",
  "增量协议", "错误恢复", "内存缓存", "布局抖动", "中文排版",
];

const CODE_SNIPPETS = [
  [
    "```ts",
    "export function measureRow(node: HTMLElement): number {",
    "  const style = window.getComputedStyle(node);",
    "  return node.getBoundingClientRect().height + parseFloat(style.marginBottom || '0');",
    "}",
    "```",
  ].join("\n"),
  [
    "```python",
    "def watermark_recovery(last_seq: int, events: list[Event]) -> list[Event]:",
    "    buffered = [e for e in events if e.seq > last_seq]",
    "    return sorted(buffered, key=lambda e: e.seq)",
    "```",
  ].join("\n"),
  [
    "```bash",
    "npx tsc -b --pretty false",
    "npm run test -- --run src/components/conversation",
    "```",
  ].join("\n"),
  [
    "```js",
    "const virtualizer = useVirtualizer({",
    "  count: rows.length,",
    "  getScrollElement: () => viewportRef.current,",
    "  estimateSize: () => 96,",
    "  overscan: 6,",
    "});",
    "```",
  ].join("\n"),
];

const TABLE_SNIPPETS = [
  [
    "| 策略 | 流式中 | 完成后 |",
    "| --- | --- | --- |",
    "| 轻解析 | 开启 | 关闭 |",
    "| 高亮 | 关闭 | 开启 |",
    "| memo | 尾段 | 全文 |",
  ].join("\n"),
  [
    "| 不变量 | 现状 | 目标 |",
    "| --- | --- | --- |",
    "| seq 连续 | 仅丢弃 | 门控 |",
    "| 水位重订阅 | 全量刷新 | 增量恢复 |",
    "| 乐观对账 | turn 结算 | seq 对账 |",
  ].join("\n"),
];

function longToolOutput(rand: () => number, index: number): string {
  const lines = ["$ vitest run --reporter=verbose", ""];
  for (let i = 0; i < 24; i += 1) {
    const suite = TOPICS[Math.floor(rand() * TOPICS.length)] as string;
    const passed = 3 + Math.floor(rand() * 9);
    lines.push(` ✓ src/${suite.replace(/\s/g, "-")}/case-${index}-${i}.test.tsx (${passed} tests) ${Math.floor(rand() * 900 + 60)}ms`);
  }
  lines.push("", ` Test Files  24 passed (24)`, `      Tests  187 passed (187)`, "");
  return lines.join("\n");
}

function assistantAnswer(rand: () => number, index: number): string {
  const topic = TOPICS[Math.floor(rand() * TOPICS.length)] as string;
  const parts: string[] = [];
  parts.push(`### ${topic}方案（第 ${index + 1} 轮）`);
  parts.push("");
  parts.push(`按当前诊断，${topic}的瓶颈主要在重复解析与整段 DOM 常驻。下面的改动把渲染粒度从「整条消息」降到「稳定前缀 + 活跃尾段」，数据层用序列门控兜底。`);
  parts.push("");
  if (index % 3 === 0) {
    parts.push(CODE_SNIPPETS[Math.floor(rand() * CODE_SNIPPETS.length)] as string);
    parts.push("");
  }
  parts.push(`**结论：**${topic}的新方案分三层——展示层虚拟化、解析层双模、投影层不变量；三层互不阻塞，可以按阶段合入。`);
  parts.push("");
  if (index % 4 === 1) {
    parts.push(TABLE_SNIPPETS[Math.floor(rand() * TABLE_SNIPPETS.length)] as string);
    parts.push("");
  }
  if (index % 5 === 2) {
    parts.push("- 展示层：行高缓存 + 动态测高，历史区虚拟化");
    parts.push("- 解析层：流式中只做轻解析，完成后切 static 全量 AST");
    parts.push("- 投影层：seq 连续才应用，断档带水位重订阅");
    parts.push("");
  }
  parts.push(`> 注意：${topic}涉及滚动锚定时，前插消息必须按行键锚定恢复位置，避免视口跳动。`);
  return parts.join("\n");
}

export function buildSyntheticConversation(messageCount = 520): PreviewMessage[] {
  const rand = mulberry32(20260921);
  const messages: PreviewMessage[] = [];
  let turn = 0;
  while (messages.length < messageCount) {
    turn += 1;
    messages.push({
      id: `m${messages.length}`,
      role: "user",
      roleLabel: "用户",
      content: `帮我看一下${TOPICS[Math.floor(rand() * TOPICS.length)] as string}这块，第 ${turn} 轮：现在的实现长会话下会卡，流式的时候还会抖。`,
    });
    if (messages.length >= messageCount) break;
    messages.push({
      id: `m${messages.length}`,
      role: "assistant",
      roleLabel: "助手",
      content: assistantAnswer(rand, turn),
    });
    if (messages.length >= messageCount) break;
    messages.push({
      id: `m${messages.length}`,
      role: "tool",
      roleLabel: `工具 · verify_case_${turn}`,
      content: longToolOutput(rand, turn),
    });
  }
  return messages.slice(0, messageCount);
}

/** The deterministic streaming script used by the stream simulation panel. */
export const STREAM_SCRIPT: string = [
  "### 增量流式渲染的双模设计",
  "",
  "流式期间渲染管线只做轻量工作：不完整语法先补全再解析，高亮与 mermaid 全部关闭。",
  "",
  "```python",
  "def apply_delta(state, delta, seq):",
  "    if seq != state.last_seq + 1:",
  "        return state.hold(delta)  # 断档：带水位恢复",
  "    state.text += delta",
  "    state.last_seq = seq",
  "    return state",
  "```",
  "",
  "完成后切换到 static 模式：整段内容一次性 memo 化，",
  "比较器用引用相等 + FNV 哈希兜底，避免大字符串逐字符比较。",
  "",
  "| 阶段 | 解析 | 高亮 | 备注 |",
  "| --- | --- | --- | --- |",
  "| 流式中 | 轻解析+补全 | 关 | 尾段隔离 |",
  "| 完成 | 全量 AST | 开 | 一次 memo |",
  "",
  "**关键点：** 未闭合的粗体、反引号与围栏必须在解析前补全，否则会出现整屏闪烁。这一段是刻意留给演示的：前文的代码围栏和表格都会经历「从残缺到完整」的过程。",
].join("\n");

export type StreamChunk = { text: string; delayMs: number };

/** Split STREAM_SCRIPT into deterministic chunks, cutting mid-fence/mid-table. */
export function buildStreamChunks(): StreamChunk[] {
  const cutPoints = [
    8, 30, 72, 120, 188, 240, 252, 300, 344, 420,
    468, 520, 588, 640, 700, 764, 820, 900, 964, 1024,
    1100, 1180, STREAM_SCRIPT.length,
  ].filter((point) => point > 0 && point <= STREAM_SCRIPT.length);
  const chunks: StreamChunk[] = [];
  let previous = 0;
  for (const point of cutPoints) {
    if (point <= previous) continue;
    chunks.push({ text: STREAM_SCRIPT.slice(previous, point), delayMs: 110 + (point % 3) * 45 });
    previous = point;
  }
  if (previous < STREAM_SCRIPT.length) {
    chunks.push({ text: STREAM_SCRIPT.slice(previous), delayMs: 120 });
  }
  return chunks;
}
