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
  /**
   * Fired when the user activates a blocked action (soft-disabled item).
   * Surfaces should show a notice — native disabled items give zero feedback.
   */
  onBlockedAction?: (action: VWorkbenchPowerMenuAction, reason: string) => void;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Disable the whole trigger (e.g. restart already in flight). */
  disabled?: boolean;
  /** Why the whole menu trigger is disabled (busy / lifecycle in flight). */
  disabledReason?: string;
  restartDisabled?: boolean;
  stopDisabled?: boolean;
  forceStopDisabled?: boolean;
  restartDisabledReason?: string;
  stopDisabledReason?: string;
  forceStopDisabledReason?: string;
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
  onBlockedAction,
  open,
  onOpenChange,
  disabled = false,
  disabledReason = "",
  restartDisabled = false,
  stopDisabled = false,
  forceStopDisabled = false,
  restartDisabledReason = "",
  stopDisabledReason = "",
  forceStopDisabledReason = "",
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

  function selectAction(
    action: VWorkbenchPowerMenuAction,
    blocked: boolean,
    reason: string,
  ) {
    if (disabled || blocked) {
      const message = String(reason || disabledReason || "").trim()
        || (action === "restart"
          ? labels.restart
          : action === "stop"
            ? labels.stop
            : labels.forceStop);
      onBlockedAction?.(action, message);
      return;
    }
    onAction(action);
  }

  // Soft-disabled: keep items selectable so surfaces can show a notice.
  // Hard Radix `disabled` + pointer-events-none yields zero click/hover feedback.
  const items: VDropdownMenuItem[] = [
    {
      id: "restart",
      icon: <RefreshCw size={15} aria-hidden="true" />,
      disabled: false,
      title: restartDisabled || disabled
        ? (restartDisabledReason || disabledReason || labels.restart)
        : labels.restart,
      label: labels.restart,
      onSelect: () => selectAction("restart", restartDisabled, restartDisabledReason),
    },
    {
      id: "stop",
      icon: <Power size={15} aria-hidden="true" />,
      disabled: false,
      title: stopDisabled || disabled
        ? (stopDisabledReason || disabledReason || labels.stop)
        : labels.stop,
      label: labels.stop,
      onSelect: () => selectAction("stop", stopDisabled, stopDisabledReason),
    },
    ...(showForceStop
      ? [{
          id: "force-stop",
          icon: <Power size={15} aria-hidden="true" />,
          danger: true as const,
          disabled: false,
          title: forceStopDisabled || disabled
            ? (forceStopDisabledReason || disabledReason || labels.forceStop)
            : labels.forceStop,
          label: labels.forceStop,
          onSelect: () => selectAction("force-stop", forceStopDisabled, forceStopDisabledReason),
        }]
      : []),
  ];

  const triggerTooltip = disabled && disabledReason
    ? disabledReason
    : labels.menu;

  const trigger = variant === "labeled" ? (
    <VButton
      type="button"
      variant="secondary"
      className={triggerClassName}
      aria-label={labels.menu}
      tooltip={triggerTooltip}
      title={triggerTooltip}
      isDisabled={disabled}
      disabledReason={disabled ? disabledReason : undefined}
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
      tooltip={triggerTooltip}
      title={triggerTooltip}
      isDisabled={disabled}
      disabledReason={disabled ? disabledReason : undefined}
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
