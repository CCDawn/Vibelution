import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ConversationMessage } from "../../api/types";
import { buildTimelineScrollSignal, ConversationView } from "./ConversationView";

function renderConversation(
  messages: ConversationMessage[],
  options: {
    editingMessageId?: string;
    editUserMessageDisabled?: boolean;
    composerValue?: string;
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
        showHeader={false}
        showSessionOverview={false}
        composerValue={options.composerValue ?? ""}
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
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
