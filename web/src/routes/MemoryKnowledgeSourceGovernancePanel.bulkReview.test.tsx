// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeOwnerSource } from "../api/types";
import {
  MemoryKnowledgeSourceGovernancePanel,
  type MemoryKnowledgeSourceGovernancePanelCopy,
} from "./MemoryKnowledgeSourceGovernancePanel";

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const copy: MemoryKnowledgeSourceGovernancePanelCopy = {
  sourceGovernance: "来源治理",
  ownerSourceInbox: "来源收件箱",
  ownerScope: "Owner 范围",
  ownerTeam: "团队",
  ownerAgent: "Agent",
  ownerId: "Owner ID",
  status: "状态",
  useActiveKnowledgeOwner: "使用当前知识库 owner",
  collectOwnerSource: "采集来源",
  cancelEdit: "取消编辑",
  submitSource: "提交来源",
  sourceType: "来源类型",
  titleField: "标题",
  originalFilename: "原始文件名",
  sourceCreatedAt: "来源时间",
  capturedBy: "采集人",
  sourceHash: "来源哈希",
  sourceRef: "来源引用",
  evidenceRange: "证据范围",
  summaryField: "摘要",
  originalContent: "原始内容",
  reviewSource: "复核来源",
  centralSourceRegistry: "中央来源登记",
  sourceReviewNote: "复核说明",
  centralSourceId: "中央来源 ID",
  originalPath: "原始路径",
  curationStatus: "整理状态",
  dedupeStatus: "去重状态",
  acceptSource: "通过",
  needsMoreContext: "需要更多上下文",
  markDuplicate: "标记重复",
  rejectProposal: "驳回",
  noInboxSources: "无来源",
  centralPath: "中央路径",
  reviewedBy: "审核人",
  reviewedAt: "审核时间",
  attachCentralSource: "关联中央来源",
  noCentralSources: "无中央来源",
  pendingSources: "待复核",
  acceptedSources: "已通过",
  rejectedSources: "已驳回",
  duplicateSources: "重复",
  needsMoreContextSources: "需补充",
  allSourceStatuses: "全部状态",
  linkedKnowledgeSources: "已关联来源",
  lifecycleReason: "生命周期原因",
  lifecycleReasonPlaceholder: "填写原因",
  withdrawLinkedSource: "撤回",
  expireLinkedSource: "过期",
  restoreLinkedSource: "恢复",
  lifecycleUpdated: "已更新",
  lifecycleReasonRequired: "需要原因",
  noLinkedKnowledgeSources: "无关联来源",
  bulkAcceptSources: "批量通过",
  bulkRejectSources: "批量驳回",
  selectVisibleSources: "全选待复核",
  skippedSources: "跳过",
};

function makeSource(inboxSourceId: string, status: KnowledgeOwnerSource["status"]): KnowledgeOwnerSource {
  return {
    schemaVersion: 1,
    inboxSourceId,
    ownerType: "team",
    ownerId: "team-1",
    teamId: "team-1",
    agentId: "",
    sourceType: "manual_user_entry",
    sourceRef: {},
    sourceCreatedAt: "2026-10-20T00:00:00Z",
    capturedBy: "member-1",
    capturedAt: "2026-10-20T00:00:00Z",
    sourceHash: `sha256:${inboxSourceId}`,
    evidenceRange: {},
    title: `来源 ${inboxSourceId}`,
    summary: "",
    originalFilename: `${inboxSourceId}.txt`,
    originalPath: "",
    status,
    curationStatus: "",
    centralSourceId: "",
    dedupeStatus: "",
    reviewedAt: "",
    reviewedByAgentId: "",
    resolutionNote: "",
    updatedAt: "2026-10-20T00:00:00Z",
  };
}

let container: HTMLDivElement | null = null;
let root: Root | null = null;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container!);
});

afterEach(async () => {
  if (root && container) {
    await act(async () => root!.unmount());
  }
  container?.remove();
  container = null;
  root = null;
});

