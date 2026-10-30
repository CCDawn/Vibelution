export type AssistantLauncherEntryActions = {
  isQuitting(): boolean;
  present(): Promise<void>;
};

/** Coalesce human requests without selecting or starting a project. */
export function createAssistantLauncherEntry(actions: AssistantLauncherEntryActions): () => Promise<{ opened: boolean }> {
  let pending: Promise<{ opened: boolean }> | null = null;
  return () => {
    if (pending) return pending;
    const operation = (async () => {
      if (actions.isQuitting()) return { opened: false };
      await actions.present();
      return { opened: !actions.isQuitting() };
    })();
    pending = operation;
    void operation.finally(() => { if (pending === operation) pending = null; }).catch(() => undefined);
    return operation;
  };
}
