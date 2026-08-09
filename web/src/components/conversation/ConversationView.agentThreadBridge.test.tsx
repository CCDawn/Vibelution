import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { conversationMessageToAgentMessage } from "../../agent-thread";
import { dictionary } from "../../i18n/dictionary";
import { AgentContextSectionsView } from "./AgentContextSectionsView";
import { buildAgentMessageRenderState } from "./agentMessageRenderState";
import { ConversationView } from "./ConversationView";
import conversationViewSource from "./ConversationView.tsx?raw";

function renderConversation(messages: ConversationMessage[], activeTurnMessage?: ConversationMessage) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  queryClient.setQueryData(["i18n", "dictionary-domains", "core,chat"], dictionary);

  return renderToStaticMarkup(
    <QueryClientProvider client={queryClient}>
      <ConversationView
        sessionId="session-agent-thread"
        title="Session"
        phase="running"
        messages={messages}
        activeTurnMessage={activeTurnMessage}
        showHeader={false}
        showSessionOverview={false}
        showComposer={false}
        composerValue=""
        composerPlaceholder="Type"
        composerDisabled={false}
        composerPending={false}
        defaultFileContext="workspace"
        onComposerChange={() => undefined}
        onSubmit={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView agent thread bridge", () => {
  it("derives peripheral response and process visibility from AgentMessage section state", () => {
    expect(conversationViewSource).not.toMatch(/\bhas(?:Response|Thought|Mental)Block\s*\(/);
  });it("renders conversation context from AgentMessage context sections", () => {
    const message: ConversationMessage = {
      id: "user-context",
      role: "user",
      content: "继续看这个上下文",
      timestamp: "2026-07-02T09:30:00Z",
      attachments: [
        {
          artifactId: "context-image.png",
          filename: "context.png",
          url: "/api/sessions/session-agent-thread/artifacts/context-image.png",
          imageUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png",
          downloadUrl: "/api/sessions/session-agent-thread/artifacts/context-image.png?download=1",
          contentType: "image/png",
          sizeBytes: 128,
          kind: "user_image",
          status: "ready",
        },
      ],
      references: [
        {
          kind: "session",
          referenceId: "session:context-ref",
          sessionId: "context-ref",
          title: "旧会话摘录",
          agentDisplayName: "前端代理",
        },
      ],
    };
    const html = renderConversation([message]);
    const contextHtml = renderToStaticMarkup(
      <AgentContextSectionsView
        sections={buildAgentMessageRenderState(conversationMessageToAgentMessage(message)).contextSections}
        lang="zh"
      />,
    );

    expect(html).toContain('data-agent-message-id="user-context"');
    expect(html).toContain('data-agent-section-kinds="content context"');
    expect(conversationViewSource).toContain(
      "<AgentContextSectionsView sections={agentRenderState.contextSections} lang={lang} />",
    );
    expect(contextHtml).toContain('data-agent-context-section-id="user-context-section-context-1"');
    expect(contextHtml).toContain('data-agent-context-part-count="2"');
    expect(contextHtml).toContain('data-agent-context-part-type="attachment"');
    expect(contextHtml).toContain('data-agent-context-part-type="reference"');
    expect(contextHtml).toContain('src="/api/sessions/session-agent-thread/artifacts/context-image.png"');
    expect(contextHtml).toContain("context.png");
    expect(contextHtml).toContain("旧会话摘录");
    expect(contextHtml).toContain("前端代理");
  });});
