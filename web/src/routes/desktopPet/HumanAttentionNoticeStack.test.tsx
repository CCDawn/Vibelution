// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { submitHumanGateDecision } from "../personalAssistant/humanGateDecision";
import { HumanAttentionNoticeStack } from "./HumanAttentionNoticeStack";

vi.mock("../../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
// Only the network submit is mocked; the pure scope/offer helpers stay real.
vi.mock("../personalAssistant/humanGateDecision", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../personalAssistant/humanGateDecision")>();
  return { ...actual, submitHumanGateDecision: vi.fn() };
});
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let listener: ((payload: unknown) => void) | undefined;
let root: Root;
let container: HTMLDivElement;
let router: ReturnType<typeof createMemoryRouter>;
let beforeNavigate: ReturnType<typeof vi.fn>;

function Host() {
  const location = useLocation();
  return (
    <>
      <HumanAttentionNoticeStack onBeforeNavigate={beforeNavigate} />
      <output>{location.pathname}{location.search}</output>
    </>
  );
}

const FULL_PAYLOAD = {
  id: "kr-1",
  kind: "knowledge_review",
  severity: "critical",
  title: "知识待复核",
  body: "一条新知识等待确认",
  targetUrl: "/memory/knowledge",
};

const GATE_PAYLOAD = {
  id: "gate-1",
  kind: "human_gate",
  severity: "high",
  title: "研究结论等待审批",
  body: "阶段结论需要人工确认",
  targetUrl: "/teams?researchView=workflow&runId=run-7",
  actions: [
    { label: "接受", decision: "accept" },
    { label: "驳回", decision: "reject" },
  ],
  meta: { teamId: "team-1", runId: "run-7", nodeId: "node-gate", taskId: "task-9", decisions: ["accept", "reject"] },
};

function cards() {
  return [...container.querySelectorAll('[data-vui="human-attention-notice"]')];
}

async function deliver(payload: unknown) {
  await act(async () => listener?.(payload));
}

beforeEach(() => {
  vi.clearAllMocks();
  listener = undefined;
  beforeNavigate = vi.fn().mockResolvedValue(undefined);
  vi.stubGlobal("vibelutionLauncher", {
    onHumanAttentionOpened: (callback: (payload: unknown) => void) => {
      listener = callback;
      return () => undefined;
    },
  });
  router = createMemoryRouter([{ path: "*", element: <Host /> }], { initialEntries: ["/desktop-assistant"] });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("assistant window human-attention notice stack", () => {
  it("renders delivered payloads as cards with severity styling and copy", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(FULL_PAYLOAD);
    const card = cards()[0];
    expect(card).toBeDefined();
    expect(card.dataset.severity).toBe("critical");
    expect(card.textContent).toContain("知识待复核");
    expect(card.textContent).toContain("一条新知识等待确认");
    expect(card.textContent).toContain("知识复核");
  });

  it("locates the target in-window on card click after running onBeforeNavigate", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(FULL_PAYLOAD);
    const opener = container.querySelector<HTMLButtonElement>('button[aria-label^="查看该事项"]')!;
    await act(async () => opener.click());
    expect(beforeNavigate).toHaveBeenCalledTimes(1);
    expect(router.state.location.pathname + router.state.location.search).toBe("/memory/knowledge");
    expect(cards()).toHaveLength(0);
  });

  it("falls back to the kind default route when the payload has no targetUrl", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver({ id: "an-1", kind: "anomaly", severity: "high", title: "研究异常" });
    const opener = container.querySelector<HTMLButtonElement>('button[aria-label^="查看该事项"]')!;
    await act(async () => opener.click());
    expect(router.state.location.pathname + router.state.location.search).toBe("/teams?researchView=workflow");
  });

  it("dismisses a card manually without navigating", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(FULL_PAYLOAD);
    const close = container.querySelector<HTMLButtonElement>('button[aria-label="关闭通知"]')!;
    await act(async () => close.click());
    expect(cards()).toHaveLength(0);
    expect(router.state.location.pathname).toBe("/desktop-assistant");
  });

  it("navigates immediately for bare opened clicks without showing a card", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver({ id: "kr-9", targetUrl: "/memory/knowledge" });
    expect(cards()).toHaveLength(0);
    expect(router.state.location.pathname).toBe("/memory/knowledge");
  });

  it("stacks at most three cards, newest first, and refreshes duplicate ids", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    for (let index = 0; index < 4; index += 1) {
      await deliver({ id: `kr-${index}`, kind: "anomaly", severity: "medium", title: `异常 ${index}` });
    }
    expect(cards()).toHaveLength(3);
    expect(cards()[0].textContent).toContain("异常 3");
    expect(cards().some(card => card.textContent?.includes("异常 0"))).toBe(false);
    await deliver({ ...FULL_PAYLOAD });
    expect(cards()).toHaveLength(3);
    expect(cards()[0].textContent).toContain("知识待复核");
  });

  it("auto-dismisses after 12s and pauses the timer while hovered", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(FULL_PAYLOAD);
    expect(cards()).toHaveLength(1);
    // Hover pauses the countdown.
    await act(async () => {
      cards()[0].dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
    });
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    expect(cards()).toHaveLength(1);
    // Leaving the card restarts the countdown.
    await act(async () => {
      cards()[0].dispatchEvent(new MouseEvent("mouseout", { bubbles: true }));
    });
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    expect(cards()).toHaveLength(0);
  });

  it("renders nothing and never crashes without the launcher bridge", async () => {
    vi.unstubAllGlobals();
    await act(async () => root.render(<RouterProvider router={router} />));
    expect(container.textContent).not.toContain("需要你的关注");
    expect(() => container.querySelector('[data-vui="human-attention-notice"]')).not.toThrow();
  });
});

