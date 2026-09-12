/**
 * ResearchWorkflowRecoveryPanel tests: open-failure aggregation, read-only
 * waiting rows, on-demand technical detail, confirmed single/batch retry
 * hand-off (row goes pending until the ledger resolves it), and the fail-
 * silent entry strip that only appears while open failures exist.
 *
 * @vitest-environment happy-dom
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  executeHypothesisRoundFailureRetry,
  fetchHypothesisRoundFailures,
} from "../../../api/hypothesisFirst";
import type {
  HypothesisRoundFailureRecord,
  HypothesisRoundFailuresResponse,
} from "../../../api/types/hypothesisFirst";
import {
  ResearchWorkflowRecoveryEntry,
  ResearchWorkflowRecoveryPanel,
} from "./ResearchWorkflowRecoveryPanel";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisRoundFailures: vi.fn(),
  executeHypothesisRoundFailureRetry: vi.fn(),
}));

vi.mock("../../../i18n/useShellI18n", () => ({
  useShellI18n: () => ({ lang: "zh" }),
}));

const mockedFetch = vi.mocked(fetchHypothesisRoundFailures);
const mockedRetry = vi.mocked(executeHypothesisRoundFailureRetry);

function record(patch: Partial<HypothesisRoundFailureRecord>): HypothesisRoundFailureRecord {
  return {
    failureId: "hrfail-sci091-1",
    status: "failed",
    failureCode: "hypothesis_round_precondition_failed",
    reason: "candidate sci-091-c1 requires a non-empty claim",
    errorType: "ContractValidationError",
    roundId: "hround-1",
    meetingRoundIds: ["meeting-a"],
    selectionId: "selection-1",
    roundIndex: 1,
    questionId: "SCI-091",
    workflowRunId: "run-1",
    scopeHash: "scope-1",
    retryHint: "re-generate the round",
    trigger: "auto_advance",
    createdAt: "2026-09-12T04:00:00Z",
    resolvedAt: "",
    resolvedByRoundId: "",
    ...patch,
  };
}

function payload(records: HypothesisRoundFailureRecord[]): HypothesisRoundFailuresResponse {
  return {
    schemaVersion: 1,
    teamId: "team-1",
    failureCount: records.length,
    openFailureCount: records.length,
    failures: records,
    storagePath: "ignored",
  };
}

let container: HTMLDivElement;
let root: Root;
let queryClient: QueryClient;

function renderPanel() {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <ResearchWorkflowRecoveryPanel teamId="team-1" lang="zh" />
      </QueryClientProvider>,
    );
  });
}

function renderEntry(onOpen: () => void) {
  act(() => {
    root.render(
      <QueryClientProvider client={queryClient}>
        <ResearchWorkflowRecoveryEntry teamId="team-1" lang="zh" onOpen={onOpen} />
      </QueryClientProvider>,
    );
  });
}

async function flushQueries() {
  for (let index = 0; index < 5; index += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
});

afterEach(() => {
  act(() => {
    root.unmount();
  });
  container.remove();
  queryClient.clear();
});

describe("ResearchWorkflowRecoveryPanel", () => {
  it("renders retryable and waiting counts with read-only waiting rows", async () => {
    mockedFetch.mockResolvedValue(payload([
      record({ failureId: "hrfail-a" }),
      record({
        failureId: "hrfail-b",
        status: "blocked",
        failureCode: "fan_in_waiting_for_sibling_reviews",
        reason: "fan-in pending",
      }),
    ]));
    renderPanel();
    await flushQueries();

    expect(container.querySelector('[data-testid="recovery-count-retryable"]')?.textContent).toContain("1");
    expect(container.querySelector('[data-testid="recovery-count-waiting"]')?.textContent).toContain("1");
    const waitingRow = container.querySelector('[data-testid="recovery-row-hrfail-b"]');
    expect(waitingRow?.querySelector('[data-testid="recovery-arm"]')).toBeNull();
    expect(waitingRow?.querySelector('[data-testid="recovery-action-wait"]')).toBeTruthy();
    const retryableRow = container.querySelector('[data-testid="recovery-row-hrfail-a"]');
    expect(retryableRow?.querySelector('[data-testid="recovery-arm"]')).toBeTruthy();
  });

  it("keeps the technical detail hidden until the row asks for it", async () => {
    mockedFetch.mockResolvedValue(payload([record({})]));
    renderPanel();
    await flushQueries();

    expect(container.textContent).not.toContain("hypothesis_round_precondition_failed");
    const toggle = container.querySelector(
      '[data-testid="recovery-details-hrfail-sci091-1"]',
    ) as HTMLButtonElement | null;
    expect(toggle).toBeTruthy();
    act(() => {
      toggle?.click();
    });
    expect(container.textContent).toContain("hypothesis_round_precondition_failed");
    expect(container.textContent).toContain("candidate sci-091-c1 requires a non-empty claim");
  });

  it("hands one retry to the server after the confirm step and marks the row pending", async () => {
    mockedFetch.mockResolvedValue(payload([record({})]));
    mockedRetry.mockResolvedValue({
      status: "accepted",
      failureId: "hrfail-sci091-1",
    });
    renderPanel();
    await flushQueries();

    const arm = container.querySelector('[data-testid="recovery-arm"]') as HTMLButtonElement | null;
    act(() => {
      arm?.click();
    });
    const confirm = container.querySelector('[data-testid="recovery-confirm"]') as HTMLButtonElement | null;
    expect(confirm).toBeTruthy();
    await act(async () => {
      confirm?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(mockedRetry).toHaveBeenCalledWith("team-1", "hrfail-sci091-1");
    await flushQueries();
    expect(container.querySelector('[data-testid="recovery-action-pending"]')).toBeTruthy();
    expect(container.querySelector('[data-testid="recovery-arm"]')).toBeNull();
  });

  it("retries every retryable row through the batch confirm", async () => {
    mockedFetch.mockResolvedValue(payload([
      record({ failureId: "hrfail-a" }),
      record({ failureId: "hrfail-b", failureCode: "hypothesis_round_generation_error" }),
      record({
        failureId: "hrfail-c",
        status: "blocked",
        failureCode: "fan_in_waiting_for_sibling_reviews",
      }),
    ]));
    mockedRetry.mockResolvedValue({ status: "accepted", failureId: "hrfail-a" });
    renderPanel();
    await flushQueries();

    const batchArm = container.querySelector('[data-testid="recovery-batch-arm"]') as HTMLButtonElement | null;
    expect(batchArm).toBeTruthy();
    act(() => {
      batchArm?.click();
    });
    const batchConfirm = container.querySelector('[data-testid="recovery-batch-confirm"]') as HTMLButtonElement | null;
    expect(batchConfirm?.textContent).toContain("2");
    await act(async () => {
      batchConfirm?.click();
      await new Promise((resolve) => setTimeout(resolve, 0));
    });

    expect(mockedRetry).toHaveBeenCalledTimes(2);
    expect(mockedRetry).toHaveBeenCalledWith("team-1", "hrfail-a");
    expect(mockedRetry).toHaveBeenCalledWith("team-1", "hrfail-b");
  });

  it("shows the entry strip only while open failures exist", async () => {
    mockedFetch.mockResolvedValue(payload([]));
    const onOpen = vi.fn();
    renderEntry(onOpen);
    await flushQueries();
    expect(container.querySelector('[data-testid="research-recovery-entry"]')).toBeNull();

    mockedFetch.mockResolvedValue(payload([record({ failureId: "hrfail-a" })]));
    queryClient.clear();
    renderEntry(onOpen);
    await flushQueries();
    const entry = container.querySelector('[data-testid="research-recovery-entry-open"]') as HTMLButtonElement | null;
    expect(entry?.textContent).toContain("待恢复 1 项");
    act(() => {
      entry?.click();
    });
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});
