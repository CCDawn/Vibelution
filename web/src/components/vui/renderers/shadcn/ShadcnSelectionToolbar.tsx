import { useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

import {
  resolveSelectionToolbarPosition,
  SELECTION_TOOLBAR_HEIGHT_PX,
  SELECTION_TOOLBAR_WIDTH_PX,
  type SelectionToolbarAnchorRect,
} from "../../../layout/selectionToolbarPosition";
import { cn } from "../../lib/cn";

export type ShadcnSelectionToolbarProps = {
  anchorRect: SelectionToolbarAnchorRect;
  ariaLabel: string;
  children: ReactNode;
  className?: string;
};

const selectionToolbarClass = "fixed z-[80] flex min-w-0 w-max max-w-[calc(100vw-24px)] items-center gap-0.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-panel)] p-1 shadow-[var(--vui-shadow-hairline)]";

/** Viewport positioning without focus transfer, modal state, or action ownership. */
export function ShadcnSelectionToolbar({
  anchorRect,
  ariaLabel,
  children,
  className,
}: ShadcnSelectionToolbarProps) {
  const toolbarRef = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const toolbar = toolbarRef.current;
    if (!toolbar) return;
    const place = () => {
      const measured = toolbar.getBoundingClientRect();
      const position = resolveSelectionToolbarPosition(
        anchorRect,
        { width: window.innerWidth, height: window.innerHeight },
        {
          width: measured.width || SELECTION_TOOLBAR_WIDTH_PX,
          height: measured.height || SELECTION_TOOLBAR_HEIGHT_PX,
        },
      );
      toolbar.style.left = `${position.left}px`;
      toolbar.style.top = `${position.top}px`;
      toolbar.style.transform = position.above ? "translateY(-100%)" : "none";
    };
    place();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(toolbar);
    window.addEventListener("resize", place);
    return () => {
      observer?.disconnect();
      window.removeEventListener("resize", place);
    };
  }, [anchorRect.bottom, anchorRect.height, anchorRect.left, anchorRect.right, anchorRect.top, anchorRect.width]);

  const toolbar = (
    <div
      ref={toolbarRef}
      className={cn(selectionToolbarClass, className)}
      role="toolbar"
      aria-label={ariaLabel}
      data-vui="selection-toolbar"
      data-renderer="shadcn"
      // Keep the existing ConversationView outside-click boundary compatible.
      data-conversation-selection-menu="1"
      onMouseDown={(event) => event.preventDefault()}
    >
      {children}
    </div>
  );
  return typeof document === "undefined" ? toolbar : createPortal(toolbar, document.body);
}
