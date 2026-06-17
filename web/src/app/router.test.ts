import { describe, expect, it } from "vitest";

import routerSource from "./router.tsx?raw";

describe("router error boundary contract", () => {
  it("uses the project route error boundary instead of the React Router default boundary", () => {
    expect(routerSource).toContain("RouteErrorBoundary");
    expect(routerSource).toContain("errorElement: routeErrorElement(\"workbench\")");
    expect(routerSource).toContain("errorElement: routeErrorElement(\"launcher\")");
    expect(routerSource).toContain("guardedLazyElement");
    expect(routerSource).toContain("RouteLoadingShell");
    expect(routerSource).toContain("fallback={<RouteLoadingShell surface={surface} />}");
    expect(routerSource).not.toContain("fallback={null}");
    expect(routerSource).not.toContain("Hey developer");
  });

  it("times chat route chunk loading separately from route mount", () => {
    expect(routerSource).toContain("browser.chat_route.chunk_load_started");
    expect(routerSource).toContain("browser.chat_route.chunk_loaded");
    expect(routerSource).toContain("durationMs: elapsedMs(startedAt)");
  });

  it("guards the evolution routes that are split into dynamic chunks", () => {
    const supervisedStart = routerSource.indexOf('path: "supervised-evolution"');
    const supervisedRunsStart = routerSource.indexOf('path: "supervised-evolution/runs"');
    const supervisedLibraryStart = routerSource.indexOf('path: "supervised-evolution/library"');
    const selfEvolutionStart = routerSource.indexOf('path: "self-evolution"');

    expect(routerSource.slice(supervisedStart, supervisedStart + 260)).toContain("guardedLazyElement");
    expect(routerSource.slice(supervisedRunsStart, supervisedRunsStart + 260)).toContain("guardedLazyElement");
    expect(routerSource.slice(supervisedLibraryStart, supervisedLibraryStart + 260)).toContain("guardedLazyElement");
    expect(routerSource.slice(selfEvolutionStart, selfEvolutionStart + 260)).toContain("guardedLazyElement");
  });
});
