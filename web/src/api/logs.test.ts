import { describe, expect, it } from "vitest";

import apiSource from "./logs.ts?raw";
import logsRouteSource from "../routes/LogsRoute.tsx?raw";
import runtimeScenesSource from "../routes/RuntimeScenesPane.tsx?raw";

describe("logs catalog API", () => {
  it("owns logs and runtime-scene JSON transports", () => {
    expect(apiSource).toContain("export function fetchLogRoots");
    expect(apiSource).toContain("export function fetchLogTree");
    expect(apiSource).toContain("export function fetchLogContent");
    expect(apiSource).toContain("export function clearLogFile");
    expect(apiSource).toContain("export function deleteLogFiles");
    expect(apiSource).toContain("export function fetchRuntimeSceneList");
    expect(apiSource).toContain("export function fetchRuntimeSceneDetail");
    expect(apiSource).toContain("export function fetchRuntimeSceneLogContent");
    expect(apiSource).toContain("export function deleteRuntimeScenes");
    expect(apiSource).toContain('"/api/logs/roots"');
    expect(apiSource).toContain("/api/logs/runtime-scenes/delete");
  });

  it("keeps LogsRoute and RuntimeScenesPane free of logs JSON paths", () => {
    expect(logsRouteSource).toContain("fetchLogRoots(");
    expect(logsRouteSource).toContain("fetchLogTree(");
    expect(logsRouteSource).toContain("fetchLogContent(");
    expect(logsRouteSource).toContain("clearLogFile(");
    expect(logsRouteSource).toContain("deleteLogFiles(");
    expect(logsRouteSource).not.toContain("/api/logs/");
    expect(runtimeScenesSource).toContain("fetchRuntimeSceneList(");
    expect(runtimeScenesSource).toContain("fetchRuntimeSceneDetail(");
    expect(runtimeScenesSource).toContain("fetchRuntimeSceneLogContent(");
    expect(runtimeScenesSource).toContain("deleteRuntimeScenes(");
    expect(runtimeScenesSource).not.toContain("/api/logs/");
  });
});
