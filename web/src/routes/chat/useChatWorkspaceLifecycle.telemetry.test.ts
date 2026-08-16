import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const here = dirname(fileURLToPath(import.meta.url));
const lifecycleSource = readFileSync(join(here, "useChatWorkspaceLifecycle.ts"), "utf8");
const routeSelectionSource = readFileSync(join(here, "useChatRouteSelection.ts"), "utf8");
const actionsSource = readFileSync(join(here, "useChatWorkspaceActions.ts"), "utf8");

describe("chat workspace user-action telemetry contract", () => {
  it("tracks session lifecycle mutations through startUserAction", () => {
    expect(lifecycleSource).toContain('startUserAction("session_create"');
    expect(lifecycleSource).toContain('startUserAction("session_delete"');
    expect(lifecycleSource).toContain('startUserAction("session_rename"');
    expect(lifecycleSource).toContain('startUserAction("session_clear_history"');
    expect(lifecycleSource).toContain('startUserAction("session_add_to_review"');
    expect(lifecycleSource).toContain("telemetry?.succeeded({");
    expect(lifecycleSource).toContain("telemetry?.failed(error");
  });

  it("tracks group room and project bus mutations", () => {
    expect(lifecycleSource).toContain('startUserAction("group_room_create"');
    expect(lifecycleSource).toContain('startUserAction("group_room_update"');
    expect(lifecycleSource).toContain('startUserAction("group_room_delete"');
    expect(lifecycleSource).toContain('startUserAction("group_room_reset"');
    expect(lifecycleSource).toContain('startUserAction("group_round_start"');
    expect(lifecycleSource).toContain('startUserAction("group_round_stop"');
    expect(lifecycleSource).toContain('startUserAction("project_bus_send"');
    expect(lifecycleSource).toContain('startUserAction("project_bus_revoke"');
  });

  it("records delete focus handoff fields for session delete", () => {
    expect(lifecycleSource).toContain("optimisticNextActiveSessionId");
    expect(lifecycleSource).toContain("serverNextActiveSessionId");
    expect(lifecycleSource).toContain("nextActiveSessionId");
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
