// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FinanceAnalystTeam } from "./FinanceAnalystTeam";
import type { FinancialTeamRun } from "../../api/financialTeam";
import type { FinancialAssistant } from "../../api/financialAssistant";

const api = vi.hoisted(() => ({
  team: vi.fn(), provision: vi.fn(), runs: vi.fn(), create: vi.fn(), session: vi.fn(), primary: vi.fn(),
  record: vi.fn(), debate: vi.fn(), synthesis: vi.fn(), stop: vi.fn(),
}));
vi.mock("../../api/financialTeam", async () => ({
  ...await vi.importActual<typeof import("../../api/financialTeam")>("../../api/financialTeam"),
  createFinancialTeamRun: api.create,
  fetchFinancialTeam: api.team,
  fetchFinancialTeamRuns: api.runs,
  financialTeamKeys: {
    detail: (id: string) => ["financial-team", id],
    runs: (id: string) => ["financial-team", id, "runs"],
    run: (id: string, runId: string) => ["financial-team", id, "run", runId],
  },
  provisionFinancialTeam: api.provision,
  recordFinancialTeamTurn: api.record,
  submitFinancialTeamPrimaryRole: api.primary,
  submitFinancialTeamDebate: api.debate,
  submitFinancialTeamSynthesis: api.synthesis,
}));
vi.mock("../../api/chat", () => ({
  fetchSessionDetail: api.session,
  stopSessionTurn: api.stop,
}));
vi.mock("../../components/conversation/LazyConversationMarkdownRenderer", () => ({
  LazyConversationMarkdownRenderer: ({ content }: { content: string }) => <div data-markdown>{content}</div>,
}));

Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
const assistant = { agentId: "finance-owner" } as FinancialAssistant;
const stock = { symbol: "sh600519", ticker: "600519", name: "贵州茅台", market: "上交所" };
const roleKeys = ["market", "fundamental", "news", "bull", "bear"] as const;
const labels: Record<(typeof roleKeys)[number], string> = { market: "行情", fundamental: "基本面", news: "新闻", bull: "乐观研究", bear: "审慎研究" };
let root: Root, client: QueryClient, container: HTMLDivElement, currentRun: FinancialTeamRun | null;
const openSession = vi.fn();

function team(status: "ready" | "needs_setup" = "ready") {
  return {
    assistantAgentId: assistant.agentId,
    assistantSessionId: "session-assistant",
    teamId: "team-1",
    status,
    modelBindings: {},
    assistantConfigRevision: 1,
    roles: roleKeys.map((role) => ({ role, label: labels[role], agentId: "agent-" + role, sessionId: "session-" + role, status: status === "ready" ? "ready" : "not_created", allowedTools: [] })),
  };
}

function makeRun(): FinancialTeamRun {
  const analysts = Object.fromEntries(roleKeys.map((role) => [role, {
    agentId: "agent-" + role,
    sessionId: "session-" + role,
    clientSubmissionId: "submission-" + role,
    turnId: "",
  }]));
  return {
    schemaVersion: 2,
    runId: "run-1",
    assistantAgentId: assistant.agentId,
    teamId: "team-1",
    symbol: stock.symbol,
    periodDays: 30,
    researchDate: "2026-10-05",
    depth: "standard",
    createdAt: new Date().toISOString(),
    stage: "research",
    analysts,
    synthesis: { agentId: assistant.agentId, sessionId: "session-assistant", clientSubmissionId: "submission-synthesis", turnId: "" },
  };
}

