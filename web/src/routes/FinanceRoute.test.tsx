// @vitest-environment happy-dom
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createRoot, type Root } from "react-dom/client";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFinancialAssistant, listFinancialAssistants, type FinancialAssistant } from "../api/financialAssistant";
import { FinanceRoute } from "./FinanceRoute";

vi.mock("../api/financialAssistant", () => ({ createFinancialAssistant: vi.fn(), listFinancialAssistants: vi.fn() }));
vi.mock("./ChatCodingRoute", () => ({ ChatCodingRoute: () => <div>finance-workspace</div> }));
vi.mock("../i18n/useShellI18n", () => ({ useShellI18n: () => ({ lang: "zh" }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let container: HTMLDivElement; let root: Root; let client: QueryClient;
const row: FinancialAssistant = {
  agentId: "finance-a", agentCode: "A001", displayName: "炒股智能体", status: "active",
  setupStatus: "ready", directSessionId: "native-session", knowledgeBaseId: "agent:finance-a:reports",
  knowledgeReadable: true, modelStatus: "configured_unverified", reportStatus: "not_configured",
  newsDelegationStatus: "disabled", marketDataStatus: "not_connected", privateLedgerStatus: "not_implemented",
  tradingEnabled: false,
};
function LocationEcho() {
  const location = useLocation();
  return <output>{location.pathname}{location.search}</output>;
}
beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
});
afterEach(async () => { await act(async () => root.unmount()); client.clear(); container.remove(); vi.clearAllMocks(); });
async function render(path = "/finance") {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <LocationEcho />
        <Routes><Route path="/finance" element={<FinanceRoute />} /></Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  ));
  await settle();
}
async function settle() { await act(async () => new Promise((resolve) => setTimeout(resolve, 20))); }
function button(label: string) { return [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(label)); }

describe("financial assistant page", () => {
  it("opens the assistant workspace on its own page", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([row]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
    expect(container.textContent).not.toContain("Conversation Agents");
  });

  it("creates the assistant once, then stays on this page", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([]);
    vi.mocked(createFinancialAssistant).mockResolvedValue({ created: true, assistant: row });
    await render();
    expect(createFinancialAssistant).toHaveBeenCalledTimes(1);
    expect(container.querySelector("output")?.textContent).toBe("/finance?session=native-session");
    expect(container.textContent).toContain("finance-workspace");
  });

  it("uses the session already on this page without creating another assistant", async () => {
    await render("/finance?session=native-session");
    expect(listFinancialAssistants).not.toHaveBeenCalled();
    expect(container.textContent).toContain("finance-workspace");
  });

  it("does not leave this page after it unmounts", async () => {
    let resolve!: (value: FinancialAssistant[]) => void;
    vi.mocked(listFinancialAssistants).mockReturnValue(new Promise((done) => { resolve = done; }));
    await render();
    await act(async () => root.render(<div>another route</div>));
    await act(async () => resolve([row]));
    await settle();
    expect(container.textContent).toBe("another route");
  });

  it("stops on an archived assistant instead of creating another", async () => {
    vi.mocked(listFinancialAssistants).mockResolvedValue([{ ...row, status: "archived", directSessionId: "", setupStatus: "ready" }]);
    await render();
    expect(createFinancialAssistant).not.toHaveBeenCalled();
    expect(container.textContent).toContain("已归档");
    expect(container.textContent).not.toContain("finance-workspace");
  });

  it("retries a failed open into the workspace", async () => {
    vi.mocked(listFinancialAssistants).mockRejectedValueOnce(new Error("offline")).mockResolvedValue([row]);
    await render();
    expect(container.textContent).toContain("offline");
    await act(async () => button("重试")!.click());
    await settle();
    expect(container.textContent).toContain("finance-workspace");
  });
});
