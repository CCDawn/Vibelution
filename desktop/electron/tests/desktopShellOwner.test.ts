import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import {
  DESKTOP_SHELL_OWNER_RELATIVE_PATH,
  claimElectronDesktopShellOwner,
  desktopShellOwnerPath,
  releaseElectronDesktopShellOwner
} from "../src/tray/desktopShellOwner.js";

describe("desktopShellOwner", () => {
  it("claims and releases the electron tray owner file", () => {
    const root = mkdtempSync(join(tmpdir(), "vibelution-shell-owner-"));
    try {
      const record = claimElectronDesktopShellOwner(root, 4242);
      expect(record.owner).toBe("electron");
      expect(record.pid).toBe(4242);
      expect(desktopShellOwnerPath(root).replace(/\\/g, "/")).toContain(DESKTOP_SHELL_OWNER_RELATIVE_PATH);
      const written = JSON.parse(readFileSync(desktopShellOwnerPath(root), "utf8")) as { pid: number };
      expect(written.pid).toBe(4242);
      releaseElectronDesktopShellOwner(root, 4242);
      expect(() => readFileSync(desktopShellOwnerPath(root), "utf8")).toThrow();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
