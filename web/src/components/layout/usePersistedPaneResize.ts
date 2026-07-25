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
  clampPaneWidth,
  resolvePaneWidths,
  writePaneLayout,
  type PaneSpec,
  type PaneWidthMap,
} from "./paneLayoutPersistence";
import {
  PANE_KEYBOARD_STEP,
  resolvePaneWidthFromKeyboardKey,
} from "./paneResizeKeyboard";

type DragState = {
  paneId: string;
  /** +1 grows the pane when pointer moves right; -1 for right-side panes. */
  direction: 1 | -1;
  startX: number;
  startWidth: number;
};

export type UsePersistedPaneResizeOptions = {
  /** Stable id for permanent localStorage memory (e.g. "agents", "skills"). */
  layoutId: string;
  panes: readonly PaneSpec[];
  /**
   * When true, re-clamp against container width so side panes leave room for main content.
   * mainMinWidth defaults to 360.
   */
  preserveMainMinWidth?: number;
};

export type UsePersistedPaneResizeResult = {
  layoutRef: RefObject<HTMLDivElement | null>;
  widths: PaneWidthMap;
  draggingPaneId: string | null;
  setPaneWidth: (paneId: string, width: number) => void;
  startResize: (
    paneId: string,
    event: ReactPointerEvent<HTMLDivElement>,
    options?: { direction?: 1 | -1 },
  ) => void;
  onResizeKeyDown: (
    paneId: string,
    event: ReactKeyboardEvent<HTMLDivElement>,
    options?: { direction?: 1 | -1 },
  ) => void;
  getPaneStyle: (paneId: string) => { width: number; flexBasis: number; minWidth: number; maxWidth: number };
};

function paneSpecMap(panes: readonly PaneSpec[]): Map<string, PaneSpec> {
  return new Map(panes.map((pane) => [pane.id, pane]));
}

/**
 * Persistent left/right pane resize for workbench shells.
 * Widths survive reloads under vibelution.pane-layouts.v1[layoutId].
 */
export function usePersistedPaneResize({
  layoutId,
  panes,
  preserveMainMinWidth = 360,
}: UsePersistedPaneResizeOptions): UsePersistedPaneResizeResult {
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const specs = useMemo(() => paneSpecMap(panes), [panes]);
  const [widths, setWidths] = useState<PaneWidthMap>(() => resolvePaneWidths(layoutId, panes));
  const [drag, setDrag] = useState<DragState | null>(null);

  // Re-resolve if layoutId / pane specs change (e.g. inspector appears).
  useEffect(() => {
    setWidths(resolvePaneWidths(layoutId, panes));
  }, [layoutId, panes]);

  const persist = useCallback(
    (next: PaneWidthMap) => {
      setWidths(next);
      writePaneLayout(layoutId, next);
    },
    [layoutId],
  );

  const setPaneWidth = useCallback(
    (paneId: string, width: number) => {
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      const nextWidth = clampPaneWidth(width, spec.minWidth, spec.maxWidth);
      persist({ ...widths, [paneId]: nextWidth });
    },
    [persist, specs, widths],
  );

  // Keep side panes from eating the main column when the window shrinks.
  useEffect(() => {
    const element = layoutRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }
    const reclamp = () => {
      const total = element.getBoundingClientRect().width;
      if (!total) {
        return;
      }
      setWidths((current) => {
        let next = { ...current };
        let changed = false;
        const handleBudget = panes.length * 6;
        const sideIds = panes.map((pane) => pane.id);
        let sideTotal = sideIds.reduce((sum, id) => sum + (next[id] ?? 0), 0);
        const maxSide = Math.max(preserveMainMinWidth, total - preserveMainMinWidth - handleBudget);
        if (sideTotal > maxSide && sideTotal > 0) {
          const scale = maxSide / sideTotal;
          for (const pane of panes) {
            const scaled = clampPaneWidth(
              Math.round((next[pane.id] ?? pane.defaultWidth) * scale),
              pane.minWidth,
              pane.maxWidth,
            );
            if (scaled !== next[pane.id]) {
              next[pane.id] = scaled;
              changed = true;
            }
          }
        }
        if (changed) {
          writePaneLayout(layoutId, next);
          return next;
        }
        return current;
      });
    };
    reclamp();
    const observer = new ResizeObserver(reclamp);
    observer.observe(element);
    return () => observer.disconnect();
  }, [layoutId, panes, preserveMainMinWidth]);

  useEffect(() => {
    if (!drag) {
      return;
    }
    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    const onMove = (event: PointerEvent) => {
      const spec = specs.get(drag.paneId);
      if (!spec) {
        return;
      }
      const delta = (event.clientX - drag.startX) * drag.direction;
      const nextWidth = clampPaneWidth(drag.startWidth + delta, spec.minWidth, spec.maxWidth);
      setWidths((current) => (
        current[drag.paneId] === nextWidth
          ? current
          : { ...current, [drag.paneId]: nextWidth }
      ));
    };
    const onUp = () => {
      setDrag(null);
      setWidths((current) => {
        writePaneLayout(layoutId, current);
        return current;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [drag, layoutId, specs]);

  const startResize = useCallback(
    (paneId: string, event: ReactPointerEvent<HTMLDivElement>, options?: { direction?: 1 | -1 }) => {
      if (event.button !== 0) {
        return;
      }
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      event.preventDefault();
      setDrag({
        paneId,
        direction: options?.direction ?? 1,
        startX: event.clientX,
        startWidth: widths[paneId] ?? spec.defaultWidth,
      });
    },
    [specs, widths],
  );

  const onResizeKeyDown = useCallback(
    (paneId: string, event: ReactKeyboardEvent<HTMLDivElement>, options?: { direction?: 1 | -1 }) => {
      const spec = specs.get(paneId);
      if (!spec) {
        return;
      }
      const next = resolvePaneWidthFromKeyboardKey(event.key, {
        direction: options?.direction ?? 1,
        step: PANE_KEYBOARD_STEP,
        minWidth: spec.minWidth,
        maxWidth: spec.maxWidth,
        currentWidth: widths[paneId] ?? spec.defaultWidth,
      });
      if (next == null) {
        return;
      }
      event.preventDefault();
      setPaneWidth(paneId, next);
    },
    [setPaneWidth, specs, widths],
  );

  const getPaneStyle = useCallback(
    (paneId: string) => {
      const spec = specs.get(paneId);
      const width = widths[paneId] ?? spec?.defaultWidth ?? 280;
      return {
        width,
        flexBasis: width,
        minWidth: spec?.minWidth ?? width,
        maxWidth: spec?.maxWidth ?? width,
      };
    },
    [specs, widths],
  );

  return {
    layoutRef,
    widths,
    draggingPaneId: drag?.paneId ?? null,
    setPaneWidth,
    startResize,
    onResizeKeyDown,
    getPaneStyle,
  };
}
