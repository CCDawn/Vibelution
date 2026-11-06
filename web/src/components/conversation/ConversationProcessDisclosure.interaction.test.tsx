/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { ConversationProcessDisclosure } from "./ConversationProcessDisclosure";
import type { CodexTranscriptCell } from "./codexTranscriptCells";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it("collapses settled work without a second thought switch and preserves child choices", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const cells: CodexTranscriptCell[] = [{ id: "thought", kind: "reasoning_summary", messageId: "m1", status: "completed", tone: "neutral", text: "思考摘要" }];
  function NativeUnit() {
    const [open, setOpen] = React.useState(false);
    return <><button data-unit-toggle aria-expanded={open} onClick={() => setOpen(!open)}>思考</button>
      <span data-thought-body hidden={!open}>思考摘要</span></>;
  }
  const render = (streaming: boolean) => root.render(
    <ConversationProcessDisclosure cells={cells} language="zh" presentation="flow" turnStreaming={streaming}>
      <><button data-tool-action>读取配置</button><NativeUnit /></>
    </ConversationProcessDisclosure>,
  );
  const workToggle = () => host.querySelector<HTMLButtonElement>("[data-codex-process-work-toggle]")!;
  const thoughtToggle = () => host.querySelector<HTMLButtonElement>("[data-unit-toggle]")!;
  try {
    await act(async () => render(true));
    expect(workToggle().getAttribute("aria-expanded")).toBe("true");
    expect(host.querySelector("[data-codex-process-thought-toggle]")).toBeNull();
    await act(async () => { thoughtToggle().click(); await new Promise((resolve) => setTimeout(resolve, 35)); });
    expect(host.querySelector<HTMLElement>("[data-thought-body]")!.hidden).toBe(false);
    thoughtToggle().focus();
    await act(async () => render(false));
    expect(workToggle().getAttribute("aria-expanded")).toBe("false");
    expect(host.querySelector("[data-thought-body]")!.closest("[hidden][inert]")).not.toBeNull();
    expect(document.activeElement).toBe(workToggle());
    expect(host.querySelector("[data-tool-action]")?.closest("[hidden][inert]")).not.toBeNull();
    await act(async () => workToggle().click());
    expect(workToggle().getAttribute("aria-expanded")).toBe("true");
    expect(thoughtToggle().getAttribute("aria-expanded")).toBe("true");
    expect(host.querySelector("[data-tool-action]")?.closest("[hidden], [inert]")).toBeNull();
    await act(async () => workToggle().click());
    await act(async () => render(true));
    expect(workToggle().getAttribute("aria-expanded")).toBe("false");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("restores focus to the matching guidance segment when a live flow becomes collapsed history", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (streaming: boolean) => root.render(<>
    <ConversationProcessDisclosure cells={[]} language="zh" presentation="flow" focusScope="s:turn:t:process">
      <button>Earlier segment</button>
    </ConversationProcessDisclosure>
    <ConversationProcessDisclosure key={streaming ? "live" : "history"} cells={[]} language="zh"
      presentation="flow" focusScope="s:turn:t:guide:g1:process" turnStreaming={streaming}>
      <button data-current-segment>Current segment</button>
    </ConversationProcessDisclosure>
  </>);
  try {
    await act(async () => render(true));
    host.querySelector<HTMLButtonElement>("[data-current-segment]")!.focus();
    await act(async () => render(false));
    const triggers = [...host.querySelectorAll<HTMLButtonElement>("[data-codex-process-work-toggle]")];
    expect(triggers).toHaveLength(2);
    expect(document.activeElement).toBe(triggers[1]);
    expect(document.activeElement).not.toBe(triggers[0]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("keeps the work clock through thinking/tool stage switches and freezes at settle", async () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-20T04:00:10Z"));
  const host = document.createElement("div");
  const root = createRoot(host);
  const render = (stage: string, streaming = true) => root.render(
    <ConversationProcessDisclosure cells={[]} language="zh" turnStreaming={streaming}
      turnStartedAt="2026-10-20T04:00:00Z" activeStage={stage}
      workSummary={streaming ? null : { durationMs: 12_000, basis: "turn_header", toolCallCount: 0, toolDurationMs: null }}>
      <span>Current activity</span>
    </ConversationProcessDisclosure>,
  );
  try {
    await act(async () => render("model_thinking"));
    expect(host.querySelector("summary")?.textContent).toContain("工作中 10 秒");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    await act(async () => render("tool_running"));
    expect(host.querySelector("summary")?.textContent).toContain("工作中 11 秒");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    await act(async () => render("responding", false));
    expect(host.querySelector("summary")?.textContent).toContain("已工作 12 秒");
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(host.querySelector("summary")?.textContent).toContain("已工作 12 秒");
  } finally {
    await act(async () => root.unmount());
    vi.useRealTimers();
  }
});

it("keeps a user-opened streaming trail open after settle and restores focus on collapse", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (streaming: boolean) => root.render(
    <ConversationProcessDisclosure cells={[]} language="en" turnStreaming={streaming}>
      <button type="button">Tool action</button>
    </ConversationProcessDisclosure>,
  );
  try {
    await act(async () => render(true));
    const summary = host.querySelector("summary")!;
    const content = host.querySelector('div[aria-hidden="false"]')!;
    expect(content.hasAttribute("inert")).toBe(false);
    await act(async () => summary.click());
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
    // The live trail stays mounted after its collapse animation finishes.
    await act(async () => new Promise((resolve) => setTimeout(resolve, 320)));
    expect(host.querySelector("button")).not.toBeNull();
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
    await act(async () => summary.click());
    await act(async () => new Promise((resolve) => setTimeout(resolve, 40)));
    host.querySelector("button")!.focus();
    await act(async () => render(false));
    expect(summary.getAttribute("aria-expanded")).toBe("true");
    expect(document.activeElement).toBe(host.querySelector("button"));
    await act(async () => summary.click());
    expect(document.activeElement).toBe(summary);
    expect(host.querySelector('div[aria-hidden="true"]')?.hasAttribute("inert")).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("keeps an explicit collapsed choice through settled and running state changes", async () => {
  const host = document.createElement("div");
  const root = createRoot(host);
  const render = (streaming: boolean) => root.render(
    <ConversationProcessDisclosure cells={[]} language="en" turnStreaming={streaming}>
      <span>Tool activity</span>
    </ConversationProcessDisclosure>,
  );
  try {
    await act(async () => render(true));
    const summary = host.querySelector("summary")!;
    await act(async () => summary.click());
    await act(async () => render(false));
    expect(summary.getAttribute("aria-expanded")).toBe("false");
    await act(async () => render(true));
    expect(summary.getAttribute("aria-expanded")).toBe("false");
  } finally {
    await act(async () => root.unmount());
  }
});

it("still auto-collapses an untouched running trail when it settles", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (streaming: boolean) => root.render(
    <ConversationProcessDisclosure cells={[]} language="en" turnStreaming={streaming}>
      <button type="button">Tool action</button>
    </ConversationProcessDisclosure>,
  );
  try {
    await act(async () => render(true));
    host.querySelector("button")!.focus();
    await act(async () => render(false));
    expect(host.querySelector("summary")!.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(host.querySelector("summary"));
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