function detailFor(sessionId: string, ref: { clientSubmissionId: string; turnId: string } | undefined, text: string, status = "completed") {
  if (!ref?.turnId) return {
    id: sessionId, title: sessionId, agentId: "agent", status: "ready", taskSummary: "", lastActive: "", updatedAt: "",
    currentPhase: "ready", defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [], messages: [],
  };
  const messages = [
    { id: "user-" + ref.clientSubmissionId, timestamp: "2026-10-05T00:00:00Z", role: "user", content: "prompt", metadata: { clientSubmissionId: ref.clientSubmissionId, turnId: ref.turnId } },
    { id: "assistant-" + ref.turnId, timestamp: "2026-10-05T00:00:01Z", role: "assistant", turnId: ref.turnId, status, metadata: { clientSubmissionId: ref.clientSubmissionId, turnId: ref.turnId }, turnItems: [{ id: "item-" + ref.turnId, itemId: "item-" + ref.turnId, version: 3, sessionId, turnId: ref.turnId, status: status === "completed" ? "completed" : "running", revision: 1, sequence: 1, type: "agent_message", phase: status === "completed" ? "final_answer" : "commentary", text }] },
  ];
  return {
    id: sessionId, title: sessionId, agentId: "agent", status: status === "completed" ? "ready" : "running", taskSummary: "", lastActive: "", updatedAt: "",
    currentPhase: status, defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [], messages,
    lastTurnTerminalTurnId: status === "completed" ? ref.turnId : "",
    terminalReason: status === "completed" ? "success" : "",
  };
}

async function settle(rounds = 5) {
  for (let index = 0; index < rounds; index += 1) {
    await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
  }
}

async function render() {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceAnalystTeam assistant={assistant} stock={stock} zh onOpenSession={openSession} /></QueryClientProvider>));
  await settle();
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((node) => node.textContent?.includes(text))!;
}

beforeEach(() => {
  vi.resetAllMocks();
  currentRun = null;
  openSession.mockReset();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  api.team.mockImplementation(async () => team());
  api.runs.mockImplementation(async () => ({ assistantAgentId: assistant.agentId, runs: currentRun ? [currentRun] : [] }));
  api.provision.mockImplementation(async () => team());
  api.create.mockImplementation(async () => {
    currentRun = makeRun();
    return currentRun;
  });
  api.session.mockImplementation(async (sessionId: string) => {
    if (!currentRun) return detailFor(sessionId, undefined, "");
    const role = roleKeys.find((key) => currentRun?.analysts[key]?.sessionId === sessionId);
    if (role) return detailFor(sessionId, currentRun.analysts[role], labels[role] + "本轮回答");
    if (currentRun.synthesis.sessionId === sessionId) return detailFor(sessionId, currentRun.synthesis, "综合结论");
    return detailFor(sessionId, undefined, "");
  });
  api.primary.mockImplementation(async (_agentId: string, _runId: string, role: (typeof roleKeys)[number]) => {
    currentRun!.analysts[role]!.turnId = "turn-" + role;
    return structuredClone(currentRun);
  });
  api.record.mockImplementation(async (_agentId: string, _runId: string, role: string, payload: { turnId: string }) => {
    if (role === "synthesis") currentRun!.synthesis.turnId = payload.turnId;
    else currentRun!.analysts[role as (typeof roleKeys)[number]]!.turnId = payload.turnId;
    return structuredClone(currentRun);
  });
  api.debate.mockImplementation(async () => {
    currentRun!.analysts.bull!.turnId = "turn-bull";
    currentRun!.analysts.bear!.turnId = "turn-bear";
    currentRun!.stage = "debate";
    return structuredClone(currentRun);
  });
  api.synthesis.mockImplementation(async () => {
    currentRun!.synthesis.turnId = "turn-synthesis";
    currentRun!.stage = "synthesis";
    return structuredClone(currentRun);
  });
  api.stop.mockResolvedValue({});
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
});

