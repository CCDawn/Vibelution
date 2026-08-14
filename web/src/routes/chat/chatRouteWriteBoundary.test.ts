import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const useChatRouteSelectionSourcePath = fileURLToPath(new URL("./useChatRouteSelection.ts", import.meta.url));
const useChatWorkspaceActionsSourcePath = fileURLToPath(new URL("./useChatWorkspaceActions.ts", import.meta.url));
const useChatWorkspaceLifecycleSourcePath = fileURLToPath(new URL("./useChatWorkspaceLifecycle.ts", import.meta.url));
const useChatArchivedAgentRetirementSourcePath = fileURLToPath(new URL("./useChatArchivedAgentRetirement.ts", import.meta.url));
const chatCodingRouteWorkbenchSourcePath = fileURLToPath(new URL("./ChatCodingRouteWorkbench.tsx", import.meta.url));

function readSource(path: string): string {
  return readFileSync(path, "utf8");
}

function navigatesToChatSelection(source: string): string[] {
  const lines = source.split("\n");
  const offenders: string[] = [];
  for (const line of lines) {
    if (!line.includes("navigate(")) {
      continue;
    }
    if (line.includes("session=") || line.includes("room=") || line.includes("/chat?")) {
      offenders.push(line.trim());
    }
  }
  return offenders;
}

describe("Chat route write boundary (single authority)", () => {
  it("useChatRouteSelection is the only module allowed to build session/room route targets", () => {
    const writerSource = readSource(useChatRouteSelectionSourcePath);
    expect(writerSource).toContain('pathname: "/chat"');
    expect(writerSource).toContain("serializeChatRouteSelection");

    for (const [path, source] of [
      [useChatWorkspaceActionsSourcePath, readSource(useChatWorkspaceActionsSourcePath)],
      [useChatWorkspaceLifecycleSourcePath, readSource(useChatWorkspaceLifecycleSourcePath)],
      [useChatArchivedAgentRetirementSourcePath, readSource(useChatArchivedAgentRetirementSourcePath)],
    ]) {
      expect(navigatesToChatSelection(source), path).toEqual([]);
    }
  });

  it("workspace actions delegate all Chat selection navigation to the route controller", () => {
    const source = readSource(useChatWorkspaceActionsSourcePath);
    expect(source).toContain("chatRoute.openSession(");
    expect(source).toContain("chatRoute.openRoom(");
    expect(source).toContain("chatRoute.openProjectBus()");
    expect(source).not.toContain("/chat?session=");
    expect(source).not.toContain("/chat?room=");
    expect(source).not.toContain("encodeURIComponent(normalizedSessionId)}`, { replace: true }");
  });

  it("workspace lifecycle uses compare-and-swap route transitions only", () => {
    const source = readSource(useChatWorkspaceLifecycleSourcePath);
    expect(source).toContain("replaceIfStillViewing");
    expect(source).toContain("routeSelectionRef.current");
    expect(source).not.toContain("setActiveSession");
    expect(source).not.toContain("setSearchParams");
    expect(navigatesToChatSelection(source)).toEqual([]);
    // Temp create failure must not auto-restore a previous session.
    expect(source).toContain("Never auto-restore");
  });

  it("archived Agent retirement compares-and-swaps the explicit route target only", () => {
    const source = readSource(useChatArchivedAgentRetirementSourcePath);
    expect(source).toContain("replaceIfStillViewing");
    expect(source).not.toContain("setActiveSession");
    expect(navigatesToChatSelection(source)).toEqual([]);
  });

  it("workbench derives active ids from the route and never writes selection URLs directly", () => {
    const source = readSource(chatCodingRouteWorkbenchSourcePath);
    expect(source).toContain("activeSessionIdFromRouteSelection(chatRouteSelection)");
    expect(source).toContain("activeGroupRoomIdFromRouteSelection(chatRouteSelection)");
    expect(source).toContain("useChatRouteSelection()");
    expect(source).toContain("canonicalizeBareRoute(bareRouteBootstrapTarget)");
    // No direct Chat selection navigation remains in the workbench shell.
    for (const line of source.split("\n")) {
      if (line.includes("navigate(`/chat")) {
        expect.unreachable(`workbench builds a direct chat selection URL: ${line.trim()}`);
      }
    }
    expect(source).not.toContain("window.history");
    expect(source).not.toContain("useChatWorkbenchStore((state) => state.activeSessionId)");
    expect(source).not.toContain("state.setActiveSession");
  });
});
