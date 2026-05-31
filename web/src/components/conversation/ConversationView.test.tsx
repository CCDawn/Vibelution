import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ChatNextStateSignalSummary, ConversationMessage } from "../../api/types";
import {
  buildTimelineScrollSignal,
  ConversationView,
  extractComposerImageDropFiles,
  hasComposerImageDragPayload,
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
        },
      },
    ]);

    expect(html).toContain("turnErrorNotice");
    expect(html).toContain("运行提示");
    expect(html).toContain("RuntimeError");
    expect(html).toContain("模型服务上游暂时失败");
    expect(html).toContain("assistantTurn");
    expect(html).toContain("思考过程");
    expect(html).toContain("工具调用");
    expect(html).toContain("The generation failed with a 502 upstream error.");
    expect(html).not.toContain("回答");
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
    expect(html).toContain("operationItemTool");
    expect(html).not.toContain("operationIcon_tool");
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

    expect(html.match(/statusSpinner/g)?.length).toBe(2);
    expect(html).toContain("opening session_service.py");
    expect(html).toContain("已读取文件。");
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
    expect(html.match(/statusSpinner/g)?.length).toBe(2);
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
