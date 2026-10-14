// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fetchPersonalAssistant, createPersonalAssistant } from "../../api/personalAssistant";
import type { PersonalAssistant, PersonalAssistantResponse } from "../../api/types/personalAssistant";
import { DesktopAssistantReturnNotice } from "./DesktopAssistantReturnNotice";

vi.mock("../../api/personalAssistant", () => ({ fetchPersonalAssistant: vi.fn(), createPersonalAssistant: vi.fn() }));
vi.mock("../../app/userActionTelemetry", () => ({ postUserActionObservation: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const assistant: PersonalAssistant = { agentId: "agent", directSessionId: "personal-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };
let listener: (value: unknown) => void, root: Root, container: HTMLDivElement, router: ReturnType<typeof createMemoryRouter>;
function Host() { const location = useLocation(); return <><DesktopAssistantReturnNotice /><output>{location.pathname}{location.search}</output></>; }
beforeEach(async () => {
  vi.clearAllMocks();
  vi.mocked(fetchPersonalAssistant).mockResolvedValue({ assistant });
  vi.stubGlobal("vibelutionLauncher", { onConversationNotificationOpened: (callback: (value: unknown) => void) => { listener = callback; return () => undefined; } });
  router = createMemoryRouter([{ path: "*", element: <Host /> }], { initialEntries: ["/agents"] });
  container = document.createElement("div"); document.body.appendChild(container); root = createRoot(container);
  await act(async () => root.render(<RouterProvider router={router} />));
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); vi.unstubAllGlobals(); });
async function settle() { await act(async () => new Promise(resolve => setTimeout(resolve, 20))); }
async function opened(sessionId: string) {
  await act(async () => listener({ schemaVersion: 1, sessionId, source: "desktop-assistant" })); await settle();
}
function deferred() { let resolve!: (value: PersonalAssistantResponse) => void; const promise = new Promise<PersonalAssistantResponse>(done => { resolve = done; }); return { promise, resolve }; }

describe("main workbench assistant return", () => {
  it("opens the backend canonical Session in the personal assistant without provisioning", async () => {
    await opened("personal-session");
    expect(router.state.location.pathname).toBe("/personal-assistant");
    expect(router.state.location.search).toBe("?session=personal-session");
    expect(createPersonalAssistant).not.toHaveBeenCalled();
  });
  it("opens a foreign Session through the existing ordinary chat route", async () => {
    await opened("ordinary-session");
    expect(router.state.location.pathname).toBe("/chat");
    expect(router.state.location.search).toBe("?session=ordinary-session");
  });
  it("shows a retryable identity read failure and never guesses a personal target", async () => {
    vi.mocked(fetchPersonalAssistant).mockRejectedValueOnce(new Error("identity offline"));
    await opened("personal-session");
    expect(router.state.location.pathname).toBe("/agents");
    expect(document.body.textContent).toContain("identity offline");
    const retry = [...document.querySelectorAll("button")].find(button => button.textContent === "重试")!;
    await act(async () => retry.click()); await settle();
    expect(router.state.location.pathname).toBe("/personal-assistant");
  });
  it("discards a slow result after the user navigates elsewhere", async () => {
    const pending = deferred(); vi.mocked(fetchPersonalAssistant).mockReturnValueOnce(pending.promise);
    await opened("personal-session");
    await act(async () => router.navigate("/memory"));
    await act(async () => pending.resolve({ assistant })); await settle();
    expect(router.state.location.pathname).toBe("/memory");
  });
  it("keeps the latest return request when responses finish out of order", async () => {
    const old = deferred(), current = deferred();
    vi.mocked(fetchPersonalAssistant).mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise);
    await opened("personal-session"); await opened("ordinary-session");
    await act(async () => current.resolve({ assistant })); await settle();
    await act(async () => old.resolve({ assistant })); await settle();
    expect(router.state.location.pathname).toBe("/chat");
    expect(router.state.location.search).toBe("?session=ordinary-session");
  });
});
