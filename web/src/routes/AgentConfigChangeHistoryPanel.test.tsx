import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { AgentConfigChangeHistoryPanel } from "./AgentConfigChangeHistoryPanel";

describe("AgentConfigChangeHistoryPanel", () => {
  it("separates the active draft from compact published revision evidence", () => {
    const markup = renderToStaticMarkup(
      <AgentConfigChangeHistoryPanel
        changes={{
          schemaVersion: 1,
          agentId: "agent-1",
          activeDraft: {
            draftId: "draft-1",
            status: "active",
            baseUpdatedAt: "2026-07-25T00:00:00Z",
            createdAt: "2026-07-25T00:00:05Z",
            summary: "Prepare an updated model binding.",
            changedFields: ["displayName", "llmBindings"],
            stale: false,
          },
          revisions: [
            {
              revisionId: "configrev-3",
              revisionNumber: 3,
              publishedAt: "2026-07-25T00:01:00Z",
              source: "direct_patch",
              sourceDraftId: "draft-0",
              changedFields: ["promptTemplateId"],
              runtimeBinding: {
                directSessionId: "session-123",
              },
            },
          ],
        }}
        configDirty
        loading={false}
        savePending={false}
        discardPending={false}
        onSaveDraft={() => undefined}
        onDiscardDraft={() => undefined}
        onOpenConfig={() => undefined}
      />,
    );

    expect(markup).toContain("草稿与版本");
    expect(markup).toContain("当前草稿");
    expect(markup).toContain("名称");
    expect(markup).toContain("模型绑定");
    expect(markup).toContain("v3");
    expect(markup).toContain("session-123");
  });
});
