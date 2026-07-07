import { describe, expect, it } from "vitest";

import {
  createCodexStreamController,
  type CodexStreamDrainResult,
} from "./codexStreamController";

function drainText(result: CodexStreamDrainResult) {
  return result.segments.map((segment) => segment.source).join("");
}

describe("codexStreamController", () => {
  it("keeps incomplete deltas in the live tail and commits completed lines on ticks", () => {
    const controller = createCodexStreamController({ nowMs: () => 0 });

    controller.push("Hello");
    expect(controller.snapshot()).toMatchObject({
      emittedStableText: "",
      queuedStableText: "",
      liveTailText: "Hello",
    });

    controller.push("!\nNext");
    expect(controller.snapshot()).toMatchObject({
      emittedStableText: "",
      queuedStableText: "Hello!\n",
      liveTailText: "Next",
    });

    expect(drainText(controller.drainTick({ nowMs: 16 }))).toBe("Hello!\n");
    expect(controller.snapshot()).toMatchObject({
      emittedStableText: "Hello!\n",
      queuedStableText: "",
      liveTailText: "Next",
    });

    const finalized = controller.finalize();
    expect(drainText(finalized)).toBe("Next\n");
    expect(finalized.consolidatedSource).toBe("Hello!\nNext\n");
    expect(controller.snapshot().consolidatedSource).toBe("");
  });

  it("holds a streaming markdown table in the live tail until finalization", () => {
    const controller = createCodexStreamController({ nowMs: () => 0 });

    controller.push([
      "Intro paragraph.\n",
      "\n",
      "| Metric | Value |\n",
      "| --- | --- |\n",
      "| Cache | 98% |\n",
    ].join(""));

    expect(controller.snapshot().queuedStableText).toBe("Intro paragraph.\n\n");
    expect(controller.snapshot().liveTailText).toContain("| Metric | Value |");
    expect(controller.snapshot().liveTailText).toContain("| Cache | 98% |");

    controller.push("| Latency | 42ms |\n");
    expect(controller.snapshot().queuedStableText).toBe("Intro paragraph.\n\n");
    expect(controller.snapshot().liveTailText).toContain("| Latency | 42ms |");

    expect(drainText(controller.drainTick({ nowMs: 16 }))).toBe("Intro paragraph.\n\n");
    const finalized = controller.finalize();
    expect(drainText(finalized)).toContain("| Metric | Value |");
    expect(finalized.consolidatedSource).toContain("| Latency | 42ms |");
  });

  it("keeps an open code fence mutable and releases it after the fence closes", () => {
    const controller = createCodexStreamController({ nowMs: () => 0 });

    controller.push("Before fence.\n\n```ts\nconst value = 1;\n");

    expect(controller.snapshot().queuedStableText).toBe("Before fence.\n\n");
    expect(controller.snapshot().liveTailText).toContain("```ts");
    expect(controller.snapshot().liveTailText).toContain("const value = 1;");

    expect(drainText(controller.drainTick({ nowMs: 16 }))).toBe("Before fence.\n\n");
    controller.push("```\nAfter fence.\n");

    expect(controller.snapshot().queuedStableText).toContain("```ts\nconst value = 1;\n```\nAfter fence.\n");
    expect(controller.snapshot().liveTailText).toBe("");
  });

  it("drains one stable segment in smooth mode and drains backlog in catch-up mode", () => {
    const smooth = createCodexStreamController({ nowMs: () => 0 });
    smooth.push("one\n");
    smooth.push("two\n");

    expect(drainText(smooth.drainTick({ nowMs: 16 }))).toBe("one\n");
    expect(smooth.snapshot().queuedStableText).toBe("two\n");

    const catchUp = createCodexStreamController({ nowMs: () => 0 });
    catchUp.push(Array.from({ length: 9 }, (_, index) => `line ${index}\n`).join(""));

    expect(drainText(catchUp.drainTick({ nowMs: 16 }))).toBe(
      Array.from({ length: 9 }, (_, index) => `line ${index}\n`).join(""),
    );
    expect(catchUp.snapshot().queuedStableText).toBe("");
  });

  it("enters catch-up mode when queued stable output grows old", () => {
    const controller = createCodexStreamController({ nowMs: () => 0 });
    controller.push("one\n");
    controller.push("two\n");

    expect(drainText(controller.drainTick({ nowMs: 121 }))).toBe("one\ntwo\n");
    expect(controller.snapshot().queuedStableText).toBe("");
  });

  it("starts a fresh stream after finalization", () => {
    const controller = createCodexStreamController({ nowMs: () => 0 });
    controller.push("First answer");
    expect(controller.finalize().consolidatedSource).toBe("First answer\n");

    controller.push("Second");
    expect(controller.snapshot()).toMatchObject({
      emittedStableText: "",
      queuedStableText: "",
      liveTailText: "Second",
      consolidatedSource: "Second",
    });
  });
});
