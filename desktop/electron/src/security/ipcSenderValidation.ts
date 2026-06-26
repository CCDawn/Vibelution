import type { IpcMainInvokeEvent } from "electron";

export function assertTrustedIpcSender(event: IpcMainInvokeEvent, allowedOrigins: string[]): void {
  const rawUrl = event.senderFrame?.url;
  if (!rawUrl) {
    throw new Error("blocked ipc sender origin: <unknown>");
  }
  const origin = new URL(rawUrl).origin;
  if (!allowedOrigins.includes(origin)) {
    throw new Error(`blocked ipc sender origin: ${origin}`);
  }
}
