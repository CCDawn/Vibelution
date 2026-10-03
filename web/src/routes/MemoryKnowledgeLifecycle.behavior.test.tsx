// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeItem, KnowledgeItemBodyPage, KnowledgeItemHistoryPage, TeamKnowledgeBase } from "../api/types";
import {
  createKnowledgeRevisionProposal,
  fetchKnowledgeItemBody,
  readKnowledgeItemBodyAllPages,
} from "../api/knowledgeLifecycle";
import {
  MemoryKnowledgeDetailPanel,
  type MemoryKnowledgeDetailPanelCopy,
} from "./MemoryKnowledgeDetailPanel";
import type { MemoryKnowledgeRatingDraft } from "./MemoryKnowledgeItemRatingCard";

vi.mock("../api/knowledgeLifecycle", () => ({
  createKnowledgeRevisionProposal: vi.fn(),
  fetchKnowledgeItemBody: vi.fn(),
  readKnowledgeItemBodyAllPages: vi.fn(),
}));

vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

const copy: MemoryKnowledgeDetailPanelCopy = {
  formalKnowledge: "正式知识",
  selectedKnowledgeDetail: "选择知识条目",
  sourceChain: "来源链",
  traceability: "溯源对象",
  sourceArtifacts: "来源",
  pendingProposals: "待审核提案",
  ratingSuggestions: "评级建议",
  loading: "正在加载",
  confidence: "置信度",
  stability: "稳定性",
  reviewPriority: "审核优先级",
  markingReason: "标记原因",
  submitRatingSuggestion: "提交评级建议",
  noMatches: "没有匹配内容",
  knowledgeRevisionDialog: "修订正式知识",
  knowledgeBodyDialog: "正式知识正文",
  knowledgeSourceDialog: "原始来源正文",
  knowledgeHistoryDialog: "版本历史",
  knowledgeBodyLoading: "正在读取完整内容…",
  knowledgeBodyEmpty: "该条目没有正文内容。",
  sourceBodyUnavailable: "原始来源快照不可用或已失效。",
  knowledgeBodyTrustNotice: "正文和来源均按不可信资料展示；嵌入指令只作为文本，不执行。",
  knowledgeSourceSelector: "选择关联来源",
  knowledgeHistoryEmpty: "该知识条目尚无历史版本。",
  knowledgeHistoryMore: "读取更多版本",
  knowledgeVersion: "版本",
  revisionTitle: "标题",
  revisionSummary: "摘要",
  revisionContent: "完整正文",
  revisionReason: "修订原因",
  revisionReasonPlaceholder: "说明这次修订与当前版本相比改变了什么",
  submitRevision: "提交审核",
  cancel: "取消",
  revisionSubmitted: "修订提案已提交，审核通过后才会生成新版本。",
  revisionSubmitPending: "正在提交修订…",
  reloadLatestKnowledge: "重新读取最新版本",
  knowledgeState: "知识状态",
  knowledgeRevision: "版本",
  knowledgeActive: "有效",
  knowledgeSuperseded: "已由新版本替代",
  knowledgeWithdrawn: "已撤回",
  knowledgeExpired: "已过期",
  knowledgeSourceWithdrawn: "来源已撤回",
  knowledgeSourceExpired: "来源已过期",
  knowledgeSourceUnavailable: "来源不可用",
  knowledgeStateUnknown: "状态未知",
  viewKnowledgeBody: "查看完整正文",
  viewOriginalSource: "查看原始来源",
  viewKnowledgeHistory: "查看版本历史",
  proposeKnowledgeRevision: "提交修订提案",
};

