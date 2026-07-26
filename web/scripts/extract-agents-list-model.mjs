/**
 * Extract pure presentation helpers from AgentsRoute into agents/agentRouteListModel.ts
 * Scope: normalizeText .. buildAgentModelChoices (no filter/workspace deps).
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const outPath = path.join(root, "web/src/routes/agents/agentRouteListModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const start = lines.findIndex((l) => l.startsWith("function normalizeText("));
const end = lines.findIndex((l, i) => i > start && l.startsWith("function agentLlmSlots("));
if (start < 0 || end < 0) {
  console.error("markers", start, end);
  process.exit(1);
}

const helperLines = lines.slice(start, end).map((line) => {
  if (line.startsWith("function ")) {
    return line.replace(/^function /, "export function ");
  }
  return line;
});

const content = `/**
 * Pure Agents presentation helpers (D3).
 * Free of React hooks and AgentsRoute-only draft helpers.
 */
import type { AgentConfigWorkspaceAgent, AgentModelChoice } from "../../api/types";
import { agentDisplayInfo } from "../agentDisplay";

export type ModelProfileChoice = {
  key: string;
  modelId: string;
  label: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  unresolved?: boolean;
};

${helperLines.join("\n")}
`;

fs.writeFileSync(outPath, content);

const importBlock = `import {
  agentDialogueModelDisplay,
  agentFunctionalLabel,
  agentFunctionTone,
  agentLabel,
  agentModelChoiceAllowed,
  agentModelLabel,
  agentSearchText,
  avatarInitials,
  buildAgentModelChoices,
  encodeArrayBufferBase64,
  formatTimestamp,
  normalizeText,
  promptTemplateDisplayName,
  promptTemplateOptionLabel,
  timestampValue,
  type ModelProfileChoice,
} from "./agents/agentRouteListModel";
`;

let joined = [...lines.slice(0, start), ...lines.slice(end)].join("\n");
if (!joined.includes("agentRouteListModel")) {
  joined = joined.replace(
    'from "./agents/agentWorkspaceQuery";',
    `from "./agents/agentWorkspaceQuery";\n${importBlock}`,
  );
}
// Prefer shared ModelProfileChoice from list model
joined = joined.replace(/type ModelProfileChoice = \{[\s\S]*?\n\};\n\n/m, "");

fs.writeFileSync(routePath, joined);
console.log(`extracted ${start + 1}-${end} (${end - start} lines) -> agentRouteListModel.ts`);
console.log(`AgentsRoute lines: ${joined.split(/\n/).length}`);
