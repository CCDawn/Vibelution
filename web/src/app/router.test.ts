import { isValidElement, type ComponentType, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { RouteObject } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createBrowserRouterMock = vi.hoisted(() => vi.fn((routes: RouteObject[]) => ({ routes })));
const postBrowserTelemetryMock = vi.hoisted(() => vi.fn());

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual<typeof import("react-router-dom")>("react-router-dom");
  return {
    ...actual,
    createBrowserRouter: createBrowserRouterMock,
  };
});

vi.mock("./browserTelemetry", () => ({
  postBrowserTelemetry: postBrowserTelemetryMock,
}));

import { loadChatCodingRouteChunk, router } from "./router";

type CapturedRouter = {
  routes: RouteObject[];
};

type ChatCodingRouteModule = typeof import("../routes/ChatCodingRoute");

function capturedRoutes(): RouteObject[] {
  return (router as unknown as CapturedRouter).routes;
}

function findTopRoute(path: string): RouteObject {
  const route = capturedRoutes().find((item) => item.path === path);
  expect(route, `top route ${path}`).toBeTruthy();
  return route as RouteObject;
}

function findWorkbenchRoute(path: string): RouteObject {
  const root = findTopRoute("/");
  const route = root.children?.find((item) => item.path === path);
  expect(route, `workbench route ${path}`).toBeTruthy();
  return route as RouteObject;
}

function expectRouteErrorSurface(route: RouteObject, surface: "launcher" | "workbench") {
  expect(isValidElement(route.errorElement)).toBe(true);
  expect((route.errorElement as ReactElement<{ surface?: string }>).props.surface).toBe(surface);
}

function expectLazyFallback(route: RouteObject, expectedLabel: string, expectedSurface: "launcher" | "workbench") {
  expect(isValidElement(route.element)).toBe(true);
  const fallback = (route.element as ReactElement<{ fallback?: ReactNode }>).props.fallback;
  expect(isValidElement(fallback)).toBe(true);
  const markup = renderToStaticMarkup(fallback as ReactElement);
  expect(markup).toContain('role="status"');
  expect(markup).toContain('aria-busy="true"');
  expect(markup).toContain(`data-vui-app="${expectedSurface}"`);
  expect(markup).toContain(expectedLabel);
  expect(markup).not.toContain("Hey developer");
  expect(markup).not.toContain("style=");
}

function lazyFallbackMarkup(route: RouteObject): string {
  expect(isValidElement(route.element)).toBe(true);
  const fallback = (route.element as ReactElement<{ fallback?: ReactNode }>).props.fallback;
  expect(isValidElement(fallback)).toBe(true);
  return renderToStaticMarkup(fallback as ReactElement);
}

describe("router route contracts", () => {
  beforeEach(() => {
    postBrowserTelemetryMock.mockClear();
  });

  it("builds launcher and workbench roots with project-owned error boundaries", () => {
    expect(createBrowserRouterMock).toHaveBeenCalledTimes(1);

    const launcher = findTopRoute("/launcher");
    expectRouteErrorSurface(launcher, "launcher");
    const launcherIndex = launcher.children?.find((item) => item.index);
    expect(launcherIndex).toBeTruthy();
    expectRouteErrorSurface(launcherIndex as RouteObject, "launcher");
    expectLazyFallback(launcherIndex as RouteObject, "正在打开启动器", "launcher");

    const workbench = findTopRoute("/");
    expectRouteErrorSurface(workbench, "workbench");
    expect(workbench.children?.find((item) => item.index)).toBeTruthy();
  });

  it("guards split evolution routes with loading fallback and error boundary elements", () => {
    [
      "supervised-evolution",
      "supervised-evolution/runs",
      "supervised-evolution/library",
      "self-evolution",
    ].forEach((path) => {
      const route = findWorkbenchRoute(path);
      expectRouteErrorSurface(route, "workbench");
      expectLazyFallback(route, "正在打开工作台", "workbench");
    });
  });

  it("guards the usage route with workbench fallback and error boundary elements", () => {
    const route = findWorkbenchRoute("usage");
    expectRouteErrorSurface(route, "workbench");
    expectLazyFallback(route, "正在打开工作台", "workbench");
  });

  it("keeps settings and Team workspace structure visible while route chunks load", () => {
    const configMarkup = lazyFallbackMarkup(findWorkbenchRoute("config"));
    expect(configMarkup).toContain('data-route-loading="config"');
    expect(configMarkup).toContain('data-loading-region="settings-navigation"');
    expect(configMarkup).toContain('data-loading-region="settings-content"');
    expect(configMarkup).toContain("正在打开设置工作台");
    expect(configMarkup).toContain("animate-spin");

    const teamsMarkup = lazyFallbackMarkup(findWorkbenchRoute("teams"));
    expect(teamsMarkup).toContain('data-route-loading="teams"');
    expect(teamsMarkup).toContain('data-loading-region="team-canvas"');
    expect(teamsMarkup).toContain('data-loading-region="team-inspector"');
    expect(teamsMarkup).toContain("正在打开团队工作台");
    expect(teamsMarkup).toContain("animate-spin");
  });

  it("guards the chat route while timing the chat chunk loader itself", async () => {
    const chatRoute = findWorkbenchRoute("chat");
    expectRouteErrorSurface(chatRoute, "workbench");
    expectLazyFallback(chatRoute, "正在打开对话工作台", "workbench");
    const chatMarkup = lazyFallbackMarkup(chatRoute);
    expect(chatMarkup).toContain('data-route-loading="chat"');
    expect(chatMarkup).toContain('data-loading-region="chat-index"');
    expect(chatMarkup).toContain('data-loading-region="chat-workspace"');

    const ChatRoute: ComponentType = () => null;
    const loaded = await loadChatCodingRouteChunk(
      async () => ({ ChatCodingRoute: ChatRoute }) as ChatCodingRouteModule,
    );

    expect(loaded.default).toBe(ChatRoute);
    expect(postBrowserTelemetryMock).toHaveBeenNthCalledWith(
      1,
      expect.objectContaining({
        phase: "navigation",
        eventCode: "browser.chat_route.chunk_load_started",
        fields: expect.objectContaining({ pathname: "" }),
      }),
    );
    expect(postBrowserTelemetryMock).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({
        phase: "navigation",
        eventCode: "browser.chat_route.chunk_loaded",
        fields: expect.objectContaining({
          durationMs: expect.any(Number),
          pathname: "",
        }),
      }),
    );
  });
});
