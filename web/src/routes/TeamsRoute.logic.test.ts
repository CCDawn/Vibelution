import { describe, expect, it } from "vitest";

import { linkedRoomRefetchInterval } from "./TeamsRoute";

describe("TeamsRoute polling policy", () => {
  it("polls linked rooms quickly only while an active round is settling", () => {
    expect(linkedRoomRefetchInterval(true, "running")).toBe(5_000);
    expect(linkedRoomRefetchInterval(true, "stopping")).toBe(5_000);
    expect(linkedRoomRefetchInterval(true, "ready")).toBe(30_000);
  });

  it("stops linked room polling while the page is hidden", () => {
    expect(linkedRoomRefetchInterval(false, "running")).toBe(false);
    expect(linkedRoomRefetchInterval(false, "ready")).toBe(false);
  });
});
