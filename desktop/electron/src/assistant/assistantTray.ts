import { Menu, Tray, nativeImage } from "electron";
import { join } from "node:path";

/** The resident assistant remains reachable while project control is unavailable. */
export function createAssistantTray(sourceRoot: string, actions: { open: () => void; quit: () => void }): Tray {
  const tray = new Tray(nativeImage.createFromPath(join(sourceRoot, "assets", "icons", "vibelution.ico")));
  tray.setToolTip("Vibelution 个人助理");
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: "打开个人助理", click: actions.open },
    { label: "项目控制尚未连接", enabled: false },
    { type: "separator" },
    { label: "退出个人助理", click: actions.quit },
  ]));
  tray.on("double-click", actions.open);
  return tray;
}
