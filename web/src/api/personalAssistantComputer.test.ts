import { afterEach, describe, expect, it, vi } from "vitest";
import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import { confirmPersonalAssistantComputer, controlPersonalAssistantComputer, fetchPersonalAssistantComputer,
  fetchPersonalAssistantComputerWindows, grantPersonalAssistantComputer } from "./personalAssistantComputer";

afterEach(() => { resetControlTokenForTests(); vi.unstubAllGlobals(); });
describe("personal assistant computer transport", () => {
  it("passes abort signals for reads and explicit scoped payloads for mutations", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn<typeof fetch>().mockImplementation(async () => Response.json({ status: "idle" }));
    vi.stubGlobal("fetch", fetchMock);
    const signal = new AbortController().signal;
    await fetchPersonalAssistantComputer({ signal }); await fetchPersonalAssistantComputerWindows({ signal });
    await grantPersonalAssistantComputer({ selectionId: "window-selection", allowVision: true });
    for (const action of ["pause", "resume", "takeover", "return", "end"] as const) await controlPersonalAssistantComputer({ grantId: "grant", action });
    await confirmPersonalAssistantComputer({ grantId: "grant", pendingId: "pending", approved: true });
    await confirmPersonalAssistantComputer({ grantId: "grant", pendingId: "pending", approved: false });
    expect(fetchMock.mock.calls.slice(0, 2).map(([path, options]) => [path, options?.signal, options?.method ?? "GET"])).toEqual([
      ["/api/personal-assistant/computer", signal, "GET"], ["/api/personal-assistant/computer/windows", signal, "GET"],
    ]);
    const requests = fetchMock.mock.calls.slice(2).map(([path, options]) => [path, options?.method, JSON.parse(String(options?.body))]);
    expect(requests).toEqual([
      ["/api/personal-assistant/computer/grant", "POST", { selectionId: "window-selection", allowVision: true }],
      ...["pause", "resume", "takeover", "return", "end"].map(action => ["/api/personal-assistant/computer/control", "POST", { grantId: "grant", action }]),
      ["/api/personal-assistant/computer/confirm", "POST", { grantId: "grant", pendingId: "pending", approved: true }],
      ["/api/personal-assistant/computer/confirm", "POST", { grantId: "grant", pendingId: "pending", approved: false }],
    ]);
  });
  it("propagates server failures without a fabricated control success", async () => {
    seedControlTokenForTests();
    vi.stubGlobal("fetch", vi.fn<typeof fetch>().mockResolvedValue(Response.json({ detail: "窗口已关闭" }, { status: 409 })));
    await expect(controlPersonalAssistantComputer({ grantId: "expired", action: "resume" })).rejects.toThrow("窗口已关闭");
  });
});
