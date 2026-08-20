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
  allocateSidePaneWidths,
  clampPaneWidth,
  resolvePaneWidths,
  writePaneLayout,
  type PaneSpec,
  type PaneWidthMap,
} from "./paneLayoutPersistence";
import { attachAxisResizeSession } from "./attachAxisResizeSession";
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
  /** Host element for width reclamp (section/div page roots or workspace grids). */
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
        const next = allocateSidePaneWidths({
          containerWidth: total,
          panes,
          current,
          preserveMainMinWidth,
        });
        const changed = panes.some((pane) => next[pane.id] !== current[pane.id]);
        if (!changed) {
          return current;
        }
        writePaneLayout(layoutId, next);
        return next;
      });
    };
    reclamp();
    const observer = new ResizeObserver(reclamp);
    observer.observe(element);
    return () => observer.disconnect();
  }, [layoutId, panes, preserveMainMinWidth]);

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
      const direction = options?.direction ?? 1;
      const startX = event.clientX;
      const startWidth = widths[paneId] ?? spec.defaultWidth;
      setDrag({
        paneId,
        direction,
        startX,
        startWidth,
      });
      attachAxisResizeSession({
        cursor: "col-resize",
        onMove: (moveEvent) => {
          const delta = (moveEvent.clientX - startX) * direction;
          const nextWidth = clampPaneWidth(startWidth + delta, spec.minWidth, spec.maxWidth);
          setWidths((current) => (
            current[paneId] === nextWidth
              ? current
              : { ...current, [paneId]: nextWidth }
          ));
        },
        onEnd: () => {
          setDrag(null);
          setWidths((current) => {
            writePaneLayout(layoutId, current);
            return current;
          });
        },
      });
    },
    [layoutId, specs, widths],
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
