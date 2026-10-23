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
  vi.resetAllMocks();
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
async function render(agentId = "agent-companion", strict = false) {
  const panel = <QueryClientProvider client={client}>
    <PersonalAssistantDialoguePreferences agentId={agentId} />
  </QueryClientProvider>;
  await act(async () => root.render(strict ? <React.StrictMode>{panel}</React.StrictMode> : panel));
  await settle(); await settle();
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise; reject = rejectPromise;
  });
  return { promise, resolve, reject };
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
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "natural", preferenceProposalMode: "ask_first",
    });
    expect(document.body.textContent).toContain("已保存");
  });

  it("surfaces a save failure as an alert without crashing", async () => {
    vi.mocked(updateVirtualHumanDialogueSettings).mockRejectedValue(new Error("助理未启用对话偏好"));
    await render();
    await chooseOption("提问主动性", "主动");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", {
      speakingInitiative: "natural", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.querySelector('p[role="alert"]')?.textContent).toContain("助理未启用对话偏好");
  });

  it("keeps a second field selection while a delayed first save is running", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...settings, speakingInitiative: "talkative", questionInitiative: "proactive" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await chooseOption("提问主动性", "主动");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(1);
    expect(document.body.textContent).toContain("正在保存…");
    expect(document.body.textContent).toContain("等待保存…");
    expect((document.querySelector('button[aria-label="说话主动性"]') as HTMLButtonElement).disabled).toBe(true);
    expect((document.querySelector('button[aria-label="提问主动性"]') as HTMLButtonElement).disabled).toBe(false);
    await act(async () => first.resolve({ ...settings, speakingInitiative: "talkative" }));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.querySelector('button[aria-label="说话主动性"]')?.textContent).toContain("健谈");
    expect(document.querySelector('button[aria-label="提问主动性"]')?.textContent).toContain("主动");
  });

  it("preserves other customized fields in the replacement PUT", async () => {
    const customized: VirtualHumanDialogueSettings = {
      ...settings, speakingInitiative: "restrained", questionInitiative: "few", preferenceProposalMode: "manual_only",
    };
    vi.mocked(fetchVirtualHumanDialogueSettings).mockResolvedValue(customized);
    vi.mocked(updateVirtualHumanDialogueSettings).mockResolvedValue({ ...customized, speakingInitiative: "talkative" });
    await render();
    await chooseOption("说话主动性", "健谈");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "few", preferenceProposalMode: "manual_only",
    });
  });

  it("keeps the latest queued choice and prevents duplicate saves of the active field", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...settings, speakingInitiative: "talkative", questionInitiative: "few" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await act(async () => (document.querySelector('button[aria-label="说话主动性"]') as HTMLButtonElement).click());
    expect(document.querySelector('[role="option"]')).toBeNull();
    await chooseOption("提问主动性", "主动");
    await chooseOption("提问主动性", "少问");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve({ ...settings, speakingInitiative: "talkative" }));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "few", preferenceProposalMode: "ask_first",
    });
  });

  it("continues queued fields after failure and lets the failed choice be retried", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...settings, questionInitiative: "proactive" })
      .mockResolvedValueOnce({ ...settings, speakingInitiative: "talkative", questionInitiative: "proactive" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await chooseOption("提问主动性", "主动");
    await act(async () => first.reject(new Error("保存暂时失败")));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "natural", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("保存暂时失败");
    expect((document.querySelector('button[aria-label="说话主动性"]') as HTMLButtonElement).disabled).toBe(false);
    expect(document.querySelector('button[aria-label="说话主动性"]')?.textContent).toContain("自然");
    await chooseOption("说话主动性", "健谈");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(3);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it("keeps accepted saves serial across StrictMode unmount and remount of the same Agent", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    const second = deferred<VirtualHumanDialogueSettings>();
    const stored = { ...settings };
    const update = vi.mocked(updateVirtualHumanDialogueSettings);
    vi.mocked(fetchVirtualHumanDialogueSettings).mockImplementation(async () => ({ ...stored }));
    update.mockImplementation(async (_agentId, payload) => {
      const response = update.mock.calls.length === 1
        ? await first.promise
        : update.mock.calls.length === 2
          ? await second.promise
          : { ...stored, ...payload };
      Object.assign(stored, response);
      return response;
    });
    await render("agent-companion", true);
    await chooseOption("说话主动性", "健谈");
    await chooseOption("提问主动性", "主动");
    await act(async () => root.render(null));
    await render("agent-companion", true);
    await chooseOption("提问主动性", "少问");
    expect(update).toHaveBeenCalledTimes(1);
    await act(async () => root.render(null));
    await act(async () => first.resolve({ ...settings, speakingInitiative: "talkative" }));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    await render("agent-companion", true);
    expect(document.body.textContent).toContain("正在保存…");
    expect(document.querySelector('button[aria-label="提问主动性"]')?.textContent).toContain("少问");
    expect((document.querySelector('button[aria-label="提问主动性"]') as HTMLButtonElement).disabled).toBe(true);
    await chooseOption("偏好建议", "仅手动");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    expect(document.body.textContent).toContain("等待保存…");
    await act(async () => second.resolve({ ...settings, speakingInitiative: "talkative", questionInitiative: "few" }));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(3);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "few", preferenceProposalMode: "manual_only",
    });
  });

  it("cancels an old remount GET before it can overwrite successful saves", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    const staleRead = deferred<VirtualHumanDialogueSettings>();
    let remountSignal: AbortSignal | undefined;
    vi.mocked(fetchVirtualHumanDialogueSettings)
      .mockResolvedValueOnce({ ...settings })
      .mockImplementationOnce((_agentId, options) => { remountSignal = options?.signal; return staleRead.promise; });
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...settings, speakingInitiative: "talkative", questionInitiative: "proactive" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await chooseOption("提问主动性", "主动");
    await act(async () => root.render(null));
    await render();
    expect(remountSignal?.aborted).toBe(false);
    await act(async () => first.resolve({ ...settings, speakingInitiative: "talkative" }));
    await settle();
    expect(remountSignal?.aborted).toBe(true);
    await act(async () => staleRead.resolve({ ...settings }));
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: "talkative", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.querySelector('button[aria-label="说话主动性"]')?.textContent).toContain("健谈");
    expect(document.querySelector('button[aria-label="提问主动性"]')?.textContent).toContain("主动");
  });

  it("shows a save failure that finished while hidden on remount and allows retry", async () => {
    const first = deferred<VirtualHumanDialogueSettings>();
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => first.promise)
      .mockResolvedValueOnce({ ...settings, speakingInitiative: "talkative" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await act(async () => root.render(null));
    await act(async () => first.reject(new Error("隐藏期间保存失败")));
    await settle();
    await render();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("隐藏期间保存失败");
    await chooseOption("说话主动性", "健谈");
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(2);
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });

  it.each(["success", "failure"] as const)("isolates an old Agent's in-flight %s while completing its accepted queue", async outcome => {
    const oldSave = deferred<VirtualHumanDialogueSettings>();
    const newSave = deferred<VirtualHumanDialogueSettings>();
    const newSettings = { ...settings, agentId: "agent-new", preferenceProposalMode: "manual_only" as const };
    vi.mocked(fetchVirtualHumanDialogueSettings).mockImplementation(async agentId => agentId === "agent-new" ? newSettings : settings);
    vi.mocked(updateVirtualHumanDialogueSettings)
      .mockImplementationOnce(() => oldSave.promise)
      .mockImplementationOnce(() => newSave.promise)
      .mockResolvedValueOnce({ ...settings, speakingInitiative: outcome === "success" ? "talkative" : "natural", questionInitiative: "proactive" });
    await render();
    await chooseOption("说话主动性", "健谈");
    await chooseOption("提问主动性", "主动");
    await render("agent-new");
    expect(document.body.textContent).not.toContain("等待保存…");
    await chooseOption("说话主动性", "克制");
    await act(async () => {
      if (outcome === "success") oldSave.resolve({ ...settings, speakingInitiative: "talkative" });
      else oldSave.reject(new Error("旧助理保存失败"));
    });
    await settle();
    expect(updateVirtualHumanDialogueSettings).toHaveBeenCalledTimes(3);
    expect(updateVirtualHumanDialogueSettings).toHaveBeenLastCalledWith("agent-companion", {
      speakingInitiative: outcome === "success" ? "talkative" : "natural", questionInitiative: "proactive", preferenceProposalMode: "ask_first",
    });
    expect(document.body.textContent).not.toContain("旧助理保存失败");
    expect((document.querySelector('button[aria-label="说话主动性"]') as HTMLButtonElement).disabled).toBe(true);
    expect(document.querySelector('button[aria-label="说话主动性"]')?.textContent).toContain("克制");
    expect(document.querySelector('button[aria-label="偏好建议"]')?.textContent).toContain("仅手动");
    await act(async () => newSave.resolve({ ...newSettings, speakingInitiative: "restrained" }));
    await settle();
    expect((document.querySelector('button[aria-label="说话主动性"]') as HTMLButtonElement).disabled).toBe(false);
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
