import type { KeyboardEvent, PointerEvent, ReactNode } from "react";

import styles from "./PaneResizeHandle.styles";

export type PaneResizeHandleProps = {
  label: string;
  valueNow: number;
  valueMin: number;
  valueMax: number;
  active?: boolean;
  /** When true, keeps hit target but disables lit rule / col-resize cursor. */
  collapsed?: boolean;
  className?: string;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  children?: ReactNode;
};

/**
 * Vertical resize separator (role=separator). Pair with usePersistedPaneResize.
 * Collapse + resize: use PaneCollapseHandle (composes this visual contract).
 */
export function PaneResizeHandle({
  label,
  valueNow,
  valueMin,
  valueMax,
  active = false,
  collapsed = false,
  className = "",
  onPointerDown,
  onKeyDown,
  children,
}: PaneResizeHandleProps) {
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(valueNow)}
      aria-valuemin={Math.round(valueMin)}
      aria-valuemax={Math.round(valueMax)}
      aria-disabled={collapsed || undefined}
      data-vui-layout-handle="resize"
      data-active={active ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      tabIndex={0}
      className={[
        styles.handle,
        active && !collapsed ? styles.handleActive : "",
        collapsed ? styles.handleCollapsed : "",
        className,
      ].filter(Boolean).join(" ")}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}

export { styles as paneResizeHandleStyles };