function makePanel(overrides: {
  ownerInboxSources?: KnowledgeOwnerSource[];
  selectedInboxSourceIds?: string[];
  onToggleInboxSourceSelection?: (id: string) => void;
  onToggleVisibleInboxSources?: () => void;
  onBulkReviewOwnerSource?: (decision: "accepted" | "rejected") => void;
}) {
  return (
    <MemoryKnowledgeSourceGovernancePanel
      copy={copy}
      sourceOwnerType="team"
      sourceOwnerId="team-1"
      sourceInboxStatus="pending"
      sourceCount={overrides.ownerInboxSources?.length ?? 0}
      centralSourceCount={0}
      showOwnerSourceForm={false}
      ownerSourceDraft={{
        sourceType: "manual_user_entry",
        sourceRef: "",
        sourceCreatedAt: "",
        capturedBy: "",
        evidenceRange: "",
        title: "",
        summary: "",
        originalContent: "",
        originalFilename: "",
        sourceHash: "",
      }}
      sourceReviewNote=""
      duplicateCentralSourceId=""
      ownerInboxSources={overrides.ownerInboxSources ?? []}
      centralSources={[]}
      isSourceInboxPending={false}
      isCentralSourcesPending={false}
      knowledgeBusy={false}
      canSubmitOwnerSource={false}
      canAttachCentralSource={false}
      knowledgeBaseId=""
      knowledgeAgentId="reviewer-1"
      canReviewKnowledge
      linkedKnowledgeSources={[]}
      onLifecycleChanged={() => undefined}
      onSourceOwnerTypeChange={() => undefined}
      onSourceOwnerIdChange={() => undefined}
      onSourceInboxStatusChange={() => undefined}
      onApplyActiveKnowledgeOwner={() => undefined}
      onShowOwnerSourceFormChange={() => undefined}
      onOwnerSourceDraftChange={() => undefined}
      onSourceReviewNoteChange={() => undefined}
      onDuplicateCentralSourceIdChange={() => undefined}
      onSubmitOwnerSource={() => undefined}
      onReviewOwnerSource={() => undefined}
      selectedInboxSourceIds={overrides.selectedInboxSourceIds ?? []}
      onToggleInboxSourceSelection={overrides.onToggleInboxSourceSelection ?? (() => undefined)}
      onToggleVisibleInboxSources={overrides.onToggleVisibleInboxSources ?? (() => undefined)}
      onBulkReviewOwnerSource={overrides.onBulkReviewOwnerSource ?? (() => undefined)}
      onAttachCentralSource={() => undefined}
      formatTimestamp={(value) => value}
    />
  );
}

function findButtonByText(text: string): HTMLButtonElement | null {
  const buttons = Array.from(container?.querySelectorAll("button") ?? []);
  return buttons.find((item) => item.textContent?.includes(text)) ?? null;
}

describe("MemoryKnowledgeSourceGovernancePanel bulk review", () => {
  it("shows the bulk toolbar with selection count for reviewable sources", () => {
    act(() => {
      root!.render(makePanel({
        ownerInboxSources: [
          makeSource("inbox-src-1", "pending"),
          makeSource("inbox-src-2", "needs_more_context"),
          makeSource("inbox-src-done", "accepted"),
        ],
        selectedInboxSourceIds: ["inbox-src-1"],
      }));
    });
    const toolbar = container?.querySelector('[data-inbox-bulk-toolbar="true"]');
    expect(toolbar).not.toBeNull();
    expect(toolbar!.textContent).toContain("1/2");
    expect(findButtonByText("批量通过")).not.toBeNull();
    expect(findButtonByText("批量驳回")).not.toBeNull();
  });

  it("omits the bulk toolbar when nothing is reviewable", () => {
    act(() => {
      root!.render(makePanel({
        ownerInboxSources: [makeSource("inbox-src-done", "accepted")],
      }));
    });
    expect(container?.querySelector('[data-inbox-bulk-toolbar="true"]')).toBeNull();
  });

  it("toggles one source selection from its row checkbox", () => {
    const onToggleInboxSourceSelection = vi.fn();
    act(() => {
      root!.render(makePanel({
        ownerInboxSources: [makeSource("inbox-src-1", "pending")],
        onToggleInboxSourceSelection,
      }));
    });
    const checkbox = container?.querySelector<HTMLInputElement>(
      'input[type="checkbox"][aria-label="来源 inbox-src-1"]',
    );
    expect(checkbox).not.toBeNull();
    act(() => {
      checkbox!.click();
    });
    expect(onToggleInboxSourceSelection).toHaveBeenCalledWith("inbox-src-1");
  });

  it("fires bulk accept with the selected reviewable sources", () => {
    const onBulkReviewOwnerSource = vi.fn();
    act(() => {
      root!.render(makePanel({
        ownerInboxSources: [makeSource("inbox-src-1", "pending")],
        selectedInboxSourceIds: ["inbox-src-1"],
        onBulkReviewOwnerSource,
      }));
    });
    const button = findButtonByText("批量通过");
    expect(button).not.toBeNull();
    act(() => button!.click());
    expect(onBulkReviewOwnerSource).toHaveBeenCalledWith("accepted");
  });

  it("fires bulk reject and disables batch buttons while busy or empty selection", () => {
    act(() => {
      root!.render(makePanel({
        ownerInboxSources: [makeSource("inbox-src-1", "pending")],
        selectedInboxSourceIds: [],
      }));
    });
    expect(findButtonByText("批量驳回")!.hasAttribute("disabled")).toBe(true);
  });
});
