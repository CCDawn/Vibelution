import { readFileSync } from "node:fs";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatNextStateSignalSummary, ConversationMessage, SessionTurnError } from "../../api/types";
import conversationViewSource from "./ConversationView.tsx?raw";
import streamingRevealStateSource from "./streamingRevealState.ts?raw";
import {
  buildStreamingTimelineScrollSignal,
  buildTimelineScrollSignal,
  COMPOSER_SESSION_REFERENCE_MIME,
  ConversationView,
  type ConversationProcessDisplayMode,
  extractComposerImageDropFiles,
  extractComposerSessionReferenceDrop,
  hasComposerImageDragPayload,
  safeConversationMarkdownUrl,
  shouldShowNextStateSignalInConversation,
} from "./ConversationView";
import { isAgentInboxMessage } from "./messageSections";

const conversationViewStylesSource = readFileSync(new URL("./ConversationView.module.css", import.meta.url), "utf-8");

function cssRule(selector: string) {
  const start = conversationViewStylesSource.indexOf(`${selector} {`);
  if (start === -1) {
    return "";
  }
  const end = conversationViewStylesSource.indexOf("\n}", start);
  return end === -1 ? conversationViewStylesSource.slice(start) : conversationViewStylesSource.slice(start, end + 2);
}

function renderConversation(
  messages: ConversationMessage[],
  options: {
    editingMessageId?: string;
    editUserMessageDisabled?: boolean;
    composerValue?: string;
    density?: "default" | "compact";
    nextStateSignals?: ChatNextStateSignalSummary[];
    userAvatarPreset?: string;
    userAvatarImageUrl?: string;
    userDisplayName?: string;
    assistantDisplayName?: string;
    assistantAvatarImageUrl?: string;
    assistantAvatarFallback?: string;
    resolveTurnAvatar?: (message: ConversationMessage) => { imageUrl?: string; fallback: string } | undefined;
    composerAttachments?: Array<{
      id: string;
      filename: string;
      previewUrl: string;
      sizeBytes: number;
      contentType: string;
    }>;
    composerReferences?: Array<{
      referenceId: string;
      kind: string;
      sessionId: string;
      title?: string;
      agentDisplayName?: string;
    }>;
    composerDisabled?: boolean;
    composerActionMode?: "send" | "stop";
    composerActionDisabled?: boolean;
    composerError?: string;
    composerGuidance?: string;
    turnError?: SessionTurnError | null;
    onSafeGuidance?: () => void;
    onInterruptGuidance?: () => void;
    showMentalSnapshots?: boolean;
    showComposer?: boolean;
    processDisplayMode?: ConversationProcessDisplayMode;
    useDefaultProcessDisplayMode?: boolean;
    activeTurnMessage?: ConversationMessage;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  const processDisplayProps = options.useDefaultProcessDisplayMode
    ? {}
    : { processDisplayMode: options.processDisplayMode ?? ("trace" as ConversationProcessDisplayMode) };
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={messages}
        activeTurnMessage={options.activeTurnMessage}
        density={options.density}
        showHeader={false}
        showSessionOverview={false}
        showMentalSnapshots={options.showMentalSnapshots}
        showComposer={options.showComposer}
        {...processDisplayProps}
        composerValue={options.composerValue ?? ""}
        composerPlaceholder="Type"
        composerDisabled={options.composerDisabled ?? false}
        composerActionMode={options.composerActionMode}
        composerActionDisabled={options.composerActionDisabled}
        composerPending={false}
        composerError={options.composerError}
        composerGuidance={options.composerGuidance}
        turnError={options.turnError}
        composerAttachments={options.composerAttachments}
        composerReferences={options.composerReferences}
        nextStateSignals={options.nextStateSignals}
        userAvatarPreset={options.userAvatarPreset}
        userAvatarImageUrl={options.userAvatarImageUrl}
        userDisplayName={options.userDisplayName}
        assistantDisplayName={options.assistantDisplayName}
        assistantAvatarImageUrl={options.assistantAvatarImageUrl}
        assistantAvatarFallback={options.assistantAvatarFallback}
        resolveTurnAvatar={options.resolveTurnAvatar}
        editingMessageId={options.editingMessageId}
        editUserMessageDisabled={options.editUserMessageDisabled}
        editUserMessageLabel="Edit and resend"
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onSafeGuidance={options.onSafeGuidance}
        onInterruptGuidance={options.onInterruptGuidance}
        onEditUserMessage={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView VUI control contract", () => {
  it("routes conversation controls through VUI primitives", () => {
    expect(conversationViewSource).toContain('from "../vui"');
    expect(conversationViewSource).toContain("<VButton");
    expect(conversationViewSource).not.toMatch(/<button\b/);
  });
});

describe("ConversationView edit resend affordance", () => {
  it("does not force-collapse thinking sections when streaming settles", () => {
    expect(conversationViewSource).not.toContain("previousStreamingRef");
    expect(conversationViewSource).not.toContain("thought: false,\n          mental: false,\n          tools: false");
  });

  it("freezes first-seen expansion defaults so SSE status changes do not fight the UI", () => {
    expect(conversationViewSource).toContain("defaultExpansionRef");
    expect(conversationViewSource).toContain("messageDefaults[section] === undefined");
    expect(conversationViewSource).toContain("return messageDefaults[section]");
  });

  it("renders streaming assistant markdown progressively instead of waiting for the final answer", () => {
    expect(conversationViewSource).toContain("function renderStreamingResponseText(content: string)");
    expect(conversationViewSource).toContain("<StreamingResponseContent content={content} renderBlock={renderMarkdownBlock} />");
    expect(conversationViewSource).toContain("projectStreamingMarkdownBlocks");
    expect(conversationViewSource).toContain("nextStreamingRevealLength");
    expect(conversationViewSource).toContain("type StreamingRevealState");
    expect(conversationViewSource).toContain("appendStableText");
    expect(streamingRevealStateSource).toContain("STREAMING_RESPONSE_REVEAL_MAX_CHARS");
    expect(streamingRevealStateSource).toContain("STREAMING_RESPONSE_CATCH_UP_BACKLOG_CHARS");
    expect(streamingRevealStateSource).toContain("stableText");
    expect(streamingRevealStateSource).toContain("revealTail");
    expect(conversationViewSource).toContain("requestAnimationFrame");
    expect(conversationViewSource).toContain("setVisibleContent");
    expect(conversationViewSource).toContain("const isResponseStreaming = Boolean(message.streaming) && showResponseBlock");
    expect(conversationViewSource).toContain("showResponseBlock && !isStreamingStatusPlaceholder && responseExpanded && !isResponseStreaming");
    expect(conversationViewSource).toContain("? renderStreamingResponseText(message.content)");
    expect(conversationViewStylesSource).toContain(".streamingResponseText");
  });

  it("does not reintroduce a fixed-rate typewriter buffer for live assistant deltas", () => {
    expect(conversationViewSource).not.toContain("STREAMING_REVEAL_INTERVAL_MS");
    expect(conversationViewSource).not.toContain("STREAMING_REVEAL_FAST_FORWARD_BACKLOG_CHARS");
    expect(conversationViewSource).not.toContain("setTimeout(pump");
    expect(conversationViewSource).not.toContain("advanceStreamingRevealText");
    expect(conversationViewSource).not.toContain("setInterval");
  });

  it("keeps answer and process toggles as borderless text controls", () => {
    const responseToggleRule = cssRule(".responseToggle");
    const responseToggleHoverRule = cssRule(".responseToggle:hover");
    const processToggleRule = cssRule(".answerOnlyProcessToggle");
    const processToggleHoverRule = cssRule(".answerOnlyProcessToggle:hover");

    expect(responseToggleRule).toContain("border: 0");
    expect(responseToggleRule).toContain("background: transparent");
    expect(responseToggleRule).toContain("padding: 0");
    expect(responseToggleHoverRule).not.toContain("background");
    expect(responseToggleHoverRule).not.toContain("border-color");
    expect(processToggleRule).toContain("border: 0");
    expect(processToggleRule).toContain("background: transparent");
    expect(processToggleRule).toContain("padding: 0");
    expect(processToggleHoverRule).not.toContain("background");
    expect(processToggleHoverRule).not.toContain("border-color");
  });

  it("uses readable contrast for compact conversation metadata and toggles", () => {
    const readableRules = [
      ".turnMeta",
      ".turnMetaActions",
      ".turnIconButton",
      ".operationSummaryPreview",
      ".operationSummaryCount",
      ".answerOnlyProcessToggle",
      ".answerOnlyProcessTitle",
      ".answerOnlyProcessMeta",
      ".answerOnlyProcessPreview",
      ".timelineCellHeader",
      ".timelineCellPreview",
      ".timelineCellMeta",
      ".responseToggle",
    ];

    for (const selector of readableRules) {
      const rule = cssRule(selector);
      expect(rule).not.toBe("");
      expect(rule).not.toMatch(/color:\s*var\(--fg-tertiary\)/);
      expect(rule).not.toMatch(/color:\s*color-mix\(in srgb,\s*var\(--fg-tertiary\)[^;]*transparent\)/);
    }

    expect(cssRule(".responseToggle")).toContain("color: var(--fg-secondary)");
    expect(cssRule(".answerOnlyProcessToggle")).toContain("color: var(--fg-secondary)");
  });

  it("folds streaming request placeholders into the process strip", () => {
    expect(conversationViewSource).toContain("function isStreamingStatusPlaceholderContent(content: string)");
    expect(conversationViewSource).toContain("const isStreamingStatusPlaceholder = Boolean(message.streaming)");
    expect(conversationViewSource).toContain("compactStreamingStatusPlaceholder(message.content)");
    expect(conversationViewSource).toContain("showResponseBlock && !isStreamingStatusPlaceholder");
    expect(conversationViewStylesSource).toContain("grid-template-columns: 14px auto auto minmax(0, 1fr) 14px");
  });

  it("caches response and markdown parsing so repeated expands avoid synchronous reparsing", () => {
    expect(conversationViewSource).toContain("const responseSegmentCacheRef = useRef<Map<string, ResponseSegment[]>>(new Map())");
    expect(conversationViewSource).toContain("const markdownBlockCacheRef = useRef<Map<string, MarkdownBlock[]>>(new Map())");
    expect(conversationViewSource).toContain("function getCachedResponseSegments(content: string)");
    expect(conversationViewSource).toContain("function getCachedMarkdownBlocks(content: string)");
    expect(conversationViewSource).toContain("trimOldestCacheEntries(responseSegmentCacheRef.current, RESPONSE_PARSE_CACHE_LIMIT)");
    expect(conversationViewSource).toContain("trimOldestCacheEntries(markdownBlockCacheRef.current, MARKDOWN_PARSE_CACHE_LIMIT)");
    expect(conversationViewSource).toContain("const responseSegments = showResponseBlock && !isStreamingStatusPlaceholder && responseExpanded && !isResponseStreaming");
    expect(conversationViewSource).toContain("? getCachedResponseSegments(message.content)");
    expect(conversationViewSource).toContain("const blocks = getCachedMarkdownBlocks(content)");
    expect(conversationViewSource).toContain("const prewarmMessages = timelineMessages");
    expect(conversationViewSource).toContain("window.setTimeout(prewarmNext, 48)");
  });

  it("keeps tool detail expansion work off collapsed renders", () => {
    expect(conversationViewSource).toContain("function DeferredOperationDetails");
    expect(conversationViewSource).toContain("const deferredExpanded = useDeferredValue(expanded)");
    expect(conversationViewSource).toContain("const detailRows = deferredExpanded ? buildDetailRows(operation) : []");
    expect(conversationViewSource).toContain("const canExpandDetails = hasOperationDetails(operation)");
    expect(conversationViewSource).toContain("<DeferredOperationDetails");
    expect(conversationViewSource).toContain("buildDetailRows={operationDetailRows}");
    expect(conversationViewSource).not.toContain("const detailRows = detailsExpanded ? operationDetailRows(operation) : []");
  });

  it("uses lightweight tool signals instead of full detail payloads for scroll tracking", () => {
    expect(conversationViewSource).toContain("function lightweightJsonSignal(value: unknown)");
    expect(conversationViewSource).toContain("function lightweightTextSignal(value: unknown)");
    expect(conversationViewSource).toContain("lightweightJsonSignal(toolCall.arguments ?? {})");
    expect(conversationViewSource).toContain("lightweightTextSignal(toolCall.resultPreview ?? \"\")");
    expect(conversationViewSource).not.toContain("JSON.stringify(toolCall.arguments ?? {})");
  });

  it("keeps active-turn projection and history expansion anchors outside the render hot path", () => {
    expect(conversationViewSource).toContain("projectConversationTimelineMessages");
    expect(conversationViewSource).toContain("const activeTimelineProjection = useMemo");
    expect(conversationViewSource).toContain("activeTimelineProjection.messages");
    expect(conversationViewSource).toContain("activeTimelineProjection.streamingMessages");
    expect(conversationViewSource).toContain("activeTimelineProjection.rowIdentities");
    expect(conversationViewSource).toContain("captureTimelineRowKeyAnchor");
    expect(conversationViewSource).toContain("restoreTimelineRowKeyAnchor");
    expect(conversationViewSource).not.toContain("buildConversationTimelineRowIdentities(activeTimelineMessages)");
  });

  it("defaults to answer-only process display while keeping details expandable", () => {
    const html = renderConversation(
      [
        {
          id: "message-answer-only",
          role: "assistant",
          content: "最终回答已经完成。",
          timestamp: "2026-06-21T10:00:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "thought",
              status: "done",
              summary: "先分析缓存链路",
              resultPreview: "先分析缓存链路",
            },
            {
              sequence: 2,
              kind: "tool",
              status: "done",
              name: "read_file",
              summary: "opened session_service.py",
              relatedThoughtSequence: 1,
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("过程");
    expect(html).toContain("思考过程 1");
    expect(html).toContain("工具调用 1");
    expect(html).toContain("最终回答已经完成。");
    expect(html.indexOf("answerOnlyProcessGroup")).toBeLessThan(html.indexOf("responseSection"));
    expect(html).toContain('title="展开执行明细"');
    expect(html).not.toContain("先分析缓存链路");
    expect(html).not.toContain("opened session_service.py");
  });

  it("shows recent assistant answers by default in answer-only display", () => {
    const html = renderConversation(
      [
        {
          id: "assistant-answer-1",
          role: "assistant",
          content: "第一轮回答正文。",
          timestamp: "2026-06-27T10:00:00Z",
        },
        {
          id: "assistant-answer-2",
          role: "assistant",
          content: "第二轮回答正文。",
          timestamp: "2026-06-27T10:01:00Z",
        },
        {
          id: "assistant-answer-3",
          role: "assistant",
          content: "第三轮回答正文。",
          timestamp: "2026-06-27T10:02:00Z",
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("第一轮回答正文。");
    expect(html).toContain("第二轮回答正文。");
    expect(html).toContain("第三轮回答正文。");
  });

  it("surfaces the current running process before the live answer in the default display", () => {
    const html = renderConversation(
      [
        {
          id: "message-running-process",
          role: "assistant",
          content: "正在整理回答。",
          timestamp: "2026-06-21T10:00:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "thought",
              status: "done",
              summary: "已确定检查范围",
            },
            {
              sequence: 2,
              kind: "tool",
              status: "running",
              name: "read_file",
              summary: "正在读取 ConversationView 渲染链路",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("正在整理回答。");
    expect(html).toContain("正在读取 ConversationView 渲染链路");
    expect(html.indexOf("answerOnlyProcessGroup")).toBeLessThan(html.indexOf("responseSection"));
    expect(html).not.toContain("已确定检查范围");
  });

  it("keeps the answer block visible in trace display when process timeline items exist", () => {
    const html = renderConversation(
      [
        {
          id: "message-trace-answer",
          role: "assistant",
          content: "这是最终回答。",
          timestamp: "2026-06-26T08:00:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "thought",
              status: "done",
              summary: "已完成分析",
            },
          ],
        },
      ],
      { processDisplayMode: "trace" },
    );

    expect(html).toContain("已完成分析");
    expect(html).toContain("这是最终回答。");
    expect(html.indexOf("conversationCellTimeline")).toBeLessThan(html.indexOf("responseSection"));
  });

  it("renders the active assistant turn after committed history without requiring it in messages", () => {
    const html = renderConversation(
      [
        {
          id: "message-committed",
          role: "assistant",
          content: "上一轮正式回答。",
          timestamp: "2026-06-26T08:00:00Z",
        },
      ],
      {
        useDefaultProcessDisplayMode: true,
        activeTurnMessage: {
          id: "session-1-message-active-turn-1",
          role: "assistant",
          content: "当前回答正在流式显示。",
          timestamp: "2026-06-26T08:01:00Z",
          streaming: true,
          streamStage: "responding",
          metadata: {
            kind: "session_active_turn_layer",
            turnId: "turn-1",
          },
        },
      },
    );

    expect(html).toContain("上一轮正式回答。");
    expect(html).toContain("当前回答正在流式显示。");
    expect(html.indexOf("上一轮正式回答。")).toBeLessThan(html.indexOf("当前回答正在流式显示。"));
  });

  it("drops the active assistant turn once the same turn has a committed answer", () => {
    const html = renderConversation(
      [
        {
          id: "message-committed-turn-1",
          role: "assistant",
          content: "最终回答已经落库。",
          timestamp: "2026-06-26T08:01:02Z",
          metadata: {
            turnId: "turn-1",
          },
        },
      ],
      {
        useDefaultProcessDisplayMode: true,
        activeTurnMessage: {
          id: "session-1-message-active-turn-1",
          role: "assistant",
          content: "临时活动层旧尾巴。",
          timestamp: "2026-06-26T08:01:01Z",
          streaming: true,
          streamStage: "responding",
          metadata: {
            kind: "session_active_turn_layer",
            turnId: "turn-1",
          },
        },
      },
    );

    expect(html).toContain("最终回答已经落库。");
    expect(html).not.toContain("临时活动层旧尾巴。");
    expect(html.match(/<article class="_assistantTurn_/g)?.length ?? 0).toBe(1);
  });

  it("merges a same-turn live overlay into the active assistant turn instead of rendering duplicates", () => {
    const html = renderConversation(
      [
        {
          id: "session-1-message-live-turn-1",
          role: "assistant",
          content: "正在唤起对话 agent...\n正在绑定 Agent 实例、私人工作区、记忆根和工具工作区。",
          timestamp: "2026-06-26T10:30:00Z",
          streaming: true,
          streamStage: "agent_prepare",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "agent_prepare",
              summary: "正在绑定 Agent",
            },
          ],
          metadata: {
            kind: "session_live_overlay",
            turnId: "turn-1",
          },
        },
      ],
      {
        useDefaultProcessDisplayMode: true,
        activeTurnMessage: {
          id: "session-1-message-active-turn-1",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T10:30:01Z",
          streaming: true,
          streamStage: "model_request",
          feedbackEvents: [
            {
              sequence: 2,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: "正在请求模型，等待首个响应片段。",
            },
          ],
          metadata: {
            kind: "session_active_turn_layer",
            turnId: "turn-1",
          },
        },
      },
    );

    expect(html).toContain("正在请求");
    expect(html).not.toContain("正在唤起对话 agent");
    expect(html).not.toContain("正在绑定 Agent 实例");
    expect(html.match(/assistantTurn/g)?.length ?? 0).toBe(1);
  });

  it("renders stable row and part identities for the active assistant turn", () => {
    const html = renderConversation(
      [],
      {
        useDefaultProcessDisplayMode: true,
        activeTurnMessage: {
          id: "session-1-message-active-turn-1",
          role: "assistant",
          content: "当前回答正在流式显示。",
          timestamp: "2026-06-26T10:30:01Z",
          streaming: true,
          streamStage: "responding",
          metadata: {
            kind: "session_active_turn_layer",
            turnId: "turn-identity",
          },
        },
      },
    );

    expect(html).toContain('data-conversation-row-key="assistant-turn:turn-identity"');
    expect(html).toContain('data-conversation-message-key="assistant-turn:turn-identity:message"');
    expect(html).toContain('data-conversation-part-key="assistant-turn:turn-identity:answer"');
  });

  it("coalesces same-tool feedback updates when merging live overlay with the active turn", () => {
    const html = renderConversation(
      [
        {
          id: "session-1-message-live-turn-1",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T10:30:00Z",
          streaming: true,
          streamStage: "tooling",
          feedbackEvents: [
            {
              sequence: 0,
              kind: "tool",
              status: "running",
              name: "source_collection_context_tool",
              summary: "正在读取受控资料上下文",
            },
          ],
          metadata: {
            kind: "session_live_overlay",
            turnId: "turn-1",
          },
        },
      ],
      {
        activeTurnMessage: {
          id: "session-1-message-active-turn-1",
          role: "assistant",
          content: "上下文已读取，正在整理回答。",
          timestamp: "2026-06-26T10:30:01Z",
          streaming: true,
          streamStage: "responding",
          feedbackEvents: [
            {
              sequence: 0,
              kind: "tool",
              status: "done",
              name: "source_collection_context_tool",
              summary: "上下文已读取",
              resultPreview: "candidatePage.returned=19",
            },
          ],
          metadata: {
            kind: "session_active_turn_layer",
            turnId: "turn-1",
          },
        },
      },
    );

    expect(html.match(/assistantTurn/g)?.length ?? 0).toBe(1);
    expect(html.match(/source_collection_context_tool/g)?.length ?? 0).toBe(1);
    expect(html).toContain("上下文已读取");
    expect(html).not.toContain("正在读取受控资料上下文");
  });

  it("projects consecutive same-turn process-only tool messages into one compact assistant turn", () => {
    const html = renderConversation(
      [
        {
          id: "message-tool-1",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T14:56:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "tool",
              status: "done",
              name: "apply_diff_edit_tool",
              summary: "[编辑] 成功修改 config/public_config.py 共处理 1 个块",
              durationSeconds: 0.8,
            },
          ],
          metadata: { turnId: "turn-edit" },
        },
        {
          id: "message-tool-2",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T14:56:01Z",
          feedbackEvents: [
            {
              sequence: 2,
              kind: "tool",
              status: "done",
              name: "apply_diff_edit_tool",
              summary: "[编辑] 成功修改 config/workbench.py 共处理 1 个块",
              durationSeconds: 0.6,
            },
          ],
          metadata: { turnId: "turn-edit" },
        },
        {
          id: "message-tool-3",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T14:56:02Z",
          feedbackEvents: [
            {
              sequence: 3,
              kind: "tool",
              status: "done",
              name: "apply_diff_edit_tool",
              summary: "[编辑] 成功修改 config/settings.py 共处理 1 个块",
              durationSeconds: 0.9,
            },
          ],
          metadata: { turnId: "turn-edit" },
        },
        {
          id: "message-tool-4",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T14:56:03Z",
          feedbackEvents: [
            {
              sequence: 4,
              kind: "tool",
              status: "done",
              name: "apply_diff_edit_tool",
              summary: "[编辑] 成功修改 scripts/vibelution_desktop_entry.py 共处理 1 个块",
              durationSeconds: 0.6,
            },
          ],
          metadata: { turnId: "turn-edit" },
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html.match(/<article class="_assistantTurn_/g)?.length ?? 0).toBe(1);
    expect(html).toContain("工具调用 4");
    expect(html).not.toContain("工具调用 1");
  });

  it("does not repeat the tool-call label inside an expanded tool-only process packet", () => {
    const html = renderConversation(
      [
        {
          id: "message-failed-tool-only",
          role: "assistant",
          content: "",
          timestamp: "2026-06-26T14:57:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "tool",
              status: "failed",
              name: "apply_diff_edit_tool",
              summary: "[编辑] 修改 config/public_config.py 失败",
              error: "patch context not found",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html.match(/工具调用/g)?.length ?? 0).toBe(1);
    expect(html).toContain("apply_diff_edit_tool");
    expect(html).toContain("[编辑] 修改 config/public_config.py 失败");
  });

  it("keeps active streaming scroll signals on a small streaming-only tail", () => {
    expect(conversationViewSource).toContain("projectConversationTimelineMessages({ timelineMessages, activeTurnMessage })");
    expect(conversationViewSource).toContain("const streamingTimelineMessages = activeTimelineProjection.streamingMessages");
    expect(conversationViewSource).toContain("buildStreamingTimelineScrollSignal(streamingTimelineMessages)");
    expect(conversationViewSource).not.toContain("activeTimelineMessages.filter((message) => message.streaming)");
    expect(conversationViewSource).not.toContain("activeTimelineSignalMessages");
  });

  it("captures a scroll anchor before revealing earlier messages", () => {
    expect(conversationViewSource).toContain("function showEarlierMessages()");
    expect(conversationViewSource).toContain("captureTimelineRowKeyAnchor(timelineRef.current)");
    expect(conversationViewSource).toContain("restoreTimelineRowKeyAnchor(timelineRef.current, anchor)");
    expect(conversationViewSource).toContain("onClick={showEarlierMessages}");
    expect(conversationViewSource).not.toContain("onClick={() => setAllMessagesVisible(true)}");
  });

  it("can render the opt-in compact workbench density", () => {
    const html = renderConversation([], { density: "compact" });

    expect(html).toContain("surfaceCompact");
  });

  it("keeps execution tool-call content borderless", () => {
    const traceSummaryRule = cssRule(".executionTraceGroup .operationSummary");
    const reactSummaryRule = cssRule(".reActOperationSummary");
    const reactSummaryHoverRule = cssRule(".reActOperationSummary:hover");
    const reactResultRule = cssRule(".reActResultItem");
    const operationDetailsRule = cssRule(".operationDetails");
    const operationItemRule = cssRule(".operationItem");
    const reactGroupRule = cssRule(".reActOperationGroup");
    const reactThoughtRule = cssRule(".reActThoughtText");
    const timelineThoughtRule = cssRule(".timelineThoughtText");
    const reactResultToggleRule = cssRule(".reActResultToggle");

    expect(traceSummaryRule).toContain("border: 0");
    expect(reactSummaryRule).toContain("border: 0");
    expect(reactSummaryRule).toContain("display: inline-grid");
    expect(reactSummaryRule).toContain("width: fit-content");
    expect(reactSummaryRule).not.toContain("minmax(0, 1fr)");
    expect(reactSummaryHoverRule).not.toContain("border-color");
    expect(reactResultRule).toContain("border: 0");
    expect(reactResultRule).toContain("background: transparent");
    expect(reactGroupRule).toContain("border-left: 0");
    expect(reactThoughtRule).toContain("border-left: 0");
    expect(reactThoughtRule).toContain("background: transparent");
    expect(operationDetailsRule).toContain("border: 0");
    expect(operationItemRule).toContain("width: min(100%, 860px)");
    expect(operationItemRule).toContain("grid-template-columns: 22px minmax(0, 1fr) auto auto 16px");
    expect(timelineThoughtRule).toContain("border: 0");
    expect(timelineThoughtRule).toContain("background: transparent");
    expect(reactResultToggleRule).toContain("border: 0");
  });

  it("keeps streamed execution rows readable instead of squeezed into micro columns", () => {
    const operationItemRule = cssRule(".operationItem");
    const operationItemToolRule = cssRule(".operationItemTool");
    const operationTextRule = cssRule(".operationText");
    const statusBodyRule = cssRule(".responseSegment_status .messageBody");

    expect(conversationViewStylesSource).not.toMatch(/font-size:\s*0\.(?:[0-6]\d?|7(?:0|1)?)rem/);
    expect(operationItemRule).not.toContain("width: fit-content");
    expect(operationItemRule).not.toContain("max-content");
    expect(operationItemToolRule).not.toContain("max-content");
    expect(operationTextRule).toContain("max-width: 100%");
    expect(statusBodyRule).toContain("white-space: pre-wrap");
    expect(statusBodyRule).toContain("overflow-wrap: anywhere");
  });

  it("can render a read-only transcript without the composer", () => {
    const html = renderConversation(
      [
        {
          id: "message-1",
          role: "assistant",
          content: "supervised transcript output",
          timestamp: "2026-06-16T00:00:00Z",
        },
      ],
      { showComposer: false },
    );

    expect(html).toContain("supervised transcript output");
    expect(html).not.toContain("<textarea");
    expect(html).not.toContain("placeholder=\"Type\"");
  });

  it("renders composer session reference chips", () => {
    const html = renderConversation([], {
      composerReferences: [
        {
          referenceId: "session:ref-1",
          kind: "session",
          sessionId: "ref-1",
          title: "顾云舒上下文",
          agentDisplayName: "顾云舒",
        },
      ],
    });

    expect(html).toContain("顾云舒上下文");
    expect(html).toContain("顾云舒");
  });

  it("extracts structured session reference drag payloads", () => {
    const payload = {
      referenceId: "session:ref-1",
      kind: "session",
      sessionId: "ref-1",
      title: "Reference session",
    };

    const reference = extractComposerSessionReferenceDrop({
      types: [COMPOSER_SESSION_REFERENCE_MIME],
      getData: (format) => (format === COMPOSER_SESSION_REFERENCE_MIME ? JSON.stringify(payload) : ""),
    });

    expect(reference?.sessionId).toBe("ref-1");
    expect(reference?.referenceId).toBe("session:ref-1");
  });

  it("uses the configured user avatar preset for user turns", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Use my profile",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain(">C</div>");
    expect(html).toContain("Vibe Owner");
  });

  it("renders assistant turns with the configured agent avatar image", () => {
    const html = renderConversation(
      [
        {
          id: "message-assistant",
          role: "assistant",
          content: "Ready to help.",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        assistantDisplayName: "白予安",
        assistantAvatarImageUrl: "/api/agents/avatar-image/01-chat-companion.png",
        assistantAvatarFallback: "11",
      },
    );

    expect(html).toContain('src="/api/agents/avatar-image/01-chat-companion.png"');
    expect(html).toContain("白予安");
  });

  it("compacts a process-only prefix while keeping the following answer in the same avatar group", () => {
    const html = renderConversation(
      [
        {
          id: "assistant-process-prepare",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:00:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "agent_prepare",
              summary: "正在绑定 Agent",
            },
          ],
          metadata: {
            turnId: "turn-avatar-group",
          },
        },
        {
          id: "assistant-process-tool",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:00:04Z",
          feedbackEvents: [
            {
              sequence: 2,
              kind: "tool",
              status: "done",
              name: "source_collection_context_tool",
              summary: "读取受控资料上下文",
            },
          ],
          metadata: {
            turnId: "turn-avatar-group",
          },
        },
        {
          id: "assistant-process-answer",
          role: "assistant",
          content: "上下文已读取，继续整理结果。",
          timestamp: "2026-06-27T01:00:08Z",
          feedbackEvents: [
            {
              sequence: 3,
              kind: "thought",
              status: "done",
              summary: "整理结果",
            },
          ],
          metadata: {
            turnId: "turn-avatar-group",
          },
        },
      ],
      {
        useDefaultProcessDisplayMode: true,
        assistantDisplayName: "周南栀",
        assistantAvatarImageUrl: "/api/agents/avatar-image/agent-zhounanzhi.png",
        assistantAvatarFallback: "周",
      },
    );

    expect(html.match(/src="\/api\/agents\/avatar-image\/agent-zhounanzhi\.png"/g)?.length ?? 0).toBe(1);
    expect(html.match(/周南栀/g)?.length ?? 0).toBe(1);
    expect(html.match(/<article class="_assistantTurn_/g)?.length ?? 0).toBe(1);
    expect(html.match(/assistantTurnContinuation/g)?.length ?? 0).toBe(0);
    expect(html.indexOf("answerOnlyProcessGroup")).toBeLessThan(html.indexOf("responseSection"));
    expect(html).toContain("上下文已读取，继续整理结果。");
  });

  it("keeps the settled answer visible after projecting same-turn process packets", () => {
    const html = renderConversation(
      [
        {
          id: "assistant-settled-process-prepare",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:00:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "done",
              name: "agent_prepare",
              summary: "已绑定 Agent",
            },
          ],
          metadata: {
            turnId: "turn-settled-answer",
          },
        },
        {
          id: "assistant-settled-process-tool",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:00:04Z",
          feedbackEvents: [
            {
              sequence: 2,
              kind: "tool",
              status: "done",
              name: "source_collection_context_tool",
              summary: "读取受控资料上下文",
            },
          ],
          metadata: {
            turnId: "turn-settled-answer",
          },
        },
        {
          id: "assistant-settled-answer",
          role: "assistant",
          content: "这是最终回答，默认应该直接可见。",
          timestamp: "2026-06-27T01:00:08Z",
          metadata: {
            turnId: "turn-settled-answer",
          },
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html.match(/<article class="_assistantTurn_/g)?.length ?? 0).toBe(1);
    expect(html).toContain("这是最终回答，默认应该直接可见。");
  });

  it("starts a new assistant avatar group after a user turn", () => {
    const html = renderConversation(
      [
        {
          id: "assistant-process-before-user",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:00:00Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "tool",
              status: "done",
              name: "read_file",
              summary: "读取上下文",
            },
          ],
        },
        {
          id: "user-break",
          role: "user",
          content: "继续",
          timestamp: "2026-06-27T01:01:00Z",
        },
        {
          id: "assistant-process-after-user",
          role: "assistant",
          content: "",
          timestamp: "2026-06-27T01:01:05Z",
          feedbackEvents: [
            {
              sequence: 1,
              kind: "tool",
              status: "done",
              name: "read_file",
              summary: "读取下一轮上下文",
            },
          ],
        },
      ],
      {
        useDefaultProcessDisplayMode: true,
        assistantDisplayName: "周南栀",
        assistantAvatarImageUrl: "/api/agents/avatar-image/agent-zhounanzhi.png",
        assistantAvatarFallback: "周",
      },
    );

    expect(html.match(/src="\/api\/agents\/avatar-image\/agent-zhounanzhi\.png"/g)?.length ?? 0).toBe(2);
    expect(html.match(/assistantTurnContinuation/g)?.length ?? 0).toBe(0);
  });

  it("falls back to assistant initials when no avatar image is configured", () => {
    const html = renderConversation(
      [
        {
          id: "message-assistant",
          role: "assistant",
          content: "Ready to help.",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        assistantDisplayName: "白予安",
        assistantAvatarFallback: "11",
      },
    );

    expect(html).toContain(">11</div>");
  });

  it("renders agent inbox turns with the resolved source agent avatar", () => {
    const html = renderConversation(
      [
        {
          id: "agent-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n请从组织设计角度回复。",
          timestamp: "2026-05-29T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            sourceAgentCode: "A011",
            sourceAgentName: "夏予安",
          },
        },
      ],
      {
        resolveTurnAvatar: (message) => {
          if (!isAgentInboxMessage(message)) {
            return undefined;
          }
          return {
            imageUrl: "/api/agents/avatar-image/11-white-guardian.png",
            fallback: "11",
          };
        },
      },
    );

    expect(html).toContain('src="/api/agents/avatar-image/11-white-guardian.png"');
    expect(html).toContain("Agent 私信 · A011 · 夏予安");
  });

  it("renders Agent inbox messages as inbound private messages instead of operator turns", () => {
    const html = renderConversation(
      [
        {
          id: "agent-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A011 · 夏予安\n\n消息内容:\n请从组织设计角度回复。",
          timestamp: "2026-05-29T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            sourceAgentCode: "A011",
            sourceAgentName: "夏予安",
          },
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain("agentInboxTurn");
    expect(html).toContain("Agent 私信 · A011 · 夏予安");
    expect(html).toContain("私信内容");
    expect(html).toContain('aria-expanded="false"');
    expect(html).toContain("请从组织设计角度回复");
    expect(html).not.toContain("Vibe Owner");
    expect(html).not.toContain("aria-label=\"Edit and resend\"");
    expect(html).not.toContain("消息内容:");
  });

  it("renders research organization intent and wake chips on Agent inbox messages", () => {
    const html = renderConversation(
      [
        {
          id: "research-org-inbox",
          role: "user",
          content: "[Agent 私信]\n来源 Agent: A014 · 能力管家\n\n消息内容:\n权限审查已完成。",
          timestamp: "2026-05-30T14:13:33Z",
          metadata: {
            kind: "agent_inbox_message",
            inboxKind: "research_org_report",
            sourceAgentCode: "A014",
            sourceAgentName: "能力管家",
            researchOrgIntent: "status_report",
            researchOrgMessageType: "report",
            researchOrgDeliveryMode: "private",
            wakeStatus: "not_requested",
          },
        },
      ],
      { userAvatarPreset: "codex", userDisplayName: "Vibe Owner" },
    );

    expect(html).toContain("科研组织消息标签");
    expect(html).toContain("intent: status report");
    expect(html).toContain("type: report");
    expect(html).toContain("delivery: private");
    expect(html).toContain("wake: not requested");
    expect(html).toContain("Agent 私信 · A014 · 能力管家");
  });

  it("keeps completed feedback timelines collapsed without step counters by default", () => {
    const feedbackEvents = Array.from({ length: 40 }, (_, index) => ({
      sequence: index + 1,
      kind: "tool" as const,
      status: "done",
      name: `tool_${index + 1}`,
      summary: `step ${index + 1}`,
    }));
    const html = renderConversation([
      {
        id: "assistant-feedback-heavy",
        role: "assistant",
        content: "",
        timestamp: "2026-05-22T00:00:00Z",
        feedbackEvents,
      },
    ]);

    expect(html).toContain("已运行 40 条命令");
    expect(html).not.toContain("40 步");
    expect(html).not.toContain("40/40");
    expect(html).not.toContain("+33");
    expect(html).not.toContain("tool_40");
    expect(html).not.toContain("已折叠更早 4 步执行记录");
    expect(html).not.toContain("step 5");
  });

  it("hides completed execution rail details until the trace is expanded", () => {
    const repeatedCommandEvents = Array.from({ length: 8 }, (_, index) => ({
      sequence: index + 1,
      kind: "tool" as const,
      status: "done",
      name: "cli_tool",
      summary: `命令 ${index + 1}`,
    }));
    const html = renderConversation([
      {
        id: "assistant-feedback-repeated-command",
        role: "assistant",
        content: "",
        timestamp: "2026-05-22T00:00:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "done",
            name: "context_prepare",
            summary: "准备上下文",
          },
          ...repeatedCommandEvents,
        ],
      },
    ]);

    expect(html).toContain("已运行 8 条命令");
    expect(html).not.toContain("+");
    expect(html).not.toContain("9 步");
    expect(html).not.toContain("9/9");
    expect(html).not.toContain("准备上下文");
    expect(html).not.toContain("命令 5");
    expect(html.match(/title="命令 · 已完成"/g)?.length ?? 0).toBe(0);
  });

  it("keeps noisy completed command output out of the expanded ReAct result body", () => {
    const html = renderConversation([
      {
        id: "assistant-noisy-command-output",
        role: "assistant",
        content: "",
        timestamp: "2026-05-22T00:00:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "running",
            summary: "检查缓存命中实现",
            resultPreview: "检查缓存命中实现",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "cli_tool",
            summary: "读取缓存代码",
            resultPreview: [
              "def _context_segment(",
              "    key: str,",
              "    block: str,",
              "):",
              "    return hashlib.sha256(block.encode()).hexdigest()",
            ].join("\n"),
            relatedThoughtSequence: 1,
          },
          {
            sequence: 3,
            kind: "tool",
            status: "running",
            name: "grep_search_tool",
            summary: "继续定位缓存统计",
            relatedThoughtSequence: 1,
          },
        ],
      },
    ]);

    expect(html).toContain("检查缓存命中实现");
    expect(html).toContain("读取缓存代码");
    expect(html).toContain("继续定位缓存统计");
    expect(html).not.toContain("return hashlib.sha256");
  });

  it("expands failed execution traces while keeping the real failure visible in the summary", () => {
    const html = renderConversation([
      {
        id: "assistant-feedback-synthetic-failures",
        role: "assistant",
        content: "",
        timestamp: "2026-05-22T00:00:00Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "failed",
            name: "context_prepare",
            summary: "正在准备对话上下文",
          },
          {
            sequence: 2,
            kind: "status",
            status: "failed",
            name: "agent_prepare",
            summary: "正在唤起对话 agent",
          },
          {
            sequence: 3,
            kind: "status",
            status: "failed",
            name: "model_request",
            summary: "正在请求模型",
          },
          {
            sequence: 4,
            kind: "tool",
            status: "done",
            name: "cli_tool",
            summary: "git status",
          },
          {
            sequence: 5,
            kind: "tool",
            status: "failed",
            name: "cli_tool",
            summary: "[超时] cli_tool 执行超时",
            error: "[超时] cli_tool 执行超时",
          },
        ],
      },
    ]);

    expect(html).toContain("执行失败");
    expect(html).toContain("命令");
    expect(html).not.toContain("工具调用");
    expect(html).not.toContain("结果</");
    expect(html).not.toContain("4/5");
    expect(html).not.toContain("准备上下文");
    expect(html).not.toContain("绑定 Agent");
    expect(html).not.toContain("请求模型");
    expect(html).toContain("[超时] cli_tool 执行超时");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("已折叠更早");
  });

  it("renders group-room transcripts as sync records instead of assistant answers", () => {
    const html = renderConversation([
      {
        id: "group-transcript",
        role: "assistant",
        content: [
          "[群聊同步]",
          "群聊: 科研团队 团队群聊",
          "议题: 同步研究方向",
          "",
          "你的发言:",
          "- 本轮你没有发言。",
          "",
          "其他 Agent 发言:",
          "- A012: 建议优先药物-靶点预测。",
        ].join("\n"),
        timestamp: "2026-05-29T14:08:04Z",
        metadata: {
          kind: "group_room_transcript",
          sourceRoomTitle: "科研团队 团队群聊",
        },
      },
    ]);

    expect(html).toContain("groupTranscriptTurn");
    expect(html).toContain("群聊同步记录 · 科研团队 团队群聊");
    expect(html).toContain("建议优先药物-靶点预测");
    expect(html).not.toContain("回答</span>");
  });

  it("does not render runtime recovery notices as assistant replies", () => {
    const html = renderConversation([
      {
        id: "runtime-notice",
        role: "assistant",
        content: "上一轮运行已被中断，当前会话已恢复为可继续状态。",
        timestamp: "2026-05-29T10:15:27Z",
      },
      {
        id: "assistant-answer",
        role: "assistant",
        content: "我已经恢复上下文，继续检查日志。",
        timestamp: "2026-05-29T10:16:32Z",
      },
    ]);

    expect(html).not.toContain("上一轮运行已被中断");
    expect(html).toContain("我已经恢复上下文，继续检查日志。");
  });

  it("renders generated-image markdown as an inline preview instead of raw syntax", () => {
    const html = renderConversation([
      {
        id: "assistant-image-markdown",
        role: "assistant",
        content: [
          "海报生成完成！",
          "",
          "### AI 特色海报",
          "",
          "![AI 特色海报](/api/sessions/session-b/artifacts/image2-demo.png?download=1)",
          "",
          "| 元素 | 含义 |",
          "|------|------|",
          "| AI 芯片 | 算力之源 |",
          "",
          "下载链接：[点击下载](/api/sessions/session-b/artifacts/image2-demo.png?download=1)",
        ].join("\n"),
        timestamp: "2026-05-29T11:16:08Z",
      },
    ]);

    expect(html).toContain('src="/api/sessions/session-b/artifacts/image2-demo.png"');
    expect(html).toContain('href="/api/sessions/session-b/artifacts/image2-demo.png?download=1"');
    expect(html).toContain('aria-label="预览图片"');
    expect(html).toContain("<table");
    expect(html).toContain("AI 芯片");
    expect(html).not.toContain("![AI 特色海报]");
    expect(html).not.toContain("[点击下载]");
  });

  it("keeps wide markdown tables within the conversation content width", () => {
    const html = renderConversation([
      {
        id: "assistant-wide-table",
        role: "assistant",
        content: [
          "二、已启用的可选组件（本轮已激活）",
          "",
          "| 组件 | 来源 | 内容 |",
          "|---|---|---|",
          "| CODEBASE_MAP | `workspace/prompts/CODEBASE_MAP.md` + `core/prompt_manager/codebase_map_builder.py` | 项目代码骨架、测试覆盖、根据工作区自动生成 |",
          "| RUNTIME_LOG_INDEX | `core/runtime_manager/scene_logging.py` 生成 | 最近运行和错误数据索引 |",
        ].join("\n"),
        timestamp: "2026-06-17T11:32:00Z",
      },
    ]);

    expect(html).toContain("markdownBodyWithTable");
    expect(html).toContain("markdownTableWrap");
    expect(html).toContain("workspace/prompts/CODEBASE_MAP.md");
    expect(conversationViewStylesSource).not.toContain(":has(.markdownTableWrap)");
    expect(cssRule(".markdownBodyWithTable")).toContain("max-width: 100%");
    expect(cssRule(".markdownTable")).toContain("table-layout: fixed");
    expect(cssRule(".markdownTable .inlineCode")).toContain("white-space: normal");
  });

  it("suppresses a duplicate generated-image markdown preview when an artifact already rendered it", () => {
    const html = renderConversation([
      {
        id: "message-image-artifact",
        role: "assistant",
        content: "已生成图片。",
        timestamp: "2026-05-29T11:16:06Z",
        metadata: {
          kind: "image2_generation",
          status: "succeeded",
          prompt: "AI 特色海报",
          artifactId: "image2-demo.png",
          imageUrl: "/api/sessions/session-b/artifacts/image2-demo.png",
          downloadUrl: "/api/sessions/session-b/artifacts/image2-demo.png?download=1",
        },
      },
      {
        id: "message-image-answer",
        role: "assistant",
        content: [
          "海报生成完成！",
          "",
          "![AI 特色海报](/api/sessions/session-b/artifacts/image2-demo.png?download=1)",
          "",
          "下载链接：[点击下载](/api/sessions/session-b/artifacts/image2-demo.png?download=1)",
        ].join("\n"),
        timestamp: "2026-05-29T11:16:08Z",
      },
    ]);

    expect(html.match(/src="\/api\/sessions\/session-b\/artifacts\/image2-demo\.png"/g)?.length).toBe(1);
    expect(html).toContain("海报生成完成");
    expect(html).toContain("点击下载");
    expect(html).not.toContain("![AI 特色海报]");
  });

  it("prefers the configured user avatar image for user turns", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Use my local avatar",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        userAvatarPreset: "codex",
        userAvatarImageUrl: "/api/config/avatar-image/avatar-test.png",
        userDisplayName: "Vibe Owner",
      },
    );

    expect(html).toContain('src="/api/config/avatar-image/avatar-test.png"');
    expect(html).not.toContain(">C</div>");
  });

  it("renders edit controls for user messages only", () => {
    const html = renderConversation([
      {
        id: "message-user",
        role: "user",
        content: "Original prompt",
        timestamp: "2026-05-22T00:00:00Z",
      },
      {
        id: "message-assistant",
        role: "assistant",
        content: "Answer",
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html.match(/aria-label="Edit and resend"/g)?.length).toBe(1);
    expect(html).toContain("Original prompt");
    expect(html).toContain("Answer");
  });

  it("keeps the composer writable while a running turn hides explanatory guidance and keeps stop actions", () => {
    const html = renderConversation([], {
      composerValue: "下一句先写在这里",
      composerDisabled: true,
      composerActionMode: "stop",
      composerActionDisabled: false,
      composerGuidance: "当前轮仍在运行。安全引导会记录到会话上下文；打断引导会先记录再请求停止当前轮。",
      onSafeGuidance: () => undefined,
      onInterruptGuidance: () => undefined,
    });

    expect(html).toContain("下一句先写在这里");
    expect(html).not.toContain("当前轮仍在运行");
    expect(html).not.toContain("打断引导");
    expect(html).toContain('aria-label="安全引导"');
    expect(html).not.toContain('aria-label="打断引导"');
    expect(html).toContain('aria-label="终止"');
    expect(html).toContain("composerRoundButtonPrimary");
    expect(html).toContain("stopButton");
    const textarea = html.match(/<textarea[^>]*>/)?.[0] ?? "";
    expect(textarea).not.toContain("disabled");
  });

  it("keeps the running composer stop-only until guidance text exists", () => {
    const html = renderConversation([], {
      composerValue: "",
      composerDisabled: true,
      composerActionMode: "stop",
      composerActionDisabled: false,
      composerGuidance: "当前轮仍在运行。安全引导会记录到会话上下文；打断引导会先记录再请求停止当前轮。",
      onSafeGuidance: () => undefined,
      onInterruptGuidance: () => undefined,
    });

    expect(html).not.toContain("当前轮仍在运行");
    expect(html).not.toContain("打断引导");
    expect(html).not.toContain('aria-label="安全引导"');
    expect(html).toContain('aria-label="终止"');
    expect(html.match(/composerRoundButton/g)?.length).toBe(1);
  });

  it("renders edit controls only for the latest user message", () => {
    const html = renderConversation([
      {
        id: "message-user-1",
        role: "user",
        content: "First prompt",
        timestamp: "2026-05-22T00:00:00Z",
      },
      {
        id: "message-assistant-1",
        role: "assistant",
        content: "First answer",
        timestamp: "2026-05-22T00:01:00Z",
      },
      {
        id: "message-user-2",
        role: "user",
        content: "Second prompt",
        timestamp: "2026-05-22T00:02:00Z",
      },
    ]);

    expect(html.match(/aria-label="Edit and resend"/g)?.length).toBe(1);
    expect(html).toContain("Second prompt");
    expect(html).toContain("First prompt");
  });

  it("keeps the response toggle visible even when a message has no tool block", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: "Answer",
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain('aria-expanded="true"');
    expect(html).toContain("回答");
    expect(html).toContain("Answer");
  });

  it("renders image2 artifact messages with a message-local download action", () => {
    const html = renderConversation([
      {
        id: "message-image",
        role: "assistant",
        content: "已生成图片。",
        timestamp: "2026-05-22T00:01:00Z",
        metadata: {
          kind: "image2_generation",
          status: "succeeded",
          prompt: "一间雨夜里的工作室",
          artifactId: "image2-test.png",
          imageUrl: "/api/sessions/session-1/artifacts/image2-test.png",
          downloadUrl: "/api/sessions/session-1/artifacts/image2-test.png?download=1",
          size: "1024x1024",
          quality: "auto",
          model: "gpt-image-1.5",
        },
      },
    ]);

    expect(html).toContain('src="/api/sessions/session-1/artifacts/image2-test.png"');
    expect(html).toContain('href="/api/sessions/session-1/artifacts/image2-test.png?download=1"');
    expect(html).toContain('download="image2-test.png"');
    expect(html).toContain('aria-label="预览图片"');
    expect(html).toContain("下载图片");
    expect(html).toContain("一间雨夜里的工作室");
  });

  it("renders user image attachments and composer image chips", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "看看这张图",
          timestamp: "2026-05-22T00:00:00Z",
          attachments: [
            {
              artifactId: "user-image-test.png",
              filename: "sketch.png",
              url: "/api/sessions/session-1/artifacts/user-image-test.png",
              imageUrl: "/api/sessions/session-1/artifacts/user-image-test.png",
              downloadUrl: "/api/sessions/session-1/artifacts/user-image-test.png?download=1",
              contentType: "image/png",
              sizeBytes: 128,
              kind: "user_image",
              status: "ready",
            },
          ],
        },
      ],
      {
        composerAttachments: [
          {
            id: "pending-image",
            filename: "pending.png",
            previewUrl: "blob:pending-image",
            sizeBytes: 256,
            contentType: "image/png",
          },
        ],
      },
    );

    expect(html).toContain('src="/api/sessions/session-1/artifacts/user-image-test.png"');
    expect(html).toContain("sketch.png");
    expect(html).toContain("pending.png");
    expect(html).toContain("blob:pending-image");
  });

  it("filters composer drag payloads down to image files", () => {
    const png = { name: "sketch.png", type: "image/png" } as File;
    const text = { name: "notes.txt", type: "text/plain" } as File;

    expect(extractComposerImageDropFiles({ files: [png, text] })).toEqual([png]);
    expect(
      hasComposerImageDragPayload({
        items: [
          { kind: "file", type: "text/plain" } as DataTransferItem,
          { kind: "file", type: "image/webp" } as DataTransferItem,
        ],
      }),
    ).toBe(true);
    expect(hasComposerImageDragPayload({ files: [text] })).toBe(false);
  });

  it("renders assistant responses as semantic labeled blocks", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: [
          "已继续完成并提交。",
          "",
          "根因已经收口：任务管理工具不应算作有效推进。",
          "",
          "已提交：",
          "",
          "8697ecf fix(chat): keep bookkeeping guard resumable",
          "",
          "验证已跑：",
          "",
          "```text",
          "101 passed, 245 deselected",
          "```",
        ].join("\n"),
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("状态");
    expect(html).toContain("responseSegment_status");
    expect(html).toContain("提交");
    expect(html).toContain("验证");
    expect(html).toContain("8697ecf fix(chat): keep bookkeeping guard resumable");
    expect(html).toContain("101 passed, 245 deselected");
    expect(html).not.toContain("```text");
  });

  it("keeps historical assistant responses collapsed while preserving latest and streaming responses", () => {
    const html = renderConversation([
      {
        id: "message-older-assistant",
        role: "assistant",
        content: "OLDER_HEAVY_ASSISTANT_RESPONSE_SHOULD_NOT_RENDER_BY_DEFAULT",
        timestamp: "2026-05-22T00:00:00Z",
      },
      {
        id: "message-old-assistant",
        role: "assistant",
        content: "OLD_RECENT_ASSISTANT_RESPONSE_STAYS_VISIBLE",
        timestamp: "2026-05-22T00:01:00Z",
      },
      {
        id: "message-streaming-assistant",
        role: "assistant",
        content: "STREAMING_ASSISTANT_RESPONSE_STAYS_VISIBLE",
        timestamp: "2026-05-22T00:02:00Z",
        streaming: true,
      },
      {
        id: "message-latest-assistant",
        role: "assistant",
        content: "LATEST_ASSISTANT_RESPONSE_STAYS_VISIBLE",
        timestamp: "2026-05-22T00:03:00Z",
      },
    ]);

    expect(html).toContain('aria-expanded="false"');
    expect(html).not.toContain("OLDER_HEAVY_ASSISTANT_RESPONSE_SHOULD_NOT_RENDER_BY_DEFAULT");
    expect(html).toContain("OLD_RECENT_ASSISTANT_RESPONSE_STAYS_VISIBLE");
    expect(html).toContain("STREAMING_ASSISTANT_RESPONSE_STAYS_VISIBLE");
    expect(html).toContain("LATEST_ASSISTANT_RESPONSE_STAYS_VISIBLE");
  });

  it("renders streaming headings lists and open code fences as components", () => {
    const html = renderConversation([
      {
        id: "message-streaming-markdown",
        role: "assistant",
        content: [
          "## 实时标题",
          "",
          "- **第一项**：`alpha`",
          "- 第二项",
          "",
          "```ts",
          "const value = 1;",
          "return value;",
        ].join("\n"),
        timestamp: "2026-05-22T00:02:00Z",
        streaming: true,
      },
    ]);

    expect(html).toContain("markdownHeading2");
    expect(html).toContain("实时标题");
    expect(html).toContain("<ul");
    expect(html).toContain("inlineStrong");
    expect(html).toContain("inlineCode");
    expect(html).toContain("responseSegmentPre");
    expect(html).toContain("const value = 1;");
    expect(html).not.toContain("## 实时标题");
    expect(html).not.toContain("```ts");
  });

  it("renders streaming markdown tables once the header and separator are visible", () => {
    const html = renderConversation([
      {
        id: "message-streaming-table",
        role: "assistant",
        content: [
          "| 指标 | 数值 |",
          "| --- | --- |",
          "| 缓存 | 98% |",
        ].join("\n"),
        timestamp: "2026-05-22T00:02:00Z",
        streaming: true,
      },
    ]);

    expect(html).toContain("markdownTable");
    expect(html).toContain("<table");
    expect(html).toContain("<th");
    expect(html).toContain("<td");
    expect(html).toContain("缓存");
    expect(html).toContain("98%");
    expect(html).not.toContain("| --- | --- |");
  });

  it("renders only the latest message window by default for long conversations", () => {
    const messages = Array.from({ length: 18 }, (_, index) => ({
      id: `message-${index + 1}`,
      role: index % 2 === 0 ? "user" : "assistant",
      content: `MESSAGE_${index + 1}_CONTENT`,
      timestamp: "2026-05-22T00:01:00Z",
    })) satisfies ConversationMessage[];

    const html = renderConversation(messages);

    expect(html).toContain("显示更早 4 条消息");
    expect(html).not.toContain("MESSAGE_1_CONTENT");
    expect(html).not.toContain("MESSAGE_4_CONTENT");
    expect(html).toContain("MESSAGE_5_CONTENT");
    expect(html).toContain("MESSAGE_18_CONTENT");
  });

  it("renders inline code and simple lists inside semantic response blocks", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: [
          "根因：`task_create_tool` 和 `task_update_tool` 被当成真实推进。",
          "",
          "改动文件：",
          "",
          "- web/src/components/conversation/ConversationView.tsx",
          "- web/src/components/conversation/messageResponseSegments.ts",
        ].join("\n"),
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("inlineCode");
    expect(html).toContain("task_create_tool");
    expect(html).not.toContain("`task_create_tool`");
    expect(html).toContain("<ul");
    expect(html).toContain("ConversationView.tsx");
  });

  it("renders inline bold markers inside list and paragraph content", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: [
          "1. **工具权限清单**：确认工具和 Agent 管理的边界。",
          "2. __风险等级__：保持可读但不过度抢眼。",
          "",
          "- **整体风险**：高",
          "",
          "结论：**需要在对话框内渲染 Markdown 强调**。",
        ].join("\n"),
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("inlineStrong");
    expect(html).toContain("<strong");
    expect(html).toContain("工具权限清单</strong>");
    expect(html).toContain("风险等级</strong>");
    expect(html).toContain("整体风险</strong>");
    expect(html).toContain("需要在对话框内渲染 Markdown 强调</strong>");
    expect(html).not.toContain("**工具权限清单**");
    expect(html).not.toContain("__风险等级__");
  });

  it("renders inline code nested inside bold markdown content", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: "**我当前使用的模型档案 `primary` 不支持图像输入。**",
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("inlineStrong");
    expect(html).toContain("inlineCode");
    expect(html).toContain("我当前使用的模型档案");
    expect(html).toContain("primary");
    expect(html).not.toContain("**我当前使用的模型档案");
    expect(html).not.toContain("输入。**");
  });

  it("renders markdown inside multiline log response segments", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: [
          "日志",
          "",
          "## 需要的决策",
          "此方案由**CEO夏予安**审阅并确认。确认后，我将：",
          "1. 准备并提交最终的工具权限配置提案（使用 `agent_tool_permission_request_tool`）。",
          "2. 所有变更将记录在审计日志中。",
        ].join("\n"),
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("日志");
    expect(html).toContain("markdownHeading");
    expect(html).toContain(">需要的决策</h3>");
    expect(html).toContain("<ol");
    expect(html).toContain("inlineStrong");
    expect(html).toContain("inlineCode");
    expect(html).not.toContain("## 需要的决策");
    expect(html).not.toContain("**CEO夏予安**");
  });

  it("renders common markdown blocks without exposing heading markers", () => {
    const html = renderConversation([
      {
        id: "message-assistant",
        role: "assistant",
        content: [
          "### Python 编译检查通过",
          "",
          "执行：",
          "",
          "```bash",
          "python -m py_compile core/web/services/runtime_scene_service.py",
          "```",
          "",
          "结果：",
          "",
          "- 通过",
          "- 无输出",
          "",
          "---",
          "",
          "## 未完成但已明确原因的验证",
        ].join("\n"),
        timestamp: "2026-05-22T00:01:00Z",
      },
    ]);

    expect(html).toContain("markdownHeading");
    expect(html).toContain(">Python 编译检查通过</h4>");
    expect(html).toContain("<ul");
    expect(html).toContain("通过");
    expect(html).toContain("markdownDivider");
    expect(html).toContain(">未完成但已明确原因的验证</h3>");
    expect(html).not.toContain("### Python 编译检查通过");
    expect(html).not.toContain("## 未完成但已明确原因的验证");
    expect(html).not.toContain("```bash");
  });

  it("renders markdown in user messages with the same safe renderer", () => {
    const html = renderConversation([
      {
        id: "message-user",
        role: "user",
        content: [
          "### 我的目标",
          "",
          "- 修复显示",
          "- 保持安全",
        ].join("\n"),
        timestamp: "2026-05-22T00:00:00Z",
      },
    ]);

    expect(html).toContain("markdownHeading");
    expect(html).toContain(">我的目标</h4>");
    expect(html).toContain("<ul");
    expect(html).not.toContain("### 我的目标");
  });

  it("marks the active edit target and disables edit controls while busy", () => {
    const html = renderConversation(
      [
        {
          id: "message-user",
          role: "user",
          content: "Original prompt",
          timestamp: "2026-05-22T00:00:00Z",
        },
      ],
      {
        editingMessageId: "message-user",
        editUserMessageDisabled: true,
        composerValue: "Original prompt",
      },
    );

    expect(html).toContain('aria-pressed="true"');
    expect(html).toContain("disabled");
    expect(html).toContain("Original prompt");
    expect(html).toContain("编辑消息");
  });

  it("does not render the mental-model option in the composer", () => {
    const html = renderConversation([]);

    expect(html).not.toContain("下轮启用心智模型");
    expect(html).not.toContain("发送选项");
  });

  it("does not render next-state control signals inside the conversation body", () => {
    const html = renderConversation(
      [
        {
          id: "message-assistant",
          role: "assistant",
          content: "Visible assistant answer",
          timestamp: "2026-05-22T00:01:00Z",
        },
      ],
      {
        nextStateSignals: [
          {
            signalId: "chat-signal-1",
            sessionId: "session-1",
            turnId: "turn-1",
            source: "runtime",
            kind: "provider_failure",
            polarity: "negative",
            mode: "evaluative",
            relatedEventCode: "conversation.turn_circuit_breaker",
            createdAt: "2026-05-22T00:01:03Z",
            summary: "Provider failed after one ReAct pass.",
          },
        ],
      },
    );

    expect(html).not.toContain("最近控制信号");
    expect(html).not.toContain("Provider failed after one ReAct pass.");
    expect(html).toContain("Visible assistant answer");
  });

  it("renders turn errors as timeline notices instead of assistant replies", () => {
    const html = renderConversation([
      {
        id: "message-turn-error",
        role: "assistant",
        content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
        timestamp: "2026-05-22T00:01:00Z",
        thought: "The generation failed with a 502 upstream error.",
        toolCalls: [{ name: "image2_generate_tool", status: "done", summary: "failed" }],
        metadata: {
          kind: "turn_error",
          errorType: "RuntimeError",
          providerFailure: true,
          reasonCode: "rate_limited",
          reasonSummary: "provider 正在限流",
          reasonDetail: "group requests-per-minute limit exceeded",
          httpStatus: 429,
          provider: "anthropic",
          providerHost: "www.atpify.cn",
          providerErrorType: "rate_limit_exceeded",
          providerErrorMessage: "group requests-per-minute limit exceeded",
          model: "claude-opus-4-7",
        },
      },
    ]);

    expect(html).toContain("turnErrorNotice");
    expect(html).toContain("运行提示");
    expect(html).toContain("RuntimeError");
    expect(html).toContain("模型服务上游暂时失败");
    expect(html).toContain("原因");
    expect(html).toContain("provider 正在限流");
    expect(html).toContain("详情");
    expect(html).toContain("group requests-per-minute limit exceeded");
    expect(html).toContain("状态码");
    expect(html).toContain("429");
    expect(html).toContain("rate_limit_exceeded");
    expect(html).toContain("www.atpify.cn");
    expect(html).toContain("claude-opus-4-7");
    expect(html).toContain("rate_limited");
    expect(html).toContain("assistantTurn");
    expect(html).toContain("思考过程");
    expect(html).toContain("工具调用");
    expect(html).toContain("The generation failed with a 502 upstream error.");
    expect(html).not.toContain("回答");
  });

  it("does not duplicate a persisted turn-error message with the current turn error banner", () => {
    const html = renderConversation(
      [
        {
          id: "message-turn-error",
          role: "assistant",
          content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
          timestamp: "2026-05-22T00:01:00Z",
          metadata: {
            kind: "turn_error",
            errorType: "provider_protocol_error",
          },
        },
      ],
      {
        turnError: {
          message: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
          errorType: "provider_protocol_error",
          httpStatus: 503,
          provider: "anthropic",
          providerHost: "www.atpify.cn",
          providerErrorType: "api_error",
          providerErrorMessage: "No available accounts: no available accounts",
          model: "claude-opus-4-7",
          recoverable: true,
          timestamp: "2026-05-22T00:01:00Z",
          turnId: "turn-1",
        },
      },
    );

    expect(html).toContain("turnErrorNotice");
    expect(html).not.toContain("turnErrorText");
  });

  it("renders current turn error provider diagnostics with HTTP status", () => {
    const html = renderConversation([], {
      turnError: {
        message: "模型服务上游暂时失败，本轮没有完成。",
        errorType: "provider_upstream_error",
        reasonCode: "upstream_unavailable",
        reasonSummary: "provider 上游服务不可用或网关失败",
        reasonDetail: "No available accounts: no available accounts",
        httpStatus: 503,
        provider: "anthropic",
        providerHost: "www.atpify.cn",
        providerErrorType: "api_error",
        providerErrorMessage: "No available accounts: no available accounts",
        model: "claude-opus-4-7",
        recoverable: true,
        timestamp: "2026-05-22T00:01:00Z",
        turnId: "turn-1",
      },
    });

    expect(html).toContain("turnErrorText");
    expect(html).toContain("状态码: 503");
    expect(html).toContain("类型: api_error");
    expect(html).toContain("通道: anthropic · www.atpify.cn");
    expect(html).toContain("模型: claude-opus-4-7");
  });

  it("renders legacy provider-failure summaries as a single timeline notice", () => {
    const failureText = "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志；可以稍后直接重试或发送“继续”。";
    const html = renderConversation([
      {
        id: "message-image2-failed",
        role: "assistant",
        content: failureText,
        timestamp: "2026-05-22T00:01:00Z",
        toolCalls: [{ name: "image2_generate_tool", status: "done", summary: "failed" }],
        metadata: {
          kind: "image2_generation",
          status: "failed",
          errorType: "RuntimeError",
        },
      },
      {
        id: "message-provider-summary",
        role: "assistant",
        content: failureText,
        timestamp: "2026-05-22T00:01:03Z",
        thought: "The generation failed with a 502 upstream error.",
        toolCalls: [{ name: "image2_generate_tool", status: "done", summary: "failed" }],
      },
    ]);

    expect(html.match(/role="status"/g)?.length).toBe(1);
    expect(html).toContain("运行提示");
    expect(html).toContain("RuntimeError");
    expect(html).toContain("模型服务上游暂时失败");
    expect(html).toContain("思考过程");
    expect(html).toContain("工具调用");
    expect(html).toContain("The generation failed with a 502 upstream error.");
    expect(html).not.toContain("回答");
  });

  it("does not render the next-state signal panel when no signals exist", () => {
    const html = renderConversation([]);

    expect(html).not.toContain("最近控制信号");
  });

  it("hides completed continue signals from the main conversation panel", () => {
    const continueSignal: ChatNextStateSignalSummary = {
      signalId: "chat-signal-continue",
      sessionId: "session-1",
      turnId: "turn-continue",
      source: "user",
      kind: "user_continues",
      polarity: "neutral",
      mode: "directive",
      relatedEventCode: "conversation.user_continue_requested",
      createdAt: "2026-05-25T00:19:12Z",
      summary: "用户请求继续上一轮未完成任务。",
    };

    expect(shouldShowNextStateSignalInConversation(continueSignal, "ready")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(continueSignal, "completed")).toBe(false);
    expect(shouldShowNextStateSignalInConversation(continueSignal, "running")).toBe(true);

    const html = renderConversation([], { nextStateSignals: [continueSignal] });
    expect(html).not.toContain("最近控制信号");
    expect(html).not.toContain("用户请求继续上一轮未完成任务。");
  });

  it("keeps stop and failure signals visible after the turn finishes", () => {
    expect(
      shouldShowNextStateSignalInConversation(
        {
          signalId: "chat-signal-stop",
          sessionId: "session-1",
          turnId: "turn-stop",
          source: "user",
          kind: "user_stops",
          polarity: "negative",
          mode: "directive",
          relatedEventCode: "conversation.user_stop_requested",
          createdAt: "2026-05-25T00:19:12Z",
          summary: "用户请求停止当前对话轮次。",
        },
        "ready",
      ),
    ).toBe(true);
  });

  it("separates mental model traces from tool call counts", () => {
    const html = renderConversation([
      {
        id: "message-mental",
        role: "assistant",
        content: "已暂停，等待继续。",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking state",
          whisper: "",
          summary: "No tool call happened.",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-26T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(html).toContain("心智模型");
    expect(html).toContain("认知态");
    expect(html).toContain("顺畅");
    expect(html).toContain("来源");
    expect(html).toContain("运行时");
    expect(html).toContain("样本数");
    expect(html).toContain("摘要");
    expect(html).toContain("tracking state");
    expect(html).toContain("No tool call happened.");
    expect(html).not.toContain("执行了 1 个操作");
    expect(html).not.toContain("工具调用 1");
  });

  it("hides stored mental snapshots when the mental model switch is off", () => {
    const html = renderConversation(
      [
        {
          id: "message-mental-off",
          role: "assistant",
          content: "已完成。",
          timestamp: "2026-05-26T00:01:00Z",
          mentalSnapshot: {
            mood: "focused",
            feeling: "historical state",
            whisper: "",
            summary: "Old mental snapshot",
            cognitiveState: "productive",
            confidence: 0.7,
            sampleSize: 1,
            interventionCount: 0,
            updatedAt: "2026-05-26T00:01:05Z",
            source: "runtime",
          },
        },
      ],
      { showMentalSnapshots: false },
    );

    expect(html).not.toContain("心智模型");
    expect(html).not.toContain("historical state");
    expect(html).not.toContain("Old mental snapshot");
    expect(html).toContain("已完成。");
  });

  it("does not carry a previous turn-error mental snapshot onto a merged later error", () => {
    const html = renderConversation([
      {
        id: "error-with-mental",
        role: "assistant",
        content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
        timestamp: "2026-05-26T00:01:00Z",
        metadata: { kind: "turn_error" },
        mentalSnapshot: {
          mood: "focused",
          feeling: "stale failure state",
          whisper: "",
          summary: "Previous failure snapshot",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-26T00:01:05Z",
          source: "runtime",
        },
      },
      {
        id: "error-without-mental",
        role: "assistant",
        content: "模型服务上游暂时失败，本轮没有完成。完整 provider 错误已写入运行日志。",
        timestamp: "2026-05-26T00:02:00Z",
        metadata: { kind: "turn_error" },
      },
    ]);

    expect(html).toContain("运行提示");
    expect(html).not.toContain("心智模型");
    expect(html).not.toContain("stale failure state");
    expect(html).not.toContain("Previous failure snapshot");
  });

  it("renders real tool calls in their own tool-call group", () => {
    const html = renderConversation([
      {
        id: "message-tool",
        role: "assistant",
        content: "已读取文件。",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        toolCalls: [{ name: "read_file", status: "done", summary: "opened session_service.py" }],
      },
    ]);

    expect(html).toContain("工具调用 1");
    expect(html).toContain("read_file");
    expect(html).toContain("opened session_service.py");
    expect(html).not.toContain("operationItemTool");
    expect(html).toContain("operationIcon_tool");
    expect(html).not.toContain("执行了 1 个操作");
  });

  it("renders computer use screenshot and confirmation controls from tool result JSON", () => {
    const html = renderConversation([
      {
        id: "message-computer-use",
        role: "assistant",
        content: "沙盒浏览器已暂停等待确认。",
        timestamp: "2026-06-03T00:01:00Z",
        toolCalls: [
          {
            name: "computer_use_task_tool",
            status: "done",
            summary: "need_confirmation",
            resultPreview: JSON.stringify({
              status: "need_confirmation",
              sessionId: "cu-test",
              summary: "Ready before submit.",
              steps: [{ index: 1, action: "submit", summary: "Submit contact form", status: "ready" }],
              screenshotUrl: "/api/computer-use/sessions/cu-test/screenshots/screenshot.png",
              needsConfirmation: true,
              error: "",
            }),
          },
        ],
      },
    ]);

    expect(html).toContain("cu-test");
    expect(html).toContain("Ready before submit.");
    expect(html).toContain('src="/api/computer-use/sessions/cu-test/screenshots/screenshot.png"');
    expect(html).toContain("Submit contact form");
    expect(html).toContain("确认继续");
    expect(html).toContain("停止任务");
  });

  it("renders captured thought text in the folded thought summary", () => {
    const html = renderConversation([
      {
        id: "message-thought",
        role: "assistant",
        content: "我会先检查日志。",
        timestamp: "2026-05-29T09:35:18Z",
        thought: "先确认后端是否捕获 thought，再看前端是否把它渲染出来。",
      },
    ]);

    expect(html).toContain("思考过程");
    expect(html).toContain("先确认后端是否捕获 thought，再看前端是否把它渲染出来。");
    expect(html).toContain('title="展开思考过程"');
  });

  it("renders ordered feedback events as a collapsed execution package without counts", () => {
    const html = renderConversation([
      {
        id: "message-feedback",
        role: "assistant",
        content: "已经完成检查。",
        timestamp: "2026-06-05T09:35:18Z",
        thought: "legacy latest thought",
        toolCalls: [{ name: "legacy_tool", status: "done", summary: "legacy" }],
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "先看日志",
            resultPreview: "先看日志",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "read_log",
            summary: "opened latest log",
            relatedThoughtSequence: 1,
          },
          {
            sequence: 3,
            kind: "thought",
            status: "done",
            summary: "再查 React 链路",
            resultPreview: "再查 React 链路",
          },
        ],
      },
    ]);

    expect(html).toContain("思考");
    expect(html).toContain("读取");
    expect(html).not.toContain("3 步");
    expect(html).not.toContain("2 轮");
    expect(html).not.toContain("3/3");
    expect(html).not.toContain("执行过程");
    expect(html).toContain('title="展开思考过程"');
    expect(html).not.toContain('title="展开工具调用"');
    expect(html).toContain("先看日志");
    expect(html).toContain("opened latest log");
    expect(html).toContain("再查 React 链路");
    expect(html).not.toContain("legacy latest thought");
    expect(html).not.toContain("legacy_tool");
  });

  it("expands the active ReAct packet while showing model thinking content", () => {
    const html = renderConversation([
      {
        id: "message-feedback-active-react",
        role: "assistant",
        content: "",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "先看日志",
            resultPreview: "先看日志",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "done",
            name: "read_log",
            summary: "opened latest log",
            relatedThoughtSequence: 1,
          },
          {
            sequence: 3,
            kind: "thought",
            status: "running",
            summary: "再查会话链路",
            resultPreview: "再查会话链路",
          },
          {
            sequence: 4,
            kind: "tool",
            status: "running",
            name: "cli_tool",
            summary: "running rg",
            relatedThoughtSequence: 3,
          },
        ],
      },
    ]);

    expect(html).not.toContain("执行过程");
    expect(html).not.toContain("4 步");
    expect(html).not.toContain("2 轮");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("第 2 轮");
    expect(html).not.toContain("工具调用");
    expect(html).toContain("思考");
    expect(html).toContain("命令");
    expect(html).toContain("running rg");
    expect(html).toContain("读取");
    expect(html).not.toContain("命令 · running rg");
    expect(html).not.toContain("读取 · opened latest log");
    expect(html).toContain("再查会话链路");
  });

  it("renders active thought-only feedback as readable thinking content", () => {
    const html = renderConversation([
      {
        id: "message-active-thought-only",
        role: "assistant",
        content: "",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "running",
            summary: "模型正在重新规划执行过程布局",
            resultPreview: "模型正在重新规划执行过程布局。\n需要保留真实思考，但隐藏准备上下文和绑定 Agent。",
          },
        ],
      },
    ]);

    expect(html).toContain("执行过程");
    expect(html).toContain("思考");
    expect(html).toContain("模型正在重新规划执行过程布局。");
    expect(html).toContain("需要保留真实思考，但隐藏准备上下文和绑定 Agent。");
    expect(html).not.toContain("准备上下文</span>");
    expect(html).not.toContain("绑定 Agent</span>");
  });

  it("keeps runtime status content out of the assistant answer block", () => {
    const html = renderConversation([
      {
        id: "message-runtime-status-content",
        role: "assistant",
        content: "状态 正在思考，已收到思考片段... 模型已经开始返回 reasoning，正文可能稍后出现。",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_thinking",
            summary: "正在思考，已收到思考片段...",
          },
        ],
      },
    ]);

    expect(html).toContain("正在请求");
    expect(html).not.toContain("执行过程");
    expect(html).not.toContain("模型思考");
    expect(html).not.toContain("工具调用");
    expect(html).not.toContain("1 步");
    expect(html).not.toContain("0/1");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("reasoning 已开始返回");
    expect(html).not.toContain('title="展开工具详情"');
    expect(html).not.toContain("正在思考，已收到思考片段");
    expect(html).not.toContain("回答</span>");
  });

  it("keeps transient reasoning placeholders out of the assistant answer block", () => {
    const html = renderConversation([
      {
        id: "message-runtime-reasoning-placeholder",
        role: "assistant",
        content: "正在思考，已收到思考片段...\n模型已经开始返回 reasoning，正文可能稍后出现。",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        streamStage: "model_thinking",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "model_thinking",
            summary: "正在思考，已收到思考片段...",
          },
        ],
      },
    ]);

    expect(html).toContain("正在请求");
    expect(html).not.toContain("正在思考，已收到思考片段");
    expect(html).not.toContain("模型已经开始返回 reasoning");
    expect(html).not.toContain("正文可能稍后出现");
    expect(html).not.toContain("回答</span>");
    expect(html).not.toContain("responseSection");
  });

  it("hides internal runtime pipeline steps behind a compact request state", () => {
    const fullModelStatus = "正在请求模型，等待首个响应片段... 上下文已组装完成，正在进入 LLM 调用。";
    const html = renderConversation([
      {
        id: "message-runtime-status-compact",
        role: "assistant",
        content: "",
        timestamp: "2026-06-05T10:16:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "running",
            name: "context_prepare",
            summary: "正在准备对话上下文... 正在读取当前会话、绑定 Agent、工具权限和可恢复的上轮现场。",
          },
          {
            sequence: 2,
            kind: "status",
            status: "running",
            name: "agent_prepare",
            summary: "正在唤起对话 agent... 正在绑定 Agent 实例、私有工作区、记忆根和工具工作区。",
          },
          {
            sequence: 3,
            kind: "status",
            status: "running",
            name: "model_request",
            summary: fullModelStatus,
          },
        ],
      },
    ]);

    expect(html).toContain("正在请求");
    expect(html).not.toContain("执行过程");
    expect(html).not.toContain("执行中");
    expect(html).not.toContain("行动");
    expect(html).not.toContain("2/3");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("准备上下文");
    expect(html).not.toContain("绑定 Agent");
    expect(html).not.toContain("请求模型");
    expect(html).not.toContain("当前位置");
    expect(html).not.toContain("请求模型中");
    expect(html).not.toContain("首个响应片段等待中");
    expect(html).not.toContain("运行状态 3");
    expect(html).not.toContain("回答</span>");
    expect((html.match(new RegExp(fullModelStatus, "g")) ?? [])).toHaveLength(0);
    expect(html.match(/statusSpinner/g)?.length).toBe(1);
  });

  it("shows model-request placeholder as a compact process state instead of a separate answer block", () => {
    const placeholder = "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。";
    const html = renderConversation(
      [
        {
          id: "message-model-request-preview",
          role: "assistant",
          content: placeholder,
          timestamp: "2026-06-23T18:11:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: placeholder,
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("生成中");
    expect(html).toContain("正在请求");
    expect(html).not.toContain("正在请求模型，等待首个响应片段...");
    expect(html).not.toContain("上下文已组装完成");
    expect(html).not.toContain("answerOnlyProcessPreview");
    expect(html).not.toContain("回答</span>");
    expect(html).not.toContain("responseSection");
  });

  it("renders request-only process state as static status without empty expandable details", () => {
    const html = renderConversation(
      [
        {
          id: "message-request-only-static",
          role: "assistant",
          content: "",
          timestamp: "2026-06-29T13:32:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: "正在请求模型，等待首个响应片段。",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("生成中");
    expect(html).toContain("正在请求");
    expect(html).not.toContain("aria-expanded");
    expect(html).not.toContain('title="展开执行明细"');
    expect(html.match(/正在请求/g)?.length).toBe(1);
  });

  it("shows long tool loops as visible progress instead of an empty answer block", () => {
    const html = renderConversation(
      [
        {
          id: "message-long-loop-progress",
          role: "assistant",
          content: "",
          timestamp: "2026-06-28T16:52:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "thought",
              status: "running",
              summary: "我正在换可访问来源继续查证。",
              resultPreview: "我正在换可访问来源继续查证。",
            },
            {
              sequence: 2,
              kind: "tool",
              status: "failed",
              name: "web_fetch_tool",
              summary: "[错误] HTTP 403: https://example.test/paper",
              error: "[错误] HTTP 403: https://example.test/paper",
            },
            {
              sequence: 3,
              kind: "status",
              status: "running",
              name: "long_loop_progress",
              summary: "尚未形成最终回答 · web_fetch_tool 第 3 次工具调用；失败 2 次，最近失败：HTTP 403",
              resultPreview:
                "尚未形成最终回答 · web_fetch_tool 第 3 次工具调用；失败 2 次，最近失败：HTTP 403\n当前仍在工具循环中，过程会继续更新；如果中断，可发送“继续”恢复这轮现场。",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("生成中");
    expect(html).toContain("状态 1");
    expect(html).toContain("工具循环");
    expect(html).toContain("尚未形成最终回答");
    expect(html).toContain("HTTP 403");
    expect(html).toContain("思考过程 1");
    expect(html).not.toContain("Long Loop Progress");
    expect(html).not.toContain("回答</span>");
    expect(html).not.toContain("responseSection");
  });

  it("keeps only the latest repeated visible status process update", () => {
    const html = renderConversation(
      [
        {
          id: "message-long-loop-progress-updates",
          role: "assistant",
          content: "",
          timestamp: "2026-06-28T16:52:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "long_loop_progress",
              summary: "尚未形成最终回答 · 第 1 次工具调用",
              resultPreview: "尚未形成最终回答 · 第 1 次工具调用",
            },
            {
              sequence: 2,
              kind: "status",
              status: "running",
              name: "long_loop_progress",
              summary: "尚未形成最终回答 · 第 2 次工具调用",
              resultPreview: "尚未形成最终回答 · 第 2 次工具调用",
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("状态 1");
    expect(html).toContain("第 2 次工具调用");
    expect(html).not.toContain("第 1 次工具调用");
  });

  it("keeps the collapsed answer-only process summary static before details are expanded", () => {
    const placeholder = "正在请求模型，等待首个响应片段...\n上下文已组装完成，正在进入 LLM 调用。";
    const html = renderConversation(
      [
        {
          id: "message-model-request-single-spinner",
          role: "assistant",
          content: placeholder,
          timestamp: "2026-06-23T18:11:00Z",
          streaming: true,
          feedbackEvents: [
            {
              sequence: 1,
              kind: "status",
              status: "running",
              name: "model_request",
              summary: placeholder,
            },
          ],
        },
      ],
      { useDefaultProcessDisplayMode: true },
    );

    expect(html).toContain("生成中");
    expect(html).toContain("正在请求");
    expect(html).not.toContain("statusSpinner");
  });

  it("does not use an animated spinner for the answer-only process summary icon", () => {
    const start = conversationViewSource.indexOf("function processSummaryIcon");
    const end = conversationViewSource.indexOf("function operationMatchesAny", start);
    const processSummaryIconSource = conversationViewSource.slice(start, end);

    expect(processSummaryIconSource).toContain("function processSummaryIcon");
    expect(processSummaryIconSource).not.toContain("styles.statusSpinner");
  });

  it("keeps the active execution trace compact while preserving expandable details", () => {
    const html = renderConversation([
      {
        id: "message-active-location",
        role: "assistant",
        content: "",
        timestamp: "2026-06-05T13:36:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "status",
            status: "done",
            name: "context_prepare",
            summary: "准备上下文",
            timestamp: "2026-06-05T13:36:01Z",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "running",
            name: "cli_tool",
            summary: "正在搜索最新运行日志",
            durationSeconds: 75,
            timeoutSeconds: 120,
            timestamp: "2026-06-05T13:37:10Z",
          },
        ],
      },
    ]);

    expect(html).toContain("运行中");
    expect(html).toContain("命令");
    expect(html).toContain("1m 15s");
    expect(html).not.toContain("工具调用");
    expect(html).not.toContain("1/2");
    expect(html).not.toContain("第 1 轮");
    expect(html).not.toContain("当前位置");
    expect(html).not.toContain("最后事件");
    expect(html).not.toContain("超时阈值");
    expect(html).not.toContain("准备上下文");
    expect(html).toContain("正在搜索最新运行日志");
    expect(html).not.toContain(">当前</span>");
  });

  it("shows display tool labels while preserving raw names in expandable details", () => {
    const html = renderConversation([
      {
        id: "message-feedback-tool-label",
        role: "assistant",
        content: "完成。",
        timestamp: "2026-06-05T09:35:18Z",
        feedbackEvents: [
          {
            sequence: 1,
            kind: "tool",
            status: "done",
            name: "grep_search_tool",
            summary: "[搜索] 正则: memory_index",
            resultPreview: "grep_search_tool raw result",
          },
        ],
      },
    ]);

    expect(html).toContain("搜索");
    expect(html).not.toContain("1 步");
    expect(html).not.toContain("1/1");
    expect(html).toContain('title="展开工具详情"');
    expect(html).not.toContain("grep_search_tool raw result");
  });

  it("keeps structured tool results collapsed by default instead of showing raw JSON", () => {
    const html = renderConversation([
      {
        id: "message-feedback-structured-result",
        role: "assistant",
        content: "",
        timestamp: "2026-06-05T09:35:18Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "done",
            summary: "需要看缓存统计",
            resultPreview: "需要看缓存统计",
          },
          {
            sequence: 2,
            kind: "tool",
            status: "running",
            name: "grep_search_tool",
            summary: "搜索缓存统计代码",
            resultPreview: JSON.stringify({
              summary: "找到 8 处缓存统计入口",
              raw: { sequence: 2, timestamp: "2026-06-05T09:35:18Z" },
            }),
            relatedThoughtSequence: 1,
          },
        ],
      },
    ]);

    expect(html).toContain("思考");
    expect(html).not.toContain("工具调用");
    expect(html).not.toContain("结果</");
    expect(html).toContain("搜索");
    expect(html).toContain("搜索缓存统计代码");
    expect(html).not.toContain("找到 8 处缓存统计入口");
    expect(html).not.toContain("&quot;summary&quot;");
    expect(html).not.toContain("原始名称");
    expect(html).not.toContain("事件索引");
  });

  it("renders expandable tool call details when the backend provides them", () => {
    const html = renderConversation([
      {
        id: "message-tool-details",
        role: "assistant",
        content: "已调用图片工具。",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        toolCalls: [
          {
            name: "image2_generate_tool",
            status: "failed",
            summary: "Read timed out.",
            arguments: {
              prompt: "生成美女图片",
              size: "1024x1024",
            },
            error: "HTTPSConnectionPool read timed out",
            durationMs: 180452,
            timeoutSeconds: 180,
            resultType: "str",
            resultLength: 755,
            tracePath: "conversations/session/tool_calls.jsonl",
          },
        ],
      },
    ]);

    expect(html).toContain("image2_generate_tool");
    expect(html).toContain('title="展开工具详情"');
    expect(html).not.toContain("生成美女图片");
  });

  it("keeps collapsed tool details out of the initial render cost", () => {
    const html = renderConversation([
      {
        id: "message-tool-collapsed",
        role: "assistant",
        content: "已完成大批量搜索。",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        toolCalls: [
          {
            name: "batch_web_search_tool",
            status: "done",
            summary: "batch search done",
            arguments: {
              queries: [
                "predictive coding neural network Rao Ballard 1999 review",
                "predictive coding backpropagation equivalent implementation PyTorch",
                "biologically plausible learning predictive coding survey 2020 2023",
              ],
            },
            resultPreview: JSON.stringify({
              summary: "找到多条学术结果",
              details: new Array(10).fill("very long line of result text").join("\n"),
            }),
            resultType: "json",
            resultLength: 12000,
          },
        ],
      },
    ]);

    expect(html).toContain("batch_web_search_tool");
    expect(html).toContain('title="展开工具详情"');
    expect(html).not.toContain("predictive coding backpropagation equivalent implementation PyTorch");
    expect(html).not.toContain("very long line of result text");
  });

  it("shows spinners only for active conversation sections", () => {
    const html = renderConversation([
      {
        id: "message-running",
        role: "assistant",
        content: "正在读取文件。",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        toolCalls: [{ name: "read_file", status: "running", summary: "opening session_service.py" }],
      },
      {
        id: "message-done",
        role: "assistant",
        content: "已读取文件。",
        timestamp: "2026-05-26T00:02:00Z",
        streaming: false,
        toolCalls: [{ name: "read_file", status: "done", summary: "opened session_service.py" }],
      },
    ]);

    expect(html.match(/statusSpinner/g)?.length).toBe(1);
    expect(html).toContain("opening session_service.py");
    expect(html).toContain("已读取文件。");
  });

  it("only animates the latest running timeline item", () => {
    const html = renderConversation([
      {
        id: "message-running-timeline",
        role: "assistant",
        content: "",
        timestamp: "2026-06-18T00:01:00Z",
        streaming: true,
        feedbackEvents: [
          {
            sequence: 1,
            kind: "thought",
            status: "running",
            summary: "先确认上下文",
            resultPreview: "先确认上下文",
          },
          {
            sequence: 2,
            kind: "thought",
            status: "running",
            summary: "再查看当前渲染",
            resultPreview: "再查看当前渲染",
          },
        ],
        timelineItems: [
          {
            id: "timeline-thought-1",
            kind: "thought",
            status: "running",
            text: "先确认上下文",
            preview: "先确认上下文",
            defaultExpanded: true,
          },
          {
            id: "timeline-thought-2",
            kind: "thought",
            status: "running",
            text: "再查看当前渲染",
            preview: "再查看当前渲染",
            defaultExpanded: true,
          },
        ],
      },
    ]);

    expect(html).toContain("先确认上下文");
    expect(html).toContain("再查看当前渲染");
    expect(html.match(/statusSpinner/g)?.length).toBe(1);
  });

  it("does not keep completed auxiliary sections spinning while a later tool is active", () => {
    const html = renderConversation([
      {
        id: "message-tool-running",
        role: "assistant",
        content: "好的，我直接生成方案二！",
        timestamp: "2026-05-29T19:39:00Z",
        streaming: true,
        thought: "The user wants me to try generating the image again.",
        mentalSnapshot: {
          mood: "focused",
          feeling: "目标很明确，继续尝试方案二的生成。",
          whisper: "稍等片刻，让速率限制冷却一下再重试。",
          summary: "目标很明确，继续尝试方案二的生成。",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-29T19:39:05Z",
          source: "runtime",
        },
        toolCalls: [
          { name: "spawn_agent_tool", status: "done", summary: "delegation policy blocked" },
          { name: "image2_generate_tool", status: "running", summary: "生成方案二" },
        ],
      },
    ]);

    expect(html).toContain("思考过程");
    expect(html).toContain("心智模型");
    expect(html).toContain("工具调用 2");
    expect(html.match(/statusSpinner/g)?.length).toBe(1);
  });

  it("shows a spinner for an active mental model section", () => {
    const html = renderConversation([
      {
        id: "message-mental-running",
        role: "assistant",
        content: "",
        timestamp: "2026-05-26T00:01:00Z",
        streaming: true,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking state",
          whisper: "",
          summary: "Following the active turn",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-26T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(html).toContain("心智模型");
    expect(html).toContain("Following the active turn");
    expect(html).toContain("tracking state");
    expect(html).toContain("运行时");
    expect(html.match(/statusSpinner/g)?.length).toBe(1);
  });

  it("deduplicates matching mental feeling and summary rows", () => {
    const html = renderConversation([
      {
        id: "message-mental-deduped",
        role: "assistant",
        content: "继续。",
        timestamp: "2026-05-29T22:45:00Z",
        mentalSnapshot: {
          mood: "专注",
          feeling: "规则感知: normal",
          whisper: "继续",
          summary: "规则感知: normal",
          cognitiveState: "normal",
          confidence: 0,
          sampleSize: 0,
          interventionCount: 0,
          updatedAt: "2026-05-29T22:45:00Z",
          source: "state",
        },
      },
    ]);

    expect(html.match(/规则感知: normal/g)?.length).toBe(1);
    expect(html).toContain("感受");
    expect(html).not.toContain("摘要");
    expect(html).toContain("低语");
  });
});

describe("ConversationView markdown URL safety", () => {
  it("allows http, https, and relative markdown URLs", () => {
    expect(safeConversationMarkdownUrl("https://example.com/a.png")).toBe("https://example.com/a.png");
    expect(safeConversationMarkdownUrl("http://example.com/a")).toBe("http://example.com/a");
    expect(safeConversationMarkdownUrl("/api/sessions/s1/artifacts/a.png")).toBe("/api/sessions/s1/artifacts/a.png");
    expect(safeConversationMarkdownUrl("./images/a.png")).toBe("./images/a.png");
    expect(safeConversationMarkdownUrl("../images/a.png")).toBe("../images/a.png");
    expect(safeConversationMarkdownUrl("#section")).toBe("#section");
  });

  it("rejects executable and ambiguous markdown URLs", () => {
    expect(safeConversationMarkdownUrl("javascript:alert(1)")).toBeNull();
    expect(safeConversationMarkdownUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeConversationMarkdownUrl("vbscript:msgbox(1)")).toBeNull();
    expect(safeConversationMarkdownUrl("file:///C:/secret.txt")).toBeNull();
    expect(safeConversationMarkdownUrl("//evil.example/a.png")).toBeNull();
    expect(safeConversationMarkdownUrl("java\nscript:alert(1)")).toBeNull();
  });

  it("renders unsafe inline markdown links as plain text", () => {
    const html = renderConversation([
      {
        id: "unsafe-link",
        role: "assistant",
        content: "[Run it](javascript:alert(1)) and [open docs](https://example.com/docs).",
        timestamp: "2026-06-02T00:00:00Z",
      },
    ]);

    expect(html).not.toContain("javascript:alert");
    expect(html).toContain("Run it and");
    expect(html).toContain('href="https://example.com/docs"');
  });

  it("does not render unsafe markdown images or image download links", () => {
    const html = renderConversation([
      {
        id: "unsafe-image",
        role: "assistant",
        content: "![bad](javascript:alert(1))\n\n![good](/api/sessions/s1/artifacts/good.png)",
        timestamp: "2026-06-02T00:00:00Z",
      },
    ]);

    expect(html).not.toContain("javascript:alert");
    expect(html).toContain('src="/api/sessions/s1/artifacts/good.png"');
    expect(html).toContain('href="/api/sessions/s1/artifacts/good.png"');
  });
});

describe("ConversationView timeline scroll signal", () => {
  const baseAssistantMessage: ConversationMessage = {
    id: "message-assistant",
    role: "assistant",
    content: "",
    timestamp: "2026-05-22T00:01:00Z",
    streaming: true,
    toolCalls: [{ name: "read_file", status: "running" }],
  };

  it("changes when a tool status changes without changing tool count", () => {
    const before = buildTimelineScrollSignal([baseAssistantMessage]);
    const after = buildTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        toolCalls: [{ name: "read_file", status: "done" }],
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes when a tool summary appears without changing message text length", () => {
    const before = buildTimelineScrollSignal([baseAssistantMessage]);
    const after = buildTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        toolCalls: [{ name: "read_file", status: "running", summary: "opened session_service.py" }],
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes when a mental snapshot becomes visible", () => {
    const before = buildTimelineScrollSignal([baseAssistantMessage]);
    const after = buildTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        mentalSnapshot: {
          mood: "focused",
          feeling: "tracking tool output",
          whisper: "",
          summary: "Following the active tool result",
          cognitiveState: "productive",
          confidence: 0.7,
          sampleSize: 1,
          interventionCount: 0,
          updatedAt: "2026-05-22T00:01:05Z",
          source: "runtime",
        },
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("does not change the synchronous scroll signal when streaming text grows", () => {
    const before = buildTimelineScrollSignal([baseAssistantMessage]);
    const after = buildTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        content: "streaming response text is still growing",
      },
    ]);

    expect(after).toBe(before);
  });

  it("tracks streaming text growth in the deferred scroll signal", () => {
    const before = buildStreamingTimelineScrollSignal([baseAssistantMessage]);
    const after = buildStreamingTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        content: "streaming response text is still growing",
      },
    ]);

    expect(after).not.toBe(before);
  });

  it("changes the synchronous scroll signal when settled text changes", () => {
    const before = buildTimelineScrollSignal([{ ...baseAssistantMessage, streaming: false }]);
    const after = buildTimelineScrollSignal([
      {
        ...baseAssistantMessage,
        streaming: false,
        content: "settled response text changed",
      },
    ]);

    expect(after).not.toBe(before);
  });
});
