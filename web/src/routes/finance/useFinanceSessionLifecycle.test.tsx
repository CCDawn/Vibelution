// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createMemoryRouter, RouterProvider, type Router } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deleteChatSession, fetchSessionDetail, querySessions } from "../../api/chat";
import { queryKeys } from "../../api/queryKeys";
import { archiveChatSession, unarchiveChatSession } from "../../api/sessionArchive";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../../api/financialAssistant";
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
const catalogKey = ["finance", "report-catalog", "finance-a", {}];
const exactKey = ["finance", "exact-report", "finance-a", "current", "report-turn"];
let state: ReturnType<typeof useFinanceSessionLifecycle>;
let client: QueryClient, router: Router, root: Root, container: HTMLElement;
const OwnerContext = React.createContext("finance-a");
function Host() { state = useFinanceSessionLifecycle(React.useContext(OwnerContext), true); return <>{state.dialog}<output aria-label="lifecycle error">{state.error}</output><output aria-label="lifecycle notice">{state.notice}</output><output aria-label="batch undo available">{String(state.canUndoBatchArchive)}</output></>; }
async function switchOwner(agentId = "finance-b") { await act(async () => root.render(<QueryClientProvider client={client}><OwnerContext.Provider value={agentId}><RouterProvider router={router} /></OwnerContext.Provider></QueryClientProvider>)); }
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 15))); }
beforeEach(async () => {
  vi.resetAllMocks(); resetSessionDeleteTombstonesForTests();
  vi.mocked(fetchSessionDetail).mockImplementation(async (id) => ({ ...current, id, messages: [] }) as SessionDetail);
  vi.mocked(querySessions).mockResolvedValue({ items: [next], nextCursor: "" });
  vi.mocked(archiveChatSession).mockResolvedValue({ sessionId: current.id, status: "archived", changed: true });
  vi.mocked(unarchiveChatSession).mockResolvedValue({ sessionId: current.id, status: "active", changed: true });
  vi.mocked(deleteChatSession).mockImplementation(async (id) => ({ deleted: true, deletedSessionId: id, nextActiveSessionId: "foreign-agent-session" }));
  vi.mocked(listFinancialAssistants).mockResolvedValue([{ agentId: "finance-a", status: "active", setupStatus: "ready", directSessionId: "direct" } as FinancialAssistant]);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  client.setQueryData(indexKey, { pages: [{ items: [current, next], nextCursor: "" }], pageParams: [""] });
  client.setQueryData(catalogKey, { pages: [{ items: [{ sessionId: "current", turnId: "report-turn" }, { sessionId: "next", turnId: "next-turn" }], nextCursor: null }], pageParams: [""] });
  client.setQueryData(exactKey, { content: "deleted research report" });
  router = createMemoryRouter([{ path: "*", element: <Host /> }], { initialEntries: ["/finance?session=current"] });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root.render(<QueryClientProvider client={client}><OwnerContext.Provider value="finance-a"><RouterProvider router={router} /></OwnerContext.Provider></QueryClientProvider>));
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); resetSessionDeleteTombstonesForTests(); });
function indexedIds() { return (client.getQueryData(indexKey) as { pages: { items: SessionSummary[] }[] }).pages.flatMap((page) => page.items.map((row) => row.id)); }

