import React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Real production streaming projection, imported read-only.
import { projectStreamingMarkdownBlocks } from "../../../../src/components/conversation/streamingMarkdown";

import { DualModeBadges, DualModeMarkdown } from "../next/DualModeMarkdown";
import { buildStreamChunks } from "../mock/syntheticConversation";

/**
 * Stream simulation panel: a deterministic mock delta stream (timers, no
 * network) feeds two renderers side by side:
 * - left: current production strategy — the real codexStreamController /
 *   projectStreamingMarkdownBlocks stable+live split, live tail re-parsed
 *   through the full react-markdown each frame;
 * - right: proposed Streamdown-pattern dual-mode (repair while streaming,
 *   static memo once done).
 */

type StreamPhase = "idle" | "streaming" | "done";

function useMockStream() {
  const [phase, setPhase] = React.useState<StreamPhase>("idle");
  const [content, setContent] = React.useState("");
  const [currentParseCount, setCurrentParseCount] = React.useState(0);
  const [nextParseCount, setNextParseCount] = React.useState(0);
  const timerRef = React.useRef<number | null>(null);

  const stop = React.useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const start = React.useCallback(() => {
    stop();
    const chunks = buildStreamChunks();
    let index = 0;
    let accumulated = "";
    setContent("");
    setCurrentParseCount(0);
    setNextParseCount(0);
    setPhase("streaming");
    const tick = () => {
      const chunk = chunks[index];
      if (!chunk) {
        setPhase("done");
        return;
      }
      accumulated += chunk.text;
      setContent(accumulated);
      index += 1;
      if (index < chunks.length) {
        timerRef.current = window.setTimeout(tick, chunk.delayMs);
      } else {
        timerRef.current = window.setTimeout(() => setPhase("done"), chunk.delayMs);
      }
    };
    timerRef.current = window.setTimeout(tick, 200);
  }, [stop]);

  React.useEffect(() => stop, [stop]);

  return {
    phase,
    content,
    start,
    stop,
    reset: () => {
      stop();
      setPhase("idle");
      setContent("");
      setCurrentParseCount(0);
      setNextParseCount(0);
    },
    currentParseCount,
    nextParseCount,
    bumpCurrentParse: () => setCurrentParseCount((count) => count + 1),
    bumpNextParse: () => setNextParseCount((count) => count + 1),
  };
}

function PhaseBadge({ phase }: { phase: StreamPhase }) {
  if (phase === "streaming") {
    return <span className="state-badge on">● 流式中</span>;
  }
  if (phase === "done") {
    return <span className="state-badge on">✓ 已完成（切 static）</span>;
  }
  return <span className="state-badge">待开始</span>;
}

export function StreamPanel() {
  const stream = useMockStream();
  const streaming = stream.phase === "streaming";

  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0, gap: 8 }}>
      <div className="control-bar">
        <button className="primary" onClick={stream.start} disabled={stream.phase === "streaming"}>
          ▶ 播放模拟流（确定性 mock）
        </button>
        <button onClick={stream.stop} disabled={stream.phase !== "streaming"}>暂停</button>
        <button onClick={stream.reset}>重置</button>
        <PhaseBadge phase={stream.phase} />
        <span className="panel-note" style={{ margin: 0 }}>
          剧本含一段 python 围栏与表格从残缺到补全；断言点：左栏 live 区每帧全量 react-markdown，右栏流式中补全+轻解析、完成后仅一次 static。
        </span>
      </div>
      <div className="split-grid" style={{ flex: 1, minHeight: 0 }}>
        <div className="stream-card">
          <div className="stream-card-head">
            <h2>现状复刻 · stable + live 双实例</h2>
            <span className="tag">codexStreamController + streamingMarkdown</span>
            <span className="parse-counter">
              live 区解析次数 <b>{stream.currentParseCount}</b>
            </span>
          </div>
          <div className="stream-card-body">
            <div className="md-body">
              {stream.content ? (
                <>
                  <CurrentStrategyStreaming content={stream.content} onParse={stream.bumpCurrentParse} streaming={streaming} />
                  {streaming ? <span className="streaming-caret" /> : null}
                </>
              ) : (
                <span className="panel-note">点击「播放模拟流」开始。</span>
              )}
            </div>
          </div>
        </div>
        <div className="stream-card">
          <div className="stream-card-head">
            <h2>新方案 · 双模 markdown + live-tail</h2>
            <DualModeBadges streaming={streaming} />
            <span className="parse-counter">
              解析次数 <b>{stream.nextParseCount}</b>
              {stream.phase === "done" ? "（static 后不再增长）" : ""}
            </span>
          </div>
          <div className="stream-card-body">
            <div className="md-body">
              {stream.content ? (
                <DualModeMarkdown
                  content={stream.content}
                  streaming={streaming}
                  onParse={stream.bumpNextParse}
                />
              ) : (
                <span className="panel-note">等待开始。</span>
              )}
            </div>
          </div>
        </div>
      </div>
      <div className="proj-card" style={{ flex: "none", maxHeight: 200 }}>
        <h2>说明</h2>
        <p className="panel-note" style={{ margin: 0 }}>
          左栏复刻现状：<b>ConversationStreamingResponseContent</b> 的 stable/live 拆分（真实
          codexStreamController 帧批 drain + streamingMarkdown 的 960 字符 live-tail 上限），live
          区域是独立 markdown 实例，每帧重跑完整 react-markdown；不完整语法靠「留在 live 区」而非解析器修复。
          右栏为 Streamdown 模式（Apache-2.0，zai-org/ZCode 同款用法）：流式中 parseIncompleteMarkdown
          等价补全（关高亮/mermaid），完成后切 static 全量 AST + memo（比较器：引用相等 + FNV 哈希兜底）。
        </p>
      </div>
    </div>
  );
}

/**
 * CURRENT streaming strategy replica: stable/live split with the real
 * projectStreamingMarkdownBlocks (imports the real production module), live
 * tail re-parsed through full react-markdown each frame.
 */
function CurrentStrategyStreaming({ content, onParse, streaming }: {
  content: string;
  onParse: () => void;
  streaming: boolean;
}) {
  const projection = React.useMemo(
    () => projectStreamingMarkdownBlocks(content),
    [content],
  );
  if (!streaming) {
    return <FinalMarkdown content={content} onParse={onParse} />;
  }
  return (
    <>
      {projection.stableText ? (
        <FinalMarkdown content={projection.stableText} onParse={onParse} />
      ) : null}
      {projection.liveText ? (
        <div className="live-tail-region" data-streaming-live-tail="1">
          <FinalMarkdown content={projection.liveText} onParse={onParse} />
        </div>
      ) : null}
    </>
  );
}

const FinalMarkdown = React.memo(
  function FinalMarkdown({ content, onParse }: { content: string; onParse: () => void }) {
    React.useEffect(() => {
      onParse();
    });
    return (
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>{content}</ReactMarkdown>
    );
  },
  (previous, next) => previous.content === next.content,
);
