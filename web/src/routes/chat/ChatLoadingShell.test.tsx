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
    expect(markup.match(/aria-hidden="true"/g)?.length).toBeGreaterThanOrEqual(5);
  });

  it("keeps transcript and composer geometry visible while session detail loads", () => {
    const markup = renderToStaticMarkup(<ConversationWorkspaceLoadingShell label="加载会话中" />);

    expect(markup).toContain('data-testid="conversation-workspace-loading-shell"');
    expect(markup).toContain('aria-label="加载会话中"');
    expect(markup).toContain("grid-rows-[minmax(0,1fr)_auto]");
    expect(markup).toContain("shadow-[var(--vui-shadow-hairline)]");
  });
});
