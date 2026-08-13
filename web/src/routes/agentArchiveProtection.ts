/**
 * Shared archive-protection predicate for Agent directory grouping,
 * context-menu archive, and Agents workbench bulk archive.
 */

export const PROTECTED_RESEARCH_ORG_ROLES = [
  "ceo",
  "organization_advisor",
  "capability_steward",
  "knowledge_steward",
] as const;

export type AgentArchiveProtectionSource = {
  metadata?: Record<string, unknown> | null;
} | null | undefined;

function metadataString(agent: AgentArchiveProtectionSource, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "string") {
    return value.trim();
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  return "";
}

function metadataFlag(agent: AgentArchiveProtectionSource, key: string) {
  const value = agent?.metadata?.[key];
  if (typeof value === "boolean") {
    return value;
  }
  return ["1", "true", "yes"].includes(metadataString(agent, key).toLowerCase());
}

export function agentArchiveProtected(agent: AgentArchiveProtectionSource) {
  const researchOrgRole = metadataString(agent, "researchOrgRole");
  const systemOwnedRole = [
    metadataString(agent, "systemRole"),
    metadataString(agent, "selfEvolutionRole"),
    metadataString(agent, "supervisedRole"),
    metadataString(agent, "aiSearchRole"),
  ].some(Boolean);
  return metadataFlag(agent, "protected")
    || metadataFlag(agent, "fixedRole")
    || systemOwnedRole
    || (PROTECTED_RESEARCH_ORG_ROLES as readonly string[]).includes(researchOrgRole);
}
