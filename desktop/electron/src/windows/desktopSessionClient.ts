import type { ManagedWindowState } from "./windowProviderTypes.js";

export type DesktopSessionRegistration = {
  desktopSessionId: string;
  revision: number;
};

export async function registerDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  workspaceRoot: string;
  capabilities: string[];
  fetchImpl?: typeof fetch;
}): Promise<DesktopSessionRegistration> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(`${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions`, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "X-Vibelution-Control-Token": input.controlToken
    },
    body: JSON.stringify({
      desktopSessionId: input.desktopSessionId,
      provider: "electron",
      workspaceRoot: input.workspaceRoot,
      capabilities: input.capabilities
    })
  });
  if (!response.ok) {
    throw new Error(`desktop session registration failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}

export async function heartbeatDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  fetchImpl?: typeof fetch;
}): Promise<DesktopSessionRegistration> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(
    `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}/heartbeat`,
    {
      method: "POST",
      headers: {
        "X-Vibelution-Control-Token": input.controlToken
      }
    }
  );
  if (!response.ok) {
    throw new Error(`desktop session heartbeat failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}

export async function closeDesktopSession(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  fetchImpl?: typeof fetch;
}): Promise<DesktopSessionRegistration> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(
    `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}`,
    {
      method: "DELETE",
      headers: {
        "X-Vibelution-Control-Token": input.controlToken
      }
    }
  );
  if (!response.ok) {
    throw new Error(`desktop session close failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}

export async function reportDesktopWindowState(input: {
  launcherOrigin: string;
  controlToken: string;
  desktopSessionId: string;
  role: "launcher" | "workbench";
  revision: number;
  state: ManagedWindowState;
  fetchImpl?: typeof fetch;
}): Promise<DesktopSessionRegistration> {
  const fetcher = input.fetchImpl ?? fetch;
  const response = await fetcher(
    `${new URL(input.launcherOrigin).origin}/api/launcher/desktop-sessions/${encodeURIComponent(input.desktopSessionId)}/windows/${input.role}`,
    {
      method: "PUT",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": input.controlToken
      },
      body: JSON.stringify({
        revision: input.revision,
        provider: input.state.provider,
        open: input.state.open,
        focused: input.state.focused,
        windowId: input.state.windowId,
        rendererProcessId: input.state.rendererProcessId,
        url: input.state.url
      })
    }
  );
  if (!response.ok) {
    throw new Error(`desktop session window update failed: ${response.status}`);
  }
  return (await response.json()) as DesktopSessionRegistration;
}
