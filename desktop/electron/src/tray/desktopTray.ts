import { Menu, Tray, nativeImage } from "electron";
import { resolveWorkspaceIconPath, type DesktopPaths } from "../paths.js";

export type DesktopTrayActions = {
  openLauncher: () => void;
  quit: () => void;
};

export function createDesktopTray(paths: DesktopPaths, actions: DesktopTrayActions): Tray {
  const tray = new Tray(nativeImage.createFromPath(resolveWorkspaceIconPath(paths)));
  tray.setToolTip("Vibelution");
  tray.on("click", actions.openLauncher);
  tray.setContextMenu(
    Menu.buildFromTemplate([
      { label: "打开 Vibelution Launcher", click: actions.openLauncher },
      { type: "separator" },
      { label: "退出 Vibelution", click: actions.quit }
    ])
  );
  return tray;
}
