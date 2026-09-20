/** Team bundle DTOs (export payload / import preview+result). */

export type TeamBundleAgent = {
  bundleAgentKey?: string;
  agentCode?: string;
  displayName?: string;
  kind?: string;
  primaryMode?: string;
  roleKey?: string;
  llmBindings?: Record<string, { modelId?: string }>;
  promptTemplateId?: string;
  toolPolicy?: Record<string, unknown>;
  memoryPolicy?: Record<string, unknown>;
  contextCompressionPolicy?: Record<string, unknown>;
  permissionPreset?: string;
  metadata?: Record<string, unknown>;
  personaProfile?: Record<string, unknown>;
  taskProfile?: Record<string, unknown>;
};

export type TeamBundleMember = {
  bundleAgentKey?: string;
  role?: string;
  purpose?: string;
  responsibilities?: string[];
};

export type TeamBundle = {
  kind: string;
  schemaVersion: number;
  exportedAt?: string;
  appVersion?: string;
  team: {
    name: string;
    description?: string;
    purpose?: string;
    members: TeamBundleMember[];
    chatRoom?: { mode?: string; purpose?: string };
  };
  agents: TeamBundleAgent[];
  promptTemplates?: Array<{ templateId: string; label?: string; content?: string }>;
  canvas?: Record<string, unknown>;
  dependencies?: {
    providers?: Record<string, { models?: string[] }>;
  };
};

export type TeamBundleImportDependencyReport = {
  missingProviders: string[];
  missingModels: Array<{ providerId: string; model: string }>;
  pendingCredentials: Array<{ providerId: string; credentialEnv: string }>;
};

export type TeamBundleImportReport = {
  schemaVersion: number;
  bundleSchemaVersion: number;
  status: "ready" | "pending" | "completed";
  dryRun: boolean;
  team: { name: string; action: "create" | "update" };
  agents: { create: string[]; overwrite: string[] };
  dependencies: TeamBundleImportDependencyReport;
  warnings: string[];
  result?: { teamId: string; agents: Array<{ agentId: string; action: string }> };
};
