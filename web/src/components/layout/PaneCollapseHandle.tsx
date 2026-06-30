import { ChevronLeft, ChevronRight } from "lucide-react";
import type { KeyboardEvent, MouseEvent, PointerEvent, ReactNode } from "react";

import { VIconButton } from "../vui";

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

const paneHandleClass = "relative";
const paneToggleButtonClass = [
  "absolute left-1/2 top-1/2 z-[2] h-10 w-6 min-w-0 -translate-x-1/2 -translate-y-1/2 px-0",
  "rounded-[8px] border-vui-border-subtle bg-vui-surface-glass text-vui-fg-secondary shadow-[var(--vui-shadow-soft)]",
  "transition-[border-color,background-color,color,box-shadow] duration-150",
  "hover:border-vui-accent-warm hover:bg-vui-control-muted hover:text-[var(--accent-warm-2)] hover:shadow-[var(--vui-shadow-accent)]",
  "focus-visible:border-vui-accent-warm focus-visible:bg-vui-control-muted focus-visible:text-[var(--accent-warm-2)] focus-visible:shadow-[var(--vui-shadow-accent)]",
  "[&_svg]:shrink-0",
].join(" ");

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
    paneHandleClass,
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
        className={paneToggleButtonClass}
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
