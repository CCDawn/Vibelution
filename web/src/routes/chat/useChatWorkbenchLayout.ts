import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type KeyboardEvent,
  type PointerEvent,
  type RefObject,
  type SetStateAction,
} from "react";

import { resolveChatResponsiveLayout, type ChatResponsiveLayout } from "../chatCompactPanel";
import { useShellStore } from "../../store/shellStore";
import styles from "../ChatCodingRoute.styles";
import {
  clamp,
  getResizeBounds,
  normalizePanelWidths,
  type ResizableSide,
} from "./chatCodingRouteViewModel";

const KEYBOARD_RESIZE_STEP = 24;

type DragState = {
  side: ResizableSide;
  startX: number;
  startLeftWidth: number;
  startRightWidth: number;
};

export type UseChatWorkbenchLayoutOptions = {
  standardGroupRoomActive: boolean;
};

export type UseChatWorkbenchLayoutResult = {
  layoutRef: RefObject<HTMLDivElement | null>;
  dragState: DragState | null;
  responsiveLayout: ChatResponsiveLayout;
  leftPanelWidth: number;
  rightPanelWidth: number;
  conversationIndexCollapsed: boolean;
  statusRailCollapsed: boolean;
  conversationIndexOverlayOpen: boolean;
  statusRailOverlayOpen: boolean;
  responsiveOverlayOpen: boolean;
  layoutStyle: CSSProperties;
  chatLayoutClassName: string;
  centerPaneClassName: string;
  statusRailClassName: string;
  conversationIndexPaneClassName: string;
  handleResizeStart: (side: ResizableSide, event: PointerEvent<HTMLDivElement>) => void;
  handleResizeKeyDown: (side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) => void;
  closeResponsiveOverlayPane: () => void;
  setLeftRailCollapsed: Dispatch<SetStateAction<boolean>>;
  setRightPaneCollapsed: Dispatch<SetStateAction<boolean>>;
  setResponsiveOverlayPane: Dispatch<SetStateAction<"left" | "right" | null>>;
};

/**
 * Chat workbench shell layout: panel widths, resize drag/keyboard, responsive
 * collapse/overlay, and CSS vars / class names for the three-pane grid.
 */
