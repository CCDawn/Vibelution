import type { ManagedWindowState } from "./windowProviderTypes.js";

export type DesktopSessionRegistration = {
  desktopSessionId: string;
  revision: number;
};

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
