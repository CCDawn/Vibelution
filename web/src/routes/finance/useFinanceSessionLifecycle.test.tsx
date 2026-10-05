// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type Router } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deleteChatSession, fetchSessionDetail, querySessions } from "../../api/chat";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../../api/financialAssistant";
import { FetchJsonHttpError } from "../../api/client";
import type { SessionDetail, SessionSummary } from "../../api/types";
import { isSessionDeleteTombstoned, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import { useFinanceSessionLifecycle } from "./useFinanceSessionLifecycle";

vi.mock("../../api/chat", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../api/chat")>()), deleteChatSession: vi.fn(), fetchSessionDetail: vi.fn(), querySessions: vi.fn() }));
vi.mock("../../api/sessionArchive", () => ({ archiveChatSession: vi.fn(), unarchiveChatSession: vi.fn() }));
vi.mock("../../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const current = { id: "current", agentId: "finance-a", title: "待管理研究", status: "idle", taskSummary: "completed report", lastActive: "", updatedAt: "", currentPhase: "" } as SessionSummary;
const next = { ...current, id: "next", title: "下一条研究" };
const indexKey = ["sessions", "finance", "finance-a"];
let state: ReturnType<typeof useFinanceSessionLifecycle>;
let client: QueryClient, router: Router, root: Root, container: HTMLElement;
function Host() { state = useFinanceSessionLifecycle("finance-a", true); return <>{state.dialog}<output>{state.error}</output></>; }
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }
beforeEach(async () => {
  vi.resetAllMocks(); resetSessionDeleteTombstonesForTests();
  vi.mocked(fetchSessionDetail).mockImplementation(async (id) => ({ ...current, id, messages: [] }) as SessionDetail);
  vi.mocked(querySessions).mockResolvedValue({ items: [next], nextCursor: "" });
  vi.mocked(archiveChatSession).mockResolvedValue({ sessionId: current.id, status: "archived", changed: true });
  vi.mocked(unarchiveChatSession).mockResolvedValue({ sessionId: current.id, status: "active", changed: true });
  vi.mocked(deleteChatSession).mockResolvedValue({ deleted: true, deletedSessionId: current.id, nextActiveSessionId: "foreign-agent-session" });
  vi.mocked(listFinancialAssistants).mockResolvedValue([{ agentId: "finance-a", status: "active", setupStatus: "ready", directSessionId: "direct" } as FinancialAssistant]);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(indexKey, { pages: [{ items: [current, next], nextCursor: "" }], pageParams: [""] });
  router = createMemoryRouter([{ path: "*", element: <Host /> }], { initialEntries: ["/finance?session=current"] });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root.render(<QueryClientProvider client={client}><RouterProvider router={router} /></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); resetSessionDeleteTombstonesForTests(); });
function indexedIds() { return (client.getQueryData(indexKey) as { pages: { items: SessionSummary[] }[] }).pages.flatMap((page) => page.items.map((row) => row.id)); }

describe("native financial research lifecycle", () => {
  it("archives once and selects only a surviving owned native research", async () => {
    await act(async () => { state.requestAction(current, "archive"); state.requestAction(current, "archive"); }); await settle();
    expect(archiveChatSession).toHaveBeenCalledTimes(1);
    expect(indexedIds()).toEqual(["next"]);
    expect(router.state.location.search).toBe("?session=next");
    expect(fetchSessionDetail).toHaveBeenCalledWith("next", expect.objectContaining({ transcriptScope: "none" }));
  });
  it("retains a rejected archive and its committed selection", async () => {
    vi.mocked(archiveChatSession).mockRejectedValue(new Error("研究正在运行，请先停止"));
    await act(async () => state.requestAction(current, "archive")); await settle();
    expect(indexedIds()).toEqual(["current", "next"]);
    expect(router.state.location.search).toBe("?session=current");
    expect(state.error).toContain("请先停止");
  });
  it("uses native delete after confirmation and ignores another Agent's replacement id", async () => {
    await act(async () => state.requestAction(current, "delete"));
    expect(deleteChatSession).not.toHaveBeenCalled();
    const confirm = [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "删除研究") as HTMLButtonElement;
    expect(confirm).toBeTruthy();
    await act(async () => { confirm.click(); confirm.click(); }); await settle();
    expect(deleteChatSession).toHaveBeenCalledTimes(1);
    expect(isSessionDeleteTombstoned("current")).toBe(true);
    expect(indexedIds()).toEqual(["next"]);
    expect(router.state.location.search).toBe("?session=next");
  });
  it("restores an archive through the existing native endpoint", async () => {
    vi.mocked(fetchSessionDetail).mockResolvedValue({ ...current, messages: [], hiddenFromIndex: true, archiveState: { status: "archived" } } as SessionDetail);
    await act(async () => state.requestAction({ ...current, archiveState: { status: "archived" } }, "restore")); await settle();
    expect(unarchiveChatSession).toHaveBeenCalledTimes(1);
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(deleteChatSession).not.toHaveBeenCalled();
    expect(router.state.location.search).toBe("?session=current");
  });
  it("repairs a deleted last direct session through the existing owner provisioning", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ agentId: "finance-a", status: "active", setupStatus: "session_missing", directSessionId: "" } as FinancialAssistant]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: false, assistant: { agentId: "finance-a", status: "active", setupStatus: "ready", directSessionId: "replacement-direct" } as FinancialAssistant });
    vi.mocked(querySessions).mockResolvedValue({ items: [{ ...next, id: "replacement-direct" }], nextCursor: "" });
    await act(async () => state.requestAction(current, "delete"));
    const confirm = [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "删除研究") as HTMLButtonElement;
    await act(async () => confirm.click()); await settle();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(router.state.location.search).toBe("?session=replacement-direct");
    expect(isSessionDeleteTombstoned("current")).toBe(true);
  });
  it("reconciles a verified delete after an unknown response instead of retaining a ghost row", async () => {
    vi.mocked(deleteChatSession).mockRejectedValueOnce(new Error("删除响应未知"));
    await act(async () => state.requestAction(current, "delete"));
    const confirmation = () => [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "删除研究") as HTMLButtonElement;
    await act(async () => confirmation().click()); await settle();
    expect(indexedIds()).toContain("current");
    vi.mocked(fetchSessionDetail).mockRejectedValueOnce(new FetchJsonHttpError("session not found", { status: 404 }));
    await act(async () => confirmation().click()); await settle();
    expect(deleteChatSession).toHaveBeenCalledTimes(2);
    expect(indexedIds()).not.toContain("current");
    expect(isSessionDeleteTombstoned("current")).toBe(true);
  });
  it("rejects a changed ownership before sending any mutation", async () => {
    vi.mocked(fetchSessionDetail).mockResolvedValue({ ...current, agentId: "foreign", messages: [] } as SessionDetail);
    await act(async () => state.requestAction(current, "archive")); await settle();
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(state.error).toContain("不属于当前助手");
    expect(indexedIds()).toContain("current");
  });
  it("does not navigate after leaving while native archiving is pending", async () => {
    let finish!: (value: Awaited<ReturnType<typeof archiveChatSession>>) => void;
    vi.mocked(archiveChatSession).mockReturnValue(new Promise((resolve) => { finish = resolve; }));
    await act(async () => state.requestAction(current, "archive")); await settle();
    await act(async () => root.render(<div>another page</div>));
    await act(async () => finish({ sessionId: current.id, status: "archived", changed: true })); await settle();
    expect(querySessions).not.toHaveBeenCalled();
    expect(router.state.location.search).toBe("?session=current");
    expect(container.textContent).toBe("another page");
  });
});
