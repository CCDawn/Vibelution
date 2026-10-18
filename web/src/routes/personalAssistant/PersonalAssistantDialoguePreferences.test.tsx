// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  acceptVirtualHumanPreferenceProposal,
  fetchVirtualHumanDialogueSettings,
  fetchVirtualHumanPreferenceProposals,
  rejectVirtualHumanPreferenceProposal,
  updateVirtualHumanDialogueSettings,
} from "../../api/virtualHumanLife";
import type {
  VirtualHumanDialogueSettings,
  VirtualHumanPreferenceProposalList,
} from "../../api/types/virtualHumanLife";
import { PersonalAssistantDialoguePreferences } from "./PersonalAssistantDialoguePreferences";

vi.mock("../../api/virtualHumanLife", () => ({
  fetchVirtualHumanDialogueSettings: vi.fn(),
  updateVirtualHumanDialogueSettings: vi.fn(),
  fetchVirtualHumanPreferenceProposals: vi.fn(),
  acceptVirtualHumanPreferenceProposal: vi.fn(),
  rejectVirtualHumanPreferenceProposal: vi.fn(),
}));
vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const settings: VirtualHumanDialogueSettings = {
  agentId: "agent-companion",
  speakingInitiative: "natural",
  questionInitiative: "natural",
  preferenceProposalMode: "ask_first",
  updatedAt: "2026-10-19T00:00:00Z",
};

const proposals: VirtualHumanPreferenceProposalList = {
  agentId: "agent-companion",
  proposals: [
    {
      proposalId: "proposal-1",
      agentId: "agent-companion",
      preferenceType: "verbosity",
      candidateValue: "compact",
      sourceTurnId: "turn-1",
      status: "pending",
    },
    {
      proposalId: "proposal-2",
      agentId: "agent-companion",
      preferenceType: "address",
      candidateValue: "老板",
      sourceTurnId: "turn-2",
      status: "accepted",
      decidedAt: "2026-10-18T00:00:00Z",
    },
  ],
};

let root: Root, container: HTMLDivElement, client: QueryClient;
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(fetchVirtualHumanDialogueSettings).mockResolvedValue({ ...settings });
  vi.mocked(fetchVirtualHumanPreferenceProposals).mockResolvedValue({
    agentId: proposals.agentId,
    proposals: proposals.proposals.map(item => ({ ...item })),
  });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, retryDelay: () => 0, gcTime: Infinity } } });
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); client.clear(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 25))); }
async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}>
    <PersonalAssistantDialoguePreferences agentId="agent-companion" />
  </QueryClientProvider>));
  await settle(); await settle();
}
async function chooseOption(ariaLabel: string, optionText: string) {
  const trigger = document.querySelector(`button[role="combobox"][aria-label="${ariaLabel}"]`) as HTMLButtonElement;
  await act(async () => trigger.click());
  const option = await vi.waitFor(() => {
    const found = [...document.body.querySelectorAll('[role="option"]')].find(node => node.textContent === optionText);
    if (!found) throw new Error(`${optionText} options not rendered yet`);
    return found as HTMLElement;
  });
  await act(async () => option.click());
  await settle();
}

describe("PersonalAssistantDialoguePreferences", () => {
  it("renders the three dialogue settings from the backend with mapped labels", async () => {
    await render();
    expect(fetchVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", expect.anything());
    for (const label of ["说话主动性", "提问主动性", "偏好建议"]) {
      expect(document.querySelector(`button[role="combobox"][aria-label="${label}"]`)).toBeTruthy();
    }
    expect(document.querySelector('button[role="combobox"][aria-label="说话主动性"]')?.textContent).toContain("自然");
    expect(document.querySelector('button[role="combobox"][aria-label="偏好建议"]')?.textContent).toContain("先问我");
  });

  it("saves a speaking initiative change through the update API", async () => {
    vi.mocked(updateVirtualHumanDialogueSettings).mockResolvedValue({ ...settings, speakingInitiative: "talkative" });
    await render();
    await chooseOption("说话主动性", "健谈");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", { speakingInitiative: "talkative" });
  });

  it("surfaces a save failure as an alert without crashing", async () => {
    vi.mocked(updateVirtualHumanDialogueSettings).mockRejectedValue(new Error("助理未启用对话偏好"));
    await render();
    await chooseOption("提问主动性", "主动");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", { questionInitiative: "proactive" });
    expect(document.querySelector('p[role="alert"]')?.textContent).toContain("助理未启用对话偏好");
  });

  it("lists pending proposals with mapped type and value labels and decides them", async () => {
    vi.mocked(acceptVirtualHumanPreferenceProposal).mockResolvedValue({
      agentId: "agent-companion",
      proposal: { ...proposals.proposals[0], status: "accepted" },
    });
    await render();
    expect(document.body.textContent).toContain("表达详略");
    expect(document.body.textContent).toContain("建议：偏简短");
    expect(document.body.textContent).toContain("称呼");
    expect(document.body.textContent).toContain("已采纳");
    const accept = [...document.querySelectorAll("button")].find(button => button.textContent === "采纳") as HTMLButtonElement;
    await act(async () => accept.click());
    await settle();
    expect(acceptVirtualHumanPreferenceProposal).toHaveBeenCalledWith("agent-companion", "proposal-1");
    expect(rejectVirtualHumanPreferenceProposal).not.toHaveBeenCalled();
  });

  it("rejects a pending proposal through the reject API", async () => {
    vi.mocked(rejectVirtualHumanPreferenceProposal).mockResolvedValue({
      agentId: "agent-companion",
      proposal: { ...proposals.proposals[0], status: "rejected" },
    });
    await render();
    const reject = [...document.querySelectorAll("button")].find(button => button.textContent === "保留原样") as HTMLButtonElement;
    await act(async () => reject.click());
    await settle();
    expect(rejectVirtualHumanPreferenceProposal).toHaveBeenCalledWith("agent-companion", "proposal-1");
  });

  it("shows an empty state when no proposal is pending", async () => {
    vi.mocked(fetchVirtualHumanPreferenceProposals).mockResolvedValue({ agentId: "agent-companion", proposals: [] });
    await render();
    expect(document.body.textContent).toContain("没有待确认的偏好建议");
  });

  it("shows a retryable read failure for the settings query", async () => {
    vi.mocked(fetchVirtualHumanDialogueSettings).mockRejectedValue(new Error("后端不可用"));
    await render();
    expect(document.body.textContent).toContain("偏好读取失败");
    expect(document.body.textContent).toContain("后端不可用");
    vi.mocked(fetchVirtualHumanDialogueSettings).mockResolvedValue({ ...settings });
    await act(async () => ([...document.querySelectorAll("button")].find(button => button.textContent === "重试") as HTMLButtonElement).click());
    await settle(); await settle();
    expect(document.querySelector('button[role="combobox"][aria-label="说话主动性"]')).toBeTruthy();
  });
});
