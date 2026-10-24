import { readFileSync } from "node:fs";
import { expect, it, vi } from "vitest";
import { configureWindowsNotificationIdentity } from "../src/notifications/windowsNotificationIdentity.js";

it("uses the portable product shortcut identity on Windows before creating notifications", () => {
  const app = { setAppUserModelId: vi.fn() };
  configureWindowsNotificationIdentity(app, "win32");
  expect(app.setAppUserModelId).toHaveBeenCalledExactlyOnceWith("electron.app.Vibelution");
  const source = readFileSync(new URL("../src/main.ts", import.meta.url), "utf8");
  expect(source.indexOf("configureWindowsNotificationIdentity(app)")).toBeLessThan(source.indexOf("app.whenReady()"));
});

it.each(["darwin", "linux"] as const)("does not change notification identity on %s", platform => {
  const app = { setAppUserModelId: vi.fn() };
  configureWindowsNotificationIdentity(app, platform);
  expect(app.setAppUserModelId).not.toHaveBeenCalled();
});
