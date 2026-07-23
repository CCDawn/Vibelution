import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ComponentProps,
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";

import { AgentFilterRail } from "../components/vui/product/agent-management";
import { AgentDetailWorkspacePanel } from "./AgentDetailWorkspacePanel";
import { AgentInspectorRailPanel } from "./AgentInspectorRailPanel";
import { AgentListWorkspacePanel } from "./AgentListWorkspacePanel";
import styles from "./AgentWorkspaceLayoutPanel.styles";

const STORAGE_KEY = "vibelution.agent-workspace.column-widths.v1";
const DEFAULT_LEFT = 300;
const DEFAULT_RIGHT = 320;
const MIN_LEFT = 220;
const MAX_LEFT = 480;
const MIN_RIGHT = 240;
const MAX_RIGHT = 480;
const MIN_MAIN = 360;
const KEYBOARD_STEP = 24;

type ColumnWidths = {
  left: number;
  right: number;
};

type DragSide = "left" | "right";

type DragState = {
  side: DragSide;
  startX: number;
  startLeft: number;
  startRight: number;
};

type AgentWorkspaceLayoutPanelProps = {
  detailWorkspace: ComponentProps<typeof AgentDetailWorkspacePanel>;
  filterRail: ComponentProps<typeof AgentFilterRail>;
  listWorkspace: ComponentProps<typeof AgentListWorkspacePanel>;
  inspectorRail?: ComponentProps<typeof AgentInspectorRailPanel> | null;
};

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function readStoredWidths(): ColumnWidths {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return { left: DEFAULT_LEFT, right: DEFAULT_RIGHT };
    }
    const parsed = JSON.parse(raw) as Partial<ColumnWidths>;
    return {
      left: clamp(Number(parsed.left) || DEFAULT_LEFT, MIN_LEFT, MAX_LEFT),
      right: clamp(Number(parsed.right) || DEFAULT_RIGHT, MIN_RIGHT, MAX_RIGHT),
    };
  } catch {
    return { left: DEFAULT_LEFT, right: DEFAULT_RIGHT };
  }
}

function normalizeWidths(totalWidth: number, left: number, right: number, hasInspector: boolean): ColumnWidths {
  if (!totalWidth) {
    return { left, right };
  }
  let nextLeft = clamp(left, MIN_LEFT, MAX_LEFT);
  let nextRight = hasInspector ? clamp(right, MIN_RIGHT, MAX_RIGHT) : 0;
  const handles = hasInspector ? 12 : 6;
  const maxSideBudget = Math.max(MIN_MAIN, totalWidth - MIN_MAIN - handles);
  if (hasInspector) {
    const sideTotal = nextLeft + nextRight;
    if (sideTotal > maxSideBudget) {
      const scale = maxSideBudget / sideTotal;
      nextLeft = clamp(Math.round(nextLeft * scale), MIN_LEFT, MAX_LEFT);
      nextRight = clamp(maxSideBudget - nextLeft, MIN_RIGHT, MAX_RIGHT);
    }
  } else if (nextLeft > maxSideBudget) {
    nextLeft = clamp(maxSideBudget, MIN_LEFT, MAX_LEFT);
  }
  return { left: nextLeft, right: nextRight || DEFAULT_RIGHT };
}

