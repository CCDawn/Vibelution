/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { useTeamCommunicationEvents } from "./useTeamCommunicationEvents";

const api = vi.hoisted(() => ({
  bus: vi.fn(async () => ({ events: [] })),
}));
vi.mock("../../api/projectAgentBus", async (original) => ({
  ...await original<typeof import("../../api/projectAgentBus")>(),
  listProjectAgentBusTimeline: api.bus,
}));

let root: Root;
let client: QueryClient;
let host: HTMLDivElement;
async function show(ui: React.ReactNode) {
  if (!root) {
    vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
    host = document.createElement("div");
    document.body.append(host);
    root = createRoot(host);
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  }
  await act(async () => { root.render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>); });
}
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  client?.clear(); host?.remove();
  root = undefined as unknown as Root;
  vi.clearAllMocks(); vi.unstubAllGlobals();
});

it("loads communication only when its panel opens", async () => {
  function Probe({ visible }: { visible: boolean }) {
    useTeamCommunicationEvents("research-team", visible);
    return null;
  }
  await show(<Probe visible={false} />);
  expect(api.bus).not.toHaveBeenCalled();
  await show(<Probe visible />);
  expect(api.bus).toHaveBeenCalledOnce();
});
