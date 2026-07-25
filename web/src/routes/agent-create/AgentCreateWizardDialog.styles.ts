import {
  vuiElevatedPanelClass,
  vuiOpaqueRowClass,
  vuiStateWarningPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  overlay: "fixed inset-0 z-[90] grid min-w-0 place-items-center overflow-y-auto bg-[color-mix(in_srgb,var(--bg-canvas)_52%,transparent)] p-4 backdrop-blur-[5px] max-[700px]:p-2",
  // Wave 6H dialog policy: viewport clamp + internal scroll rows — not pane-heights.
  dialog: `grid w-[min(880px,calc(100vw-32px))] max-h-[calc(100dvh-64px)] min-w-0 [grid-template-rows:auto_minmax(0,1fr)] overflow-hidden ${vuiElevatedPanelClass} rounded-[calc(var(--radius-panel)_+_4px)] border-[color-mix(in_srgb,var(--vui-border-subtle)_94%,var(--accent-cool))] text-[var(--fg-primary)] shadow-[var(--vui-shadow-floating)] max-[700px]:w-[calc(100vw-16px)] max-[700px]:max-h-[calc(100dvh-16px)]`,
  header: `grid min-w-0 grid-cols-[minmax(0,1fr)_auto] items-start gap-4 border-b border-[var(--vui-border-subtle)] ${vuiOpaqueRowClass} border-x-0 border-t-0 rounded-none px-5 py-4 max-[700px]:px-4 max-[700px]:py-3`,
  heading: "grid min-w-0 gap-1 [&_h2]:m-0 [&_h2]:[font-size:var(--vui-font-lg)] [&_h2]:font-semibold [&_h2]:leading-tight [&_p]:m-0 [&_p]:[font-size:var(--vui-font-xs)] [&_p]:leading-relaxed [&_p]:text-[var(--fg-secondary)]",
  eyebrow: "text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--accent-cool)]",
  body: "min-h-0 overflow-y-auto px-5 py-4 max-[700px]:px-4 max-[700px]:py-3",
  confirmation: `grid gap-3 ${vuiStateWarningPanelClass} p-4 [&_p]:m-0 [&_p]:[font-size:var(--vui-font-sm)] [&_p]:text-[var(--fg-secondary)]`,
  confirmationActions: "flex flex-wrap justify-end gap-2",
  success: "grid min-h-[280px] content-center justify-items-start gap-3 px-3 py-6 [&>svg]:text-[var(--state-success)] [&_strong]:[font-size:var(--vui-font-lg)] [&_p]:m-0 [&_p]:text-[var(--fg-secondary)]",
  successActions: "flex flex-wrap gap-2 pt-2",
  error: "m-0 rounded-[var(--radius-control)] border-s-2 border-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-3 py-2 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
} as const;

export default styles;
