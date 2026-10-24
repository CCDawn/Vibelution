import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { resolveWorkRunActivity, workRunHasExecution, workRunStatusLabel, type WorkRunActivitySource } from "./workRunActivityState";

const cases = JSON.parse(readFileSync(new URL("../../../tests/fixtures/work_run_activity_cases.json", import.meta.url), "utf8")) as Array<{
  name: string; snapshot: WorkRunActivitySource; expected: ReturnType<typeof resolveWorkRunActivity>;
}>;
describe("backend/frontend WorkRun activity contract", () => {
  it.each(cases)("$name", ({ snapshot, expected }) => {
    expect(resolveWorkRunActivity(snapshot)).toEqual(expected);
  });
  it("distinguishes unknown protection from a proven live owner", () => {
    expect(workRunHasExecution({ status: "paused" })).toBe(true);
    expect(workRunHasExecution({ status: "blocked" })).toBe(false);
    expect(workRunHasExecution({ status: "running", endedAt: "2026-10-24T00:00:00Z" })).toBe(false);
    expect(workRunStatusLabel({ status: "force_stopped" }, "zh")).toBe("已停止");
    expect(workRunStatusLabel({ status: "future_status" }, "zh")).toBe("未知状态");
  });
});
