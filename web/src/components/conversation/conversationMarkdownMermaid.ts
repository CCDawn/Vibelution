/**
 * Mermaid support for settled conversation markdown code blocks (state-machine
 * semantics borrowed from zai-org/ZCode, Apache-2.0): the ```mermaid fence
 * stays plaintext behind an explicit render action; clicking loads the mermaid
 * module on demand (its own chunk), and a source budget gate keeps oversized
 * diagrams out of the renderer entirely.
 *
 * Budget + loader helpers are pure/module-scoped so tests can exercise them
 * without the component.
 */

/** Source budget: diagrams above either bound never enter the mermaid renderer. */
export const MERMAID_SOURCE_MAX_CHARS = 20_000;
export const MERMAID_SOURCE_MAX_LINES = 600;

export type MermaidSourceBudgetDecision =
  | { renderable: true }
  | { renderable: false; reason: "source-too-large" | "line-count-too-large" };

export function resolveMermaidSourceBudgetDecision(
  source: string,
  limits: { maxChars?: number; maxLines?: number } = {},
): MermaidSourceBudgetDecision {
  const text = String(source ?? "");
  const maxChars = limits.maxChars ?? MERMAID_SOURCE_MAX_CHARS;
  const maxLines = limits.maxLines ?? MERMAID_SOURCE_MAX_LINES;
  if (text.length > maxChars) {
    return { renderable: false, reason: "source-too-large" };
  }
  const lineCount = text.length === 0 ? 0 : text.split("\n").length;
  if (lineCount > maxLines) {
    return { renderable: false, reason: "line-count-too-large" };
  }
  return { renderable: true };
}

type MermaidModuleApi = (typeof import("mermaid"))["default"];

let mermaidModulePromise: Promise<MermaidModuleApi> | null = null;

/**
 * Lazily import mermaid (keeps it out of the main/renderer chunks) and
 * initialize it once: no auto-run on DOM content, strict security (the SVG
 * output is sanitized by mermaid), and no parallel error DOM injection.
 */
export function loadMermaidRenderer(): Promise<MermaidModuleApi> {
  mermaidModulePromise ??= import("mermaid").then((module) => {
    module.default.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      suppressErrorRendering: true,
    });
    return module.default;
  });
  return mermaidModulePromise;
}

/** Unique per-render id for mermaid's internal SVG registration. */
let mermaidRenderSequence = 0;
export function nextMermaidRenderId(): string {
  mermaidRenderSequence += 1;
  return `vibelution-mermaid-${mermaidRenderSequence}`;
}

export function normalizeMermaidRenderError(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  return raw.length > 200 ? `${raw.slice(0, 200)}…` : raw;
}