const knowledgeItem: KnowledgeItem = {
  knowledgeItemId: "item-1",
  teamId: "team-1",
  knowledgeBaseId: "kb-1",
  batchId: "batch-1",
  sourceArtifactIds: ["local-source-1"],
  centralSourceIds: ["central-source-1"],
  title: "知识条目标题",
  summary: "知识条目摘要",
  content: "卡片上的摘要正文",
  tags: ["reviewed"],
  importanceLevel: "high",
  confidence: 0.9,
  stability: "stable",
  scope: "team",
  reviewPriority: "normal",
  createdAt: "2026-10-01T00:00:00Z",
  updatedAt: "2026-10-02T00:00:00Z",
  reviewedAt: "2026-10-02T00:00:00Z",
  appliedAt: "2026-10-02T00:00:00Z",
  reviewedByAgentId: "reviewer-1",
  markedBy: "reviewer-1",
  markedAt: "2026-10-02T00:00:00Z",
  markingReason: "",
  knowledgeState: "active",
  revision: 2,
  contentSha256: "old-hash",
};

const activeKnowledgeBase: TeamKnowledgeBase = {
  knowledgeBaseId: "kb-1",
  scopedKnowledgeBaseId: "scoped-kb-1",
  teamId: "team-1",
  teamName: "团队一",
  name: "团队知识库",
  description: "",
  status: "active",
  acl: {},
  createdAt: "2026-10-01T00:00:00Z",
  updatedAt: "2026-10-02T00:00:00Z",
  stats: { sourceArtifactCount: 1, pendingProposalCount: 0, proposalCount: 1, itemCount: 1, batchCount: 1 },
  pendingProposals: [],
  permissions: { canRead: true, canPropose: true, canReview: true, canRate: true },
};

function bodyPage(
  content: string,
  readMode: "item" | "source" = "item",
  item: KnowledgeItem = knowledgeItem,
): KnowledgeItemBodyPage & { content: string } {
  return {
    knowledgeBaseId: item.knowledgeBaseId,
    scopedKnowledgeBaseId: item.knowledgeBaseId === "kb-1" ? "scoped-kb-1" : item.knowledgeBaseId,
    knowledgeItemId: item.knowledgeItemId,
    title: item.title,
    content,
    contentLength: content.length,
    offset: 0,
    returnedChars: content.length,
    hasMore: false,
    nextOffset: null,
    sourceArtifactIds: item.sourceArtifactIds,
    centralSourceIds: item.centralSourceIds || [],
    citations: [],
    sourceBodyStatus: readMode === "source" ? "source_body_available" : "source_body_unavailable",
    contentSha256: "f".repeat(64),
    revision: item.revision,
    rootKnowledgeItemId: item.rootKnowledgeItemId || item.knowledgeItemId,
    readMode,
    untrusted: true,
    contentTrust: "untrusted_reference_material",
    embeddedInstructionsAreData: true,
  };
}

const ratingDraft: MemoryKnowledgeRatingDraft = {
  actorAgentId: "reviewer-1",
  importanceLevel: "high",
  confidence: "0.9",
  stability: "stable",
  scope: "team",
  reviewPriority: "normal",
  markingReason: "",
};

function knowledgeHistoryPage(title: string, item: KnowledgeItem = knowledgeItem, hasMore = false): KnowledgeItemHistoryPage {
  return {
    knowledgeBaseId: item.knowledgeBaseId,
    ownerType: "team",
    ownerId: item.teamId,
    rootKnowledgeItemId: item.rootKnowledgeItemId || item.knowledgeItemId,
    versionCount: 1,
    versions: [{
      knowledgeItemId: `${item.knowledgeItemId}-version-1`,
      revision: 1,
      contentSha256: "history-hash",
      contentLength: 12,
      state: "superseded",
      title,
      reviewedAt: "2026-10-01T00:00:00Z",
      reviewedByAgentId: "reviewer-1",
      supersedesKnowledgeItemId: "",
      revisionReason: "Earlier version",
    }],
    offset: 0,
    nextOffset: hasMore ? 1 : null,
    hasMore,
    offsetUnit: "versions",
    readMode: "history",
    untrusted: true,
    embeddedInstructionsAreData: true,
  };
}

