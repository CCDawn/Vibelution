import { describe, expect, it } from "vitest";
import { matchedConversationMessage, matchedScenario } from "./conversation-matched-scenario";

const start = Date.parse("2026-11-06T04:00:00Z");
describe("matched conversation fixture adaptation", () => {
  it("retains tool identities and inputs as one call settles while its peers continue", () => {
    const running = matchedConversationMessage("tools-running", start, "matched-test");
    const mixed = matchedConversationMessage("run-mixed", start, "matched-test");
    const calls = (message: typeof running) => message.role === "assistant" ? message.turnItems.filter((item) => item.type === "tool_call") : [];
    expect(calls(running).map((item) => item.itemId)).toEqual(calls(mixed).map((item) => item.itemId));
    expect(calls(mixed).map((item) => item.status)).toEqual(["completed", "running", "running"]);
    expect(calls(running).map((item) => item.input)).toEqual(calls(mixed).map((item) => item.input));
    expect(calls(mixed).every((item) => item.createdAt && item.updatedAt)).toBe(true);
    if (mixed.role !== "assistant") throw new Error("Expected fixture turn");
    expect(mixed.turnItems.find((item) => item.type === "reasoning")).toMatchObject({
      status: "completed", createdAt: "2026-11-06T04:00:00.000Z", updatedAt: "2026-11-06T04:00:02.000Z",
    });
  });
  it("preserves the final text and authoritative 12-second duration without reporting failed output as success", () => {
    const complete = matchedConversationMessage("completed", start, "matched-test");
    const failed = matchedConversationMessage("failed", start, "matched-test");
    expect(complete).toMatchObject({ status: "completed", turnState: "completed", turnActiveMs: 12000 });
    expect(failed).toMatchObject({ status: "failed", turnState: "failed", turnActiveMs: 12000 });
    if (failed.role !== "assistant" || complete.role !== "assistant") throw new Error("Expected fixture turns");
    expect(complete.turnItems.at(-1)).toMatchObject({ phase: "final_answer", text: matchedScenario.finalText });
    expect(failed.turnItems.find((item) => item.type === "tool_call" && item.callId === "matched-command"))
      .toMatchObject({ status: "failed", error: { code: "MATCHED_READONLY_CHECK_FAILED" } });
    expect(failed.turnItems.at(-1)).toMatchObject({ text: matchedScenario.failedText });
    expect(failed.turnItems.at(-1)).not.toMatchObject({ text: matchedScenario.finalText });
  });
  it("marks an interrupted scene separately from a tool failure", () => {
    const message = matchedConversationMessage("stopped", start, "matched-test");
    expect(message).toMatchObject({ status: "completed", turnState: "interrupted", metadata: { interrupted: true } });
    if (message.role !== "assistant") throw new Error("Expected fixture turn");
    const call = message.turnItems.find((item) => item.type === "tool_call" && item.callId === "matched-command");
    expect(call).toMatchObject({ status: "completed", semanticStatus: "cancelled", output: matchedScenario.stoppedText });
    expect(call).not.toHaveProperty("error");
  });
});
