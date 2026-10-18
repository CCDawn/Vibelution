import { describe, expect, it } from "vitest";
import type { RuntimeTaskCard } from "../api/runtimeTasks";
import { runtimeTaskMenuItem } from "./runtimeTaskMenu";

const task: RuntimeTaskCard = {
  taskId: "research-1", kind: "research_task", status: "running",
  title: "研究范围", parentSessionId: "", startedAt: "",
};

describe("runtime task menu", () => {
  it("keeps research/CLI work distinct from chats and links to the task center", () => {
    expect(runtimeTaskMenuItem(task)).toMatchObject({ kind: "research_task", href: "/aux", tone: "running" });
    expect(runtimeTaskMenuItem({ ...task, kind: "cli_agent" }).kind).toBe("cli_agent");
    expect(runtimeTaskMenuItem({ ...task, kind: "child_session", childSessionId: "a b" }).href).toBe("/chat?session=a%20b");
  });
  it.each([
    ["queued", "caution"], ["stopping", "caution"], ["incomplete", "failed"],
    ["failed", "failed"], ["completed", "idle"], ["", "caution"], ["future_status", "caution"],
  ])("does not paint %s as running", (status, tone) => {
    expect(runtimeTaskMenuItem({ ...task, status })).toMatchObject({ status: status || "unknown", tone });
  });
});
