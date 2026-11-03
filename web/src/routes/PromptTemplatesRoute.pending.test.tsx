// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchPromptTemplate, resetPromptTemplate, updatePromptTemplate } from "../api/agents";
import { queryKeys } from "../api/queryKeys";
import type { PromptTemplate } from "../api/types";
import { PromptTemplatesRoute } from "./PromptTemplatesRoute";

vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh", t: (key: string) => key }) }));
vi.mock("../api/agents", () => ({
  fetchPromptTemplate: vi.fn(), listAgentSummaries: vi.fn(), listPromptTemplates: vi.fn(),
  resetPromptTemplate: vi.fn(), updatePromptTemplate: vi.fn(),
}));
vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);

function template(id: string): PromptTemplate {
  return {
    promptTemplateId: id, name: `模板 ${id}`, category: "general", sourceType: "inline_record", sourcePath: "",
    sourceExists: true, sourceAuthority: "record_content", sourceDriftStatus: "synced", sourceContentHash: "",
    content: `正文 ${id}`, contentHash: "", hasDefault: true, defaultContent: "默认正文", defaultContentHash: "",
    defaultContentPreview: "默认正文", status: "active", metadata: {}, createdAt: "", updatedAt: "",
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
const tick = () => new Promise<void>((done) => setTimeout(done, 0));
let root: Root, host: HTMLDivElement, client: QueryClient;
const button = (text: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((row) => row.textContent?.trim() === text);
const templateButton = (id: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find((row) => row.querySelector("strong")?.textContent === `模板 ${id}`);
async function click(target: HTMLButtonElement | undefined) {
  expect(target).toBeDefined();
  await act(async () => { target!.click(); await tick(); });
}
beforeEach(async () => {
  vi.resetAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity, gcTime: Infinity }, mutations: { retry: false } } });
  client.setQueryData(queryKeys.promptTemplates(), { schemaVersion: 1, path: "fixture", templates: [template("a"), template("b")], repairWarnings: [] });
  client.setQueryData(queryKeys.agents(), []);
  for (const id of ["a", "b"]) client.setQueryData(["prompt-templates", id, "detail"], template(id));
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  await act(async () => {
    root.render(<QueryClientProvider client={client}><MemoryRouter><PromptTemplatesRoute /></MemoryRouter></QueryClientProvider>);
    await tick();
  });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); });

describe("Prompt template pending state", () => {
  it("keeps the save label while the current detail refreshes and blocks both writes", async () => {
    const refresh = deferred<PromptTemplate>();
    vi.mocked(fetchPromptTemplate).mockReturnValue(refresh.promise);
    await act(async () => { void client.refetchQueries({ queryKey: ["prompt-templates", "a", "detail"], exact: true }); await tick(); });
    expect(button("保存模板")?.disabled).toBe(true);
    expect(button("恢复默认")?.disabled).toBe(true);
    expect(button("保存中")).toBeUndefined();
    await act(async () => { refresh.resolve(template("a")); await tick(); });
    await vi.waitFor(async () => {
      await act(async () => { await tick(); });
      expect(button("保存模板")?.disabled).toBe(false);
    }, { timeout: 2000, interval: 10 });
  });

  it("shows saving only for the template being saved and keeps reset mutually exclusive", async () => {
    vi.mocked(updatePromptTemplate).mockReturnValue(deferred<PromptTemplate>().promise);
    await click(button("保存模板"));
    expect(button("保存中")?.disabled).toBe(true);
    expect(button("恢复默认")?.disabled).toBe(true);
    await click(button("恢复默认"));
    expect(resetPromptTemplate).not.toHaveBeenCalled();
    await click(templateButton("b"));
    expect(button("保存模板")?.disabled).toBe(false);
    expect(button("恢复默认")?.disabled).toBe(false);
    expect(button("保存中")).toBeUndefined();
    await click(templateButton("a"));
    expect(button("保存中")?.disabled).toBe(true);
    expect(updatePromptTemplate).toHaveBeenCalledTimes(1);
  });

  it("does not describe reset as saving and isolates its pending state to the current template", async () => {
    vi.mocked(resetPromptTemplate).mockReturnValue(deferred<PromptTemplate>().promise);
    await click(button("恢复默认"));
    expect(button("保存模板")?.disabled).toBe(true);
    expect(button("恢复默认")?.disabled).toBe(true);
    expect(button("保存中")).toBeUndefined();
    await click(button("保存模板"));
    expect(updatePromptTemplate).not.toHaveBeenCalled();
    await click(templateButton("b"));
    expect(button("保存模板")?.disabled).toBe(false);
    expect(button("恢复默认")?.disabled).toBe(false);
  });
});
