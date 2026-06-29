import { ChevronLeft, ChevronRight } from "lucide-react";
import type { KeyboardEvent, MouseEvent, PointerEvent, ReactNode } from "react";

import { VIconButton } from "../vui";
import styles from "./PaneCollapseHandle.module.css";

type PaneSide = "left" | "right";

type PaneCollapseHandleProps = {
  side: PaneSide;
  collapsed: boolean;
  className?: string;
  activeClassName?: string;
  active?: boolean;
  separatorLabel: string;
  collapseLabel: string;
  expandLabel: string;
  onToggle: () => void;
  onPointerDown?: (event: PointerEvent<any>) => void;
  onMouseDown?: (event: MouseEvent<any>) => void;
  onKeyDown?: (event: KeyboardEvent<any>) => void;
  children?: ReactNode;
};

function stopHandleDrag(event: PointerEvent<HTMLButtonElement> | MouseEvent<HTMLButtonElement>) {
  event.stopPropagation();
}

export function PaneCollapseHandle({
  side,
  collapsed,
  className = "",
  activeClassName = "",
  active = false,
  separatorLabel,
  collapseLabel,
  expandLabel,
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
  const rootClassName = [
    styles.handle,
    className,
    active ? activeClassName : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={separatorLabel}
      title={separatorLabel}
      tabIndex={0}
      className={rootClassName}
      onPointerDown={onPointerDown}
      onMouseDown={onMouseDown}
      onKeyDown={onKeyDown}
    >
      {children}
      <VIconButton
        type="button"
        className={styles.toggleButton}
        label={label}
        title={label}
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
