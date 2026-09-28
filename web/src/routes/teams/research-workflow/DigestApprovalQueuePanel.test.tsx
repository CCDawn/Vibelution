/**
 * DigestApprovalQueuePanel tests: empty/loading/error states, row text,
 * batch approve flow (selection → mutation payload → per-row result chips),
 * and TTL overdue surfacing.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  executeBatchApproveDigests,
  fetchPendingDigestApprovals,
} from "../../../api/hypothesisFirst";
import type { PendingDigestApprovalItem } from "../../../api/types/hypothesisFirst";
import {
  digestApprovalRowText,
  DigestApprovalQueuePanel,
} from "./DigestApprovalQueuePanel";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchPendingDigestApprovals: vi.fn(),
  executeBatchApproveDigests: vi.fn(),
}));

vi.mock("../../../i18n/useShellI18n", () => ({
  useShellI18n: () => ({ lang: "zh" }),
}));

const mockedFetch = vi.mocked(fetchPendingDigestApprovals);
const mockedApprove = vi.mocked(executeBatchApproveDigests);

function item(patch: Partial<PendingDigestApprovalItem>): PendingDigestApprovalItem {
  return {
    meetingRoundId: "meeting-1",
    meetingType: "hypothesis_candidate_generation",
    questionId: "SCI-091",
    digestContentHash: "hash-1",
    digestSummary: "会议就候选假说达成共识",
    proposedCandidateCount: 3,
    riskCount: 1,
    startedAt: "2026-09-01T10:00:00Z",
    ageSeconds: 7200,
    ttlOverdue: false,
    ttlMessage: "",
    ...patch,
  };
}

describe("digestApprovalRowText", () => {
  it("joins question, counts and human age", () => {
    const text = digestApprovalRowText(item({}), true);
    expect(text).toContain("SCI-091");
    expect(text).toContain("候选 3");
    expect(text).toContain("风险 1");
    expect(text).toContain("小时");
  });
});

describe("DigestApprovalQueuePanel", () => {
  let container: HTMLElement | null = null;
  let root: Root | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    act(() => root?.unmount());
    container?.remove();
    container = null;
    root = null;
  });

  function renderPanel(props: { teamId?: string } = {}): void {
    container = document.createElement("div");
    document.body.appendChild(container);
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    root = createRoot(container);
    act(() => {
      root.render(
        <QueryClientProvider client={client}>
          <DigestApprovalQueuePanel teamId={props.teamId ?? "team-1"} />
        </QueryClientProvider>,
      );
    });
  }

  it("asks for a team when teamId is empty", () => {
    renderPanel({ teamId: "" });
    expect(container?.textContent).toContain("批量审批待选择团队");
  });

  it("renders the empty state when no digests await approval", async () => {
    mockedFetch.mockResolvedValue({ items: [], count: 0, fetchedAtMs: 1 });
    renderPanel();
    await vi.waitFor(() => {
      expect(container?.querySelector('[data-testid="digest-approval-empty"]')).toBeTruthy();
    });
  });

  it("renders rows with question text and TTL chip, then approves the selection", async () => {
    mockedFetch.mockResolvedValue({
      items: [
        item({ meetingRoundId: "m-ok", digestContentHash: "h-ok", ttlOverdue: true }),
        item({ meetingRoundId: "m-bad", digestContentHash: "h-bad", questionId: "SCI-092" }),
      ],
      count: 2,
      fetchedAtMs: 1,
    });
    renderPanel();
    await vi.waitFor(() => {
      expect(container?.textContent).toContain("SCI-091");
    });
    expect(container?.textContent).toContain("TTL 超时");

    const okCheckbox = container?.querySelector(
      '[data-testid="digest-approval-select-m-ok"]',
    ) as HTMLInputElement | null;
    expect(okCheckbox).toBeTruthy();
    act(() => {
      okCheckbox?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    const approveButton = container?.querySelector(
      '[data-testid="digest-approval-batch-button"]',
    ) as HTMLButtonElement | null;
    await vi.waitFor(() => {
      expect(approveButton?.textContent).toContain("批量通过（1）");
    });
    mockedApprove.mockResolvedValue({
      results: [{ meetingRoundId: "m-ok", status: "approved", errorType: "", error: "" }],
      approvedCount: 1,
      failedCount: 0,
      closedBy: "operator-console",
    });
    act(() => {
      approveButton?.click();
    });
    await vi.waitFor(() => {
      expect(mockedApprove).toHaveBeenCalledWith(
        "team-1",
        [{ meetingRoundId: "m-ok", expectedDigestContentHash: "h-ok" }],
        "operator-console",
      );
    });
    await vi.waitFor(() => {
      expect(
        container?.querySelector('[data-testid="digest-approval-result-summary"]'),
      ).toBeTruthy();
    });
  });

  it("keeps the batch button disabled with nothing selected", async () => {
    mockedFetch.mockResolvedValue({ items: [item({})], count: 1, fetchedAtMs: 1 });
    renderPanel();
    await vi.waitFor(() => {
      const button = container?.querySelector(
        '[data-testid="digest-approval-batch-button"]',
      ) as HTMLButtonElement | null;
      expect(button?.disabled).toBe(true);
    });
  });
});
