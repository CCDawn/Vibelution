import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import {
  isStaleInFlightStart,
  OWNER_LEASE_HEARTBEAT_MS,
  OWNER_LEASE_TTL_MS,
  REGISTRY_SCHEMA_VERSION,
  remainingDeadlineMs,
  type RegistryEntry
} from "../src/lifecycle/instanceRegistryStore.js";

const fixturePath = join(
  dirname(fileURLToPath(import.meta.url)),
  "..",
  "src",
  "lifecycle",
  "__fixtures__",
  "instanceOwnerLease.cases.json"
);
const fixture = JSON.parse(readFileSync(fixturePath, "utf8")) as {
  protocol: {
    registrySchemaVersion: number;
    ownerLeaseTtlMs: number;
    ownerLeaseHeartbeatMs: number;
  };
  nowMs: number;
  cases: Array<{
    id: string;
    entry: RegistryEntry;
    input?: {
      backendAlive?: boolean;
      backendListening?: boolean;
      windowOpen?: boolean;
    };
    expected: { stale: boolean };
  }>;
};

describe("instance owner lease", () => {
  it("locks shared protocol constants", () => {
    expect(fixture.protocol.registrySchemaVersion).toBe(REGISTRY_SCHEMA_VERSION);
    expect(fixture.protocol.ownerLeaseTtlMs).toBe(OWNER_LEASE_TTL_MS);
    expect(fixture.protocol.ownerLeaseHeartbeatMs).toBe(OWNER_LEASE_HEARTBEAT_MS);
  });

  it.each(fixture.cases)("$id", (item) => {
    expect(
      isStaleInFlightStart(item.entry, {
        nowMs: fixture.nowMs,
        backendAlive: item.input?.backendAlive,
        backendListening: item.input?.backendListening,
        windowOpen: item.input?.windowOpen
      })
    ).toBe(item.expected.stale);
  });

  it("reads remaining wait from registry deadlineAt instead of a fresh 180s window", () => {
    expect(remainingDeadlineMs("2026-08-20T12:03:00Z", Date.parse("2026-08-20T12:00:00Z"))).toBe(180_000);
    expect(remainingDeadlineMs("2026-08-20T12:00:00Z", Date.parse("2026-08-20T12:02:30Z"))).toBe(0);
  });
});
