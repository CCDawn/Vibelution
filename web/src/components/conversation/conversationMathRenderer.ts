/**
 * Lazy KaTeX pipeline for conversation markdown.
 *
 * KaTeX (+ its stylesheet) is ~240 KiB minified, while only a minority of
 * messages carry formulas. The renderer module therefore stays katex-free at
 * rest: the plugin module and stylesheet are fetched on the first message that
 * contains deliberate math (see containsDeliberateConversationMath), and the
 * render upgrades once both land. Messages without math never fetch it.
 */

export type RehypeKatexModule = typeof import("rehype-katex")["default"];

let katexModulePromise: Promise<RehypeKatexModule> | null = null;
let settledKatexModule: RehypeKatexModule | null = null;

/**
 * Fetch the rehype-katex plugin module plus the local KaTeX stylesheet once.
 * The stylesheet is part of the same dynamic import so a loaded plugin can
 * never render before its fonts/metrics CSS is attached (no unstyled flash).
 * Import-time side-effect free: nothing loads until the first math message.
 */
export function loadConversationMathRenderer(): Promise<RehypeKatexModule> {
  katexModulePromise ??= Promise.all([
    import("rehype-katex"),
    import("katex/dist/katex.min.css"),
  ]).then(([katexModule]) => {
    // Dynamic import yields the module namespace; the unified plugin lives on
    // the default export (runtime interop may or may not hoist it, hence the
    // namespace-then-namespace-default fallback).
    const namespace = katexModule as unknown as { default?: RehypeKatexModule };
    const katex = namespace.default ?? (katexModule as unknown as RehypeKatexModule);
    settledKatexModule = katex;
    return katex;
  });
  return katexModulePromise;
}

/** Synchronous peek: the loaded plugin module, or null before it arrives. */
export function peekConversationMathRenderer(): RehypeKatexModule | null {
  return settledKatexModule;
}
