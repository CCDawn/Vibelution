import { describe, expect, it } from "vitest";

import { PythonJsonBridgeError } from "../src/process/pythonJsonBridge.js";
import { parseWorkbenchLifecycleResult } from "../src/process/workbenchLifecycle.js";

describe("parseWorkbenchLifecycleResult", () => {
  it("validates the bridge schema", () => {
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow();
    expect(() =>
      parseWorkbenchLifecycleResult(JSON.stringify({ schemaVersion: 2, accepted: true, operation: "start" }))
    ).toThrow();
    expect(() => parseWorkbenchLifecycleResult("{}")).toThrow(PythonJsonBridgeError);
  });

  it("accepts a schemaVersion 1 result", () => {
    expect(
      parseWorkbenchLifecycleResult(
        JSON.stringify({ schemaVersion: 1, accepted: true, operation: "start", commandId: "cmd-1" })
      )
    ).toEqual({
      schemaVersion: 1,
      accepted: true,
      operation: "start",
      commandId: "cmd-1"
    });
  });
});
