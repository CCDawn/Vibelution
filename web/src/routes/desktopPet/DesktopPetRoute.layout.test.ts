import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import routeSource from "./DesktopPetRoute.tsx?raw";

const routeStylesSource = readFileSync(
  fileURLToPath(new URL("../../design/route-css/desktop-pet.tailwind.css", import.meta.url)),
  "utf8",
);

describe("DesktopPetRoute compact window layout", () => {
  it("anchors the toolbar, HUD, and character to one compact character stage", () => {
    expect(routeSource).toContain('<div className={styles.stage}>');
    expect(routeStylesSource).toContain(".desktop-pet-stage");
    expect(routeStylesSource).toContain("width: min(292px, 100%)");
    expect(routeStylesSource).toContain("width: min(260px, calc(100% - 16px))");
    expect(routeStylesSource).not.toContain("inset: 5px 6px auto 6px");
  });

  it("delegates window motion to Electron instead of renderer window.moveBy", () => {
    expect(routeSource).toContain("desktopPetWindowDragBridge");
    expect(routeSource).toContain("window.requestAnimationFrame(flushWindowDrag)");
    expect(routeSource).not.toContain("window.moveBy(");
  });
});
