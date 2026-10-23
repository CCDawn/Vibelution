import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resolveSessionActivity, type SessionActivitySource } from "./sessionActivityState";

const cases = JSON.parse(readFileSync(new URL("../../../tests/fixtures/activity_contract_cases.json", import.meta.url), "utf8")) as Array<{
  name: string;
  session: SessionActivitySource;
  runtimeRunning?: boolean;
  authoritativeRuntime?: boolean;
  expected: ReturnType<typeof resolveSessionActivity>;
}>;

describe("backend/frontend Session activity behavior contract", () => {
  it.each(cases)("$name", (sample) => {
    expect(resolveSessionActivity(sample.session, {
      runtimeRunning: sample.runtimeRunning, authoritativeRuntime: sample.authoritativeRuntime,
    })).toEqual(sample.expected);
  });
});