export function AgentWorkspaceLayoutPanel({
  detailWorkspace,
  filterRail,
  listWorkspace,
  inspectorRail = null,
}: AgentWorkspaceLayoutPanelProps) {
  const hasInspector = Boolean(inspectorRail);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [widths, setWidths] = useState<ColumnWidths>(() => (
    typeof window === "undefined" ? { left: DEFAULT_LEFT, right: DEFAULT_RIGHT } : readStoredWidths()
  ));
  const [dragState, setDragState] = useState<DragState | null>(null);

  const persistWidths = useCallback((next: ColumnWidths) => {
    setWidths(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } catch {
      // ignore storage failures
    }
  }, []);

  const syncToContainer = useCallback(() => {
    const total = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!total) {
      return;
    }
    const normalized = normalizeWidths(total, widths.left, widths.right, hasInspector);
    if (normalized.left !== widths.left || normalized.right !== widths.right) {
      persistWidths(normalized);
    }
  }, [hasInspector, persistWidths, widths.left, widths.right]);

  useEffect(() => {
    syncToContainer();
    const element = layoutRef.current;
    if (!element || typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(() => syncToContainer());
    observer.observe(element);
    return () => observer.disconnect();
  }, [syncToContainer]);

  useEffect(() => {
    if (!dragState) {
      return;
    }
    const onMove = (event: PointerEvent) => {
      const total = layoutRef.current?.getBoundingClientRect().width ?? 0;
      const delta = event.clientX - dragState.startX;
      if (dragState.side === "left") {
        const nextLeft = clamp(dragState.startLeft + delta, MIN_LEFT, MAX_LEFT);
        const normalized = normalizeWidths(total, nextLeft, dragState.startRight, hasInspector);
        setWidths(normalized);
        return;
      }
      const nextRight = clamp(dragState.startRight - delta, MIN_RIGHT, MAX_RIGHT);
      const normalized = normalizeWidths(total, dragState.startLeft, nextRight, hasInspector);
      setWidths(normalized);
    };
    const onUp = () => {
      setDragState(null);
      setWidths((current) => {
        try {
          window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
        } catch {
          // ignore
        }
        return current;
      });
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
  }, [dragState, hasInspector]);

  const startResize = (side: DragSide, event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    setDragState({
      side,
      startX: event.clientX,
      startLeft: widths.left,
      startRight: widths.right,
    });
  };

  const onResizeKeyDown = (side: DragSide, event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
      return;
    }
    event.preventDefault();
    const total = layoutRef.current?.getBoundingClientRect().width ?? 0;
    const delta = event.key === "ArrowRight" ? KEYBOARD_STEP : -KEYBOARD_STEP;
    if (side === "left") {
      const nextLeft = clamp(widths.left + delta, MIN_LEFT, MAX_LEFT);
      persistWidths(normalizeWidths(total, nextLeft, widths.right, hasInspector));
      return;
    }
    const nextRight = clamp(widths.right - delta, MIN_RIGHT, MAX_RIGHT);
    persistWidths(normalizeWidths(total, widths.left, nextRight, hasInspector));
  };

  const layoutStyle = {
    ["--agent-left-w" as string]: `${widths.left}px`,
    ["--agent-right-w" as string]: `${widths.right}px`,
  } as CSSProperties;

  return (
    <div
      ref={layoutRef}
      className={styles.workspace}
      style={layoutStyle}
      data-agent-workspace="resizable"
      data-has-inspector={hasInspector ? "true" : "false"}
    >
      <div
        className={styles.directory}
        style={{ width: widths.left, flexBasis: widths.left }}
        data-agent-pane="directory"
      >
        <div className={styles.directoryFilter}>
          <AgentFilterRail {...filterRail} />
        </div>
        <div className={styles.directoryList}>
          <AgentListWorkspacePanel {...listWorkspace} />
        </div>
      </div>

      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="调整目录栏宽度"
        aria-valuenow={Math.round(widths.left)}
        aria-valuemin={MIN_LEFT}
        aria-valuemax={MAX_LEFT}
        tabIndex={0}
        className={[
          styles.resizeHandle,
          dragState?.side === "left" ? styles.resizeHandleActive : "",
        ].filter(Boolean).join(" ")}
        onPointerDown={(event) => startResize("left", event)}
        onKeyDown={(event) => onResizeKeyDown("left", event)}
      />

      <div className={styles.main} data-agent-pane="main">
        <AgentDetailWorkspacePanel {...detailWorkspace} />
      </div>

      {hasInspector && inspectorRail ? (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="调整侧栏宽度"
            aria-valuenow={Math.round(widths.right)}
            aria-valuemin={MIN_RIGHT}
            aria-valuemax={MAX_RIGHT}
            tabIndex={0}
            className={[
              styles.resizeHandle,
              dragState?.side === "right" ? styles.resizeHandleActive : "",
            ].filter(Boolean).join(" ")}
            onPointerDown={(event) => startResize("right", event)}
            onKeyDown={(event) => onResizeKeyDown("right", event)}
          />
          <div
            className={styles.inspector}
            style={{ width: widths.right, flexBasis: widths.right }}
            data-agent-pane="inspector"
          >
            <AgentInspectorRailPanel {...inspectorRail} />
          </div>
        </>
      ) : null}
    </div>
  );
}
