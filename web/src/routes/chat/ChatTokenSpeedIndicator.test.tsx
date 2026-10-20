/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";
import { ActiveTurnLayersStoreProvider, createActiveTurnLayersStore } from "./activeTurnLayersStore";
import { ChatTokenSpeedIndicator } from "./ChatTokenSpeedIndicator";

vi.mock("../../components/vui", () => ({ VTooltip: ({ children }: { children: React.ReactNode }) => children }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | undefined;
let host: HTMLDivElement | undefined;
afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove(); root = undefined; host = undefined;
  vi.restoreAllMocks(); vi.useRealTimers();
});

function layer(text: string, status: ActiveTurnLayerState["status"] = "running"): ActiveTurnLayerState {
  return { id: "layer", sessionId: "s", turnId: "t", status, updatedAt: "", ledgerSeq: 1, turnItems: [{
    id: "i", itemId: "i", sessionId: "s", turnId: "t", version: 3, revision: 1, sequence: 1,
    type: "agent_message", phase: "final_answer", status: "running", text,
  }] };
}

describe("live token gauge", () => {
  it("baselines snapshots, measures append-only output and clears on stall, rewrite, tool, completion and disconnect", async () => {
    vi.useFakeTimers();
    let time = 0;
    vi.spyOn(performance, "now").mockImplementation(() => time);
    const store = createActiveTurnLayersStore();
    store.setActiveTurnLayersBySession({ s: layer("中".repeat(100)) });
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    const render = async (sessionId = "s", disconnected = false) => {
      await act(async () => root!.render(<ActiveTurnLayersStoreProvider store={store}>
        <ChatTokenSpeedIndicator key={sessionId} sessionId={sessionId} lang="zh" disconnected={disconnected}/>
      </ActiveTurnLayersStoreProvider>));
    };
    const push = async (next: ActiveTurnLayerState, at: number) => {
      time = at;
      await act(async () => store.setActiveTurnLayersBySession({ s: next }));
    };
    const value = () => host!.querySelector('[data-testid="conversation-token-speed"]')!.textContent;
    await render(); expect(value()).toContain("— tok/s");
    await push(layer("中".repeat(110)), 500); expect(value()).toContain("— tok/s");
    await push(layer("中".repeat(120)), 1000); expect(value()).toContain("≈20.0 tok/s");
    // Unrelated sessions cannot be mixed into the current session's speed.
    await act(async () => store.setActiveTurnLayersBySession(current => ({ ...current, other: layer("中".repeat(900)) })));
    expect(value()).toContain("≈20.0 tok/s");
    time = 2550; await act(async () => vi.advanceTimersByTime(2000)); expect(value()).toContain("— tok/s");
    await push(layer("中".repeat(130)), 2600); expect(value()).toContain("— tok/s");
    await push(layer("新".repeat(150)), 3100); expect(value()).toContain("— tok/s");
    await push(layer("新".repeat(160)), 3600); expect(value()).toContain("≈20.0 tok/s");
    const tool = layer("新".repeat(160));
    tool.turnItems.push({ id: "tool", itemId: "tool", version: 3, sessionId: "s", turnId: "t", revision: 1, sequence: 2,
      type: "tool_call", callId: "c", toolName: "example", status: "running", output: "中".repeat(900) });
    await push(tool, 3700); expect(value()).toContain("— tok/s");
    await push(layer("新".repeat(170), "completed"), 4000); expect(value()).toContain("— tok/s");
    await push(layer("新".repeat(180)), 4500);
    await push(layer("新".repeat(190)), 5000); expect(value()).toContain("≈20.0 tok/s");
    await render("s", true); expect(value()).toContain("— tok/s");
    await render("s", false); expect(value()).toContain("— tok/s");
    // The first reconnect frame contains backfilled full text, not a live burst.
    await push(layer("新".repeat(600)), 5500); expect(value()).toContain("— tok/s");
    await push(layer("新".repeat(610)), 6000); expect(value()).toContain("≈20.0 tok/s");
    await render("other"); expect(value()).toContain("— tok/s");
  });
});
