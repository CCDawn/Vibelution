import { vuiFlatPanelClass } from "../../design/vuiSurfaceRecipes";

/**
 * The Launcher model popover keeps the canonical conversation model recipe
 * (flat panel, overlay radius, soft elevation) and only widens the shell so a
 * provider-grouped candidate list has room. The list body is the shared
 * `ConversationModelCandidateList`, never a host-local copy.
 */
const styles = {
  root: "inline-flex h-7 min-w-0 max-w-full items-center",
  popover: `grid w-[min(352px,calc(100vw-16px))] gap-2.5 rounded-[var(--vui-radius-overlay)] border border-[color-mix(in_srgb,var(--fg-primary)_22%,transparent)] ${vuiFlatPanelClass} p-3 shadow-[0_12px_32px_color-mix(in_srgb,var(--fg-primary)_12%,transparent),var(--vui-shadow-soft)]`,
  actions: "flex items-center justify-end border-t border-[var(--vui-border-subtle)] pt-1.5",
  services: "grid gap-1 border-t border-[var(--vui-border-subtle)] pt-2",
  servicesLabel: "px-1 text-[length:var(--vui-font-size-xs)] text-[var(--fg-secondary)]",
  servicesList: "grid gap-0.5",
  serviceRow: "flex w-full items-center justify-between gap-2 rounded-[var(--vui-radius-control)] px-1.5 py-1 text-left text-[length:var(--vui-font-size-sm)]",
  serviceName: "min-w-0 truncate",
  serviceCount: "shrink-0 text-[length:var(--vui-font-size-xs)] text-[var(--fg-secondary)]",
} as const;

export default styles;
