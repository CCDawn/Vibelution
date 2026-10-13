import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  ConversationIndexLoadingShell,
  ConversationWorkspaceLoadingShell,
} from "./ChatLoadingShell";

describe("chat structural loading shells", () => {
  it("renders conversation groups and cards before index data arrives", () => {
    const markup = renderToStaticMarkup(<ConversationIndexLoadingShell label="加载会话中" />);

    expect(markup).toContain('data-testid="conversation-index-loading-shell"');
    expect(markup).toContain('aria-label="加载会话中"');
    expect(markup).toContain("min-h-[44px]");
    expect(markup).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(markup).toContain("size-8");
    expect(markup.match(/aria-hidden="true"/g)?.length).toBeGreaterThanOrEqual(5);
  });

  it("keeps transcript and composer geometry visible while session detail loads", () => {
    const markup = renderToStaticMarkup(<ConversationWorkspaceLoadingShell label="加载会话中" />);

    expect(markup).toContain('data-testid="conversation-workspace-loading-shell"');
    expect(markup).toContain('aria-label="加载会话中"');
    expect(markup).toContain("grid-rows-[minmax(0,1fr)_auto]");
    expect(markup).toContain("min-h-[104px]");
    expect(markup).toContain("min-h-[48px]");
    expect(markup).toContain("grid-cols-[2rem_minmax(0,1fr)]");
  });
});
