/**
 * Dialog / modal height policy (Wave 6H).
 *
 * Overlay dialogs and modal sheets must clamp to the viewport. They must not use
 * workbench pane-height persistence: permanent height memory fights short windows,
 * focus traps, and stacked overlays.
 *
 * Prefer viewport-relative max-height + internal scroll rows:
 * - max-h-[calc(100dvh-…)] / max-h-[min(…,calc(100dvh-…))]
 * - grid-template-rows: auto minmax(0,1fr) with overflow on the body
 *
 * Avoid:
 * - usePersistedPaneHeight / PersistedHeightListShell as dialog shell roots
 * - Fixed px-only max-h that overflows small displays without a viewport clamp
 */

export const DIALOG_HEIGHT_POLICY_MARKERS = {
  /** Strings expected on dialog shell max-height classes. */
  viewportTokens: ["100dvh", "100vh", "100dvw"] as const,
  /** Modules that must not import workbench height hooks for shell chrome. */
  forbiddenWorkbenchHeightApis: [
    "usePersistedPaneHeight",
    "PersistedHeightListShell",
  ] as const,
} as const;
