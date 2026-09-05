/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { KnowledgePackageReader } from "./KnowledgePackageReader";
import { safeSourceUrl } from "./evidenceReadingModel";

const fetchDetail = vi.hoisted(() => vi.fn());
vi.mock("../../../api/research-workflow/domain-projections", () => ({ fetchResearchWorkflowHandoffDetail: fetchDetail }));

it("reads the selected handoff as text and clears it when the handoff changes", async () => {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  fetchDetail.mockResolvedValueOnce({knowledgePackages: [{artifactId: "one", status: "available", title: "Paper",
    content: "<script>unsafe()</script>", summary: "Summary", sourceUrl: "https://example.org/paper", riskSummary: "", uncertainties: []}]});
  const client = new QueryClient({defaultOptions: {queries: {retry: false}}});
  const container = document.createElement("div"); const root = createRoot(container);
  const view = (id: string) => <MemoryRouter><QueryClientProvider client={client}><KnowledgePackageReader runId="child" teamId="team" handoffId={id} /></QueryClientProvider></MemoryRouter>;
  await act(async () => root.render(view("h1")));
  await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
  expect(fetchDetail).toHaveBeenCalledWith("child", "h1", {teamId: "team"});
  expect(container.textContent).toContain("<script>unsafe()</script>");
  expect(container.querySelector("script")).toBeNull();
  expect(container.querySelector("a")?.href).toBe("https://example.org/paper");
  expect(container.textContent).toContain("不代表已审核或已入库");
  fetchDetail.mockImplementationOnce(() => new Promise(() => undefined));
  await act(async () => root.render(view("h2")));
  expect(container.textContent).not.toContain("Paper");
  expect(container.textContent).toContain("正在读取");
  await act(async () => root.unmount()); client.clear();
});

it("does not turn internal refs, executable URLs or embedded credentials into source links", () => {
  for (const url of ["javascript:alert(1)", "data:text/html,hello", "knowledge_package_draft://team/run/hash", "https://user:secret@example.org", "//example.org"]) expect(safeSourceUrl(url)).toBeNull();
});
