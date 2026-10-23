/** @vitest-environment happy-dom */
import { focusManager, QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../api/client";
import { querySessions } from "../api/chat";
import { queryKeys } from "../api/queryKeys";
import { VuiProvider } from "../components/vui/VuiProvider";
import { HomeRedirect } from "../routes/HomeRedirect";
import { AppShell } from "./AppShell";
import { resetBrowserTelemetryDeliveryBufferForTests, setBrowserTelemetryStartupPending } from "./browserTelemetry";
import { resetWorkbenchUiPreferencesSyncForTests } from "./workbenchUiPreferencesSync";
import { resetWorkbenchWindowMemoryForTests } from "./workbenchWindowMemory";
import { useReportWorkbenchStartupReady } from "./workbenchStartupReady";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined;
let client: QueryClient | undefined;
let container: HTMLDivElement | undefined;

async function waitForRouteCommit(assertion: () => void) {
  // Navigate uses a transition. Flush each turn instead of holding one act
  // open while waiting for the transition that act itself needs to commit.
  await vi.waitFor(async () => {
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
    assertion();
  });
}

afterEach(async () => {
  await act(async () => root?.unmount());
  client?.clear();
  focusManager.setFocused(undefined);
  container?.remove();
  root = undefined;
  resetWorkbenchUiPreferencesSyncForTests();
  resetWorkbenchWindowMemoryForTests();
  resetBrowserTelemetryDeliveryBufferForTests();
  resetControlTokenForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Workbench initial route priority", () => {
  it("releases background owners when a nondefault session index reaches an error surface", async () => {
    seedControlTokenForTests();
    setBrowserTelemetryStartupPending(true);
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), window.location.origin).pathname;
      paths.push(path);
      const payload = path === "/api/health" ? { status: "ok", routesReady: true }
        : path.includes("companion-activity") ? []
          : path === "/api/runtime-tasks" ? { running: [], ended: [] }
            : path === "/api/workbench/ui-preferences" ? { schemaVersion: 1, paneLayouts: {}, shell: {} } : {};
      return new Response(JSON.stringify(payload), {
        status: path === "/api/sessions/query" ? 500 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
    function FailedIndexRoute() {
      const sessions = useQuery({
        queryKey: queryKeys.sessionQuery("", 50, "", "createdAt_desc"),
        queryFn: () => querySessions({ limit: 50, sort: "createdAt_desc" }),
      });
      useReportWorkbenchStartupReady(false, [sessions]);
      return <div>{sessions.isError ? "index failed" : "index loading"}</div>;
    }
    const router = createMemoryRouter([{
      element: <AppShell />, children: [{ path: "/chat", element: <FailedIndexRoute /> }],
    }], { initialEntries: ["/chat"] });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: 0 } } });
    // A successful bootstrap seeds default ordering, not the user's selected createdAt ordering.
    client.setQueryData(queryKeys.sessionQuery("", 50, "", "updatedAt_desc"), { pages: [{ items: [] }], pageParams: [""] });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(<VuiProvider><QueryClientProvider client={client!}><RouterProvider router={router} /></QueryClientProvider></VuiProvider>);
    });
    await act(async () => {
      await vi.waitFor(() => expect(container!.textContent).toContain("index failed"));
    });
    await act(async () => {
      await vi.waitFor(() => {
        expect(paths).toContain("/api/agent-plugins/virtual-human-life/companion-activity");
        expect(paths).toContain("/api/workbench/ui-preferences");
        expect(paths).toContain("/api/runtime/browser-telemetry");
      });
    });
    router.dispose();
  });

  it.each(["/chat", "/"])("holds background HTTP work from %s until route data settles, then keeps background owners alive", async (initialEntry) => {
    seedControlTokenForTests();
    setBrowserTelemetryStartupPending(true);
    const paths: string[] = [];
    const payloads: Record<string, unknown> = {
      "/api/config/bootstrap": {},
      "/api/launcher/current-instance": {},
      "/api/health": { status: "ok", routesReady: false },
      "/api/runtime/summary": {},
      "/api/runtime-tasks": { running: [], ended: [] },
      "/api/agent-plugins/virtual-human-life/companion-activity": [],
      "/api/workbench/ui-preferences": { schemaVersion: 1, paneLayouts: {}, shell: {} },
    };
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), window.location.origin).pathname;
      paths.push(path);
      return new Response(JSON.stringify(payloads[path] ?? {}), {
        status: 200, headers: { "Content-Type": "application/json" },
      });
    }));
    let settleRoute!: () => void;
    function InitialRoute() {
      const [ready, setReady] = useState(false);
      settleRoute = () => setReady(true);
      useReportWorkbenchStartupReady(ready);
      return <div data-testid="initial-route">{ready ? "ready" : "loading"}</div>;
    }
    const router = createMemoryRouter([{
      element: <AppShell />,
      children: [
        { index: true, element: <HomeRedirect /> },
        { path: "/chat", element: <InitialRoute /> },
        { path: "/teams", element: <div>teams</div> },
      ],
    }], { initialEntries: [initialEntry] });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: 0 } } });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(<VuiProvider><QueryClientProvider client={client!}><RouterProvider router={router} /></QueryClientProvider></VuiProvider>);
    });
    await act(async () => {
      await vi.waitFor(() => expect(paths).toContain("/api/config/bootstrap"));
    });
    await waitForRouteCommit(() => expect(container!.querySelector('[data-testid="initial-route"]')).not.toBeNull());
    expect(container.querySelector('[data-testid="initial-route"]')?.textContent).toBe("loading");
    const background = [
      "/api/runtime/summary", "/api/runtime-tasks", "/api/workbench/ui-preferences",
      "/api/agent-plugins/virtual-human-life/companion-activity", "/api/runtime/browser-telemetry",
      "/api/personal-assistant/human-attention",
    ];
    for (const path of background) expect(paths, path).not.toContain(path);
    await act(async () => settleRoute());
    await waitForRouteCommit(() => expect(paths).toContain("/api/runtime/summary"));
    for (const path of background.filter((path) => path !== "/api/runtime/summary")) {
      expect(paths, path).not.toContain(path);
    }
    // A hidden window must still notice that feature routes have finished loading.
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      focusManager.setFocused(false);
    });
    payloads["/api/health"] = { status: "ok", routesReady: true };
    await act(async () => {
      await vi.waitFor(() => {
        for (const path of background) expect(paths, path).toContain(path);
      }, { timeout: 3_000 });
    });
    expect(paths).not.toContain("/api/launcher/settings/startup");
    await act(async () => router.navigate("/teams"));
    expect(client.getQueryData(["runtime", "summary"])).toBeDefined();
    router.dispose();
  });

  it("releases background owners after the root chooses a non-chat homepage", async () => {
    seedControlTokenForTests();
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string | URL | Request) => {
      const path = new URL(String(url), window.location.origin).pathname;
      paths.push(path);
      const payload = path === "/api/config/bootstrap" ? { defaultRoute: "/teams", domainAvailability: { chat: false } }
        : path === "/api/health" ? { status: "ok", routesReady: true }
          : path.includes("companion-activity") ? []
            : path === "/api/runtime-tasks" ? { running: [], ended: [] } : {};
      return new Response(JSON.stringify(payload), { headers: { "Content-Type": "application/json" } });
    }));
    const router = createMemoryRouter([{
      element: <AppShell />,
      children: [{ index: true, element: <HomeRedirect /> }, { path: "/teams", element: <div>teams homepage</div> }],
    }], { initialEntries: ["/"] });
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000, gcTime: 0 } } });
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root!.render(<VuiProvider><QueryClientProvider client={client!}><RouterProvider router={router} /></QueryClientProvider></VuiProvider>);
    });
    await waitForRouteCommit(() => expect(paths).toContain("/api/runtime/summary"));
    expect(container.textContent).toContain("teams homepage");
    router.dispose();
  });
});
