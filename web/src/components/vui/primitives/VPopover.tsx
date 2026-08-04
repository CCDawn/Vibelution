import { type ReactNode } from "react";

import {
  ShadcnPopover,
  type ShadcnPopoverProps,
} from "../renderers/shadcn/ShadcnPopover";

export type VPopoverProps = {
  trigger: ReactNode;
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  modal?: boolean;
  "aria-label"?: string;
  contentClassName?: string;
  className?: string;
  "data-vui"?: string;
};

/**
 * Product popover API — click/focus floating panel (not a menu of actions).
 * Prefer VDropdownMenu for action lists; VDialog for blocking flows.
 */
export function VPopover(props: VPopoverProps) {
  return <ShadcnPopover {...(props as ShadcnPopoverProps)} />;
}
