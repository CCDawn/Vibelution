// @vitest-environment happy-dom
/**
 * Behavior contract for the active-turn-layers external store (stream render
 * isolation). Streaming assistant delta frames commit through this store
 * instead of workbench state, so:
 *  - the store keeps React `useState` setter semantics for its writers
 *    (functional updaters, reference-equal no-ops never notify),
 *  - a per-session subscriber re-renders only when ITS session's layer
 *    changes (unrelated sessions' frames are invisible),
 *  - primitive-signal subscribers re-render only when the derived value
 *    actually changes,
 *  - the read-through ref is current synchronously after every commit
 *    (frame-paint telemetry reads it outside render).
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  createActiveTurnLayersStore,
  ActiveTurnLayersStoreProvider,
  useActiveTurnLayerForSession,
  useActiveTurnLayersSignal,
  useActiveTurnLayersSignalFlag,
  type ActiveTurnLayersStore,
} from "./activeTurnLayersStore";
import type { ActiveTurnLayerState } from "../chatActiveTurnLayer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeLayer(sessionId: string, ledgerSeq: number): ActiveTurnLayerState {
  return {
    id: `${sessionId}-message-active-turn`,
    sessionId,
    turnId: "turn-1",
    updatedAt: "2026-01-01T00:00:00.000Z",
    status: "running",
    turnItems: [],
    ledgerSeq,
  };
}

let renderCounts: Record<string, number> = {};

function Probe({
  id,
  store,
  sessionId,
  select,
}: {
  id: string;
  store: ActiveTurnLayersStore;
  sessionId?: string;
  select?: (state: Record<string, ActiveTurnLayerState>) => string;
}) {
  const layer = sessionId === undefined ? undefined : useActiveTurnLayerForSession(sessionId);
  const signal = select ? useActiveTurnLayersSignal(select) : "";
  renderCounts[id] = (renderCounts[id] ?? 0) + 1;
  return (
    <div
      data-probe={id}
      data-layer-ledger={layer?.ledgerSeq ?? ""}
      data-signal={signal}
    />
  );
}

let root: Root | null = null;
let container: HTMLElement;

function renderTree(element: React.ReactElement) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(element);
  });
}

beforeEach(() => {
  renderCounts = {};
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
});

describe("activeTurnLayersStore", () => {
  it("updates an owner's turn signals before its returned Provider without per-frame rerenders", () => {
    const store = createActiveTurnLayersStore();
    function Owner() {
      const turnId = useActiveTurnLayersSignal((layers) => layers.s1?.turnId ?? "", store);
      const running = useActiveTurnLayersSignalFlag((layers) => layers.s1?.status === "running", store);
      renderCounts.owner = (renderCounts.owner ?? 0) + 1;
      return <ActiveTurnLayersStoreProvider store={store}>
        <div data-owner-turn={turnId} data-owner-running={String(running)} />
      </ActiveTurnLayersStoreProvider>;
    }
    renderTree(<Owner />);
    act(() => store.setActiveTurnLayersBySession({ s1: makeLayer("s1", 1) }));
    expect(container.querySelector("[data-owner-turn]")?.getAttribute("data-owner-turn")).toBe("turn-1");
    expect(container.querySelector("[data-owner-running]")?.getAttribute("data-owner-running")).toBe("true");
    const runningRenders = renderCounts.owner;
    act(() => store.setActiveTurnLayersBySession({ s1: makeLayer("s1", 2) }));
    expect(renderCounts.owner).toBe(runningRenders);
    act(() => store.setActiveTurnLayersBySession({ s1: { ...makeLayer("s1", 3), turnId: "turn-next" } }));
    expect(container.querySelector("[data-owner-turn]")?.getAttribute("data-owner-turn")).toBe("turn-next");
    expect(renderCounts.owner).toBe(runningRenders + 1);
    act(() => store.setActiveTurnLayersBySession({ s1: { ...makeLayer("s1", 4), turnId: "turn-next", status: "completed" } }));
    expect(container.querySelector("[data-owner-running]")?.getAttribute("data-owner-running")).toBe("false");
    expect(renderCounts.owner).toBe(runningRenders + 2);
  });

  it("keeps useState setter semantics: functional updaters apply, reference-equal results never notify", () => {
    const store = createActiveTurnLayersStore();
    let notifications = 0;
    const unsubscribe = store.subscribe(() => {
      notifications += 1;
    });

    const layer = makeLayer("s1", 1);
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({
        ...current,
        s1: layer,
      }));
    });
    expect(store.getSnapshot().s1).toBe(layer);
    expect(notifications).toBe(1);
    // Direct-value form is also supported (SetStateAction union).
    act(() => {
      store.setActiveTurnLayersBySession({});
    });
    expect(store.getSnapshot().s1).toBeUndefined();
    expect(notifications).toBe(2);

    act(() => {
      // setActiveTurnLayerForSession-style no-op: updater returns the same state.
      store.setActiveTurnLayersBySession((current) => current);
    });
    expect(notifications).toBe(2);
    unsubscribe();
  });

  it("keeps the read-through ref current synchronously after every commit", () => {
    const store = createActiveTurnLayersStore();
    const layer = makeLayer("s1", 7);
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: layer }));
    });
    expect(store.activeTurnLayersBySessionRef.current.s1).toBe(layer);
  });

  it("re-renders a per-session subscriber only for its own session's frames", () => {
    const store = createActiveTurnLayersStore();
    renderTree(
      <ActiveTurnLayersStoreProvider store={store}>
        <Probe id="sessionA" sessionId="s1" />
        <Probe id="sessionB" sessionId="s2" />
      </ActiveTurnLayersStoreProvider>,
    );
    const rendersAfterMount = { ...renderCounts };

    // A frame for an unrelated session must not re-render session A's subscriber.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s2: makeLayer("s2", 1) }));
    });
    expect(renderCounts.sessionA).toBe(rendersAfterMount.sessionA);
    expect(renderCounts.sessionB).toBe(rendersAfterMount.sessionB + 1);

    // A frame for the subscribed session re-renders it.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({
        ...current,
        s1: makeLayer("s1", 2),
      }));
    });
    expect(renderCounts.sessionA).toBe(rendersAfterMount.sessionA + 1);
    expect(container.querySelector("[data-probe='sessionA']")?.getAttribute("data-layer-ledger")).toBe("2");
  });

  it("re-renders a primitive-signal subscriber only when the selected value changes", () => {
    const store = createActiveTurnLayersStore();
    const selectRunningKey = (state: Record<string, ActiveTurnLayerState>) => {
      const ids = Object.entries(state)
        .filter(([, layer]) => layer.status === "running")
        .map(([sessionId]) => sessionId)
        .sort();
      return ids.join("|");
    };
    renderTree(
      <ActiveTurnLayersStoreProvider store={store}>
        <Probe id="signalProbe" select={selectRunningKey} />
      </ActiveTurnLayersStoreProvider>,
    );
    const rendersAfterMount = renderCounts.signalProbe;

    // Bring s1 into the running set first so the baseline includes it.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: makeLayer("s1", 1) }));
    });
    const rendersWithRunningSession = renderCounts.signalProbe;
    expect(rendersWithRunningSession).toBe(rendersAfterMount + 1);

    // Content revision for an already-running session keeps the key identical.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({ ...current, s1: makeLayer("s1", 2) }));
    });
    expect(renderCounts.signalProbe).toBe(rendersWithRunningSession);

    // A status transition changes the key and re-renders the subscriber.
    act(() => {
      store.setActiveTurnLayersBySession((current) => ({
        ...current,
        s1: { ...makeLayer("s1", 2), status: "completed" },
      }));
    });
    expect(renderCounts.signalProbe).toBe(rendersWithRunningSession + 1);
    expect(container.querySelector("[data-probe='signalProbe']")?.getAttribute("data-signal")).toBe("");
  });
});
