/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { useTeamCommunicationEvents } from "./useTeamCommunicationEvents";
import { useResearchWorkflowInsights } from "./research-workflow/useResearchWorkflowInsights";
import type { ResearchProcessPanel } from "./research-workflow/researchProcessPanelSelection";

const api = vi.hoisted(() => ({
  bus: vi.fn(async () => ({ events: [] })),
  ledger: vi.fn(async () => ({})), budget: vi.fn(async () => ({})),
  hypotheses: vi.fn(async () => ({})), campaigns: vi.fn(async () => ({})),
  evaluation: vi.fn(async () => ({})), handoffs: vi.fn(async () => ({})),
}));
vi.mock("../../api/projectAgentBus", async (original) => ({
  ...await original<typeof import("../../api/projectAgentBus")>(),
  listProjectAgentBusTimeline: api.bus,
}));
vi.mock("../../api/researchWorkflow", () => ({
  fetchResearchWorkflowResearchLedger: api.ledger,
  fetchResearchWorkflowBudget: api.budget,
  fetchResearchWorkflowHypotheses: api.hypotheses,
  fetchResearchWorkflowExperimentCampaigns: api.campaigns,
  fetchResearchWorkflowEvaluation: api.evaluation,
  fetchResearchWorkflowHandoffs: api.handoffs,
}));

let root: Root;
let client: QueryClient;
let host: HTMLDivElement;
async function show(ui: React.ReactNode) {
  if (!root) {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }
  await act(async () => { root.render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>); });
}
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  client?.clear(); host?.remove();
  root = undefined as unknown as Root;
  vi.clearAllMocks(); vi.unstubAllGlobals();
});

it("loads communication only when its panel opens", async () => {
  function Probe({ visible }: { visible: boolean }) {
    useTeamCommunicationEvents("research-team", visible);
    return null;
  }
  await show(<Probe visible={false} />);
  expect(api.bus).not.toHaveBeenCalled();
  await show(<Probe visible />);
  expect(api.bus).toHaveBeenCalledOnce();
});

it("loads node requirements first and overview data when the timeline opens", async () => {
  let latest: ReturnType<typeof useResearchWorkflowInsights>;
  function Probe({ panel }: { panel: ResearchProcessPanel | null }) {
    latest = useResearchWorkflowInsights("research-team", "run-1", panel);
    return null;
  }
  await show(<Probe panel={null} />);
  expect(Object.values(api).every(fn => fn.mock.calls.length === 0)).toBe(true);
  expect(latest!.loading).toBe(false);
  await show(<Probe panel="node" />);
  expect(api.budget).toHaveBeenCalledOnce();
  expect(api.handoffs).toHaveBeenCalledOnce();
  for (const fn of [api.ledger, api.hypotheses, api.campaigns, api.evaluation]) expect(fn).not.toHaveBeenCalled();
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(latest!.loading).toBe(false);
  await show(<Probe panel="timeline" />);
  for (const fn of [api.ledger, api.hypotheses, api.campaigns, api.evaluation]) expect(fn).toHaveBeenCalledOnce();
});