export function useChatWorkbenchLayout({
  standardGroupRoomActive,
}: UseChatWorkbenchLayoutOptions): UseChatWorkbenchLayoutResult {
  const chatPanelWidths = useShellStore((state) => state.chatPanelWidths);
  const setChatPanelWidths = useShellStore((state) => state.setChatPanelWidths);
  const layoutRef = useRef<HTMLDivElement | null>(null);
  const [dragState, setDragState] = useState<DragState | null>(null);
  const [leftRailCollapsed, setLeftRailCollapsed] = useState(false);
  const [rightPaneCollapsed, setRightPaneCollapsed] = useState(false);
  const [responsiveLayout, setResponsiveLayout] = useState(() =>
    resolveChatResponsiveLayout(typeof window === "undefined" ? 1440 : window.innerWidth),
  );
  const [responsiveOverlayPane, setResponsiveOverlayPane] = useState<"left" | "right" | null>(null);

  const leftPanelWidth = chatPanelWidths.leftPanelWidth;
  const rightPanelWidth = chatPanelWidths.rightPanelWidth;

  const conversationIndexCollapsed = responsiveLayout.leftVisible
    ? leftRailCollapsed
    : responsiveOverlayPane !== "left";
  const statusRailCollapsed = responsiveLayout.rightVisible
    ? rightPaneCollapsed
    : responsiveOverlayPane !== "right";
  const conversationIndexOverlayOpen = !responsiveLayout.leftVisible && responsiveOverlayPane === "left";
  const statusRailOverlayOpen = !responsiveLayout.rightVisible && responsiveOverlayPane === "right";
  const responsiveOverlayOpen = conversationIndexOverlayOpen || statusRailOverlayOpen;

  const syncPanelWidthsToLayout = useCallback(() => {
    const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
    if (!layoutWidth) {
      return;
    }
    const normalized = normalizePanelWidths(layoutWidth, leftPanelWidth, rightPanelWidth);
    if (
      normalized.leftPanelWidth !== leftPanelWidth
      || normalized.rightPanelWidth !== rightPanelWidth
    ) {
      setChatPanelWidths(normalized);
    }
  }, [leftPanelWidth, rightPanelWidth, setChatPanelWidths]);

  useEffect(() => {
    const layoutElement = layoutRef.current;
    if (!layoutElement) {
      return;
    }
    const syncResponsiveLayout = () => {
      const width = layoutElement.getBoundingClientRect().width;
      const nextLayout = resolveChatResponsiveLayout(width);
      setResponsiveLayout((current) => (
        current.mode === nextLayout.mode
        && current.leftVisible === nextLayout.leftVisible
        && current.rightVisible === nextLayout.rightVisible
          ? current
          : nextLayout
      ));
      if (nextLayout.mode === "wide" || nextLayout.mode === "compact") {
        syncPanelWidthsToLayout();
      }
    };
    syncResponsiveLayout();
    const observer = new ResizeObserver(syncResponsiveLayout);
    observer.observe(layoutElement);
    return () => observer.disconnect();
  }, [syncPanelWidthsToLayout]);

  useEffect(() => {
    if (!responsiveOverlayPane || typeof window === "undefined") {
      return;
    }
    const handleEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") {
        return;
      }
      const closingPane = responsiveOverlayPane;
      setResponsiveOverlayPane(null);
      window.requestAnimationFrame(() => {
        document.getElementById(
          closingPane === "left" ? "chat-conversation-index-toggle" : "chat-status-toggle",
        )?.focus();
      });
    };
    window.addEventListener("keydown", handleEscape);
    return () => window.removeEventListener("keydown", handleEscape);
  }, [responsiveOverlayPane]);

  useEffect(() => {
    if (responsiveOverlayPane === "left" && responsiveLayout.leftVisible) {
      setResponsiveOverlayPane(null);
    } else if (responsiveOverlayPane === "right" && responsiveLayout.rightVisible) {
      setResponsiveOverlayPane(null);
    }
  }, [responsiveLayout.leftVisible, responsiveLayout.rightVisible, responsiveOverlayPane]);

  useEffect(() => {
    if (!dragState) {
      return;
    }
    const activeDrag = dragState;

    const previousCursor = document.body.style.cursor;
    const previousUserSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function stopDragging() {
      setDragState(null);
    }

    function handlePointerMove(event: globalThis.PointerEvent) {
      const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
      if (!layoutWidth) {
        return;
      }

      const delta = event.clientX - activeDrag.startX;

      if (activeDrag.side === "left") {
        if (conversationIndexCollapsed) {
          return;
        }
        const bounds = getResizeBounds("left", layoutWidth, statusRailCollapsed ? 0 : activeDrag.startRightWidth);
        const nextLeftWidth = clamp(activeDrag.startLeftWidth + delta, bounds.min, bounds.max);
        setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
        return;
      }

      if (statusRailCollapsed) {
        return;
      }
      const bounds = getResizeBounds("right", layoutWidth, conversationIndexCollapsed ? 0 : activeDrag.startLeftWidth);
      const nextRightWidth = clamp(activeDrag.startRightWidth - delta, bounds.min, bounds.max);
      setChatPanelWidths({ rightPanelWidth: Math.round(nextRightWidth) });
    }

    window.addEventListener("pointermove", handlePointerMove);
    window.addEventListener("pointerup", stopDragging);
    window.addEventListener("pointercancel", stopDragging);

    return () => {
      document.body.style.cursor = previousCursor;
      document.body.style.userSelect = previousUserSelect;
      window.removeEventListener("pointermove", handlePointerMove);
      window.removeEventListener("pointerup", stopDragging);
      window.removeEventListener("pointercancel", stopDragging);
    };
  }, [conversationIndexCollapsed, dragState, setChatPanelWidths, statusRailCollapsed]);

  const handleResizeStart = useCallback((side: ResizableSide, event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    if ((side === "left" && conversationIndexCollapsed) || (side === "right" && statusRailCollapsed)) {
      return;
    }
    event.preventDefault();
    setDragState({
      side,
      startX: event.clientX,
      startLeftWidth: leftPanelWidth,
      startRightWidth: rightPanelWidth,
    });
  }, [conversationIndexCollapsed, leftPanelWidth, rightPanelWidth, statusRailCollapsed]);

  const handleResizeKeyDown = useCallback((side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) => {
    if (!layoutRef.current) {
      return;
    }
    if ((side === "left" && conversationIndexCollapsed) || (side === "right" && statusRailCollapsed)) {
      return;
    }

    const { key } = event;
    const direction =
      key === "ArrowLeft" ? -1 : key === "ArrowRight" ? 1 : key === "Home" ? "min" : key === "End" ? "max" : null;
    if (direction === null) {
      return;
    }

    event.preventDefault();
    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, statusRailCollapsed ? 0 : rightPanelWidth);
      const nextLeftWidth =
        direction === "min"
          ? bounds.min
          : direction === "max"
            ? bounds.max
            : clamp(leftPanelWidth + Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
      setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, conversationIndexCollapsed ? 0 : leftPanelWidth);
    const delta =
      direction === "min"
        ? bounds.min
        : direction === "max"
          ? bounds.max
          : clamp(rightPanelWidth - Number(direction) * KEYBOARD_RESIZE_STEP, bounds.min, bounds.max);
    setChatPanelWidths({ rightPanelWidth: Math.round(delta) });
  }, [
    conversationIndexCollapsed,
    leftPanelWidth,
    rightPanelWidth,
    setChatPanelWidths,
    statusRailCollapsed,
  ]);

  const layoutStyle = useMemo(
    () =>
      ({
        "--chat-left-pane-width": conversationIndexCollapsed ? "0px" : `${leftPanelWidth}px`,
        "--chat-right-pane-width": statusRailCollapsed ? "0px" : `${rightPanelWidth}px`,
      }) as CSSProperties,
    [conversationIndexCollapsed, leftPanelWidth, rightPanelWidth, statusRailCollapsed],
  );

  const rightPaneLayoutClassName = standardGroupRoomActive ? styles.rightPaneWithTabs : styles.rightPaneWithoutTabs;
  const rightPaneClassName = `${styles.rightPane} ${rightPaneLayoutClassName}`;
  const layoutModeClassName = responsiveLayout.mode === "wide"
    ? styles.layout
    : responsiveLayout.mode === "compact"
      ? `${styles.layout} ${styles.layoutCompactDesktop}`
      : `${styles.layout} ${styles.layoutOverlay}`;
  const chatLayoutClassName = [
    layoutModeClassName,
    responsiveLayout.mode === "wide" && statusRailCollapsed ? styles.layoutStatusRailCollapsed : "",
  ].filter(Boolean).join(" ");
  const centerPaneClassName = responsiveLayout.mode === "overlay" || responsiveLayout.mode === "mobile"
    ? `${styles.centerPane} ${styles.centerPaneOverlay}`
    : styles.centerPane;
  const statusRailClassName = [
    styles.leftRail,
    statusRailCollapsed ? styles.paneCollapsed : "",
    statusRailOverlayOpen ? `${styles.overlayPane} ${styles.overlayPaneRight}` : "",
  ].filter(Boolean).join(" ");
  const conversationIndexPaneClassName = [
    rightPaneClassName,
    conversationIndexCollapsed ? styles.paneCollapsed : "",
    conversationIndexOverlayOpen ? `${styles.overlayPane} ${styles.overlayPaneLeft}` : "",
  ].filter(Boolean).join(" ");

  const closeResponsiveOverlayPane = useCallback(() => {
    const closingPane = responsiveOverlayPane;
    setResponsiveOverlayPane(null);
    if (closingPane && typeof window !== "undefined") {
      window.requestAnimationFrame(() => {
        document.getElementById(
          closingPane === "left" ? "chat-conversation-index-toggle" : "chat-status-toggle",
        )?.focus();
      });
    }
  }, [responsiveOverlayPane]);

  return {
    layoutRef,
    dragState,
    responsiveLayout,
    leftPanelWidth,
    rightPanelWidth,
    conversationIndexCollapsed,
    statusRailCollapsed,
    conversationIndexOverlayOpen,
    statusRailOverlayOpen,
    responsiveOverlayOpen,
    layoutStyle,
    chatLayoutClassName,
    centerPaneClassName,
    statusRailClassName,
    conversationIndexPaneClassName,
    handleResizeStart,
    handleResizeKeyDown,
    closeResponsiveOverlayPane,
    setLeftRailCollapsed,
    setRightPaneCollapsed,
    setResponsiveOverlayPane,
  };
}
