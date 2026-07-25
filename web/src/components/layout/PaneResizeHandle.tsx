import type { KeyboardEvent, PointerEvent, ReactNode } from "react";

import styles from "./PaneResizeHandle.styles";

export type PaneResizeHandleProps = {
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
 * Vertical resize separator (role=separator). Pair with usePersistedPaneResize.
 * Collapse toggles should use PaneCollapseHandle on top of this or separately.
 */
export function PaneResizeHandle({
  label,
  valueNow,
  valueMin,
  valueMax,
  active = false,
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
      tabIndex={0}
      className={[styles.handle, active ? styles.handleActive : "", className].filter(Boolean).join(" ")}
      onPointerDown={onPointerDown}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}