const onLifecycleChanged = vi.fn();
const onTraceTargetChange = vi.fn();
const onRatingDraftChange = vi.fn();
const onUpdateKnowledgeRating = vi.fn();
let root: Root;
let host: HTMLDivElement;

function makePanel(options: {
  activeKnowledgeBase?: TeamKnowledgeBase | null;
  knowledgeItems?: KnowledgeItem[];
  agentId?: string;
} = {}) {
  return (
    <MemoryKnowledgeDetailPanel
      copy={copy}
      activeKnowledgeBase={options.activeKnowledgeBase === undefined ? activeKnowledgeBase : options.activeKnowledgeBase}
      traceTargetId=""
      trace={undefined}
      knowledgeItems={options.knowledgeItems || [knowledgeItem]}
      knowledgeItemsPending={false}
      ratingDraft={ratingDraft}
      knowledgeBusy={false}
      agentId={options.agentId || "agent-1"}
      onLifecycleChanged={onLifecycleChanged}
      onTraceTargetChange={onTraceTargetChange}
      onRatingDraftChange={onRatingDraftChange}
      onUpdateKnowledgeRating={onUpdateKnowledgeRating}
    />
  );
}

async function mount(options?: Parameters<typeof makePanel>[0]) {
  await act(async () => root.render(makePanel(options)));
}

function button(label: string, index = 0): HTMLButtonElement {
  const found = [...document.body.querySelectorAll<HTMLButtonElement>("button")].filter((candidate) => candidate.textContent?.includes(label))[index];
  if (!found) {
    throw new Error(`Button not found: ${label}`);
  }
  return found;
}

