import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import conversationViewSource from "./ConversationView.tsx?raw";
import { ConversationTranscriptLoadingState } from "./ConversationTranscriptLoadingState";

describe("ConversationTranscriptLoadingState", () => {
  it("preserves transcript geometry without a full-panel color wash", () => {
    const markup = renderToStaticMarkup(
      <ConversationTranscriptLoadingState label="正在加载会话消息" />,
    );

    expect(markup).toContain('data-testid="conversation-transcript-loading-state"');
    expect(markup).toContain('aria-label="正在加载会话消息"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain('data-vui="skeleton"');
    expect(markup).toContain("bg-transparent");
    expect(markup).not.toContain('data-vui="state-surface"');
    expect(markup).not.toContain("vui-control-muted");
  });

  it("owns the transcript pending branch in ConversationView", () => {
    expect(conversationViewSource).toContain(
      'import { ConversationTranscriptLoadingState } from "./ConversationTranscriptLoadingState";',
    );
    expect(conversationViewSource).toContain(
      '<ConversationTranscriptLoadingState label={t("sessionTranscriptLoading")} />',
    );
  });
});