describe("assistant window human-gate inline approval", () => {
  const mockedSubmit = vi.mocked(submitHumanGateDecision);

  function gateButton(testId: string): HTMLButtonElement {
    const button = container.querySelector<HTMLButtonElement>(`[data-testid="${testId}"]`);
    if (!button) throw new Error(`Missing gate button: ${testId}`);
    return button;
  }

  it("renders the accept and reject buttons on actionable gate cards", async () => {
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);
    expect(cards()).toHaveLength(1);
    expect(gateButton("notice-gate-accept").textContent).toContain("接受");
    expect(gateButton("notice-gate-reject").textContent).toContain("驳回");
    expect(container.textContent).toContain("人工审批");
  });

  it("submits accept directly through the snapshot + offer mechanism and removes the card", async () => {
    mockedSubmit.mockResolvedValue({ outcome: "submitted", receipt: { commandId: "c-1" } as never });
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);

    await act(async () => gateButton("notice-gate-accept").click());

    expect(mockedSubmit).toHaveBeenCalledTimes(1);
    expect(mockedSubmit).toHaveBeenCalledWith({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "accept",
    });
    expect(cards()).toHaveLength(0);
    expect(router.state.location.pathname).toBe("/desktop-assistant");
  });

  it("requires a two-step inline confirmation before reject executes", async () => {
    mockedSubmit.mockResolvedValue({ outcome: "submitted", receipt: {} as never });
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);

    // First click only arms; nothing is submitted and no dialog appears.
    await act(async () => gateButton("notice-gate-reject").click());
    expect(mockedSubmit).not.toHaveBeenCalled();
    expect(gateButton("notice-gate-confirm").textContent).toContain("确认驳回");

    // Cancelling returns to the plain two-button state.
    await act(async () => gateButton("notice-gate-cancel").click());
    expect(container.querySelector('[data-testid="notice-gate-confirm"]')).toBeNull();
    expect(gateButton("notice-gate-reject")).toBeTruthy();

    // Arming again and confirming executes the reject decision.
    await act(async () => gateButton("notice-gate-reject").click());
    await act(async () => gateButton("notice-gate-confirm").click());
    expect(mockedSubmit).toHaveBeenCalledTimes(1);
    expect(mockedSubmit).toHaveBeenCalledWith({
      teamId: "team-1",
      runId: "run-7",
      taskId: "task-9",
      decision: "reject",
    });
    expect(cards()).toHaveLength(0);
  });

  it("falls back to navigating the run deep link when no offer is available", async () => {
    mockedSubmit.mockResolvedValue({ outcome: "unavailable" });
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);

    await act(async () => gateButton("notice-gate-accept").click());

    expect(mockedSubmit).toHaveBeenCalledTimes(1);
    expect(cards()).toHaveLength(0);
    expect(router.state.location.pathname + router.state.location.search)
      .toBe("/teams?researchView=workflow&runId=run-7");
  });

  it("keeps the card with an inline error when the submission fails", async () => {
    mockedSubmit.mockRejectedValue(new Error("version_conflict"));
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);

    await act(async () => gateButton("notice-gate-accept").click());

    expect(cards()).toHaveLength(1);
    expect(container.querySelector('[data-testid="notice-gate-error"]')?.textContent)
      .toContain("审批失败：version_conflict");
  });

  it("does not auto-dismiss an actionable gate card", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver(GATE_PAYLOAD);
    expect(cards()).toHaveLength(1);
    await act(async () => vi.advanceTimersByTimeAsync(60_000));
    expect(cards()).toHaveLength(1);
  });

  it("renders a plain card when actions exist but the meta routing facts are missing", async () => {
    vi.useFakeTimers();
    await act(async () => root.render(<RouterProvider router={router} />));
    await deliver({ ...GATE_PAYLOAD, meta: { teamId: "team-1", runId: "run-7" } });
    expect(cards()).toHaveLength(1);
    expect(container.querySelector('[data-testid="notice-gate-actions"]')).toBeNull();
    // Without buttons the normal 12s auto-dismiss still applies.
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    expect(cards()).toHaveLength(0);
  });
});
