// Preserve the identity of the existing portable product's Start Menu shortcut.
// Unpackaged Electron otherwise uses its own executable's notification identity.
export const WINDOWS_NOTIFICATION_APP_ID = "electron.app.Vibelution";

export function configureWindowsNotificationIdentity(
  app: { setAppUserModelId(id: string): void },
  platform: NodeJS.Platform = process.platform
): void {
  if (platform === "win32") app.setAppUserModelId(WINDOWS_NOTIFICATION_APP_ID);
}
