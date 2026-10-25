/** @vitest-environment happy-dom */
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "../api/queryKeys";
import { refreshUpdateFreshness, UPDATE_FRESHNESS_QUERY_OPTIONS, useUpdateFreshnessFocus } from "./updateFreshness";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root;
let host: HTMLDivElement;
let client: QueryClient;
const code = vi.fn();
const launcher = vi.fn();

function Probe({ enabled }: { enabled: boolean }) {
  useUpdateFreshnessFocus(client, enabled);
  useQuery({ ...UPDATE_FRESHNESS_QUERY_OPTIONS, queryKey: queryKeys.codeFreshness(), queryFn: code, enabled });
  useQuery({ ...UPDATE_FRESHNESS_QUERY_OPTIONS, queryKey: queryKeys.launcherFreshness(), queryFn: launcher, enabled });
  return null;
}

async function mount(enabled = true) {
  code.mockReset().mockResolvedValue("current-code");
  launcher.mockReset().mockResolvedValue("current-shell");
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0, refetchOnWindowFocus: false } } });
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  await act(async () => {
    root.render(<QueryClientProvider client={client}><Probe enabled={enabled} /></QueryClientProvider>);
    await new Promise((resolve) => setTimeout(resolve, 10));
  });
}

afterEach(async () => {
  await act(async () => root?.unmount());
  host?.remove();
  client?.clear();
});

describe("shared update freshness refresh", () => {
  it("rechecks both owners after an update instead of only clearing the Launcher cache", async () => {
    await mount();
    code.mockResolvedValue("new-code");
    launcher.mockResolvedValue("new-shell");
    await act(async () => { await refreshUpdateFreshness(client); });
    expect(client.getQueryData(queryKeys.codeFreshness())).toBe("new-code");
    expect(client.getQueryData(queryKeys.launcherFreshness())).toBe("new-shell");
  });

  it("refreshes both owners on focus and reuses concurrent focus reads", async () => {
    await mount();
    let finish!: (value: string) => void;
    code.mockImplementation(() => new Promise<string>((resolve) => { finish = resolve; }));
    const beforeCode = code.mock.calls.length;
    const beforeLauncher = launcher.mock.calls.length;
    await act(async () => {
      window.dispatchEvent(new Event("focus"));
      window.dispatchEvent(new Event("pageshow"));
    });
    expect(code).toHaveBeenCalledTimes(beforeCode + 1);
    expect(launcher).toHaveBeenCalledTimes(beforeLauncher + 1);
    await act(async () => { finish("verified"); });
    expect(client.getQueryData(queryKeys.codeFreshness())).toBe("verified");
  });

  it("keeps freshness work off the startup critical path until enabled", async () => {
    await mount(false);
    await act(async () => { window.dispatchEvent(new Event("focus")); });
    expect(code).not.toHaveBeenCalled();
    expect(launcher).not.toHaveBeenCalled();
  });
});
