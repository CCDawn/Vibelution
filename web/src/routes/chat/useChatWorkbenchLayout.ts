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

import { attachAxisResizeSession } from "../../components/layout/attachAxisResizeSession";
import { PANE_KEYBOARD_STEP, resolvePaneWidthFromKeyboardKey } from "../../components/layout/paneResizeKeyboard";
import { WORKBENCH_LAYOUT_IDS } from "../../components/layout/workbenchLayoutIds";
import { resolveChatResponsiveLayout, type ChatResponsiveLayout } from "../chatCompactPanel";
import { useShellStore } from "../../store/shellStore";
import styles from "../ChatCodingRoute.styles";
import {
  clamp,
  getResizeBounds,
  normalizePanelWidths,
  type ResizableSide,
} from "./chatCodingRouteViewModel";

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
 *
 * Wave 5–6D Chat shell boundary (do not collapse into generic usePersistedPaneResize):
 * - Shared: attachAxisResizeSession, paneResizeKeyboard, WORKBENCH_LAYOUT_IDS.chat,
 *   PaneCollapseHandle visuals, dual-write via setChatPanelWidths → pane-layouts.v1[chat].
 * - Chat-owned: coupled left/right bounds (center track budget), responsive collapse/overlay,
 *   CSS grid template vars / class names for the three-pane session workbench.
 */
export const CHAT_WORKBENCH_LAYOUT_ID = WORKBENCH_LAYOUT_IDS.chat;

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

  const handleResizeStart = useCallback((side: ResizableSide, event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    if ((side === "left" && conversationIndexCollapsed) || (side === "right" && statusRailCollapsed)) {
      return;
    }
    event.preventDefault();
    // Wave 5: shared window pointer session; Chat keeps coupled dual-pane bounds + shellStore dual-write.
    const startX = event.clientX;
    const startLeftWidth = leftPanelWidth;
    const startRightWidth = rightPanelWidth;
    setDragState({
      side,
      startX,
      startLeftWidth,
      startRightWidth,
    });
    attachAxisResizeSession({
      cursor: "col-resize",
      onMove: (moveEvent) => {
        const layoutWidth = layoutRef.current?.getBoundingClientRect().width ?? 0;
        if (!layoutWidth) {
          return;
        }
        const delta = moveEvent.clientX - startX;
        if (side === "left") {
          if (conversationIndexCollapsed) {
            return;
          }
          const bounds = getResizeBounds("left", layoutWidth, statusRailCollapsed ? 0 : startRightWidth);
          const nextLeftWidth = clamp(startLeftWidth + delta, bounds.min, bounds.max);
          setChatPanelWidths({ leftPanelWidth: Math.round(nextLeftWidth) });
          return;
        }
        if (statusRailCollapsed) {
          return;
        }
        const bounds = getResizeBounds("right", layoutWidth, conversationIndexCollapsed ? 0 : startLeftWidth);
        const nextRightWidth = clamp(startRightWidth - delta, bounds.min, bounds.max);
        setChatPanelWidths({ rightPanelWidth: Math.round(nextRightWidth) });
      },
      onEnd: () => {
        setDragState(null);
      },
    });
  }, [
    conversationIndexCollapsed,
    leftPanelWidth,
    rightPanelWidth,
    setChatPanelWidths,
    statusRailCollapsed,
  ]);

  const handleResizeKeyDown = useCallback((side: ResizableSide, event: KeyboardEvent<HTMLDivElement>) => {
    if (!layoutRef.current) {
      return;
    }
    if ((side === "left" && conversationIndexCollapsed) || (side === "right" && statusRailCollapsed)) {
      return;
    }

    const layoutWidth = layoutRef.current.getBoundingClientRect().width;

    if (side === "left") {
      const bounds = getResizeBounds("left", layoutWidth, statusRailCollapsed ? 0 : rightPanelWidth);
      const nextLeftWidth = resolvePaneWidthFromKeyboardKey(event.key, {
        direction: 1,
        step: PANE_KEYBOARD_STEP,
        minWidth: bounds.min,
        maxWidth: bounds.max,
        currentWidth: leftPanelWidth,
      });
      if (nextLeftWidth == null) {
        return;
      }
      event.preventDefault();
      setChatPanelWidths({ leftPanelWidth: nextLeftWidth });
      return;
    }

    const bounds = getResizeBounds("right", layoutWidth, conversationIndexCollapsed ? 0 : leftPanelWidth);
    // Right rail grows when the pointer moves left; keyboard uses inverted direction.
    const nextRightWidth = resolvePaneWidthFromKeyboardKey(event.key, {
      direction: -1,
      step: PANE_KEYBOARD_STEP,
      minWidth: bounds.min,
      maxWidth: bounds.max,
      currentWidth: rightPanelWidth,
    });
    if (nextRightWidth == null) {
      return;
    }
    event.preventDefault();
    setChatPanelWidths({ rightPanelWidth: nextRightWidth });
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
  // When the docked status rail is closed, reclaim its grid track. Compact already
  // uses a 3-column template; wide needs the explicit override. Never apply on
  // overlay/mobile (single-column) or the center would be forced into a wrong track.
  const reclaimStatusRailTrack =
    statusRailCollapsed
    && !statusRailOverlayOpen
    && (responsiveLayout.mode === "wide" || responsiveLayout.mode === "compact");
  const chatLayoutClassName = [
    layoutModeClassName,
    reclaimStatusRailTrack ? styles.layoutStatusRailCollapsed : "",
  ].filter(Boolean).join(" ");
  const centerPaneClassName = responsiveLayout.mode === "overlay" || responsiveLayout.mode === "mobile"
    ? `${styles.centerPane} ${styles.centerPaneOverlay}`
    : styles.centerPane;
  // Critical: when docked status rail is collapsed, do NOT attach leftRail
  // (grid-column:5). A non-display:none item on column 5 creates implicit
  // grid tracks and a blank right strip after route remounts.
  const statusRailClassName = statusRailOverlayOpen
    ? `${styles.leftRail} ${styles.overlayPane} ${styles.overlayPaneRight}`
    : statusRailCollapsed
      ? styles.paneCollapsed
      : styles.leftRail;
  const conversationIndexPaneClassName = conversationIndexOverlayOpen
    ? `${rightPaneClassName} ${styles.overlayPane} ${styles.overlayPaneLeft}`
    : conversationIndexCollapsed
      ? styles.paneCollapsed
      : rightPaneClassName;

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
