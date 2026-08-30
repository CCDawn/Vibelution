import { readFileSync } from "node:fs";
import { afterEach, describe, expect, it, vi } from "vitest";

import { postBrowserTelemetry } from "./browserTelemetry";
import {
  buildRouteErrorBoundaryViewModel,
  buildRouteErrorTelemetryEvent,
  reportRouteErrorBoundary,
  resetRouteErrorTelemetryForTests,
} from "./RouteErrorBoundary";

vi.mock("./browserTelemetry", () => ({
  postBrowserTelemetry: vi.fn(),
}));

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

  it("labels router ErrorResponse 404 as a missing page with navigable primary action", () => {
    const notFoundError = {
      status: 404,
      statusText: "Not Found",
      internal: false,
      data: 'No route matches URL "/teams/research-workflow"',
    };
    const viewModel = buildRouteErrorBoundaryViewModel(notFoundError, "workbench");

    expect(viewModel.isDynamicImportFailure).toBe(false);
    expect(viewModel.kicker).toBe("工作台页面不存在");
    expect(viewModel.title).toContain("页面不存在");
    expect(viewModel.primaryActionLabel).toBe("返回工作台");
    expect(viewModel.primaryAction).toBe("navigate");
    expect(viewModel.secondaryActionLabel).toBe("刷新前端");
    expect(viewModel.secondaryAction).toBe("reload");
    expect(viewModel.technicalSummary).toContain("404");
    expect(viewModel.technicalSummary).toContain('No route matches URL "/teams/research-workflow"');
    expect(viewModel.technicalSummary).not.toContain("[object Object]");
  });

  it("reports non-404 ErrorResponse status in the failure copy", () => {
    const serverError = { status: 500, statusText: "Internal Server Error", internal: false, data: "boom" };
    const viewModel = buildRouteErrorBoundaryViewModel(serverError, "workbench");

    expect(viewModel.isDynamicImportFailure).toBe(false);
    expect(viewModel.title).toContain("HTTP 500");
    expect(viewModel.primaryActionLabel).toBe("刷新前端");
    expect(viewModel.primaryAction).toBe("reload");
    expect(viewModel.technicalSummary).toContain("500");
    expect(viewModel.technicalSummary).not.toContain("[object Object]");
  });

  it("serializes non-Error objects instead of leaking [object Object]", () => {
    const viewModel = buildRouteErrorBoundaryViewModel({ reason: "mystery" }, "workbench");

    expect(viewModel.technicalSummary).toContain('"reason"');
    expect(viewModel.technicalSummary).toContain('"mystery"');
    expect(viewModel.technicalSummary).not.toContain("[object Object]");
  });

  it("renders route recovery actions through shared VUI primitives", () => {
    expect(routeErrorBoundarySource).toContain("VButton");
    expect(routeErrorBoundarySource).toContain('data-vui-app={surface}');
    expect(routeErrorBoundarySource).not.toContain("<button");
    expect(routeErrorBoundarySource).not.toContain("RouteErrorBoundary.module.css");
    expect(routeErrorBoundarySource).toContain("allowNextWorkbenchWindowUnload");
    expect(routeErrorBoundarySource).toContain("location.reload()");
    expect(routeErrorBoundarySource).not.toContain("styles.primaryAction");
    expect(routeErrorBoundarySource).not.toContain("#2563eb");
    expect(routeErrorBoundarySource).toContain("useEffect");
    expect(routeErrorBoundarySource).toContain("reportRouteErrorBoundary");
    expect(routeErrorBoundarySource).toContain("browser.route.error");
  });
});

describe("RouteErrorBoundary telemetry", () => {
  afterEach(() => {
    resetRouteErrorTelemetryForTests();
    vi.mocked(postBrowserTelemetry).mockClear();
  });

  it("builds a scene-ready route error event without page body text", () => {
    vi.stubGlobal("window", { location: { pathname: "/git" } });
    const error = new Error("ordinary render failure");
    const event = buildRouteErrorTelemetryEvent(error, "workbench");

    expect(event).toMatchObject({
      phase: "error",
      eventCode: "browser.route.error",
      level: "error",
      message: "workbench route render failed",
      fields: {
        surface: "workbench",
        pathname: "/git",
        isDynamicImportFailure: false,
        title: "工作台页面加载失败",
        errorName: "Error",
        errorMessage: "Error: ordinary render failure",
      },
    });
    expect(String(event.fields?.technicalSummary)).toContain("ordinary render failure");
  });

  it("marks stale dynamic import failures in telemetry fields", () => {
    const event = buildRouteErrorTelemetryEvent(
      new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8000/assets/EvolutionRoute-old.js"),
      "launcher",
    );

    expect(event.message).toBe("launcher route chunk failed to load");
    expect(event.fields).toMatchObject({
      surface: "launcher",
      isDynamicImportFailure: true,
      title: "Launcher 需要刷新",
    });
  });

  it("posts one telemetry event per unique route error", () => {
    const error = new Error("unique route crash");
    reportRouteErrorBoundary(error, "workbench");
    reportRouteErrorBoundary(error, "workbench");

    expect(postBrowserTelemetry).toHaveBeenCalledTimes(1);
    expect(vi.mocked(postBrowserTelemetry).mock.calls[0]?.[0]).toMatchObject({
      eventCode: "browser.route.error",
      fields: {
        surface: "workbench",
        errorMessage: "Error: unique route crash",
      },
    });
  });
});
