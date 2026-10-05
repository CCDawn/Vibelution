export const agentPerceptionQueryKeys = {
  configuration: (agentId: string) => ["agents", agentId, "perception", "configuration"] as const,
  runtime: (agentId: string) => ["agents", agentId, "perception", "runtime"] as const,
};
