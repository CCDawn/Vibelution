import { isValidElement, type ComponentType, type ReactElement, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { RouteObject } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

import {
  importChatCodingRouteChunk,
  loadAgentsRouteChunk,
  loadCompanionsRouteChunk,
  loadChatCodingRouteChunk,
  loadEvolutionRouteChunk,
  loadMemoryRouteChunk,
  loadRouteChunkWithRecovery,
  loadTeamsRouteChunk,
  router,
} from "./router";
import routerSource from "./router.tsx?raw";

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

  it("keeps the transparent desktop pet outside the workbench shell", () => {
    const pet = findTopRoute("/desktop-pet");
    expectRouteErrorSurface(pet, "workbench");
    expectLazyFallback(pet, "正在打开工作台", "workbench");
    expect(findWorkbenchRoute("pet")).toBeTruthy();
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

  it("keeps the aggregated Evolution entry and the retired-nav deep links reachable", () => {
    // P2 nav collapse: the aggregate plus the four legacy paths must all stay
    // registered so existing deep links and bookmarks never 404.
    [
      "evolution/workspace",
      "supervised-evolution",
      "self-evolution",
      "kernel",
      "memory",
    ].forEach((path) => {
      expect(findWorkbenchRoute(path)).toBeTruthy();
    });

    // The aggregate renders the unforced EvolutionRoute: no forcedTrack/forcedView,
    // so the in-page track toggle owns the supervised/self split.
    const aggregate = findWorkbenchRoute("evolution/workspace");
    const suspense = aggregate.element as ReactElement<{ children?: ReactNode }>;
    const domainGate = suspense.props.children as ReactElement<{ children?: ReactNode }>;
    expect(isValidElement(domainGate)).toBe(true);
    expect((domainGate as ReactElement<{ domain?: string }>).props.domain).toBe("evolution");
    const evolutionRouteElement = domainGate.props.children as ReactElement<Record<string, unknown>>;
    expect(isValidElement(evolutionRouteElement)).toBe(true);
    expect(Object.keys(evolutionRouteElement.props)).toEqual([]);
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
    expect(configMarkup).not.toContain("animate-spin");

    const teamsMarkup = lazyFallbackMarkup(findWorkbenchRoute("teams"));
    expect(teamsMarkup).toContain('data-route-loading="teams"');
    expect(teamsMarkup).toContain('data-loading-region="team-canvas"');
    expect(teamsMarkup).toContain('data-loading-region="team-inspector"');
    expect(teamsMarkup).toContain("正在打开团队工作台");
    expect(teamsMarkup).not.toContain("animate-spin");
  });

  it("keeps the finance research frame visible while its route chunk loads", () => {
    const markup = lazyFallbackMarkup(findWorkbenchRoute("finance"));
    expect(markup).toContain('data-route-loading="finance"');
    expect(markup).toContain('data-vui-domain-recipe="financial-assistant-workspace"');
    expect(markup).toContain("炒股智能体");
    expect(markup).toContain("功能栏操作");
    expect(markup).toContain("研究对话");
    expect(markup).not.toContain("正在打开工作台");
  });

  it("guards the chat route while timing the chat chunk loader itself", async () => {
    const chatRoute = findWorkbenchRoute("chat");
    expectRouteErrorSurface(chatRoute, "workbench");
    expectLazyFallback(chatRoute, "正在加载对话", "workbench");
    const chatMarkup = lazyFallbackMarkup(chatRoute);
    expect(chatMarkup).toContain('data-route-loading="chat"');
    expect(chatMarkup).toContain('data-loading-region="chat-index"');
    expect(chatMarkup).toContain('data-loading-region="chat-workspace"');
    expect(chatMarkup).toContain('data-vui="chat-session-workbench-shell"');
    expect(chatMarkup).toContain('data-vui="skeleton"');
    expect(chatMarkup).toContain("min-h-[44px]");
    expect(chatMarkup).toContain("grid-cols-[32px_minmax(0,1fr)]");
    expect(chatMarkup).toContain("min-h-[104px]");
    expect(chatMarkup).not.toContain("animate-spin");

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

  it("keeps each remaining workbench frame while its route chunk loads", () => {
    const regions: Record<string, string> = {
      agents: "agents-workspace",
      "agents/prompts": "prompts-workspace",
      "agents/tools": "tools-workspace",
      "agents/skills": "skills-workspace",
      "evolution/workspace": "evolution-workspace",
      "supervised-evolution": "evolution-workspace",
      "supervised-evolution/runs": "evolution-runs",
      "supervised-evolution/library": "evolution-library",
      "supervised-evolution/review": "review-workspace",
      "self-evolution": "evolution-workspace",
      memory: "memory-personal",
      "memory/agents": "memory-personal",
      "memory/team": "memory-cards",
      "memory/library": "memory-cards",
      "memory/knowledge": "memory-knowledge",
      "memory/graph": "memory-graph",
      "memory/manage": "memory-ops",
      "memory/cleanup": "memory-ops",
      kernel: "kernel-workspace",
      aux: "aux-workspace",
      git: "git-workspace",
      usage: "usage-workspace",
      logs: "logs-workspace",
      pet: "pet-workspace",
      reset: "reset-workspace",
      companions: "companions-card",
    };
    for (const [path, region] of Object.entries(regions)) {
      const markup = lazyFallbackMarkup(findWorkbenchRoute(path));
      expect(markup, path).toContain(`data-loading-region="${region}"`);
      expect(markup, path).toContain('role="status"');
      expect(markup, path).toContain("正在打开工作台");
      expect(markup, path).not.toContain("animate-spin");
    }

    const launcher = findTopRoute("/launcher");
    const launcherIndex = launcher.children?.find((item) => item.index) as RouteObject;
    const launcherTools = launcher.children?.find((item) => item.path === "tools") as RouteObject;
    expect(lazyFallbackMarkup(launcherIndex)).toContain('data-loading-region="launcher-workspace"');
    expect(lazyFallbackMarkup(launcherTools)).toContain('data-loading-region="launcher-tools-workspace"');
    expect(lazyFallbackMarkup(findTopRoute("/desktop-pet"))).not.toContain('data-loading-region="pet-workspace"');

    const companions = lazyFallbackMarkup(findWorkbenchRoute("companions"));
    expect(companions).toContain("min-h-[min(590px,calc(100dvh-250px))]");
    expect(lazyFallbackMarkup(findWorkbenchRoute("usage"))).toContain("min-h-[96px]");
    expect(lazyFallbackMarkup(findWorkbenchRoute("git"))).toContain("min-h-[48px]");
    expect(lazyFallbackMarkup(findWorkbenchRoute("git"))).toContain("340px");
    expect(lazyFallbackMarkup(findWorkbenchRoute("kernel"))).toContain("min-h-[72px]");
    expect(lazyFallbackMarkup(findWorkbenchRoute("aux"))).toContain("min-h-14");
  });

  it("keeps the companion lobby separate while the native Chat route owns person conversations", () => {
    const lobbyRoute = findWorkbenchRoute("companions");
    expectRouteErrorSurface(lobbyRoute, "workbench");
    expectLazyFallback(lobbyRoute, "正在打开工作台", "workbench");

    const chatRoute = findWorkbenchRoute("chat");
    expectRouteErrorSurface(chatRoute, "workbench");
    expect(lazyFallbackMarkup(chatRoute)).toContain('data-vui="chat-session-workbench-shell"');
  });

  it("exports primary nav chunk loaders for the shell preload and idle warm", () => {
    // AppShell's hover/focus preload and idle warm reuse these loaders, so a
    // preload warms the exact chunk the route graph consumes.
    for (const loader of [
      loadTeamsRouteChunk,
      loadCompanionsRouteChunk,
      loadEvolutionRouteChunk,
      loadMemoryRouteChunk,
      loadAgentsRouteChunk,
    ]) {
      expect(typeof loader).toBe("function");
    }
    // The warm pass uses the telemetry-free chat import (no chunk telemetry).
    expect(typeof importChatCodingRouteChunk).toBe("function");
  });
});

function trackPromise<T>(promise: Promise<T>) {
  const state = {
    status: "pending" as "pending" | "fulfilled" | "rejected",
    reason: undefined as unknown,
    value: undefined as T | undefined,
  };
  promise.then(
    (result) => {
      state.status = "fulfilled";
      state.value = result;
    },
    (error) => {
      state.status = "rejected";
      state.reason = error;
    },
  );
  return state;
}

function stubChunkRecoveryWindow(pathname = "/teams") {
  const reload = vi.fn();
  const storage = new Map<string, string>();
  const win = {
    location: {
      pathname,
      search: "",
      hash: "",
      href: `http://127.0.0.1:8787${pathname}`,
      origin: "http://127.0.0.1:8787",
      reload,
    },
    sessionStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
    },
    navigator: { onLine: true },
  };
  vi.stubGlobal("window", win as unknown as Window & typeof globalThis);
  return { reload };
}

describe("lazy route chunk recovery degrade wiring", () => {
  beforeEach(() => {
    postBrowserTelemetryMock.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("keeps the route suspended during the grace window, then degrades a vetoed reload to the original error", async () => {
    vi.useFakeTimers();
    const { reload } = stubChunkRecoveryWindow();
    const chunkError = new TypeError("Failed to fetch dynamically imported module: http://127.0.0.1:8787/assets/TeamsRoute-old.js");
    const tracked = trackPromise(loadRouteChunkWithRecovery(() => Promise.reject(chunkError)));

    // The loader rejection lands on a microtask; flush it so recovery runs.
    await vi.advanceTimersByTimeAsync(0);
    // The recovery reload was requested; the lazy route stays suspended while
    // it could still tear this document down.
    expect(reload).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(3999);
    expect(tracked.status).toBe("pending");

    // The reload never took effect (vetoed by the project-close guard): the
    // original error now reaches React Router's errorElement.
    await vi.advanceTimersByTimeAsync(1);
    expect(tracked.status).toBe("rejected");
    expect(tracked.reason).toBe(chunkError);
    expect(postBrowserTelemetryMock).toHaveBeenCalledWith(
      expect.objectContaining({
        phase: "recovery",
        eventCode: "browser.route_chunk_recovery.reload_vetoed",
        level: "error",
      }),
    );
  });

  it("rethrows non-recovery loader errors immediately instead of suspending", async () => {
    const { reload } = stubChunkRecoveryWindow();
    const ordinaryError = new Error("ordinary loader failure");

    await expect(loadRouteChunkWithRecovery(() => Promise.reject(ordinaryError))).rejects.toBe(ordinaryError);
    expect(reload).not.toHaveBeenCalled();
    expect(postBrowserTelemetryMock).not.toHaveBeenCalled();
  });

  it("passes successful chunk loads through untouched", async () => {
    const LoadedRoute: ComponentType = () => null;
    const loaded = await loadRouteChunkWithRecovery(async () => ({ default: LoadedRoute }));

    expect(loaded.default).toBe(LoadedRoute);
  });

  it("wires the grace promise into the lazy route source contract", () => {
    expect(routerSource).toContain("createReloadGracePromise");
    expect(routerSource).toContain("recoverFromDynamicImportFetchError");
    // The eternal pending placeholder for vetoed reloads must stay gone.
    expect(routerSource).not.toContain("new Promise<{ default: T }>(() => undefined)");
  });
});
