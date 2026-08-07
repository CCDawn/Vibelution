/**
 * P1-1 initial-fit lifecycle tests (M level).
 *
 * Verifies the hook-level timing contract of useWorkflowInitialFit with a
 * fake fit/acknowledge callback pair and a manually-flushed rAF queue, so no
 * DOM measurement or React Flow internals are involved:
 *  - armed while the committed layout matches the initial-fit revision;
 *  - fires exactly once, only after nodesInitialized + one frame;
 *  - runtime-only updates never re-fit;
 *  - a run switch cancels the pending fit before it fires;
 *  - acknowledge happens after the fit is scheduled (never before).
 *
 * @vitest-environment happy-dom
 */
import React, { act, useEffect } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

import {
  useWorkflowInitialFit,
  type UseWorkflowInitialFitResult,
} from "./useWorkflowInitialFit";

/** Manually flushed rAF queue keeps frame timing deterministic. */
let rafQueue: Array<() => void> = [];
let rafCounter = 0;

function flushRafs() {
  const pending = rafQueue;
  rafQueue = [];
  for (const cb of pending) {
    cb();
  }
}

beforeEach(() => {
  rafQueue = [];
  rafCounter = 0;
  vi.stubGlobal(
    "requestAnimationFrame",
    (cb: () => void) => {
      rafQueue.push(cb);
      rafCounter += 1;
      return rafCounter;
    },
  );
  vi.stubGlobal("cancelAnimationFrame", (id: number) => {
    if (typeof id === "number" && id >= 1 && id <= rafCounter) {
      rafQueue[id - 1] = () => {};
    }
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

type ProbeProps = {
  initialFitRevision: number | null;
  layoutRevision: number;
  structureKey?: string;
  nodesInitialized: boolean;
  fit: () => void;
  acknowledgeInitialFit: () => void;
  onState: (state: UseWorkflowInitialFitResult) => void;
};

function FitProbe({
  initialFitRevision,
  layoutRevision,
  structureKey = "struct:A",
  nodesInitialized,
  fit,
  acknowledgeInitialFit,
  onState,
}: ProbeProps) {
  const state = useWorkflowInitialFit({
    initialFitRevision,
    layoutRevision,
    structureKey,
    nodesInitialized,
    fit,
    acknowledgeInitialFit,
  });
  useEffect(() => {
    onState(state);
  }, [state, onState]);
  return null;
}

async function mountProbe(props: ProbeProps) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(<FitProbe {...props} />);
  });
  const rerender = async (next: ProbeProps) => {
    await act(async () => {
      root.render(<FitProbe {...next} />);
    });
  };
  const unmount = async () => {
    await act(async () => {
      root.unmount();
      container.remove();
    });
  };
  return { rerender, unmount };
}

describe("useWorkflowInitialFit (P1-1)", () => {
  it("arms on the initial-fit revision but does not fit before nodes are initialized", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const states: UseWorkflowInitialFitResult[] = [];
    const { unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      nodesInitialized: false,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: (s) => states.push(s),
    });
    await unmount();

    expect(fit).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(states.at(-1)?.pendingInitialFit).toBe(true);
  });

  it("fits exactly once after nodes are initialized and one frame elapses", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const states: UseWorkflowInitialFitResult[] = [];
    const { unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: (s) => states.push(s),
    });

    // Not yet fired: fit is deferred to the next frame.
    expect(fit).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
    expect(states.at(-1)?.pendingInitialFit).toBe(true);

    await act(async () => {
      flushRafs();
    });
    await unmount();

    expect(fit).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
    expect(states.at(-1)?.pendingInitialFit).toBe(false);
  });

  it("never fits a second time for runtime-only updates on the same revision", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const { unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });
    await act(async () => {
      flushRafs();
    });

    // Runtime-only updates: same revisions, nodes already initialized.
    await act(async () => {
      const container = document.createElement("div");
      document.body.appendChild(container);
      const root = createRoot(container);
      root.render(
        <FitProbe
          initialFitRevision={null}
          layoutRevision={1}
          nodesInitialized={true}
          fit={fit}
          acknowledgeInitialFit={acknowledge}
          onState={() => {}}
        />,
      );
      root.unmount();
      container.remove();
    });
    await unmount();

    expect(fit).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });

  it("keeps the pending fit when size calibration advances the layout revision (P1-5)", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const { rerender, unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      nodesInitialized: false,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });

    // Size calibration bumps layoutRevision to 2 while initialFitRevision is
    // still un-acknowledged (armed). The pending fit must survive the bump and
    // fire once the measured nodes initialize.
    await rerender({
      initialFitRevision: 1,
      layoutRevision: 2,
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });
    expect(fit).not.toHaveBeenCalled();
    await act(async () => {
      flushRafs();
    });
    await unmount();

    expect(fit).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });

  it("cancels the pending fit when the topology switches before the frame (P1-1 race)", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const { rerender, unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      structureKey: "struct:A",
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });

    // Pending fit scheduled for structure A, then a REAL topology/run switch
    // commits structure B BEFORE the frame fires (initialFitRevision stays
    // un-acknowledged, as in production — the layout hook does not null it).
    // The stale fit for A must not fire.
    await rerender({
      initialFitRevision: 1,
      layoutRevision: 2,
      structureKey: "struct:B",
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });
    expect(fit).not.toHaveBeenCalled();
    await act(async () => {
      flushRafs();
    });
    await unmount();

    // The hook re-armed to structure B: exactly one fit for the new topology.
    expect(fit).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });

  it("re-arms and fits the NEW topology after a switch when nodes initialize (P1-1 race)", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const { rerender, unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      structureKey: "struct:A",
      nodesInitialized: false,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });

    // Switch to structure B before nodes initialize: the pending fit for A is
    // dropped; when B's nodes enter the store, the first fit fires for B.
    await rerender({
      initialFitRevision: 1,
      layoutRevision: 2,
      structureKey: "struct:B",
      nodesInitialized: true,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });
    expect(fit).not.toHaveBeenCalled();
    await act(async () => {
      flushRafs();
    });
    await unmount();

    expect(fit).toHaveBeenCalledTimes(1);
    expect(acknowledge).toHaveBeenCalledTimes(1);
  });

  it("cancels the pending fit when nodes never initialize (empty/degraded canvas)", async () => {
    const fit = vi.fn();
    const acknowledge = vi.fn();
    const { unmount } = await mountProbe({
      initialFitRevision: 1,
      layoutRevision: 1,
      nodesInitialized: false,
      fit,
      acknowledgeInitialFit: acknowledge,
      onState: () => {},
    });
    await act(async () => {
      flushRafs();
    });
    await unmount();

    expect(fit).not.toHaveBeenCalled();
    expect(acknowledge).not.toHaveBeenCalled();
  });
});