describe("native financial research lifecycle", () => {
  it("archives once and selects only a surviving owned native research", async () => {
    client.setQueryData(queryKeys.sessionArchive(), { items: [], nextCursor: "" });
    await act(async () => { state.requestAction(current, "archive"); state.requestAction(current, "archive"); }); await settle();
    expect(archiveChatSession).toHaveBeenCalledTimes(1);
    expect(indexedIds()).toEqual(["next"]);
    expect(client.getQueryState(queryKeys.sessionArchive())?.isInvalidated).toBe(true);
    expect(router.state.location.search).toBe("?session=next");
    expect(fetchSessionDetail).toHaveBeenCalledWith("next", expect.objectContaining({ transcriptScope: "none" }));
    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(true);
    expect(client.getQueryData(exactKey)).toBeDefined(); // Archived reports remain valid case references.
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
    expect(client.getQueryData(exactKey)).toBeUndefined();
    expect((client.getQueryData(catalogKey) as { pages: { items: { sessionId: string }[] }[] }).pages[0].items.map((row) => row.sessionId)).toEqual(["next"]);
  });
  it("restores an archive through the existing native endpoint", async () => {
    client.setQueryData(queryKeys.sessionArchive(), { items: [current], nextCursor: "" });
    vi.mocked(fetchSessionDetail).mockResolvedValue({ ...current, messages: [], hiddenFromIndex: true, archiveState: { status: "archived" } } as SessionDetail);
    await act(async () => state.requestAction({ ...current, archiveState: { status: "archived" } }, "restore")); await settle();
    expect(unarchiveChatSession).toHaveBeenCalledTimes(1);
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(deleteChatSession).not.toHaveBeenCalled();
    expect(indexedIds()).toEqual(["current", "next"]);
    expect(client.getQueryState(indexKey)?.isInvalidated).toBe(true);
    expect(client.getQueryState(queryKeys.sessionArchive())?.isInvalidated).toBe(true);
    expect(router.state.location.search).toBe("?session=current");
    expect(client.getQueryState(catalogKey)?.isInvalidated).toBe(true);
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
    vi.mocked(fetchSessionDetail).mockRejectedValueOnce(new Error("session not found"));
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
  it("rechecks the latest running status before single and batch mutations", async () => {
    const completedSummary = { ...current, status: "completed" } as SessionSummary;
    vi.mocked(fetchSessionDetail).mockImplementation(async (id) => ({ ...completedSummary, id, status: "running", messages: [] }) as SessionDetail);
    await act(async () => state.requestAction(completedSummary, "archive")); await settle();
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(state.notice).toContain("运行");

    await act(async () => state.requestBatchAction([{ ...next, status: "completed" } as SessionSummary], "archive")); await settle();
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(state.notice).toContain("1");
    expect(state.notice).toContain("运行");

    await act(async () => state.requestAction(completedSummary, "delete"));
    const confirm = [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "删除研究") as HTMLButtonElement;
    await act(async () => confirm.click()); await settle();
    expect(deleteChatSession).not.toHaveBeenCalled();
    expect(state.notice).toContain("跳过删除");
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
  it("confirms a batch delete once, skips running sessions, and selects the next same-assistant session", async () => {
    const running = { ...current, id: "running", status: "running" } as SessionSummary;
    const survivor = { ...next, id: "survivor" };
    client.setQueryData(indexKey, { pages: [{ items: [current, next, running, survivor], nextCursor: "" }], pageParams: [""] });
    vi.mocked(querySessions).mockResolvedValue({ items: [survivor, running], nextCursor: "" });
    const returnFocus = document.createElement("button");
    document.body.appendChild(returnFocus);
    await act(async () => state.requestBatchAction([current, next, running], "delete", returnFocus));
    expect(deleteChatSession).not.toHaveBeenCalled();
    const dialog = document.querySelector("[role=dialog]");
    expect(dialog?.textContent).toContain("运行中");
    const confirm = [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "删除研究") as HTMLButtonElement;
    expect(confirm).toBeTruthy();
    await act(async () => { confirm.click(); confirm.click(); });
    await settle();
    expect(deleteChatSession).toHaveBeenCalledTimes(2);
    expect(deleteChatSession).toHaveBeenNthCalledWith(1, "current");
    expect(deleteChatSession).toHaveBeenNthCalledWith(2, "next");
    expect(state.notice).toContain("2");
    expect(state.notice).toContain("1");
    expect(state.notice).toContain("运行");
    expect(router.state.location.search).toBe("?session=survivor");
    expect(indexedIds()).not.toContain("current");
    expect(indexedIds()).not.toContain("next");
    expect(indexedIds()).toContain("running");
    returnFocus.remove();
  });
  it("verifies each batch archive identity, reports partial failures, and undoes only this batch's successes", async () => {
    const running = { ...current, id: "running", status: "running" } as SessionSummary;
    const foreignSummary = { ...current, id: "foreign-summary" };
    const survivor = { ...next, id: "survivor" };
    client.setQueryData(indexKey, { pages: [{ items: [current, next, foreignSummary, running, survivor], nextCursor: "" }], pageParams: [""] });
    vi.mocked(querySessions).mockResolvedValue({ items: [survivor], nextCursor: "" });
    vi.mocked(fetchSessionDetail).mockImplementation(async (id) => ({
      ...current,
      id,
      agentId: id === "foreign-summary" ? "other-agent" : "finance-a",
      messages: [],
    }) as SessionDetail);
    vi.mocked(archiveChatSession).mockImplementation(async (id) => {
      if (id === "next") throw new Error("归档请求失败");
      return { sessionId: id, status: "archived", changed: true };
    });
    await act(async () => state.requestBatchAction([current, next, foreignSummary, running], "archive"));
    await settle();
    expect(archiveChatSession).toHaveBeenCalledTimes(2);
    expect(archiveChatSession).toHaveBeenCalledWith("current");
    expect(archiveChatSession).toHaveBeenCalledWith("next");
    expect(archiveChatSession).not.toHaveBeenCalledWith("foreign-summary");
    expect(archiveChatSession).not.toHaveBeenCalledWith("running");
    expect(state.notice).toContain("1");
    expect(state.notice).toContain("运行");
    expect(state.error).toContain("归档请求失败");
    expect(state.error).toContain("不属于当前助手");
    expect(state.canUndoBatchArchive).toBe(true);
    vi.mocked(unarchiveChatSession).mockClear();
    await act(async () => state.undoBatchArchive());
    await settle();
    expect(unarchiveChatSession).toHaveBeenCalledTimes(1);
    expect(unarchiveChatSession).toHaveBeenCalledWith("current");
    expect(unarchiveChatSession).not.toHaveBeenCalledWith("next");
    expect(state.canUndoBatchArchive).toBe(false);
  });
  it("does not offer undo when the native archive endpoint reports no state change", async () => {
    vi.mocked(archiveChatSession).mockImplementation(async (id) => ({ sessionId: id, status: "archived", changed: false }));
    await act(async () => state.requestBatchAction([current], "archive")); await settle();
    expect(archiveChatSession).toHaveBeenCalledWith("current");
    expect(indexedIds()).not.toContain("current");
    expect(state.notice).toContain("1");
    expect(state.canUndoBatchArchive).toBe(false);
    await act(async () => state.undoBatchArchive()); await settle();
    expect(unarchiveChatSession).not.toHaveBeenCalled();
  });
  it("clears the previous assistant's delete confirmation and archive undo on an owner change", async () => {
    await act(async () => state.requestBatchAction([current], "archive")); await settle();
    expect(state.canUndoBatchArchive).toBe(true);
    await act(async () => state.requestAction(next, "delete"));
    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    await switchOwner();
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(state.canUndoBatchArchive).toBe(false);
    expect(state.notice).toBe("");
    await act(async () => state.undoBatchArchive());
    expect(unarchiveChatSession).not.toHaveBeenCalled();
    expect(deleteChatSession).not.toHaveBeenCalled();
  });
  it("does not send an archive after its ownership check returns for an assistant that was switched away", async () => {
    let release!: (detail: SessionDetail) => void;
    vi.mocked(fetchSessionDetail).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    await act(async () => state.requestAction(current, "archive"));
    await switchOwner();
    await act(async () => release({ ...current, messages: [] } as SessionDetail)); await settle();
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(state.pending).toBe(false);
    expect(state.error).toBe("");
    expect(router.state.location.search).toBe("?session=current");
  });
  it("does not revive an old action after switching away and back to the same assistant", async () => {
    let release!: (detail: SessionDetail) => void;
    vi.mocked(fetchSessionDetail).mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    await act(async () => state.requestAction(current, "archive"));
    await switchOwner(); await switchOwner("finance-a");
    await act(async () => release({ ...current, messages: [] } as SessionDetail)); await settle();
    expect(archiveChatSession).not.toHaveBeenCalled();
    expect(state.pending).toBe(false);
  });
  it("keeps an already-sent archive in its owner's cache without continuing the batch or resetting the new owner's action", async () => {
    let releaseArchive!: (result: Awaited<ReturnType<typeof archiveChatSession>>) => void;
    let releaseDetail!: (detail: SessionDetail) => void;
    vi.mocked(archiveChatSession).mockImplementationOnce(() => new Promise(resolve => { releaseArchive = resolve; }));
    await act(async () => state.requestBatchAction([current, next], "archive"));
    expect(archiveChatSession).toHaveBeenCalledExactlyOnceWith("current");
    await switchOwner();
    const other = { ...current, id: "other", agentId: "finance-b" };
    vi.mocked(fetchSessionDetail).mockImplementationOnce(() => new Promise(resolve => { releaseDetail = resolve; }));
    await act(async () => state.requestAction(other, "archive"));
    expect(state.pending).toBe(true);
    await act(async () => releaseArchive({ sessionId: current.id, status: "archived", changed: true })); await settle();
    expect(archiveChatSession).toHaveBeenCalledTimes(1);
    expect(indexedIds()).toEqual(["next"]);
    expect(state.pending).toBe(true);
    expect(state.canUndoBatchArchive).toBe(false);
    expect(state.notice).toBe("");
    expect(router.state.location.search).toBe("?session=current");
    vi.mocked(archiveChatSession).mockResolvedValue({ sessionId: other.id, status: "archived", changed: true });
    await act(async () => releaseDetail({ ...other, messages: [] } as SessionDetail)); await settle();
    expect(archiveChatSession).toHaveBeenLastCalledWith(other.id);
    expect(state.pending).toBe(false);
  });
  it("returns focus to the invoking batch control when delete confirmation is canceled", async () => {
    const returnFocus = document.createElement("button");
    document.body.appendChild(returnFocus);
    returnFocus.focus();
    await act(async () => state.requestBatchAction([current, next], "delete", returnFocus));
    const cancel = [...document.querySelectorAll("[role=dialog] button")].find((button) => button.textContent === "取消") as HTMLButtonElement;
    await act(async () => cancel.click());
    await settle();
    expect(document.activeElement).toBe(returnFocus);
    expect(deleteChatSession).not.toHaveBeenCalled();
    returnFocus.remove();
  });
});
