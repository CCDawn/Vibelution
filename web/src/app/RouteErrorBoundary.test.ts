import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import { buildRouteErrorBoundaryViewModel } from "./RouteErrorBoundary";

const routeErrorBoundarySource = readFileSync(new URL("./RouteErrorBoundary.tsx", import.meta.url), "utf8");

describe("RouteErrorBoundary view model", () => {
  it("turns stale dynamic route chunks into a user-facing refresh state", () => {
    const viewModel = buildRouteErrorBoundaryViewModel(
      new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/EvolutionRoute-old.js"),
      "workbench",
    );

    expect(viewModel.isDynamicImportFailure).toBe(true);
    expect(viewModel.kicker).toBe("前端资源已更新");
    expect(viewModel.title).toBe("工作台需要刷新");
    expect(viewModel.detail).toContain("旧版前端入口");
    expect(viewModel.primaryActionLabel).toBe("刷新前端");
    expect(viewModel.technicalSummary).toContain("EvolutionRoute-old.js");
  });

  it("keeps ordinary route errors out of the React Router default developer copy", () => {
    const viewModel = buildRouteErrorBoundaryViewModel(new Error("ordinary render failure"), "launcher");

    expect(viewModel.isDynamicImportFailure).toBe(false);
    expect(viewModel.kicker).toBe("Launcher 页面异常");
    expect(viewModel.title).toBe("Launcher 页面加载失败");
    expect(viewModel.detail).not.toContain("Hey developer");
    expect(viewModel.technicalSummary).toContain("ordinary render failure");
  });

  it("renders route recovery actions through shared VUI primitives", () => {
    expect(routeErrorBoundarySource).toContain("VButton");
    expect(routeErrorBoundarySource).toContain('data-vui-app={surface}');
    expect(routeErrorBoundarySource).not.toContain("<button");
    expect(routeErrorBoundarySource).not.toContain("RouteErrorBoundary.module.css");
    expect(routeErrorBoundarySource).not.toContain("styles.primaryAction");
    expect(routeErrorBoundarySource).not.toContain("#2563eb");
  });
});
