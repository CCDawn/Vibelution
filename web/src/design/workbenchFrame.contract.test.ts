import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
const source = (path: string) => readFileSync(resolve(import.meta.dirname, "..", path), "utf8");
describe("shared workbench chrome ownership", () => {
  it("uses one persistent host in both shells, independent of route/loading shape", () => {
    for (const file of ["app/AppShell.tsx", "app/LauncherShell.tsx"]) {
      const shell = source(file);
      expect(shell).toContain("useMemo(() => <Outlet />, [])");
      expect(shell).toContain("<VWorkbenchFrame");
      expect(shell).toContain("{routeContent}</VWorkbenchFrame>");
      expect(shell).not.toMatch(/<VWorkbenchFrame[^>]*\bkey=/);
    }
  });
  it("declares common roles for exceptional roots and recovery states", () => {
    for (const path of ["routes/AgentsRoute.tsx", "routes/ConfigRoute.tsx", "routes/UsageRoute.tsx", "routes/finance/FinanceResearchFrame.tsx", "app/RouteLoadingShell.tsx", "app/RouteErrorBoundary.tsx", "components/vui/layout/VPage.tsx", "components/vui/layout/VWorkbenchPage.tsx", "components/vui/layout/VSessionWorkbenchPage.tsx"]) {
      expect(source(path), path).toContain("data-vui-page=");
    }
    expect(source("routes/ConfigRoute.tsx").match(/data-vui-page="workspace"/g)?.length).toBe(3);
  });
  it("keeps pane paint in shared CSS instead of subtree inference or a domain whitelist", () => {
    const css = source("design/workbench-frame.css");
    expect(css).not.toContain(":has(");
    expect(css).not.toContain("data-vui-domain-recipe");
    expect(css).toContain('data-vui-split-chrome="workbench"');
    expect(css).toContain("var(--vui-workbench-radius)");
    expect(source("design/workbench-shell.css")).not.toContain("Approved A chrome for secondary routes");
    expect(source("main.tsx")).toContain('import "./design/workbench-frame.css"');
  });
  it("lets standard recipes opt into shared panes", () => {
    for (const recipe of ["VListDetailPage", "VBoardWorkbenchPage", "VCanvasWorkbenchPage"]) {
      const code = source(`components/vui/layout/${recipe}.tsx`);
      expect(code).toContain('chrome="workspace"');
      if (recipe === "VBoardWorkbenchPage") {
        expect(code).toContain('chrome = "workbench"');
        expect(code).toContain('chrome={chrome}');
      } else {
        expect(code).toContain('chrome="workbench"');
      }
    }
  });
});
