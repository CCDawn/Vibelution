import type { IpcMainInvokeEvent } from "electron";

function ipcSenderOrigin(rawUrl: string): string {
  const url = new URL(rawUrl);
  return `${url.protocol}//${url.host}`;
}

export function assertTrustedIpcSender(event: IpcMainInvokeEvent, allowedOrigins: string[]): void {
  const rawUrl = event.senderFrame?.url;
  if (!rawUrl) {
    throw new Error("blocked ipc sender origin: <unknown>");
  }
  const origin = ipcSenderOrigin(rawUrl);
  if (!allowedOrigins.includes(origin)) {
    throw new Error(`blocked ipc sender origin: ${origin}`);
  }
}
