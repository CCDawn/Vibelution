import { useEffect, useMemo, useRef, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// Production surface under scene test (real ConversationView, real styles,
// real i18n dictionary — the same modules the shipped bundle executes).
import { dictionary } from "../../../../src/i18n/dictionary";
import { ConversationView } from "../../../../src/components/conversation/ConversationView";
import type { ConversationMessage, SessionTurnItem } from "../../../../src/api/types";

/**
 * Browser runtime scene for the chat stream core upgrade integration:
 * mounts the REAL ConversationView with a deterministic long history, a
 * timer-driven streaming active turn, and a prepend (load-earlier) loader.
 * Served only by this preview vite dev server; never part of web/'s build.
 */

const HISTORY_PAGE = 120;
const TOTAL_HISTORY = 420;

const ANSWER_SAMPLES = [
  [
    "## 结论",
    "",
    "流式渲染已切换到轻解析管线，完成消息保留 **react-markdown** 全量静态渲染。",
    "",
    "| 层 | 方案 | 状态 |",
    "| --- | --- | --- |",
    "| 展示 | react-virtual | 完成 |",
    "| 解析 | 双模 | 完成 |",
    "| 数据 | 三不变量 | 完成 |",
    "",
    "细节包括稳定 key 行高缓存与前插锚定补偿，贴底跟随语义保持不变。",
  ].join("\n"),
  [
    "seq 连续门在会话级 ledger 水位协议下允许同水位合并帧。",
    "",
    "```python",
    "def decide(seq, last):",
    "    if seq <= last:",
    "        return \"drop\"",
    "    if seq <= last + 1:",
    "        return \"apply\"",
    "    return \"hold\"",
    "```",
    "",
    "断档时从 `watermark = last + 1` 单飞恢复，退避封顶 5s。",
  ].join("\n"),
  [
    "**长列表**整段历史虚拟化后，客户端窗口删除，运行中 turn 独立 live-tail 渲染。",
    "",
    "1. 动态测高",
    "2. 稳定 key 行高缓存",
    "3. 前插锚定",
    "",
    "> 引用块：加载更早消息时视口不得跳动。",
  ].join("\n"),
];

function baseItem(turnNo: number, itemNo: number): Omit<SessionTurnItem, "type"> {
  return {
    id: `s1-item-${turnNo}-${itemNo}`,
    itemId: `s1-item-${turnNo}-${itemNo}`,
    version: 3 as const,
    sessionId: "scene-1",
    turnId: `s1-turn-${turnNo}`,
    status: "completed",
    revision: 1,
    sequence: turnNo * 10 + itemNo,
    updatedAt: "2026-09-24T08:00:00Z",
    createdAt: "2026-09-24T08:00:00Z",
  };
}

function buildPage(startTurn: number, endTurn: number): ConversationMessage[] {
  const messages: ConversationMessage[] = [];
  for (let turnNo = startTurn; turnNo < endTurn; turnNo += 1) {
    messages.push({
      id: `s1-user-${turnNo}`,
      role: "user",
      content: `第 ${turnNo} 轮：请继续验证聊天流核心升级的滚动与渲染稳定性，观察虚拟化行数与贴底行为。`,
      timestamp: new Date(Date.UTC(2026, 8, 24, 8, turnNo % 60, 0)).toISOString(),
      turnId: `s1-turn-${turnNo}`,
    });
    messages.push({
      id: `s1-assistant-${turnNo}`,
      role: "assistant",
      turnId: `s1-turn-${turnNo}`,
      status: "completed",
      timestamp: new Date(Date.UTC(2026, 8, 24, 8, turnNo % 60, 30)).toISOString(),
      turnItems: [
        {
          ...baseItem(turnNo, 1),
          type: "agent_message",
          phase: "final_answer",
          text: ANSWER_SAMPLES[turnNo % ANSWER_SAMPLES.length],
          terminal: true,
        } as SessionTurnItem,
      ],
    });
  }
  return messages;
}

function streamingItem(text: string, revision: number): SessionTurnItem {
  return {
    ...baseItem(9999, 1),
    id: "s1-item-live",
    itemId: "s1-item-live",
    turnId: "s1-turn-live",
    status: "running",
    revision,
    type: "agent_message",
    phase: "final_answer",
    text,
  } as SessionTurnItem;
}

const STREAM_CHUNK = "\n\n流式增量继续追加：live 区只做轻量块解析，稳定区保持 memo，表格与围栏由补全器兜底。";

function RuntimeScene() {
  const queryClient = useMemo(
    () => new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    [],
  );
  useEffect(() => {
    queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);
  }, [queryClient]);

  const [messages, setMessages] = useState<ConversationMessage[]>(() => buildPage(TOTAL_HISTORY - 120, TOTAL_HISTORY));
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const streamFrame = useRef(0);

  const hasEarlierMessages = messages.length < TOTAL_HISTORY;

  const activeTurnMessage = useMemo<ConversationMessage | undefined>(() => {
    if (!streaming && !streamingText) {
      return undefined;
    }
    return {
      id: "s1-message-active-live",
      role: "assistant",
      turnId: "s1-turn-live",
      status: "running",
      timestamp: new Date().toISOString(),
      turnItems: [streamingItem(streamingText, streamFrame.current + 1)],
    };
  }, [streaming, streamingText]);

  // Timer-driven stream: ~40 frames of growth, then settles.
  useEffect(() => {
    if (!streaming) {
      return;
    }
    const timer = window.setInterval(() => {
      streamFrame.current += 1;
      setStreamingText((current) => {
        if (streamFrame.current > 40) {
          window.clearInterval(timer);
          setStreaming(false);
          return current;
        }
        return current + STREAM_CHUNK;
      });
    }, 60);
    return () => window.clearInterval(timer);
  }, [streaming]);

  const onLoadEarlierMessages = () => {
    if (loadingEarlier || !hasEarlierMessages) {
      return;
    }
    setLoadingEarlier(true);
    // Async like the real server page fetch; prepend after a beat so the
    // anchor-restore path actually runs.
    window.setTimeout(() => {
      setMessages((current) => {
        const startTurn = TOTAL_HISTORY - current.length / 2;
        const nextStart = Math.max(0, startTurn - HISTORY_PAGE);
        const older = buildPage(nextStart, startTurn);
        return [...older, ...current];
      });
      setLoadingEarlier(false);
    }, 120);
  };

  // Expose scene metrics for the CDP driver.
  useEffect(() => {
    const collect = () => {
      const rows = document.querySelectorAll("[data-conversation-virtual-row]");
      const host = document.querySelector('[data-conversation-virtual-host="1"]');
      const timeline = host?.parentElement?.parentElement;
      const w = window as unknown as Record<string, unknown>;
      w.__scene = {
        rowCount: messages.length,
        mountedRows: rows.length,
        hostHeight: host instanceof HTMLElement ? host.offsetHeight : 0,
        scrollHeight: timeline instanceof HTMLElement ? timeline.scrollHeight : 0,
        scrollTop: timeline instanceof HTMLElement ? timeline.scrollTop : 0,
        clientHeight: timeline instanceof HTMLElement ? timeline.clientHeight : 0,
        streamingTextLength: streamingText.length,
        streamingActive: streaming,
        loadingEarlier,
        hasEarlierMessages,
      };
    };
    collect();
    const id = window.setInterval(collect, 120);
    return () => window.clearInterval(id);
  }, [messages.length, streamingText, streaming, loadingEarlier, hasEarlierMessages]);

  return (
    <QueryClientProvider client={queryClient}>
      <div style={{ display: "flex", height: "100vh", fontFamily: "system-ui, sans-serif" }}>
        <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", padding: 12, gap: 8 }}>
          <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
            <button type="button" data-scene="start-stream" onClick={() => { streamFrame.current = 0; setStreamingText(""); setStreaming(true); }}>
              开始流式
            </button>
            <button type="button" data-scene="scroll-top" onClick={() => {
              const host = document.querySelector('[data-conversation-virtual-host="1"]');
              const timeline = host?.parentElement?.parentElement;
              if (timeline instanceof HTMLElement) timeline.scrollTop = 0;
            }}>
              滚动到顶部
            </button>
            <button type="button" data-scene="scroll-bottom" onClick={() => {
              const host = document.querySelector('[data-conversation-virtual-host="1"]');
              const timeline = host?.parentElement?.parentElement;
              if (timeline instanceof HTMLElement) timeline.scrollTop = timeline.scrollHeight;
            }}>
              回到底部
            </button>
          </div>
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
            <ConversationView
              sessionId="scene-1"
              title="Runtime scene"
              phase="ready"
              messages={messages}
              activeTurnMessage={activeTurnMessage}
              showHeader={false}
              showSessionOverview={false}
              showComposer={false}
              processDisplayMode="trace"
              composerValue=""
              composerPlaceholder="scene"
              composerDisabled={false}
              composerPending={false}
              hasEarlierMessages={hasEarlierMessages}
              earlierMessagesLoading={loadingEarlier}
              onLoadEarlierMessages={onLoadEarlierMessages}
              onComposerChange={() => undefined}
              onSubmit={() => undefined}
              onEditUserMessage={() => undefined}
              defaultFileContext="workspace"
            />
          </div>
        </div>
      </div>
    </QueryClientProvider>
  );
}

export { RuntimeScene };
