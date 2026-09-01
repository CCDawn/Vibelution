/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const api = vi.hoisted(() => ({
  consumeResearchWorkflowEventStream: vi.fn(),
}));

vi.mock("../../../api/research-workflow/events", () => api);

import type { WorkflowEventEnvelope } from "../../../api/types/research-workflow/events";
import { useResearchWorkflowEventStream } from "./useResearchWorkflowEventStream";

type HookValue = ReturnType<typeof useResearchWorkflowEventStream>;

function HookProbe({ onEvent, onValue }: {
  onEvent: (event: WorkflowEventEnvelope) => void;
  onValue: (value: HookValue) => void;
}) {
  const value = useResearchWorkflowEventStream({
    teamId: "research-team",
    runId: "run-a",
    afterSequence: 3,
    onEvent,
  });
  onValue(value);
  return null;
}

describe("useResearchWorkflowEventStream", () => {
  let container: HTMLDivElement;
  let root: Root;
  let latest: HookValue | null = null;

  beforeEach(() => {
    vi.clearAllMocks();
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    latest = null;
  });

  afterEach(async () => {
    vi.useRealTimers();
    await act(async () => root.unmount());
    container.remove();
  });

  it("connects, advances the cursor, and aborts on unmount", async () => {
    let captured: Parameters<typeof api.consumeResearchWorkflowEventStream>[0] | undefined;
    api.consumeResearchWorkflowEventStream.mockImplementation(async (options) => {
      captured = options;
      options.onOpen?.();
      options.onFrame({
        id: "run-a:4",
        event: "node_running",
        data: JSON.stringify({ sequence: 4, runId: "run-a", type: "node_running" }),
      });
      await new Promise<void>((_resolve, reject) => {
        options.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
      });
    });
    const onEvent = vi.fn();

    await act(async () => {
      root.render(<HookProbe onEvent={onEvent} onValue={(value) => { latest = value; }} />);
      await Promise.resolve();
    });

    expect(latest?.state).toBe("connected");
    expect(latest?.error).toBeNull();
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ sequence: 4 }));
    expect(captured?.afterSequence).toBe(3);
    expect(captured?.lastEventId).toBeUndefined();

    await act(async () => root.unmount());
    expect(captured?.signal.aborted).toBe(true);
    root = createRoot(container);
  });

  it("delivers unknown event frames, advances the cursor, and reconnects from it", async () => {
    let callCount = 0;
    api.consumeResearchWorkflowEventStream.mockImplementation(async (options) => {
      callCount += 1;
      options.onOpen?.();
      if (callCount === 1) {
        options.onFrame({
          id: "run-a:6",
          event: "workflow.brand_new.future_event",
          data: JSON.stringify({
            sequence: 6,
            runId: "run-a",
            type: "workflow.brand_new.future_event",
          }),
        });
      }
      throw new Error("disconnect");
    });
    vi.useFakeTimers();
    const onEvent = vi.fn();

    await act(async () => {
      root.render(<HookProbe onEvent={onEvent} onValue={(value) => { latest = value; }} />);
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });

    // Unknown types are forwarded as generic events instead of being dropped,
    // so the cursor advances and the reconnect resumes after the new frame.
    expect(onEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        sequence: 6,
        type: "workflow.brand_new.future_event",
      }),
    );
    expect(api.consumeResearchWorkflowEventStream.mock.calls[1][0]).toEqual(
      expect.objectContaining({ afterSequence: 6, lastEventId: "run-a:6" }),
    );
  });

  it("surfaces malformed unknown frames without advancing the cursor", async () => {
    api.consumeResearchWorkflowEventStream.mockImplementation(async (options) => {
      options.onOpen?.();
      options.onFrame({
        id: "run-a:6",
        event: "workflow.brand_new.future_event",
        data: "{not-json",
      });
      await new Promise<void>((_resolve, reject) => {
        options.signal.addEventListener(
          "abort",
          () => reject(new DOMException("aborted", "AbortError")),
        );
      });
    });
    const onEvent = vi.fn();

    await act(async () => {
      root.render(<HookProbe onEvent={onEvent} onValue={(value) => { latest = value; }} />);
      await Promise.resolve();
    });

    expect(onEvent).not.toHaveBeenCalled();
    expect(latest?.error).toBe("工作流事件格式无效");
  });
});
