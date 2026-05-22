import { describe, expect, it } from "vitest";

import type { RuntimeSceneDetail, RuntimeSceneRawFile } from "../api/types";
import { runtimeScenePackageFiles, runtimeScenePackageSections } from "./runtimeScenePackageSections";

function file(path: string): RuntimeSceneRawFile {
  return {
    path,
    label: path,
    size: 12,
    language: "text",
  };
}

function scene(files: {
  rawFiles?: RuntimeSceneRawFile[];
  conversationLogs?: RuntimeSceneRawFile[];
  agentLogs?: RuntimeSceneRawFile[];
  artifacts?: RuntimeSceneRawFile[];
  eventLogs?: RuntimeSceneRawFile[];
}): RuntimeSceneDetail {
  return {
    runtimeSceneId: "scene-test",
    directoryName: "scene-test",
    displayName: "Scene test",
    packageIndex: {
      schemaVersion: 1,
      packageId: "scene-test",
      displayName: "Scene test",
      indexKey: "scene-test",
      sortableTimestamp: "",
      startedAt: "",
      startedAtLocal: "",
      startedDate: "",
      startedTime: "",
      endedAt: "",
      durationSeconds: null,
      searchText: "",
      tags: [],
    },
    manifestPath: "logs/runtime_scenes/scene-test/manifest.json",
    manifest: {},
    startedAt: "",
    endedAt: "",
    status: "running",
    result: "",
    stopReason: "",
    trigger: "",
    sessionMode: "managed",
    host: "127.0.0.1",
    port: 8000,
    url: "http://127.0.0.1:8000",
    frontend: {},
    backend: {},
    browser: {},
    supervisor: {},
    timeline: [],
    lifecycle: [],
    rawFiles: files.rawFiles ?? [],
    conversationLogs: files.conversationLogs ?? [],
    agentLogs: files.agentLogs ?? [],
    artifacts: files.artifacts ?? [],
    eventLogs: files.eventLogs ?? [],
    packageSummary: {
      schemaVersion: 2,
      eventCount: 0,
      lifecycleEventCount: 0,
      rawLogCount: files.rawFiles?.length ?? 0,
      conversationLogCount: files.conversationLogs?.length ?? 0,
      agentLogCount: files.agentLogs?.length ?? 0,
      artifactCount: files.artifacts?.length ?? 0,
      eventLogCount: files.eventLogs?.length ?? 0,
      errorCount: 0,
      warningCount: 0,
    },
  };
}

describe("runtimeScenePackageSections", () => {
  it("groups runtime scene child logs by user-facing purpose", () => {
    const detail = scene({
      rawFiles: [file("raw/backend.stdout.log")],
      conversationLogs: [file("conversations/session-demo.jsonl")],
      agentLogs: [
        file("agent/tool_calls.jsonl"),
        file("agent/supervised_runs/web-supervised-demo.jsonl"),
        file("agent/self_evolution_runs/web-self-demo.jsonl"),
      ],
      artifacts: [
        file("artifacts/report.json"),
        file("artifacts/supervised/evidence.json"),
        file("artifacts/self_evolution/rollback.json"),
      ],
      eventLogs: [
        file("events/backend.jsonl"),
        file("events/conversation.jsonl"),
        file("events/llm.jsonl"),
        file("events/supervised_run.jsonl"),
        file("events/self_evolution_run.jsonl"),
      ],
    });

    const sections = runtimeScenePackageSections(detail);

    expect(Object.fromEntries(sections.map((section) => [section.id, section.files.map((item) => item.path)]))).toEqual({
      conversations: ["conversations/session-demo.jsonl", "events/conversation.jsonl"],
      supervised: [
        "agent/supervised_runs/web-supervised-demo.jsonl",
        "artifacts/supervised/evidence.json",
        "events/supervised_run.jsonl",
      ],
      selfEvolution: [
        "agent/self_evolution_runs/web-self-demo.jsonl",
        "artifacts/self_evolution/rollback.json",
        "events/self_evolution_run.jsonl",
      ],
      agent: ["agent/tool_calls.jsonl", "events/llm.jsonl"],
      events: ["events/backend.jsonl"],
      raw: ["raw/backend.stdout.log"],
      artifacts: ["artifacts/report.json"],
    });
  });

  it("keeps empty supervised and self-evolution sections visible", () => {
    const sections = runtimeScenePackageSections(scene({ rawFiles: [file("raw/backend.stdout.log")] }));

    expect(sections.map((section) => section.id)).toEqual([
      "conversations",
      "supervised",
      "selfEvolution",
      "agent",
      "events",
      "raw",
      "artifacts",
    ]);
    expect(sections.find((section) => section.id === "supervised")?.files).toEqual([]);
    expect(sections.find((section) => section.id === "selfEvolution")?.emptyZh).toContain("没有启动无监督进化");
  });

  it("flattens files in the same order used by the package viewer", () => {
    const detail = scene({
      conversationLogs: [file("conversations/session-demo.jsonl")],
      agentLogs: [file("agent/self_evolution_runs/web-self-demo.jsonl")],
      eventLogs: [file("events/supervised_run.jsonl")],
      rawFiles: [file("raw/backend.stdout.log")],
    });

    expect(runtimeScenePackageFiles(detail).map((item) => item.path)).toEqual([
      "conversations/session-demo.jsonl",
      "events/supervised_run.jsonl",
      "agent/self_evolution_runs/web-self-demo.jsonl",
      "raw/backend.stdout.log",
    ]);
  });
});
