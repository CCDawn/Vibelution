import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConversationMessage } from "../../api/types";
import { dictionary } from "../../i18n/dictionary";
import { ConversationView } from "./ConversationView";
import styles from "./ConversationView.styles";
import conversationViewSource from "./ConversationView.tsx?raw";

function renderConversation(messages: ConversationMessage[]) {
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
        sessionId="session-process-default-expanded"
        title="Session"
        phase="running"
        messages={messages}
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
        onEditUserMessage={() => undefined}
      />
    </QueryClientProvider>,
  );
}

describe("ConversationView process expansion defaults", () => {
  it("keeps feedback process typography on dense VUI row tokens", () => {
    expect(styles.answerOnlyProcessTitle).toContain("text-vui-sm");
    expect(styles.answerOnlyProcessTitle).not.toContain("text-vui-title");
    expect(styles.answerOnlyProcessMeta).toContain("text-vui-xs");
    expect(styles.operationName).toContain("text-vui-sm");
    expect(styles.reActOperationTitle).toContain("text-vui-sm");
    expect(styles.reActToolName).toContain("text-vui-sm");
    expect(styles.reActToolSummary).toContain("text-vui-sm");
    expect(styles.reActToolStatus).toContain("text-vui-xs");
    expect(styles.reActResultToggle).toContain("text-vui-xs");
  });

  it("keeps legacy feedback details flat under the process disclosure", () => {
    const feedbackStart = conversationViewSource.indexOf("function renderFeedbackTimelineGroup(");
    const feedbackEnd = conversationViewSource.indexOf("function renderAnswerOnlyProcessGroup(", feedbackStart);
    const feedbackRenderer = conversationViewSource.slice(feedbackStart, feedbackEnd);

    expect(feedbackRenderer).toContain("renderFeedbackTimelineDetails(messageId, operations)");
    expect(feedbackRenderer).not.toContain("renderReActOperationGroup(");
  });

  it("keeps follow-latest on process toggles near the bottom and anchors only when reading history", () => {
    const handlerStart = conversationViewSource.indexOf("const handleProcessDisclosureUserToggle");
    const handlerEnd = conversationViewSource.indexOf(
      "// Stick-to-bottom:",
      handlerStart,
    );
    const handler = conversationViewSource.slice(handlerStart, handlerEnd);

    expect(handler).toContain("shouldKeepFollowingLatestOnProcessToggle({");
    expect(handler).toContain("followLatestRef.current = true");
    expect(handler).toContain("scrollTimelineToBottom(timeline)");
    expect(handler).toContain("followLatestRef.current = false");
    expect(handler).toContain("captureConversationProcessScrollAnchor(summary)");
    expect(handler).toContain("restoreConversationProcessScrollAnchor(timeline, summary, anchor)");
    expect(handler).not.toContain("scrollIntoView");
    expect(conversationViewSource).toContain("onUserToggle={handleProcessDisclosureUserToggle}");
  });});
