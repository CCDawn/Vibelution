import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type RefObject,
} from "react";

import {
  clampPaneHeight,
  persistPaneHeight,
  readPaneHeights,
  resolveStoredPaneHeight,
  writePaneHeights,
  type PaneHeightMap,
  type PaneHeightSpec,
} from "./paneHeightPersistence";
import { attachAxisResizeSession } from "./attachAxisResizeSession";
import {
  resolvePaneHeightFromKeyboardKey,
} from "./paneHeightKeyboard";
import { PANE_KEYBOARD_STEP } from "./paneResizeKeyboard";

type DragState = {
  paneId: string;
  direction: 1 | -1;
  startY: number;
  startHeight: number;
};

export type UsePersistedPaneHeightOptions = {
  layoutId: string;
  panes: readonly PaneHeightSpec[];
};

export type UsePersistedPaneHeightResult = {
  layoutRef: RefObject<HTMLDivElement | null>;
  heights: PaneHeightMap;
  draggingPaneId: string | null;
  setPaneHeight: (paneId: string, height: number) => void;
  startResize: (
    paneId: string,
    event: ReactPointerEvent<HTMLElement>,
    options?: { direction?: 1 | -1 },
  ) => void;
  onResizeKeyDown: (
    paneId: string,
    event: ReactKeyboardEvent<HTMLElement>,
    options?: { direction?: 1 | -1 },
  ) => void;
};

function paneSpecMap(panes: readonly PaneHeightSpec[]): Map<string, PaneHeightSpec> {
  return new Map(panes.map((pane) => [pane.id, pane]));
}

function resolveInitialHeights(
  layoutId: string,
  panes: readonly PaneHeightSpec[],
): PaneHeightMap {
  const stored = readPaneHeights(layoutId);
  const resolved: PaneHeightMap = {};
  for (const pane of panes) {
    const raw = stored[pane.id];
    resolved[pane.id] = clampPaneHeight(
      typeof raw === "number" ? raw : pane.defaultHeight,
      pane.minHeight,
      pane.maxHeight,
    );
  }
  return resolved;
}

/**
 * Persistent top/bottom pane height for workbench shells.
 * Heights survive reloads under vibelution.pane-heights.v1[layoutId].
 */
export function usePersistedPaneHeight({
  layoutId,
  panes,
}: UsePersistedPaneHeightOptions): UsePersistedPaneHeightResult {
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const specs = useMemo(() => paneSpecMap(panes), [panes]);
  const [heights, setHeights] = useState<PaneHeightMap>(() => resolveInitialHeights(layoutId, panes));
  const [drag, setDrag] = useState<DragState | null>(null);

  useEffect(() => {
    setHeights(resolveInitialHeights(layoutId, panes));
  }, [layoutId, panes]);

  const setPaneHeight = useCallback(
    (paneId: string, height: number) => {
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      const nextHeight = clampPaneHeight(height, spec.minHeight, spec.maxHeight);
      setHeights((current) => {
        const next = { ...current, [paneId]: nextHeight };
        writePaneHeights(layoutId, next);
        return next;
      });
    },
    [layoutId, specs],
  );

  const startResize = useCallback(
    (paneId: string, event: ReactPointerEvent<HTMLElement>, options?: { direction?: 1 | -1 }) => {
      if (event.button !== 0) {
        return;
      }
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      event.preventDefault();
      const direction = options?.direction ?? 1;
      const startY = event.clientY;
      const startHeight = heights[paneId] ?? spec.defaultHeight;
      setDrag({
        paneId,
        direction,
        startY,
        startHeight,
      });
      attachAxisResizeSession({
        cursor: "row-resize",
        onMove: (moveEvent) => {
          const delta = (moveEvent.clientY - startY) * direction;
          const nextHeight = clampPaneHeight(startHeight + delta, spec.minHeight, spec.maxHeight);
          setHeights((current) => (
            current[paneId] === nextHeight
              ? current
              : { ...current, [paneId]: nextHeight }
          ));
        },
        onEnd: () => {
          setDrag(null);
          setHeights((current) => {
            writePaneHeights(layoutId, current);
            return current;
          });
        },
      });
    },
    [heights, layoutId, specs],
  );

  const onResizeKeyDown = useCallback(
    (paneId: string, event: ReactKeyboardEvent<HTMLElement>, options?: { direction?: 1 | -1 }) => {
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      const next = resolvePaneHeightFromKeyboardKey(event.key, {
        direction: options?.direction ?? 1,
        step: PANE_KEYBOARD_STEP,
        minHeight: spec.minHeight,
        maxHeight: spec.maxHeight,
        currentHeight: heights[paneId] ?? spec.defaultHeight,
      });
      if (next == null) {
        return;
      }
      event.preventDefault();
      setPaneHeight(paneId, next);
    },
    [heights, setPaneHeight, specs],
  );

  return {
    layoutRef,
    heights,
    draggingPaneId: drag?.paneId ?? null,
    setPaneHeight,
    startResize,
    onResizeKeyDown,
  };
}

/** Convenience for one-off height panes that already migrated legacy keys. */
export function readPersistedPaneHeight(
  layoutId: string,
  pane: PaneHeightSpec,
  legacyStorageKey?: string,
): number {
  return resolveStoredPaneHeight(
    layoutId,
    pane.id,
    pane.defaultHeight,
    pane.minHeight,
    pane.maxHeight,
    legacyStorageKey,
  );
}

export function writePersistedPaneHeight(
  layoutId: string,
  paneId: string,
  height: number,
): void {
  persistPaneHeight(layoutId, paneId, height);
}
