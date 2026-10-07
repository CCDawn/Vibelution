// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FinanceAnalystTeam, FinanceAnalystTeamInspector } from "./FinanceAnalystTeam";
import type { FinancialTeamRun } from "../../api/financialTeam";
import type { FinancialAssistant } from "../../api/financialAssistant";

const api = vi.hoisted(() => ({
  team: vi.fn(), provision: vi.fn(), runs: vi.fn(), exact: vi.fn(), create: vi.fn(), session: vi.fn(), primary: vi.fn(),
  record: vi.fn(), debate: vi.fn(), synthesis: vi.fn(), stop: vi.fn(), approvals: vi.fn().mockResolvedValue([]),
  recoveryStatus: vi.fn(), recoverSynthesis: vi.fn(),
  reportText: vi.fn(),
}));
vi.mock("../../api/financialReports", async (original) => ({ ...await original<typeof import("../../api/financialReports")>(), fetchFinancialReportText: api.reportText }));
vi.mock("../../api/financialTeam", async () => ({
  ...await vi.importActual<typeof import("../../api/financialTeam")>("../../api/financialTeam"),
  createFinancialTeamRun: api.create,
  fetchFinancialTeam: api.team,
  fetchFinancialTeamRuns: api.runs,
  fetchFinancialTeamRun: api.exact,
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
  fetchFinancialTeamSynthesisRecoveryStatus: api.recoveryStatus,
  recoverFinancialTeamSynthesis: api.recoverSynthesis,
}));
vi.mock("../../api/chat", () => ({
  fetchSessionDetail: api.session,
  stopSessionTurn: api.stop,
  listPendingSessionToolApprovals: (...args: unknown[]) => api.approvals(...args) ?? Promise.resolve([]),
  resolveSessionToolApprovalDecision: vi.fn(),
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

async function render(onSelectedRunChange?: (run: FinancialTeamRun | null) => void, requestedRunId = "") {
  await act(async () => root.render(<QueryClientProvider client={client}><FinanceAnalystTeam assistant={assistant} stock={stock} zh requestedRunId={requestedRunId} onOpenSession={openSession} onSelectedRunChange={onSelectedRunChange} /></QueryClientProvider>));
  await settle();
}

function button(text: string) {
  return [...container.querySelectorAll("button")].find((node) => node.textContent?.includes(text))!;
}

it("keeps the inspector on the selected research when switching run history", async () => {
  const recent = makeRun();
  const earlier = { ...makeRun(), runId: "earlier-run", symbol: "sz000001" };
  currentRun = recent;
  api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [recent, earlier] });
  const onSelectedRunChange = vi.fn();
  await render(onSelectedRunChange);
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(recent);
  await act(async () => button("sz000001").click());
  await settle();
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(earlier);
});

it("loads an exact batch run outside recent history instead of substituting the newest run", async () => {
  currentRun = makeRun();
  currentRun.coordinationStatus = "completed";
  const earlier = { ...makeRun(), runId: "older-batch-run", symbol: "sz000001", coordinationStatus: "completed" as const };
  let resolve!: (run: FinancialTeamRun) => void;
  api.exact.mockReturnValue(new Promise((done) => { resolve = done; }));
  const onSelectedRunChange = vi.fn();
  await render(onSelectedRunChange, earlier.runId);
  expect(container.textContent).toContain("读取所选研究");
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(null);
  expect(api.exact).toHaveBeenCalledWith(assistant.agentId, earlier.runId, expect.any(Object));
  await act(async () => resolve(earlier)); await settle();
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(earlier);
  expect(api.primary).not.toHaveBeenCalled();
});

it("keeps unavailable or cross-owner exact runs out of the latest-run result", async () => {
  currentRun = makeRun();
  api.exact.mockRejectedValueOnce(new Error("missing run"));
  const onSelectedRunChange = vi.fn();
  await render(onSelectedRunChange, "older-batch-run");
  expect(container.textContent).toContain("所选研究无法读取");
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(null);
  api.exact.mockResolvedValue({ ...makeRun(), runId: "older-batch-run", assistantAgentId: "other" });
  await act(async () => { await client.refetchQueries({ queryKey: ["financial-team", assistant.agentId, "run", "older-batch-run"] }); });
  expect(onSelectedRunChange).toHaveBeenLastCalledWith(null);
  expect(api.primary).not.toHaveBeenCalled();
});

it("opens the selected synthesis and requires completed coordination with all Turn references", async () => {
  const run = makeRun();
  run.symbol = "sz000001";
  run.stage = "synthesis";
  run.coordinationStatus = "completed";
  run.synthesis.sessionId = "selected-synthesis";
  await act(async () => root.render(<FinanceAnalystTeamInspector run={run} zh onOpenSession={openSession} />));
  expect(container.textContent).toContain("sz000001");
  expect(container.textContent).not.toContain("已完成汇总");
  expect(button("查看汇总对话").disabled).toBe(true);
  roleKeys.forEach((role) => { run.analysts[role]!.turnId = "turn-" + role; });
  run.synthesis.turnId = "synthesis-turn";
  await act(async () => root.render(<FinanceAnalystTeamInspector run={run} zh onOpenSession={openSession} />));
  expect(container.textContent).toContain("已完成汇总");
  await act(async () => button("查看汇总对话").click());
  expect(openSession).toHaveBeenCalledWith("selected-synthesis");
});

it("shows the resolved per-role model effort and explains capability adjustment", async () => {
  currentRun = makeRun();
  currentRun.executionPolicy = {
    requestedDepth: "detailed",
    requestedReasoningEffort: "high",
    roles: {
      market: { requestedReasoningEffort: "high", resolvedReasoningEffort: "medium", status: "adjusted" },
      fundamental: { requestedReasoningEffort: "high", resolvedReasoningEffort: "high", status: "applied" },
      news: { requestedReasoningEffort: "high", resolvedReasoningEffort: "high", status: "applied" },
      bull: { requestedReasoningEffort: "high", resolvedReasoningEffort: "high", status: "applied" },
      bear: { requestedReasoningEffort: "high", resolvedReasoningEffort: "medium", status: "adjusted" },
    },
    synthesis: { requestedReasoningEffort: "high", resolvedReasoningEffort: null, status: "unknown" },
  };
  api.runs.mockResolvedValue({ assistantAgentId: assistant.agentId, runs: [currentRun] });
  await render();
  const summary = container.querySelector<HTMLElement>("[data-depth-execution]");
  expect(summary?.textContent).toContain("模型档位");
  expect(summary?.textContent).toContain("行情 中*");
  expect(summary?.textContent).toContain("基本 高");
  expect(summary?.textContent).toContain("汇总 默认");
  expect(summary?.title).toContain("请求4 · 深入");
  expect(summary?.title).toContain("受模型能力限制");
  expect(summary?.getAttribute("aria-label")).toBe(summary?.title);
});

it("keeps accepted Turns out of not-submitted state when reads fail and refreshes their details", async () => {
  currentRun = makeRun();
  currentRun.coordinationStatus = "completed";
  roleKeys.forEach((role) => { currentRun!.analysts[role]!.turnId = "turn-" + role; });
  currentRun.synthesis.turnId = "synthesis-turn";
  api.session.mockRejectedValue(new Error("offline"));
  await render();
  expect(container.textContent).toContain("部分对话暂无法读取");
  expect(container.querySelector('[role="status"]')?.textContent).toContain("—/5");
  expect(container.textContent).not.toContain("未提交");
  api.session.mockImplementation(async (sessionId: string) => {
    const ref = sessionId === currentRun!.synthesis.sessionId ? currentRun!.synthesis : Object.values(currentRun!.analysts).find((item) => item?.sessionId === sessionId);
    return detailFor(sessionId, ref, "本轮完成答案");
  });
  await act(async () => button("刷新").click());
  await settle();
  expect(container.querySelector('[role="status"]')?.textContent).toContain("5/5");
  expect(container.textContent).not.toContain("部分对话暂无法读取");
  expect(api.primary).not.toHaveBeenCalled();
});

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
  api.recoveryStatus.mockResolvedValue({ available: false, reason: "" });
  api.reportText.mockResolvedValue("综合结论");
});

afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  container.remove();
});

describe("Finance analyst team", () => {
  it("shows the exact exported synthesis instead of unsupported native conclusion amounts", async () => {
    currentRun = makeRun();
    currentRun.coordinationStatus = "completed";
    currentRun.stage = "synthesis";
    roleKeys.forEach((role) => { currentRun!.analysts[role]!.turnId = "turn-" + role; });
    currentRun.synthesis.turnId = "turn-synthesis";
    const raw = "## 结论\n利润999亿元。";
    api.session.mockImplementation(async (sessionId: string) => {
      const ref = sessionId === currentRun!.synthesis.sessionId ? currentRun!.synthesis : Object.values(currentRun!.analysts).find((item) => item?.sessionId === sessionId);
      return detailFor(sessionId, ref, sessionId === currentRun!.synthesis.sessionId ? raw : "本轮分析");
    });
    api.reportText.mockResolvedValue("## 结论\n利润没有这一项。");
    await render();
    const synthesis = container.querySelector("[data-financial-team-synthesis]");
    expect(synthesis?.textContent).not.toContain("999亿元");
    expect(synthesis?.textContent).toContain("没有这一项");
    expect(synthesis?.textContent).toContain("部分数字未通过核验");
    const analysts = container.querySelector("[data-financial-team-analysts]");
    expect(Boolean(synthesis!.compareDocumentPosition(analysts!) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
    expect(api.reportText).toHaveBeenCalledWith({ assistantAgentId: assistant.agentId, sessionId: "session-assistant", turnId: "turn-synthesis" }, { signal: expect.any(AbortSignal) });
    await act(async () => button("补充证据").click());
    expect(openSession).toHaveBeenCalledWith("session-assistant");
    expect(api.synthesis).not.toHaveBeenCalled();
    expect(api.primary).not.toHaveBeenCalled();
  });

  it("does not request a formal report for a stopped synthesis even if its final item has text", async () => {
    currentRun = makeRun();
    currentRun.coordinationStatus = "blocked";
    currentRun.stage = "synthesis";
    roleKeys.forEach((role) => { currentRun!.analysts[role]!.turnId = "turn-" + role; });
    currentRun.synthesis.turnId = "turn-synthesis";
    api.session.mockImplementation(async (sessionId: string) => {
      const ref = sessionId === currentRun!.synthesis.sessionId ? currentRun!.synthesis : Object.values(currentRun!.analysts).find((item) => item?.sessionId === sessionId);
      const detail = detailFor(sessionId, ref, "终止前遗留内容");
      return sessionId === currentRun!.synthesis.sessionId ? { ...detail, terminalReason: "stopped", lastTurnTerminalTurnId: "turn-synthesis" } : detail;
    });
    await render();
    expect(api.reportText).not.toHaveBeenCalled();
    expect(container.querySelector("[data-financial-team-synthesis]")?.textContent).toContain("已停止");
    const analysts = container.querySelector("[data-financial-team-analysts]");
    const synthesis = container.querySelector("[data-financial-team-synthesis]");
    expect(Boolean(analysts!.compareDocumentPosition(synthesis!) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true);
  });

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
    await act(async () => button("查看对话").click());
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
    expect(container.textContent).toContain("已提交，等待状态同步");
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

  it("shows a persisted coordination block without automatically resending a stage", async () => {
    currentRun = makeRun();
    for (const role of ["market", "fundamental", "news"] as const) currentRun.analysts[role]!.turnId = "turn-" + role;
    currentRun.coordinationStatus = "blocked";
    currentRun.coordinationError = "分析员配置已变化，请核对团队配置。";
    await render();
    expect(container.textContent).toContain("分析员配置已变化，请核对团队配置。");
    expect(container.textContent).not.toContain("重试多空分析");
    expect(api.debate).not.toHaveBeenCalled();
    expect(api.synthesis).not.toHaveBeenCalled();
  });

  it("shows explicit synthesis recovery only after the backend validates the blocked run", async () => {
    currentRun = makeRun();
    for (const role of roleKeys) currentRun.analysts[role]!.turnId = "turn-" + role;
    currentRun.coordinationStatus = "blocked";
    currentRun.coordinationError = "汇总阶段提交失败或结果未知。";
    api.recoveryStatus.mockResolvedValue({ available: false, reason: "本轮后台协作仍在运行。" });
    api.recoveryStatus.mockResolvedValueOnce({ available: true, reason: "" });
    api.recoverSynthesis.mockImplementation(async () => {
      currentRun = { ...currentRun!, coordinationStatus: "waiting", coordinationError: "" };
      return structuredClone(currentRun);
    });

    await render();

    expect(container.textContent).toContain("恢复本轮汇总");
    expect(api.recoveryStatus).toHaveBeenCalledWith(assistant.agentId, currentRun.runId, expect.any(Object));
    expect(api.recoverSynthesis).not.toHaveBeenCalled();
    await act(async () => button("恢复本轮汇总").click());
    await settle();
    expect(api.recoverSynthesis).toHaveBeenCalledWith(assistant.agentId, currentRun.runId);
    expect(api.primary).not.toHaveBeenCalled();
    expect(api.debate).not.toHaveBeenCalled();
    expect(container.textContent).not.toContain("恢复本轮汇总");
  });

  it.each(["waiting", "running", "completed"] as const)("leaves %s coordination with the server without submitting duplicate stages", async (coordinationStatus) => {
    currentRun = makeRun();
    currentRun.coordinationStatus = coordinationStatus;
    for (const role of coordinationStatus === "completed" ? roleKeys : roleKeys.slice(0, 3)) currentRun.analysts[role]!.turnId = "turn-" + role;
    if (coordinationStatus === "completed") currentRun.synthesis.turnId = "turn-synthesis";
    await render();
    expect(api.debate).not.toHaveBeenCalled();
    expect(api.synthesis).not.toHaveBeenCalled();
    if (coordinationStatus !== "completed") expect(container.textContent).not.toContain("重试多空分析");
    else expect(container.textContent).toContain("主助手已汇总");
  });

  it("keeps accepted server-coordinated turns fresh after the legacy polling window", async () => {
    currentRun = makeRun();
    currentRun.createdAt = new Date(Date.now() - 45 * 60 * 1000).toISOString();
    currentRun.coordinationStatus = "running";
    currentRun.analysts.market!.turnId = "turn-market";
    api.session.mockImplementation(async (sessionId: string) => sessionId === "session-market"
      ? detailFor(sessionId, currentRun!.analysts.market, "分析中", "running")
      : detailFor(sessionId, undefined, ""));
    await render();
    const before = api.session.mock.calls.filter(([sessionId]) => sessionId === "session-market").length;
    await act(async () => new Promise((resolve) => setTimeout(resolve, 1900)));
    expect(api.session.mock.calls.filter(([sessionId]) => sessionId === "session-market").length).toBeGreaterThan(before);
    expect(api.primary).not.toHaveBeenCalled();
  });

  it("reads the exact synthesis again when background coordination completes", async () => {
    currentRun = makeRun();
    currentRun.createdAt = new Date(Date.now() - 45 * 60 * 1000).toISOString();
    currentRun.coordinationStatus = "running";
    for (const role of roleKeys) currentRun.analysts[role]!.turnId = "turn-" + role;
    currentRun.synthesis.turnId = "turn-synthesis";
    const fetchDetail = api.session.getMockImplementation()!;
    api.session.mockImplementation(async (sessionId: string) => sessionId === "session-assistant" && currentRun!.coordinationStatus !== "completed"
      ? detailFor(sessionId, currentRun!.synthesis, "汇总分析中", "running")
      : fetchDetail(sessionId));
    await render();
    expect(container.textContent).toContain("主助手汇总中");
    currentRun = { ...currentRun, coordinationStatus: "completed" };
    await act(async () => client.invalidateQueries({ queryKey: ["financial-team", assistant.agentId, "runs"] }));
    await settle();
    expect(container.textContent).toContain("主助手已汇总");
    expect(api.synthesis).not.toHaveBeenCalled();
  });

  it.each([["failed", "失败"], ["stopped", "已停止"], ["incomplete", "缺少最终回答"]])("does not describe %s synthesis as running or waiting", async (state, label) => {
    currentRun = makeRun();
    currentRun.coordinationStatus = "blocked";
    for (const role of roleKeys) currentRun.analysts[role]!.turnId = "turn-" + role;
    currentRun.synthesis.turnId = "turn-synthesis";
    const fetchDetail = api.session.getMockImplementation()!;
    api.session.mockImplementation(async (sessionId: string) => {
      if (sessionId !== "session-assistant") return fetchDetail(sessionId);
      const detail = detailFor(sessionId, currentRun!.synthesis, "", state === "failed" ? "failed" : "completed");
      return state === "stopped" ? { ...detail, terminalReason: "stopped", lastTurnTerminalTurnId: "turn-synthesis" } : detail;
    });
    await render();
    expect(container.textContent).toContain(`汇总${label}`);
    expect(container.textContent).not.toContain("主助手汇总中");
    expect(container.textContent).not.toContain("等待主助手汇总");
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
