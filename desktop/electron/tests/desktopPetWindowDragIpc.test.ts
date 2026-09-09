import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const ipcSource = readFileSync(fileURLToPath(new URL("../src/ipc.ts", import.meta.url)), "utf8");
const preloadSource = readFileSync(fileURLToPath(new URL("../src/preload.ts", import.meta.url)), "utf8");
const mainSource = readFileSync(fileURLToPath(new URL("../src/main.ts", import.meta.url)), "utf8");

describe("desktop pet fixed-bounds drag IPC", () => {
  it("exposes drag operations only through the desktop-pet preload branch", () => {
    expect(ipcSource).toContain('beginDesktopPetWindowDrag: "pet:window-drag-begin"');
    expect(ipcSource).toContain('moveDesktopPetWindowDrag: "pet:window-drag-move"');
    expect(ipcSource).toContain('endDesktopPetWindowDrag: "pet:window-drag-end"');
    expect(preloadSource).toContain("...(isDesktopPetWindow");
    expect(preloadSource).toContain("ipcRenderer.send(IPC_CHANNELS.moveDesktopPetWindowDrag, point)");
  });

  it("moves the owning BrowserWindow with fixed bounds in the main process", () => {
    expect(mainSource).toContain("BrowserWindow.fromWebContents(event.sender)");
    expect(mainSource).toContain("const { x, y } = window.getBounds()");
    expect(mainSource).toContain("width: PET_WINDOW_WIDTH");
    expect(mainSource).toContain("height: PET_WINDOW_HEIGHT");
    expect(mainSource).not.toContain("beginDesktopPetWindowDrag(rawPoint, window.getBounds())");
    expect(mainSource).toContain("window.setBounds(desktopPetWindowBoundsAt(active.drag, rawPoint), false)");
    expect(mainSource).not.toContain("window.moveBy(update.delta.screenX");
  });
});
