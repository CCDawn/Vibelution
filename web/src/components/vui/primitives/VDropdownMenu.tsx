import { type ReactNode } from "react";

import {
  ShadcnDropdownMenu,
  type ShadcnDropdownMenuItem,
  type ShadcnDropdownMenuPosition,
  type ShadcnDropdownMenuProps,
} from "../renderers/shadcn/ShadcnDropdownMenu";

export type VDropdownMenuItem = ShadcnDropdownMenuItem;
export type VDropdownMenuPosition = ShadcnDropdownMenuPosition;

export type VDropdownMenuProps = {
  items: VDropdownMenuItem[];
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  /** Fixed coordinates for context-menu surfaces (virtual anchor). */
  position?: VDropdownMenuPosition;
  /** Classic dropdown trigger (button/icon). */
  trigger?: ReactNode;
  "aria-label"?: string;
  className?: string;
  contentClassName?: string;
  itemClassName?: string;
  dangerItemClassName?: string;
  "data-vui"?: string;
  contentProps?: Record<string, string | undefined>;
};

/**
 * Product dropdown / context menu API.
 * - Trigger mode: pass `trigger` (shadcn DropdownMenu pattern).
 * - Anchored mode: pass `position` for right-click / fixed surfaces.
 */
export function VDropdownMenu(props: VDropdownMenuProps) {
  return <ShadcnDropdownMenu {...(props as ShadcnDropdownMenuProps)} />;
}
