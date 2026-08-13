/** @vitest-environment happy-dom */

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { VDialog } from "./primitives/VDialog";

type LockPackage = {
  version?: string;
};

type PackageLock = {
  packages?: Record<string, LockPackage>;
};

const MINIMUM_SAFE_PRESENCE_VERSION = [1, 1, 10] as const;

function parseVersion(version: string): [number, number, number] {
  const [major = "0", minor = "0", patch = "0"] = version.split(".");
  return [Number(major), Number(minor), Number.parseInt(patch, 10)];
}

function isAtLeast(
  actual: readonly number[],
  minimum: readonly number[],
): boolean {
  for (let index = 0; index < minimum.length; index += 1) {
    if (actual[index] !== minimum[index]) {
      return actual[index] > minimum[index];
    }
  }
  return true;
}

describe("VUI Radix runtime contract", () => {
  it("keeps every Presence runtime on the React 19-safe line", () => {
    const lockPath = resolve(import.meta.dirname, "../../../package-lock.json");
    const lock = JSON.parse(readFileSync(lockPath, "utf8")) as PackageLock;
    const presencePackages = Object.entries(lock.packages ?? {}).filter(([path]) =>
      path.endsWith("node_modules/@radix-ui/react-presence"),
    );

    expect(presencePackages.length).toBeGreaterThan(0);
    for (const [path, entry] of presencePackages) {
      expect(entry.version, `${path} must declare a version`).toBeTruthy();
      expect(
        isAtLeast(parseVersion(entry.version ?? "0.0.0"), MINIMUM_SAFE_PRESENCE_VERSION),
        `${path} resolved ${entry.version}; React 19 requires @radix-ui/react-presence >= 1.1.10`,
      ).toBe(true);
    }
  });

  it("mounts an open dialog without entering a nested update loop", async () => {
    const reactTestGlobal = globalThis as typeof globalThis & {
      IS_REACT_ACT_ENVIRONMENT?: boolean;
    };
    reactTestGlobal.IS_REACT_ACT_ENVIRONMENT = true;
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const onOpenChange = vi.fn();

    await act(async () => {
      root.render(
        createElement(
          VDialog,
          {
            open: true,
            onOpenChange,
            title: "缓存命中详情",
          },
          createElement("p", null, "缓存详情"),
        ),
      );
    });

    expect(document.querySelector('[role="dialog"]')).not.toBeNull();
    expect(onOpenChange).not.toHaveBeenCalled();

    await act(async () => {
      root.unmount();
    });
    host.remove();
    delete reactTestGlobal.IS_REACT_ACT_ENVIRONMENT;
  });
});
