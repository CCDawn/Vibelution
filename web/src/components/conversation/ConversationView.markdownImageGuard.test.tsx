import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { ConversationView } from "./ConversationView";

vi.mock("./LazyConversationMarkdownRenderer", async () => {
  const { ConversationMarkdownRenderer } = await import("./ConversationMarkdownRenderer");
  return { LazyConversationMarkdownRenderer: ConversationMarkdownRenderer };
});

function renderAssistantAnswer(content: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-1"
        title="Session"
        phase="ready"
        messages={[
          {
            id: "assistant-doc-image",
            role: "assistant",
            timestamp: "2026-09-17T10:00:00Z",
            turnId: "turn-doc-image",
            status: "completed",
            turnItems: [
              {
                id: "answer-doc-image",
                itemId: "answer-doc-image",
                version: 3,
                sessionId: "session-1",
                turnId: "turn-doc-image",
                type: "agent_message",
                phase: "final_answer",
                status: "completed",
                revision: 1,
                sequence: 1,
                terminal: true,
                text: content,
              },
            ],
          },
        ] as unknown as ConversationMessage[]}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        processDisplayMode="trace"
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
        onStop={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView markdown image guards", () => {
  it("renders markdown images pointing at documents as links instead of broken previews", () => {
    const html = renderAssistantAnswer([
      "报告见附件：",
      "",
      "![报告](/api/sessions/session-1/artifacts/report.md)",
      "",
      "![截图](/api/sessions/session-1/artifacts/shot.png)",
    ].join("\n"));

    expect(html).toContain('href="/api/sessions/session-1/artifacts/report.md"');
    expect(html).not.toContain('src="/api/sessions/session-1/artifacts/report.md"');
    expect(html).toContain(">报告</a>");
    expect(html).toContain("markdownImageFigure");
    expect(html).toContain('src="/api/sessions/session-1/artifacts/shot.png"');
  });
});
