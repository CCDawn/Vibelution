import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatNextStateSignalSummary, ConversationMessage } from "../../api/types";
import {
  buildTimelineScrollSignal,
  ConversationView,
  shouldShowNextStateSignalInConversation,
} from "./ConversationView";

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
    composerAttachments?: Array<{
      id: string;
      filename: string;
      previewUrl: string;
      sizeBytes: number;
      contentType: string;
    }>;
    composerDisabled?: boolean;
    composerActionMode?: "send" | "stop";
    composerActionDisabled?: boolean;
    composerGuidance?: string;
  } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={messages}
        density={options.density}
        showHeader={false}
        showSessionOverview={false}
        composerValue={options.composerValue ?? ""}
        composerPlaceholder="Type"
        composerDisabled={options.composerDisabled ?? false}
        composerActionMode={options.composerActionMode}
        composerActionDisabled={options.composerActionDisabled}
        composerPending={false}
        composerGuidance={options.composerGuidance}
        composerAttachments={options.composerAttachments}
        nextStateSignals={options.nextStateSignals}
        userAvatarPreset={options.userAvatarPreset}
        userAvatarImageUrl={options.userAvatarImageUrl}
        userDisplayName={options.userDisplayName}
        editingMessageId={options.editingMessageId}
        editUserMessageDisabled={options.editUserMessageDisabled}
        editUserMessageLabel="Edit and resend"
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onEditUserMessage={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView edit resend affordance", () => {
  it("can render the opt-in compact workbench density", () => {
    const html = renderConversation([], { density: "compact" });

    expect(html).toContain("surfaceCompact");
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

  it("keeps the composer writable while a running turn uses the stop action", () => {
    const html = renderConversation([], {
      composerValue: "下一句先写在这里",
      composerDisabled: true,
      composerActionMode: "stop",
      composerActionDisabled: false,
      composerGuidance: "当前轮仍在运行。你可以先把下一句写在这里，它会作为草稿保留；要打断当前轮请点“终止”。",
    });

    expect(html).toContain("下一句先写在这里");
    expect(html).toContain("当前轮仍在运行");
    expect(html).toContain("stopButton");
    const textarea = html.match(/<textarea[^>]*>/)?.[0] ?? "";
    expect(textarea).not.toContain("disabled");
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
    expect(html).toContain("提交");
    expect(html).toContain("验证");
    expect(html).toContain("8697ecf fix(chat): keep bookkeeping guard resumable");
    expect(html).toContain("101 passed, 245 deselected");
    expect(html).not.toContain("```text");
  });

  it("keeps historical assistant responses collapsed while preserving latest and streaming responses", () => {
    const html = renderConversation([
      {
        id: "message-old-assistant",
        role: "assistant",
        content: "OLD_HEAVY_ASSISTANT_RESPONSE_SHOULD_NOT_RENDER_BY_DEFAULT",
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
    expect(html).not.toContain("OLD_HEAVY_ASSISTANT_RESPONSE_SHOULD_NOT_RENDER_BY_DEFAULT");
    expect(html).toContain("STREAMING_ASSISTANT_RESPONSE_STAYS_VISIBLE");
    expect(html).toContain("LATEST_ASSISTANT_RESPONSE_STAYS_VISIBLE");
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

  it("renders next-state signals outside the message body when available", () => {
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

    expect(html).toContain("最近控制信号");
    expect(html).toContain("Provider failed after one ReAct pass.");
    expect(html).toContain("Visible assistant answer");
    expect(html.indexOf("Provider failed after one ReAct pass.")).toBeGreaterThan(
      html.indexOf("Visible assistant answer"),
    );
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
    expect(html).toContain("tracking state");
    expect(html).not.toContain("执行了 1 个操作");
    expect(html).not.toContain("工具调用 1");
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
    expect(html).not.toContain("执行了 1 个操作");
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

    expect(html.match(/statusSpinner/g)?.length).toBe(3);
    expect(html).toContain("opening session_service.py");
    expect(html).toContain("已读取文件。");
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
    expect(html.match(/statusSpinner/g)?.length).toBe(2);
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
});
