export class AgentOperationInProgressError extends Error {
  constructor() { super("该 Agent 的操作仍在处理中，请稍后核对状态。"); }
}

/** A synchronous guard also covers the interval before React renders pending state. */
export function createAgentOperationScope(onChange: (ids: ReadonlySet<string>) => void) {
  const pending = new Set<string>();
  return {
    isPending: (id: string) => pending.has(id),
    begin(ids: readonly string[]) {
      const targets = [...new Set(ids)];
      if (targets.some(id => pending.has(id))) throw new AgentOperationInProgressError();
      targets.forEach(id => pending.add(id));
      onChange(new Set(pending));
      let released = false;
      return () => {
        if (released) return;
        released = true;
        targets.forEach(id => pending.delete(id));
        onChange(new Set(pending));
      };
    },
  };
}
