import { Power, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";

import { cn } from "../../lib/cn";
import { VButton } from "../../primitives/VButton";
import { VDropdownMenu, type VDropdownMenuItem } from "../../primitives/VDropdownMenu";

export type VWorkbenchPowerMenuAction = "restart" | "stop" | "force-stop";

export type VWorkbenchPowerMenuLabels = {
  menu: string;
  restart: string;
  stop: string;
  forceStop: string;
};

export type VWorkbenchPowerMenuProps = {
  labels: VWorkbenchPowerMenuLabels;
  onAction: (action: VWorkbenchPowerMenuAction) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Disable the whole trigger (e.g. restart already in flight). */
  disabled?: boolean;
  restartDisabled?: boolean;
  stopDisabled?: boolean;
  forceStopDisabled?: boolean;
  showForceStop?: boolean;
  /**
   * `icon` — AppShell top-bar power glyph.
   * `labeled` — dense toolbar control with text (Launcher ops strip).
   */
  variant?: "icon" | "labeled";
  triggerClassName?: string;
  contentClassName?: string;
  itemClassName?: string;
  dangerItemClassName?: string;
  clusterClassName?: string;
  clusterOpenClassName?: string;
  /** Optional leading icon override for labeled trigger. */
  triggerIcon?: ReactNode;
  "data-vui"?: string;
};

/**
 * Unified workbench lifecycle power menu (shadcn DropdownMenu composition).
 * Single source of truth for restart / stop / force-stop entry points.
 */
export function VWorkbenchPowerMenu({
  labels,
  onAction,
  open,
  onOpenChange,
  disabled = false,
  restartDisabled = false,
  stopDisabled = false,
  forceStopDisabled = false,
  showForceStop = true,
  variant = "icon",
  triggerClassName,
  contentClassName,
  itemClassName,
  dangerItemClassName,
  clusterClassName,
  clusterOpenClassName,
  triggerIcon,
  "data-vui": dataVui = "workbench-power-menu",
}: VWorkbenchPowerMenuProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = useState(false);
  const isControlled = open !== undefined;
  const menuOpen = isControlled ? Boolean(open) : uncontrolledOpen;
  const setMenuOpen = (next: boolean) => {
    if (!isControlled) {
      setUncontrolledOpen(next);
    }
    onOpenChange?.(next);
  };

  const items: VDropdownMenuItem[] = [
    {
      id: "restart",
      icon: <RefreshCw size={15} aria-hidden="true" />,
      disabled: restartDisabled || disabled,
      label: labels.restart,
      onSelect: () => onAction("restart"),
    },
    {
      id: "stop",
      icon: <Power size={15} aria-hidden="true" />,
      disabled: stopDisabled || disabled,
      label: labels.stop,
      onSelect: () => onAction("stop"),
    },
    ...(showForceStop
      ? [{
          id: "force-stop",
          icon: <Power size={15} aria-hidden="true" />,
          danger: true as const,
          disabled: forceStopDisabled || disabled,
          label: labels.forceStop,
          onSelect: () => onAction("force-stop"),
        }]
      : []),
  ];

  const trigger = variant === "labeled" ? (
    <VButton
      type="button"
      variant="secondary"
      className={triggerClassName}
      aria-label={labels.menu}
      tooltip={labels.menu}
      title={labels.menu}
      isDisabled={disabled}
      icon={triggerIcon ?? <Power size={15} aria-hidden="true" />}
    >
      <span>{labels.menu}</span>
    </VButton>
  ) : (
    <VButton
      type="button"
      isIconOnly
      className={triggerClassName}
      aria-label={labels.menu}
      tooltip={labels.menu}
      title={labels.menu}
      isDisabled={disabled}
      icon={triggerIcon ?? <Power size={16} aria-hidden="true" />}
    />
  );

  return (
    <div
      className={cn(clusterClassName, menuOpen ? clusterOpenClassName : null)}
      data-vui={dataVui}
      data-open={menuOpen ? "true" : "false"}
    >
      <VDropdownMenu
        open={menuOpen}
        onOpenChange={setMenuOpen}
        align="end"
        side="bottom"
        aria-label={labels.menu}
        contentClassName={contentClassName}
        itemClassName={itemClassName}
        dangerItemClassName={dangerItemClassName}
        data-vui={`${dataVui}-dropdown`}
        trigger={trigger}
        items={items}
      />
    </div>
  );
}
