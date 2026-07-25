import type { KeyboardEvent, PointerEvent, ReactNode } from "react";

import styles from "./PaneHeightResizeHandle.styles";

export type PaneHeightResizeHandleProps = {
  label: string;
  valueNow: number;
  valueMin: number;
  valueMax: number;
  active?: boolean;
  className?: string;
  onPointerDown: (event: PointerEvent<HTMLDivElement>) => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  children?: ReactNode;
};

/**
 * Horizontal resize separator (role=separator, row-resize). Pair with usePersistedPaneHeight.
 */
export function PaneHeightResizeHandle({
  label,
  valueNow,
  valueMin,
  valueMax,
  active = false,
  className = "",
  onPointerDown,
  onKeyDown,
  children,
}: PaneHeightResizeHandleProps) {
  return (
    <div
      role="separator"
      aria-orientation="horizontal"
      aria-label={label}
      aria-valuenow={Math.round(valueNow)}
      aria-valuemin={Math.round(valueMin)}
      aria-valuemax={Math.round(valueMax)}
      data-vui-layout-handle="height-resize"
      data-active={active ? "true" : "false"}
      tabIndex={0}
      className={[styles.handle, active ? styles.handleActive : "", className].filter(Boolean).join(" ")}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}

export { styles as paneHeightResizeHandleStyles };
