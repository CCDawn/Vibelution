import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  composeInstanceLifecycleState,
  instanceLifecycleIsStartable,
  projectInstanceLifecycle,
  type InstanceLifecycleProjectionInput,
  type InstanceLifecycleState
} from "../src/lifecycle/instanceLifecycleProjection.js";

type FixtureCase = {
  id: string;
  input: InstanceLifecycleProjectionInput;
  expected: {
    lifecycleState: InstanceLifecycleState;
    errorCode: string;
    startable: boolean;
  };
};

const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "lifecycle",
  "__fixtures__",
  "instanceLifecycleProjection.cases.json"
);

const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as { cases: FixtureCase[] };

describe("instanceLifecycleProjection shared fixture", () => {
  it("locks at least 30 dual-language cases", () => {
    expect(fixture.cases.length).toBeGreaterThanOrEqual(30);
    const ids = fixture.cases.map((item) => item.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it.each(fixture.cases)("$id", (item) => {
    const projected = projectInstanceLifecycle(item.input);
    expect(projected.lifecycleState).toBe(item.expected.lifecycleState);
    expect(projected.errorCode).toBe(item.expected.errorCode);
    expect(composeInstanceLifecycleState(item.input)).toBe(item.expected.lifecycleState);
    expect(
      instanceLifecycleIsStartable({
        lifecycleState: projected.lifecycleState,
        backendAlive: item.input.backendAlive,
        backendListening: item.input.backendListening,
        windowOpen: item.input.windowOpen
      })
    ).toBe(item.expected.startable);
  });
});
