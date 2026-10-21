// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchConfigBootstrap, updateConfigLanguage } from "../api/config";
import { queryKeys } from "../api/queryKeys";
import { useAppI18n } from "./useAppI18n";
import { useShellI18n } from "./useShellI18n";

vi.mock("../api/config", () => ({
  fetchConfigBootstrap: vi.fn(),
  updateConfigLanguage: vi.fn(),
}));

globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let root: Root | undefined;
let client: QueryClient | undefined;
let host: HTMLDivElement | undefined;

afterEach(async () => {
  await act(async () => root?.unmount());
  client?.clear();
  host?.remove();
  vi.clearAllMocks();
});

function LocaleProbe() {
  const shell = useShellI18n();
  const app = useAppI18n({ domains: ["core"] });
  return <output data-shell-language={shell.lang} data-app-language={app.lang} />;
}

async function expectLanguages(language: "zh" | "en") {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    if (host?.querySelector("output")?.getAttribute("data-shell-language") === language
      && host?.querySelector("output")?.getAttribute("data-app-language") === language) return;
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  }
  expect(host?.querySelector("output")?.getAttribute("data-shell-language")).toBe(language);
  expect(host?.querySelector("output")?.getAttribute("data-app-language")).toBe(language);
}

describe("Bootstrap locale cache", () => {
  it("shares the existing config key and refreshes both locales after a language save", async () => {
    vi.mocked(fetchConfigBootstrap)
      .mockResolvedValueOnce({ language: "en" } as Awaited<ReturnType<typeof fetchConfigBootstrap>>)
      .mockResolvedValueOnce({ language: "zh" } as Awaited<ReturnType<typeof fetchConfigBootstrap>>);
    vi.mocked(updateConfigLanguage).mockResolvedValue({ language: "zh" } as Awaited<ReturnType<typeof updateConfigLanguage>>);
    client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);

    await act(async () => root?.render(<QueryClientProvider client={client!}><LocaleProbe /></QueryClientProvider>));
    await expectLanguages("en");
    expect(fetchConfigBootstrap).toHaveBeenCalledTimes(1);
    expect(client.getQueryData(queryKeys.configPublic())).toEqual({ language: "en" });

    await act(async () => {
      await updateConfigLanguage("zh");
      await client!.invalidateQueries({ queryKey: queryKeys.configPublic() });
    });

    await expectLanguages("zh");
    expect(fetchConfigBootstrap).toHaveBeenCalledTimes(2);
    expect(client.getQueryData(queryKeys.configPublic())).toEqual({ language: "zh" });
  });
});
