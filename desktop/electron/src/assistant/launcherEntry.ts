export type AssistantLauncherEntryActions = {
  isQuitting(): boolean;
  openExisting(): Promise<boolean>;
  chooseProject(): Promise<string | null>;
  connect(projectRoot: string): Promise<boolean>;
  openConnected(): Promise<void>;
};

/** Human window action only. Never receives a renderer path or selects a grant. */
export function createAssistantLauncherEntry(actions: AssistantLauncherEntryActions): () => Promise<{ opened: boolean }> {
  let pending: Promise<{ opened: boolean }> | null = null;
  return () => {
    if (pending) return pending;
    const operation = (async () => {
      if (actions.isQuitting()) return { opened: false };
      if (await actions.openExisting()) return { opened: true };
      const root = await actions.chooseProject();
      if (!root || actions.isQuitting()) return { opened: false };
      if (!await actions.connect(root)) throw new Error("ASSISTANT_LAUNCHER_UNAVAILABLE");
      if (actions.isQuitting()) return { opened: false };
      await actions.openConnected();
      return { opened: true };
    })();
    pending = operation;
    void operation.finally(() => { if (pending === operation) pending = null; }).catch(() => undefined);
    return operation;
  };
}
