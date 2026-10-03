// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { fetchConfigWorkspace } from "../../api/config";
import { fetchHealthDiagnostics } from "../../api/diagnostics";
import { useConfigHealthDiagnosticsQuery, useConfigWorkspaceQueries } from "./useConfigWorkspaceQueries";

vi.mock("../../api/config", () => ({ fetchConfigWorkspace: vi.fn() }));
vi.mock("../../api/diagnostics", () => ({ fetchHealthDiagnostics: vi.fn() }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  vi.mocked(fetchConfigWorkspace).mockImplementation(() => new Promise(() => {}));
  vi.mocked(fetchHealthDiagnostics).mockImplementation(() => new Promise(() => {}));
});
afterEach(async () => {
  await act(async () => root.unmount());
  client.clear();
  host.remove();
  vi.resetAllMocks();
});

function HealthConsumer({ visible }: { visible: boolean }) {
  useConfigHealthDiagnosticsQuery(visible);
  return null;
}
function Settings({ visible }: { visible: boolean }) {
  useConfigWorkspaceQueries();
  return <HealthConsumer visible={visible} />;
}
async function render(visible: boolean, otherConsumer = false) {
  await act(async () => root.render(
    <QueryClientProvider client={client}>
      <Settings visible={visible} />
      {otherConsumer ? <HealthConsumer visible /> : null}
    </QueryClientProvider>,
  ));
}

describe("settings reads during navigation", () => {
  it("defers diagnostics, aborts a hidden diagnostic, and aborts workspace on leave", async () => {
    await render(false);
    expect(fetchConfigWorkspace).toHaveBeenCalledTimes(1);
    expect(fetchHealthDiagnostics).not.toHaveBeenCalled();
    const workspaceSignal = vi.mocked(fetchConfigWorkspace).mock.calls[0][0]!.signal!;
    await render(true);
    expect(fetchHealthDiagnostics).toHaveBeenCalledTimes(1);
    const healthSignal = vi.mocked(fetchHealthDiagnostics).mock.calls[0][0]!.signal!;
    expect(healthSignal.aborted).toBe(false);
    await render(false);
    expect(healthSignal.aborted).toBe(true);
    expect(workspaceSignal.aborted).toBe(false);
    await act(async () => root.render(<div>another page</div>));
    expect(workspaceSignal.aborted).toBe(true);
  });

  it("keeps a diagnostic read alive while another visible consumer needs it", async () => {
    await render(true, true);
    const healthSignal = vi.mocked(fetchHealthDiagnostics).mock.calls[0][0]!.signal!;
    await render(false, true);
    expect(fetchHealthDiagnostics).toHaveBeenCalledTimes(1);
    expect(healthSignal.aborted).toBe(false);
    await render(false);
    expect(healthSignal.aborted).toBe(true);
  });
});
