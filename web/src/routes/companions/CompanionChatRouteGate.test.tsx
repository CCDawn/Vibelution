// @vitest-environment happy-dom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { listVirtualHumanCompanions } from "../../api/agentPlugins";
import { CompanionChatRouteGate } from "./CompanionChatRouteGate";

vi.mock("../../api/agentPlugins", () => ({
  listVirtualHumanCompanions: vi.fn(),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLDivElement;
let root: Root;

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

async function renderGate(initialEntry: string) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  await act(async () => root.render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[initialEntry]}>
        <Routes>
          <Route path="/chat" element={(
            <CompanionChatRouteGate>
              <div>private companion transcript</div>
            </CompanionChatRouteGate>
          )} />
          <Route path="/companions" element={<div>companion lobby</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  ));
}

async function flushQuery() {
  await act(async () => new Promise((resolve) => setTimeout(resolve, 10)));
}

describe("CompanionChatRouteGate", () => {
  it("does not mount Chat before an exact Companion binding is verified", async () => {
    let resolveCompanions: ((value: unknown[]) => void) | undefined;
    vi.mocked(listVirtualHumanCompanions).mockReturnValue(new Promise((resolve) => {
      resolveCompanions = resolve;
    }) as ReturnType<typeof listVirtualHumanCompanions>);

    await renderGate("/chat?session=session-companion&companion=agent-wrong");

    expect(container.textContent).not.toContain("private companion transcript");
    expect(container.querySelector('[aria-label="正在验证人物身份"]')).toBeTruthy();
    await act(async () => {
      resolveCompanions?.([{
        agentId: "agent-companion",
        directSessionId: "session-companion",
      }]);
    });
    await flushQuery();
    expect(container.textContent).toContain("companion lobby");
    expect(container.textContent).not.toContain("private companion transcript");
  });

  it("mounts Chat only for the exact Agent and direct Session pair", async () => {
    vi.mocked(listVirtualHumanCompanions).mockResolvedValue([{
      agentId: "agent-companion",
      directSessionId: "session-companion",
    }] as Awaited<ReturnType<typeof listVirtualHumanCompanions>>);

    await renderGate("/chat?session=session-companion&companion=agent-companion");
    await flushQuery();

    expect(container.textContent).toContain("private companion transcript");
  });

  it("leaves ordinary Chat routes unchanged", async () => {
    await renderGate("/chat?session=session-ordinary");

    expect(container.textContent).toContain("private companion transcript");
    expect(listVirtualHumanCompanions).not.toHaveBeenCalled();
  });
});
