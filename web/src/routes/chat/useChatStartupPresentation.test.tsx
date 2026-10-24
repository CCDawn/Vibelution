// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useChatStartupPresentation } from "./useChatStartupPresentation";

const mark = vi.hoisted(() => vi.fn());
vi.mock("../../app/chatStartupMetrics", () => ({ recordChatStartupMilestone: mark }));
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
let frames: Map<number, FrameRequestCallback>;
let nextFrame: number;
let hitTarget: Element | null | undefined;
let visibility: "visible" | "hidden";

beforeEach(() => {
  mark.mockClear(); frames = new Map(); nextFrame = 0; visibility = "visible"; hitTarget = undefined;
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 10, 200, 100));
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { frames.set(++nextFrame, callback); return nextFrame; });
  vi.stubGlobal("cancelAnimationFrame", (id: number) => frames.delete(id));
  vi.spyOn(document, "elementFromPoint").mockImplementation(() => hitTarget === undefined
    ? host.querySelector("textarea") : hitTarget);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount()); host.remove(); vi.restoreAllMocks(); vi.unstubAllGlobals();
});

type Props = { enabled?: boolean; pending?: boolean; mounted?: boolean; hasMessages?: boolean;
  row?: boolean; disabled?: boolean; readOnly?: boolean; surfaceSession?: string; loading?: boolean; inlineEditor?: boolean };
function Harness({ enabled = true, pending = false, mounted = true, hasMessages = true,
  row = true, disabled = false, readOnly = false, surfaceSession = "initial", loading = false, inlineEditor = false }: Props) {
  useChatStartupPresentation({ sessionId: "initial", enabled, transcriptPending: pending });
  return mounted ? <section data-agent-thread-id={surfaceSession}>
    <div data-conversation-following="true">
      {loading ? <div data-testid="conversation-transcript-loading-state" /> : null}
      {row ? <div data-conversation-row-key="row" /> : null}
      {!hasMessages ? <div data-vui="state-surface" data-tone="empty" /> : null}
      {inlineEditor ? <textarea data-conversation-inline-edit-input="1" /> : null}
    </div>
    <textarea disabled={disabled} readOnly={readOnly} />
  </section> : null;
}
async function render(props: Props = {}) {
  await act(async () => { root.render(<Harness {...props} />); });
  // Happy DOM delivers MutationObserver records in a later task, after commit.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
}
function frame() {
  const callbacks = [...frames.values()]; frames.clear();
  act(() => callbacks.forEach((callback) => callback(performance.now())));
}
function present() { frame(); frame(); }
function milestones() { return mark.mock.calls.map(([, stage]) => stage); }

describe("native chat presentation observations", () => {
  it("waits for the real lazy surface and a rendering opportunity", async () => {
    await render({ mounted: false }); present(); expect(mark).not.toHaveBeenCalled();
    await render(); frame(); expect(mark).not.toHaveBeenCalled(); frame();
    expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
    expect(frames.size).toBe(0);
  });
  it("does not borrow a frame boundary from before the lazy surface mounted", async () => {
    await render({ mounted: false }); frame();
    await render(); frame(); expect(mark).not.toHaveBeenCalled();
    present(); expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
  });
  it("never presents a loading transcript or another session's surface", async () => {
    await render({ pending: true }); present(); expect(mark).not.toHaveBeenCalled();
    await render({ loading: true }); present(); expect(mark).not.toHaveBeenCalled();
    await render({ surfaceSession: "other" }); present(); expect(mark).not.toHaveBeenCalled();
    await render(); present(); expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
  });
  it("requires a visible history row but accepts an authoritative empty session", async () => {
    await render({ row: false }); present(); expect(milestones()).toEqual(["composerReady"]);
    await render({ row: false, hasMessages: false }); present();
    expect(milestones()).toContain("transcriptPresented");
  });
  it("never mistakes an inline message editor for the composer", async () => {
    await render({ inlineEditor: true, disabled: true });
    hitTarget = host.querySelector("[data-conversation-inline-edit-input]");
    present(); expect(milestones()).toEqual(["transcriptPresented"]);
  });
  it.each([{ disabled: true }, { readOnly: true }])("waits for an editable input: %o", async (props) => {
    await render(props); present(); expect(milestones()).toEqual(["transcriptPresented"]);
    await render(); present(); expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
  });
  it("waits for visibility and never focuses or edits the input", async () => {
    visibility = "hidden"; await render(); present(); expect(mark).not.toHaveBeenCalled();
    const focus = vi.spyOn(host.querySelector("textarea")!, "focus");
    visibility = "visible"; document.dispatchEvent(new Event("visibilitychange")); present();
    expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
    expect(focus).not.toHaveBeenCalled(); expect(host.querySelector("textarea")!.value).toBe("");
  });
  it("rejects zero-size surfaces and a covered input", async () => {
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue(new DOMRect());
    await render(); present(); expect(mark).not.toHaveBeenCalled();
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue(new DOMRect(10, 10, 200, 100));
    hitTarget = host; window.dispatchEvent(new Event("resize")); present();
    expect(milestones()).toEqual(["transcriptPresented"]);
    hitTarget = undefined; window.dispatchEvent(new Event("resize")); present();
    expect(milestones()).toEqual(["transcriptPresented", "composerReady"]);
  });
  it("rejects rows clipped by a scroll container", async () => {
    await render();
    const surface = host.querySelector<HTMLElement>("section")!;
    surface.style.overflow = "hidden";
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(new DOMRect(10, 500, 200, 100));
    present(); expect(mark).not.toHaveBeenCalled();
  });
  it("does not measure excluded surfaces or callbacks after unmount", async () => {
    await render({ enabled: false }); present(); expect(mark).not.toHaveBeenCalled();
    await render(); frame(); act(() => root.unmount()); root = createRoot(host); present();
    expect(mark).not.toHaveBeenCalled();
  });
});
