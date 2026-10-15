import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const lifecycleSource = readFileSync(join(here, "useChatWorkspaceLifecycle.ts"), "utf8");
const sessionCreateSource = readFileSync(join(here, "useChatSessionCreateMutation.ts"), "utf8");
const sessionChangeSource = readFileSync(join(here, "useChatSessionChangeMutations.ts"), "utf8");
const groupWorkspaceSource = readFileSync(join(here, "useChatGroupWorkspaceMutations.ts"), "utf8");
const routeSelectionSource = readFileSync(join(here, "useChatRouteSelection.ts"), "utf8");
const actionsSource = readFileSync(join(here, "useChatWorkspaceActions.ts"), "utf8");

describe("chat workspace user-action telemetry contract", () => {
  it("tracks session lifecycle mutations through startUserAction", () => {
    expect(sessionCreateSource).toContain('startUserAction("session_create"');
    expect(lifecycleSource).toContain("useChatSessionCreateMutation(");
    expect(sessionChangeSource).toContain('startUserAction("session_delete"');
    expect(sessionChangeSource).toContain('startUserAction("session_rename"');
    expect(sessionChangeSource).toContain('startUserAction("session_clear_history"');
    expect(sessionChangeSource).toContain('startUserAction("session_add_to_review"');
    expect(lifecycleSource).toContain("useChatSessionChangeMutations(");
    expect(sessionCreateSource).toContain("telemetry?.succeeded({");
    expect(sessionCreateSource).toContain("telemetry?.failed(error");
    expect(sessionChangeSource).toContain("telemetry?.succeeded({");
    expect(sessionChangeSource).toContain("telemetry?.failed(error");
  });

  it("tracks group room and project bus mutations", () => {
    expect(groupWorkspaceSource).toContain('startUserAction("group_room_create"');
    expect(groupWorkspaceSource).toContain('startUserAction("group_room_update"');
    expect(groupWorkspaceSource).toContain('startUserAction("group_room_delete"');
    expect(groupWorkspaceSource).toContain('startUserAction("group_room_reset"');
    expect(groupWorkspaceSource).toContain('startUserAction("group_round_start"');
    expect(groupWorkspaceSource).toContain('startUserAction("group_round_stop"');
    expect(groupWorkspaceSource).toContain('startUserAction("project_bus_send"');
    expect(groupWorkspaceSource).toContain('startUserAction("project_bus_revoke"');
    expect(lifecycleSource).toContain("useChatGroupWorkspaceMutations(");
  });

  it("records delete focus handoff fields for session delete", () => {
    expect(sessionChangeSource).toContain("optimisticNextActiveSessionId");
    expect(sessionChangeSource).toContain("serverNextActiveSessionId");
    expect(sessionChangeSource).toContain("nextActiveSessionId");
  });

  it("records route-level session and room open observations", () => {
    expect(routeSelectionSource).toContain('postUserActionObservation("session_open"');
    expect(routeSelectionSource).toContain('postUserActionObservation("group_room_open"');
    expect(routeSelectionSource).toContain('postUserActionObservation("project_bus_open"');
    expect(routeSelectionSource).toContain("telemetrySource");
    expect(routeSelectionSource).toContain('"bare_route_bootstrap"');
    expect(routeSelectionSource).toContain('"replace_if_still_viewing"');
  });

  it("passes telemetrySource from direct session open actions", () => {
    expect(actionsSource).toContain('telemetrySource: options?.telemetrySource ?? "direct_session"');
    expect(actionsSource).toContain('telemetrySource: "agent_directory"');
  });

  it("records blocked session delete and clear-history guards", () => {
    expect(actionsSource).toContain('startUserAction("session_delete"');
    expect(actionsSource).toContain('.blocked("delete_already_in_flight")');
    expect(actionsSource).toContain('.blocked("session_busy"');
    expect(actionsSource).toContain('startUserAction("session_clear_history"');
    expect(actionsSource).toContain('.blocked("clear_already_in_flight")');
  });
});
