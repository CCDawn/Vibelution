import { ChevronLeft, ChevronRight } from "lucide-react";
import type { KeyboardEvent, MouseEvent, PointerEvent, ReactNode } from "react";

import { VIconButton } from "../vui";
import styles from "./PaneCollapseHandle.styles";
import { paneResizeHandleStyles } from "./PaneResizeHandle";

export type PaneSide = "left" | "right";

export type PaneCollapseHandleProps = {
  side: PaneSide;
  collapsed: boolean;
  className?: string;
  activeClassName?: string;
  active?: boolean;
  separatorLabel: string;
  collapseLabel: string;
  expandLabel: string;
  /** Optional resize value contract (aria + Wave 4B keyboard consumers). */
  valueNow?: number;
  valueMin?: number;
  valueMax?: number;
  onToggle: () => void;
  /** Root is a div separator; callers may keep legacy HTMLButtonElement handler types. */
  onPointerDown?: (event: PointerEvent<any>) => void;
  onMouseDown?: (event: MouseEvent<any>) => void;
  onKeyDown?: (event: KeyboardEvent<any>) => void;
  children?: ReactNode;
};

function stopHandleDrag(event: PointerEvent<HTMLButtonElement> | MouseEvent<HTMLButtonElement>) {
  event.stopPropagation();
}

/**
 * Combined collapse + resize separator (Wave 4B contract).
 * Visual rail rule comes from shared PaneResizeHandle styles; routes only pass placement classes.
 */
export function PaneCollapseHandle({
  side,
  collapsed,
  className = "",
  activeClassName = "",
  active = false,
  separatorLabel,
  collapseLabel,
  expandLabel,
  valueNow,
  valueMin,
  valueMax,
  onToggle,
  onPointerDown,
  onMouseDown,
  onKeyDown,
  children,
}: PaneCollapseHandleProps) {
  const label = collapsed ? expandLabel : collapseLabel;
  const iconDirection = side === "left"
    ? collapsed ? "right" : "left"
    : collapsed ? "left" : "right";
  const Icon = iconDirection === "left" ? ChevronLeft : ChevronRight;
  const tooltip = `${separatorLabel} · ${label}`;
  const hasValueContract =
    typeof valueNow === "number"
    && typeof valueMin === "number"
    && typeof valueMax === "number";
  const rootClassName = [
    paneResizeHandleStyles.handle,
    active && !collapsed ? paneResizeHandleStyles.handleActive : "",
    collapsed ? paneResizeHandleStyles.handleCollapsed : "",
    active && activeClassName ? activeClassName : "",
    className,
  ].filter(Boolean).join(" ");

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={separatorLabel}
      aria-valuenow={hasValueContract ? Math.round(valueNow) : undefined}
      aria-valuemin={hasValueContract ? Math.round(valueMin) : undefined}
      aria-valuemax={hasValueContract ? Math.round(valueMax) : undefined}
      aria-disabled={collapsed || undefined}
      data-vui-layout-handle="collapse-resize"
      data-side={side}
      data-active={active ? "true" : "false"}
      data-collapsed={collapsed ? "true" : "false"}
      tabIndex={0}
      className={rootClassName}
      onPointerDown={onPointerDown}
      onMouseDown={onMouseDown}
      onKeyDown={onKeyDown}
    >
      {children}
      <VIconButton
        type="button"
        className={[
          styles.paneToggleButtonClass,
          active ? styles.paneToggleButtonActive : "",
        ].filter(Boolean).join(" ")}
        label={label}
        tooltip={tooltip}
        aria-pressed={collapsed}
        onPointerDown={stopHandleDrag}
        onMouseDown={stopHandleDrag}
        onClick={(event) => {
          event.stopPropagation();
          onToggle();
        }}
        icon={<Icon size={15} strokeWidth={2.4} />}
      />
    </div>
  );
}
