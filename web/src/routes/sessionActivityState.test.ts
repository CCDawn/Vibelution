import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { hasExecutionOwnership, resolveSessionActivity, sessionActivityGroup, sessionActivityPolicy, type SessionActivitySource } from "./sessionActivityState";

const cases = JSON.parse(readFileSync(new URL("../../../tests/fixtures/activity_contract_cases.json", import.meta.url), "utf8")) as Array<{
  name: string;
  session: SessionActivitySource;
  runtimeRunning?: boolean;
  authoritativeRuntime?: boolean;
  expected: ReturnType<typeof resolveSessionActivity>;
}>;

describe("backend/frontend Session activity behavior contract", () => {
  it("retains paused ownership without claiming a completed outcome", () => {
    expect(hasExecutionOwnership("paused")).toBe(true);
    expect(resolveSessionActivity({ status: "paused" }).outcome).toBe("");
  });
  it.each(cases)("$name", (sample) => {
    expect(resolveSessionActivity(sample.session, {
      runtimeRunning: sample.runtimeRunning, authoritativeRuntime: sample.authoritativeRuntime,
    })).toEqual(sample.expected);
  });
});

const policies = JSON.parse(readFileSync(new URL("../../../tests/fixtures/activity_policy_cases.json", import.meta.url), "utf8")) as Array<{
  name: string;
  session: SessionActivitySource;
  expected: ReturnType<typeof sessionActivityPolicy>;
  expectedGroup: string;
}>;

describe("backend/frontend execution and permission policy", () => {
  it.each(policies)("$name", ({ session, expected, expectedGroup }) => {
    expect(sessionActivityPolicy(session)).toEqual(expected);
    expect(sessionActivityGroup(session)).toBe(expectedGroup);
  });
});