function setTextareaValue(element: HTMLTextAreaElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
  setter?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
  element.dispatchEvent(new Event("change", { bubbles: true }));
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.mocked(readKnowledgeItemBodyAllPages).mockReset();
  vi.mocked(fetchKnowledgeItemBody).mockReset();
  vi.mocked(createKnowledgeRevisionProposal).mockReset();
  onLifecycleChanged.mockReset();
  onTraceTargetChange.mockReset();
  onRatingDraftChange.mockReset();
  onUpdateKnowledgeRating.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

describe("formal knowledge lifecycle actions", () => {
  it("opens a revision from the complete current body and submits the current hash through review", async () => {
    const currentBody = bodyPage("正式知识完整正文");
    vi.mocked(readKnowledgeItemBodyAllPages).mockResolvedValue(currentBody);
    vi.mocked(createKnowledgeRevisionProposal).mockResolvedValue({} as never);
    await mount();

    await act(async () => button(copy.proposeKnowledgeRevision).click());
    await vi.waitFor(() => expect(document.body.querySelectorAll("textarea")).toHaveLength(2));
    const textareas = [...document.body.querySelectorAll<HTMLTextAreaElement>("textarea")];
    expect(textareas[0].value).toBe("正式知识完整正文");
    expect(readKnowledgeItemBodyAllPages).toHaveBeenCalledWith(expect.objectContaining({
      knowledgeBaseId: "scoped-kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
      readMode: "item",
    }));

    await act(async () => {
      setTextareaValue(textareas[1], "来源已复核，补充一项限制条件");
    });
    await act(async () => button(copy.submitRevision).click());

    await vi.waitFor(() => expect(createKnowledgeRevisionProposal).toHaveBeenCalledOnce());
    expect(createKnowledgeRevisionProposal).toHaveBeenCalledWith("scoped-kb-1", expect.objectContaining({
      sourceArtifactIds: ["local-source-1"],
      content: "正式知识完整正文",
      proposedByAgentId: "agent-1",
      supersedesKnowledgeItemId: "item-1",
      expectedContentSha256: "f".repeat(64),
      revisionReason: "来源已复核，补充一项限制条件",
    }));
    await vi.waitFor(() => expect(document.body.textContent).toContain(copy.revisionSubmitted));
    expect(onLifecycleChanged).toHaveBeenCalledOnce();
  });

  it("reads original source only through its linked local artifact id", async () => {
    const sourceBody = bodyPage("受控来源快照正文", "source");
    vi.mocked(readKnowledgeItemBodyAllPages).mockResolvedValue(sourceBody);
    await mount();

    await act(async () => button(copy.viewOriginalSource).click());
    await vi.waitFor(() => expect(document.body.textContent).toContain("受控来源快照正文"));
    expect(readKnowledgeItemBodyAllPages).toHaveBeenCalledWith(expect.objectContaining({
      knowledgeBaseId: "scoped-kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
      readMode: "source",
      sourceArtifactId: "local-source-1",
    }));
    expect(document.body.textContent).toContain(copy.knowledgeBodyTrustNotice);
  });

  it.each([
    "superseded",
    "withdrawn",
    "expired",
    "source_withdrawn",
    "source_expired",
    "source_unavailable",
    "unknown",
  ])("disables current body and source reads for %s knowledge while keeping history readable", async (knowledgeState) => {
    await mount({ knowledgeItems: [{ ...knowledgeItem, knowledgeState }] });

    expect(button(copy.viewKnowledgeBody).disabled).toBe(true);
    expect(button(copy.viewOriginalSource).disabled).toBe(true);
    expect(button(copy.viewKnowledgeHistory).disabled).toBe(false);

    await act(async () => {
      button(copy.viewKnowledgeBody).click();
      button(copy.viewOriginalSource).click();
    });
    expect(readKnowledgeItemBodyAllPages).not.toHaveBeenCalled();
    expect(fetchKnowledgeItemBody).not.toHaveBeenCalled();
  });

  it.each([
    { label: copy.viewKnowledgeBody, mode: "item" as const, change: "knowledgeBase" as const },
    { label: copy.viewOriginalSource, mode: "source" as const, change: "agent" as const },
    { label: copy.viewKnowledgeHistory, mode: "history" as const, change: "both" as const },
  ])("closes an old $mode read when the active $change scope changes", async ({ label, mode, change }) => {
    const body = deferred<KnowledgeItemBodyPage>();
    const history = deferred<KnowledgeItemHistoryPage>();
    if (mode === "history") {
      vi.mocked(fetchKnowledgeItemBody).mockReturnValue(history.promise as never);
    } else {
      vi.mocked(readKnowledgeItemBodyAllPages).mockReturnValue(body.promise);
    }

    await mount();
    await act(async () => button(label).click());
    expect(document.body.querySelector('[role="dialog"]')).toBeTruthy();

    const nextKnowledgeBase: TeamKnowledgeBase = {
      ...activeKnowledgeBase,
      knowledgeBaseId: "kb-2",
      scopedKnowledgeBaseId: "scoped-kb-2",
      name: "第二个知识库",
    };
    const changedKnowledgeBase = change === "knowledgeBase" || change === "both" ? nextKnowledgeBase : activeKnowledgeBase;
    const changedAgentId = change === "agent" || change === "both" ? "agent-2" : "agent-1";
    await mount({ activeKnowledgeBase: changedKnowledgeBase, knowledgeItems: [], agentId: changedAgentId });

    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    if (mode === "history") {
      expect(fetchKnowledgeItemBody).toHaveBeenCalledTimes(1);
      expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({
        knowledgeBaseId: "scoped-kb-1",
        knowledgeItemId: "item-1",
        agentId: "agent-1",
        readMode: "history",
      }));
    } else {
      expect(readKnowledgeItemBodyAllPages).toHaveBeenCalledTimes(1);
      expect(readKnowledgeItemBodyAllPages).toHaveBeenCalledWith(expect.objectContaining({
        knowledgeBaseId: "scoped-kb-1",
        knowledgeItemId: "item-1",
        agentId: "agent-1",
        readMode: mode,
      }));
    }

    await act(async () => {
      body.resolve(bodyPage("stale private body", mode === "source" ? "source" : "item"));
      history.resolve(knowledgeHistoryPage("Stale history entry"));
      await Promise.all([body.promise, history.promise]);
    });
    expect(document.body.textContent).not.toContain("stale private body");
    expect(document.body.textContent).not.toContain("Stale history entry");
  });

  it("does not let an old revision proposal complete inside a changed Agent and knowledge-base scope", async () => {
    const submission = deferred<unknown>();
    vi.mocked(readKnowledgeItemBodyAllPages).mockResolvedValue(bodyPage("第一条完整正文"));
    vi.mocked(createKnowledgeRevisionProposal).mockReturnValue(submission.promise as never);

    await mount();
    await act(async () => button(copy.proposeKnowledgeRevision).click());
    await vi.waitFor(() => expect(document.body.querySelectorAll("textarea")[0]?.value).toBe("第一条完整正文"));
    await act(async () => setTextareaValue(document.body.querySelectorAll<HTMLTextAreaElement>("textarea")[1], "第一条修订原因"));
    await act(async () => button(copy.submitRevision).click());
    expect(createKnowledgeRevisionProposal).toHaveBeenCalledOnce();

    const nextKnowledgeBase: TeamKnowledgeBase = {
      ...activeKnowledgeBase,
      knowledgeBaseId: "kb-2",
      scopedKnowledgeBaseId: "scoped-kb-2",
      name: "第二个知识库",
    };
    await mount({ activeKnowledgeBase: nextKnowledgeBase, knowledgeItems: [], agentId: "agent-2" });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();

    await act(async () => {
      submission.resolve({});
      await submission.promise;
    });
    expect(document.body.textContent).not.toContain(copy.revisionSubmitted);
    expect(onLifecycleChanged).not.toHaveBeenCalled();
  });

  it("does not append a late history page to the newly selected knowledge item", async () => {
    const oldNextPage = deferred<KnowledgeItemHistoryPage>();
    const nextKnowledgeBase: TeamKnowledgeBase = {
      ...activeKnowledgeBase,
      knowledgeBaseId: "kb-2",
      scopedKnowledgeBaseId: "scoped-kb-2",
      name: "第二个知识库",
    };
    const nextItem: KnowledgeItem = {
      ...knowledgeItem,
      knowledgeBaseId: "kb-2",
      knowledgeItemId: "item-2",
      title: "第二条知识",
      sourceArtifactIds: ["local-source-2"],
    };
    vi.mocked(fetchKnowledgeItemBody)
      .mockResolvedValueOnce(knowledgeHistoryPage("旧条目初始版本", knowledgeItem, true))
      .mockReturnValueOnce(oldNextPage.promise as never)
      .mockResolvedValueOnce(knowledgeHistoryPage("当前条目版本", nextItem));

    await mount();
    await act(async () => button(copy.viewKnowledgeHistory).click());
    await vi.waitFor(() => expect(document.body.textContent).toContain("旧条目初始版本"));
    await act(async () => button(copy.knowledgeHistoryMore).click());

    await mount({ activeKnowledgeBase: nextKnowledgeBase, knowledgeItems: [nextItem], agentId: "agent-2" });
    expect(document.body.querySelector('[role="dialog"]')).toBeNull();
    await act(async () => button(copy.viewKnowledgeHistory).click());
    await vi.waitFor(() => expect(document.body.textContent).toContain("当前条目版本"));

    await act(async () => {
      oldNextPage.resolve(knowledgeHistoryPage("旧条目迟到版本", knowledgeItem));
      await oldNextPage.promise;
    });
    expect(document.body.textContent).toContain("当前条目版本");
    expect(document.body.textContent).not.toContain("旧条目迟到版本");
    expect(fetchKnowledgeItemBody).toHaveBeenCalledWith(expect.objectContaining({
      knowledgeBaseId: "scoped-kb-2",
      knowledgeItemId: "item-2",
      agentId: "agent-2",
      readMode: "history",
    }));
  });
});
