import { describe, expect, it, vi } from "vitest";
import { resolve } from "node:path";
import { createConnection } from "node:net";
import { openInitialMigrationBridge } from "../src/assistant/initialMigrationBridge.js";
import type { PreHostSourceLease } from "../src/assistant/projectRegistryConnection.js";

describe("initial migration private bridge", () => {
  it("binds one permit to the trusted source and retains it until the owned job drains", async () => {
    const check = vi.fn(), root = resolve("synthetic-project"), profile = resolve("synthetic-profile");
    let committing = false;
    const lease: PreHostSourceLease = {
      revision: 7, signal: new AbortController().signal, check,
      registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: root, root, active: true },
      commit: async work => { check(); committing = true; try { return await work(); } finally { committing = false; } },
    };
    const bridge = await openInitialMigrationBridge(lease, { registeredProjectId: "project:uuid",
      sourceConfig: resolve("source.toml"), targetProfile: profile, targetConfig: resolve(profile, "config.toml"),
      operationId: "initial-" + "a".repeat(40) });
    const { VIBELUTION_INITIAL_MIGRATION_URL: url, VIBELUTION_INITIAL_MIGRATION_TOKEN: token } = bridge.environment;
    try {
      expect((await fetch(`${url}/binding`)).status).toBe(403);
      const address = new URL(url);
      const malformed = await new Promise<string>((resolveResponse, reject) => {
        const socket = createConnection({ host: "127.0.0.1", port: Number(address.port) });
        const chunks: Buffer[] = [];
        socket.on("connect", () => socket.write(Buffer.concat([
          Buffer.from("GET /binding HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer " + token.slice(1), "ascii"),
          Buffer.from([0xff]), Buffer.from("\r\nConnection: close\r\n\r\n", "ascii"),
        ])));
        socket.on("data", data => chunks.push(data));
        socket.on("error", reject);
        socket.on("end", () => resolveResponse(Buffer.concat(chunks).toString("ascii")));
      });
      expect(malformed).toMatch(/^HTTP\/1\.1 403/);
      const headers = { Authorization: `Bearer ${token}` };
      const binding = await fetch(`${url}/binding`, { headers }).then(value => value.json());
      expect(binding).toMatchObject({ projectRoot: root, registeredProjectId: "project:uuid", revision: 7 });
      const permit = await fetch(`${url}/permit`, { method: "POST", headers, body: "{}" });
      expect(await permit.json()).toEqual({ schemaVersion: 1, granted: true });
      expect(committing).toBe(true);
      expect((await fetch(`${url}/permit`, { method: "POST", headers, body: "{}" })).status).toBe(409);
    } finally { await bridge.closeAfterDrain(); }
    expect(committing).toBe(false);
  });

  it("rejects an unregistered source or a target configuration outside its profile", async () => {
    const root = resolve("synthetic-project");
    const lease: PreHostSourceLease = { revision: 1, signal: new AbortController().signal, check: () => undefined,
      registration: { baseProjectId: "project", registrationUuid: "uuid", integrationRoot: root, root, active: true },
      commit: async work => await work() };
    const input = { registeredProjectId: "other:uuid", sourceConfig: resolve("source.toml"), targetProfile: resolve("profile"),
      targetConfig: resolve("elsewhere.toml"), operationId: "initial-" + "a".repeat(40) };
    await expect(openInitialMigrationBridge(lease, input)).rejects.toThrow("INITIAL_MIGRATION_BRIDGE_INVALID");
    await expect(openInitialMigrationBridge(lease, { ...input, registeredProjectId: "project:uuid" })).rejects.toThrow("INITIAL_MIGRATION_BRIDGE_INVALID");
  });
});
