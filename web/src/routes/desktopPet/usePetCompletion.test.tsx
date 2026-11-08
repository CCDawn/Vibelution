// @vitest-environment happy-dom
import { act, createElement, StrictMode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PET_COMPLETION_DURATION_MS, usePetCompletion } from "./usePetCompletion";

let root: Root;
let host: HTMLDivElement;
type Source = Parameters<typeof usePetCompletion>[1];
function Harness({ sessionId = "s", source, enabled = true }: { sessionId?: string; source?: Source; enabled?: boolean }) {
  return createElement("span", null, String(usePetCompletion(sessionId, source, enabled)));
}
const running = (turnId = "new"): Source => ({ id: "s", status: "running", activeTurnId: turnId, lastTurnTerminalTurnId: "old" });
const terminal = (turnId = "new", terminalReason = "success"): Source => ({ id: "s", status: "ready", lastTurnTerminalTurnId: turnId, terminalReason });
async function render(source?: Source, enabled = true, sessionId = "s") {
  await act(async () => root.render(createElement(StrictMode, null, createElement(Harness, { source, enabled, sessionId }))));
}
beforeEach(() => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  vi.useFakeTimers();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); });

describe("pet completion acknowledgement", () => {
  it("does not replay history on initial load or missing-detail recovery", async () => {
    await render(); await render(terminal()); expect(host.textContent).toBe("false");
  });
  it("acknowledges a new successful Turn once and expires without another poll", async () => {
    await render(running()); await render(terminal()); expect(host.textContent).toBe("true");
    await act(async () => { await vi.advanceTimersByTimeAsync(PET_COMPLETION_DURATION_MS - 1); });
    await render({ ...terminal() }); expect(host.textContent).toBe("true");
    await act(async () => { await vi.advanceTimersByTimeAsync(1); }); expect(host.textContent).toBe("false");
    await render({ ...terminal() }); expect(host.textContent).toBe("false");
  });
  it("waits for the terminal projection to retire its exact execution owner", async () => {
    await render(running());
    await render({ ...terminal(), status: "running", activeTurnId: "new" }); expect(host.textContent).toBe("false");
    await render(terminal()); expect(host.textContent).toBe("true");
  });
  it.each(["error", "needs_continue", "paused_limit", "stopped", "cancelled"])("does not celebrate %s", async reason => {
    await render(running()); await render(terminal("new", reason)); expect(host.textContent).toBe("false");
  });
  it("requires a stable native Turn id and an authoritative detail", async () => {
    await render(running()); await render(terminal("")); expect(host.textContent).toBe("false");
    await render({ ...terminal(), provisionalTranscript: true }); expect(host.textContent).toBe("false");
    await render(terminal()); expect(host.textContent).toBe("true");
  });
  it("does not carry a pulse into another session or new running Turn", async () => {
    await render(running()); await render(terminal()); expect(host.textContent).toBe("true");
    await render({ ...running("next"), terminalReason: "success", lastTurnTerminalTurnId: "new" });
    expect(host.textContent).toBe("false");
    await render({ ...terminal(), id: "other" }, true, "other"); expect(host.textContent).toBe("false");
    await render(terminal(), true, "other"); expect(host.textContent).toBe("false");
  });
  it("honors disabled completion feedback without replaying it when enabled later", async () => {
    await render(running(), false); await render(terminal(), false); await render(terminal(), true);
    expect(host.textContent).toBe("false");
  });
  it("does not replay observed terminal identities after an older snapshot arrives", async () => {
    await render(terminal("old")); await render(terminal()); expect(host.textContent).toBe("true");
    await act(async () => { await vi.advanceTimersByTimeAsync(PET_COMPLETION_DURATION_MS); });
    await render(terminal("old")); expect(host.textContent).toBe("false");
    await render(terminal()); expect(host.textContent).toBe("false");
  });
  it("recognizes a different live owner's terminal as history rather than a new completion", async () => {
    await render(terminal("old"));
    await render({ ...running("B"), lastTurnTerminalTurnId: "A" });
    await render(terminal("A")); expect(host.textContent).toBe("false");
    await render(terminal("B")); expect(host.textContent).toBe("true");
  });
  it("cancels a live pulse when feedback is disabled without replaying on re-enable", async () => {
    await render(running()); await render(terminal()); expect(host.textContent).toBe("true");
    await render(terminal(), false); expect(host.textContent).toBe("false");
    expect(vi.getTimerCount()).toBe(0);
    await render(terminal()); expect(host.textContent).toBe("false");
  });
  it("cleans its timer when the pet closes", async () => {
    await render(running()); await render(terminal()); expect(vi.getTimerCount()).toBe(1);
    await act(async () => root.unmount()); expect(vi.getTimerCount()).toBe(0);
  });
});