describe("Finance analyst team", () => {
  it("requires an explicit setup action before provisioning the five native Agents", async () => {
    api.team.mockImplementation(async () => team("needs_setup"));
    await render();
    expect(container.textContent).toContain("需要初始化 5 位分析员");
    expect(api.provision).not.toHaveBeenCalled();
    await act(async () => button("初始化团队").click());
    await settle();
    expect(api.provision).toHaveBeenCalledTimes(1);
    expect(api.provision).toHaveBeenCalledWith(assistant.agentId);
  });

  it("submits three native analysts, starts independent bull/bear turns, then synthesizes", async () => {
    await render();
    await act(async () => button("开始五方研究").click());
    await settle(12);
    expect(api.create).toHaveBeenCalledWith(assistant.agentId, expect.objectContaining({
      symbol: stock.symbol,
      periodDays: 30,
      researchDate: expect.stringMatching(/^\d{4}-\d{2}-\d{2}$/),
      depth: "standard",
    }), expect.stringMatching(/^[0-9a-f-]{36}$/i));
    expect(api.primary).toHaveBeenCalledTimes(3);
    for (const role of roleKeys.slice(0, 3)) {
      expect(api.primary).toHaveBeenCalledWith(assistant.agentId, "run-1", role);
    }
    expect(api.record).not.toHaveBeenCalled();
    expect(api.debate).toHaveBeenCalledWith(assistant.agentId, "run-1");
    expect(api.synthesis).toHaveBeenCalledWith(assistant.agentId, "run-1");
    expect(container.textContent).toContain("乐观研究本轮回答");
    expect(container.textContent).toContain("审慎研究本轮回答");
    expect(container.textContent).toContain("综合结论");
    await act(async () => button("原生会话").click());
    expect(openSession).toHaveBeenCalledWith(expect.stringMatching(/^session-/));
  });

  it("recovers a native Turn by exact client submission ID after refresh without resubmitting it", async () => {
    currentRun = makeRun();
    currentRun.analysts.market!.turnId = "";
    api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [currentRun] });
    api.session.mockImplementation(async (sessionId: string) => {
      if (sessionId === "session-market") return detailFor(sessionId, { clientSubmissionId: "submission-market", turnId: "turn-market" }, "已恢复的行情结论");
      return detailFor(sessionId, undefined, "");
    });
    await render();
    await settle();
    expect(api.primary).not.toHaveBeenCalled();
    expect(api.record).toHaveBeenCalledWith(assistant.agentId, "run-1", "market", {
      sessionId: "session-market",
      clientSubmissionId: "submission-market",
      turnId: "turn-market",
    });
    expect(container.textContent).toContain("已恢复的行情结论");
  });
  it.each(["running", "completed"])("combines the durable segment with the same Turn's %s live overlay", async (status) => {
    currentRun = makeRun();
    currentRun.analysts.market!.turnId = "turn-market";
    api.session.mockImplementation(async (sessionId: string) => {
      if (sessionId !== "session-market") return detailFor(sessionId, undefined, "");
      const detail = detailFor(sessionId, currentRun!.analysts.market, "实时行情结论", status);
      const live = { ...detail.messages[1], id: "assistant-live", metadata: { turnId: "turn-market" } };
      const persisted = { ...detail.messages[1], id: "assistant-durable", status: "completed", turnItems: [] };
      return { ...detail, messages: [detail.messages[0], persisted, live] };
    });
    await render();
    const card = container.querySelector('article[data-role="market"]')!;
    expect(card.textContent).not.toContain("缺少最终回答");
    if (status === "running") {
      expect(card.textContent).toContain("分析中");
      expect(card.textContent).toContain("停止本轮");
      expect(api.debate).not.toHaveBeenCalled();
    } else {
      expect(card.textContent).toContain("已完成");
      expect(card.textContent).toContain("实时行情结论");
    }
  });

  it("does not display a neighboring assistant turn that belongs to another submission", async () => {
    currentRun = makeRun();
    currentRun.analysts.market!.turnId = "turn-market";
    api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [currentRun] });
    api.session.mockImplementation(async (sessionId: string) => {
      if (sessionId !== "session-market") return detailFor(sessionId, undefined, "");
      const detail = detailFor(sessionId, currentRun!.analysts.market, "", "running");
      detail.messages = [
        { id: "user-market", timestamp: "2026-10-05T00:00:00Z", role: "user", content: "prompt", metadata: { clientSubmissionId: "submission-market", turnId: "turn-market" } },
        { id: "assistant-other", timestamp: "2026-10-05T00:00:01Z", role: "assistant", turnId: "turn-other", status: "completed", metadata: { clientSubmissionId: "submission-other", turnId: "turn-other" }, turnItems: [{ id: "item-other", itemId: "item-other", version: 1, sessionId, turnId: "turn-other", status: "completed", revision: 1, sequence: 1, type: "agent_message", phase: "final_answer", text: "错误的相邻回答" }] },
      ];
      return detail;
    });
    await render();
    expect(container.textContent).toContain("提交已记录，等待原生 Turn");
    expect(container.textContent).not.toContain("错误的相邻回答");
    expect(api.record).not.toHaveBeenCalled();
  });

  it.each(["本轮已按请求停止。", "This turn was stopped as requested."])("does not advance a stopped native notice represented as a completed answer: %s", async (notice) => {
    currentRun = makeRun();
    for (const role of ["market", "fundamental", "news"] as const) currentRun.analysts[role]!.turnId = "turn-" + role;
    api.session.mockImplementation(async (sessionId: string) => {
      const role = roleKeys.find((key) => currentRun?.analysts[key]?.sessionId === sessionId);
      return detailFor(sessionId, role ? currentRun!.analysts[role] : undefined, role === "market" ? notice : "完成的分析");
    });
    await render();
    expect(api.debate).not.toHaveBeenCalled();
    expect(container.querySelector('article[data-role="market"]')?.textContent).toContain("缺少最终回答");
    expect(container.textContent).toContain("重新开始研究");
  });

  it("reuses the same run-creation key after an ambiguous transport failure", async () => {
    api.create.mockRejectedValueOnce(new Error("network timeout"));
    await render();
    await act(async () => button("开始五方研究").click());
    await settle();
    const firstKey = api.create.mock.calls[0]?.[2];
    expect(firstKey).toMatch(/^[0-9a-f-]{36}$/i);

    await act(async () => button("开始五方研究").click());
    await settle(12);
    expect(api.create).toHaveBeenCalledTimes(2);
    expect(api.create.mock.calls[1]?.[2]).toBe(firstKey);
  });

  it.each([["failed", "失败"], ["completed", "缺少最终回答"]])("starts a fresh run with fresh submissions after a role Turn is %s without an answer", async (status, label) => {
    currentRun = makeRun();
    currentRun.analysts.market!.turnId = "turn-market-old";
    api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [currentRun] });
    api.session.mockImplementation(async (sessionId: string) => sessionId === "session-market"
      ? detailFor(sessionId, { clientSubmissionId: "submission-market", turnId: "turn-market-old" }, "", status)
      : detailFor(sessionId, undefined, ""));

    const restarted = makeRun();
    restarted.runId = "run-2";
    for (const role of roleKeys) restarted.analysts[role]!.clientSubmissionId += "-fresh";
    api.create.mockImplementation(async () => {
      currentRun = restarted;
      return restarted;
    });

    await render();
    expect(container.textContent).toContain(label);
    expect(container.textContent).toContain("重新开始研究");
    await act(async () => button("重新开始研究").click());
    await settle(12);

    expect(api.create).toHaveBeenCalledWith(assistant.agentId, {
      symbol: "sh600519",
      periodDays: 30,
      researchDate: "2026-10-05",
      depth: "standard",
    }, expect.stringMatching(/^[0-9a-f-]{36}$/i));
    expect(api.primary).toHaveBeenCalledWith(assistant.agentId, "run-2", "market");
  });

  it("stops the selected role's exact Session and Turn", async () => {
    currentRun = makeRun();
    currentRun.analysts.market!.turnId = "turn-market";
    api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [currentRun] });
    api.session.mockImplementation(async (sessionId: string) => sessionId === "session-market"
      ? detailFor(sessionId, currentRun!.analysts.market, "正在核对行情", "running")
      : detailFor(sessionId, undefined, ""));
    await render();
    await act(async () => button("停止本轮").click());
    await settle();
    expect(api.stop).toHaveBeenCalledWith("session-market", "turn-market");
  });
});
