/**
 * Global pointerdown dismiss for session/agent context menus must ignore
 * events that land inside the portaled menu surface; otherwise the menu
 * unmounts before Radix item onSelect (rename, create, …) can run.
 */
export function eventInsideContextMenuSurface(target: EventTarget | null): boolean {
  // Avoid `instanceof Element` so unit tests without a DOM still work; production
  // events always carry Element targets with `.closest`.
  const element = target as { closest?: (selector: string) => Element | null } | null;
  if (!element || typeof element.closest !== "function") {
    return false;
  }
  return Boolean(
    element.closest('[data-vui="dropdown-menu"]')
    || element.closest("[data-agent-context-menu]")
    || element.closest("[data-radix-dropdown-menu-content]")
    || element.closest("[data-radix-popper-content-wrapper]"),
  );
}
