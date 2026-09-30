import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { SourceCollectionMaterializedKnowledgeIngestion } from "../../../../api/sourceCollection";
import { TeamSourceCollectionActiveStagePanel } from "./TeamSourceCollectionActiveStagePanel";

function renderIngestionStatus(
  payload: SourceCollectionMaterializedKnowledgeIngestion | null,
) {
  return renderToStaticMarkup(createElement(TeamSourceCollectionActiveStagePanel, {
    lang: "zh",
    stageId: "ingestion",
    title: "资料入库",
    status: "当前阶段",
    materializedKnowledgeIngestion: payload,
    primaryAction: {
      tone: "primary",
      disabled: false,
      title: "开始入库",
      label: "开始入库",
      icon: "play",
      onAction: () => undefined,
    },
    agentChatAction: createElement("span", null, "Agent 私聊"),
    agentConfigAction: createElement("span", null, "配置 Agent"),
    errors: null,
    renderConversationPanel: () => createElement("span", null, "conversation"),
    renderScreeningPanel: () => createElement("span", null, "screening"),
    renderGraphPanel: () => createElement("span", null, "graph"),
    renderMemoryPanel: () => createElement("span", null, "memory"),
  }));
}

describe("knowledge ingestion status", () => {
  it("shows completed, pending, and failed sync without leaking internal ids", () => {
    const completed = renderIngestionStatus({
      status: "completed",
      formalKnowledgeItemCount: 1,
      formalKnowledgeItemIds: ["knowledge-1"],
      knowledgeBaseId: "kb-1",
      failedCount: 0,
      failed: [],
    });
    expect(completed).toContain('data-testid="source-collection-knowledge-ingestion-status"');
    expect(completed).toContain('data-ingestion-state="completed"');
    expect(completed).toContain('data-ingestion-reason-code="official_sync_completed"');
    expect(completed).toContain("1 条");
    expect(completed).not.toContain("knowledge-1");

    const pending = renderIngestionStatus({
      status: "pending_review",
      formalKnowledgeItemCount: 0,
      knowledgeBaseId: "kb-pending",
      skippedCount: 1,
    });
    expect(pending).toContain('data-ingestion-state="pending"');
    expect(pending).toContain('data-ingestion-reason-code="official_sync_pending"');
    expect(pending).toContain("等待正式同步");
    expect(pending).not.toContain("kb-pending");

    const failed = renderIngestionStatus({
      status: "completed",
      formalKnowledgeItemCount: 1,
      formalKnowledgeItemIds: ["knowledge-stale"],
      failedCount: 1,
      failed: [{ reason: "knowledge review rejected" }],
    });
    expect(failed).toContain('data-ingestion-state="failed"');
    expect(failed).toContain('data-ingestion-reason-code="official_sync_failed"');
    expect(failed).not.toContain('data-ingestion-state="completed"');
    expect(failed).toContain("正式知识同步失败");
    expect(failed).not.toContain("knowledge-stale");
    expect(failed).not.toContain("knowledge review rejected");

    const empty = renderIngestionStatus({});
    expect(empty).not.toContain("source-collection-knowledge-ingestion-status");
  });
});
