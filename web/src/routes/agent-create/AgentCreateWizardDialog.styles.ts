import {
  vuiStateWarningPanelClass,
} from "../../design/vuiSurfaceRecipes";

const styles = {
  // Wave 6H dialog policy: viewport clamp on VDialog content — not pane-heights.
  dialogContent:
    "w-[min(880px,calc(100vw-32px))] max-h-[calc(100dvh-64px)] max-[700px]:w-[calc(100vw-16px)] max-[700px]:max-h-[calc(100dvh-16px)]",
  confirmation: `grid gap-3 ${vuiStateWarningPanelClass} p-4 [&_p]:m-0 [&_p]:[font-size:var(--vui-font-sm)] [&_p]:text-[var(--fg-secondary)]`,
  confirmationActions: "flex flex-wrap justify-end gap-2",
  success: "grid min-h-[280px] content-center justify-items-start gap-3 px-3 py-6 [&>svg]:text-[var(--state-success)] [&_strong]:[font-size:var(--vui-font-lg)] [&_p]:m-0 [&_p]:text-[var(--fg-secondary)]",
  successActions: "flex flex-wrap gap-2 pt-2",
  error: "m-0 rounded-[var(--radius-control)] border-s-2 border-[var(--state-error)] bg-[color-mix(in_srgb,var(--state-error)_8%,transparent)] px-3 py-2 [font-size:var(--vui-font-sm)] text-[var(--state-error)]",
} as const;

export default styles;
