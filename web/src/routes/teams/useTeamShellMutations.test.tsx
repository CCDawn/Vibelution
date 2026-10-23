/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import type { Team } from "../../api/types";
import { useTeamShellMutations, type TeamShellChatWorkspaceCache } from "./useTeamShellMutations";

const api = vi.hoisted(() => ({ archive: vi.fn() }));
vi.mock("../../api/teams", () => ({ archiveTeam: api.archive }));
vi.mock("../../app/userActionTelemetry", () => ({ startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn() }) }));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it.each([false, true])("clears archive navigation only while the archived team is selected (switched=%s)", async switched => {
  let resolve!: (team: Team) => void;
  api.archive.mockImplementation(() => new Promise<Team>(done => { resolve = done; }));
  const afterTeamArchived = vi.fn(); const clearTeamSearchParams = vi.fn();
  let result!: ReturnType<typeof useTeamShellMutations>;
  let select!: (id: string) => void;
  let selection = ""; let node = "";
  function Probe() {
    const [teamId, setTeamId] = useState("team-a");
    const [nodeId, setNodeId] = useState("node-a");
    selection = teamId; node = nodeId;
    select = id => { setTeamId(id); setNodeId(`node-${id}`); };
    result = useTeamShellMutations({ selectedTeamId: teamId, setSelectedTeamId: setTeamId,
      setSelectedNodeId: setNodeId, clearTeamSearchParams, setTeamMessage: vi.fn(), setTeamTaskTopic: vi.fn(),
      chatWorkspaceCache: { afterTeamArchived } as unknown as TeamShellChatWorkspaceCache });
    return null;
  }
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host); const client = new QueryClient();
  try {
    await act(async () => root.render(<QueryClientProvider client={client}><Probe /></QueryClientProvider>));
    let request!: Promise<Team>;
    await act(async () => { request = result.archiveTeamMutation.mutateAsync("team-a"); });
    if (switched) act(() => select("team-b"));
    await act(async () => { resolve({ teamId: "team-a", linkedChatRoomId: "room-a" } as Team); await request; });
    expect(selection).toBe(switched ? "team-b" : "");
    expect(node).toBe(switched ? "node-team-b" : "");
    expect(clearTeamSearchParams).toHaveBeenCalledTimes(switched ? 0 : 1);
    expect(afterTeamArchived).toHaveBeenCalledWith("team-a", "room-a");
  } finally { act(() => root.unmount()); host.remove(); client.clear(); }
});
