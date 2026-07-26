/**
 * C1.1 dictionary charter: move structured Agents workbench copy under i18n/domains.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const src = path.join(root, "web/src/routes/agents/agentsRouteCopy.ts");
const domainPath = path.join(root, "web/src/i18n/domains/agentsWorkbenchCopy.ts");
const loaderPath = path.join(root, "web/src/i18n/loadAgentsWorkbenchCopy.ts");
const text = fs.readFileSync(src, "utf8");

// If already a facade, stop.
if (text.includes("i18n/domains/agentsWorkbenchCopy")) {
  console.log("already facaded");
  process.exit(0);
}

const domain = text
  .replace(
    /from "\.\/agentRouteManagementModel"/,
    'from "../../routes/agents/agentRouteManagementModel"',
  )
  .replace(
    "Agents workbench bilingual copy + pane badge helpers (structure C1).",
    [
      "Agents workbench bilingual copy tables (dictionary charter C1.1).",
      " * Domain-shaped structured copy (nested tables), not flat TranslationKey.",
      " * Ships with the Agents route graph; soft-prefetch via loadAgentsWorkbenchCopy.",
    ].join("\n"),
  );

fs.writeFileSync(domainPath, domain);

const facade = `/**
 * Facade for Agents workbench copy (structure C1 / dictionary charter C1.1).
 * Tables live under i18n/domains so ownership aligns with domain-lazy i18n.
 */
export {
  agentConfigPanes,
  agentsRouteCopy,
  type AgentsRouteCopy,
} from "../../i18n/domains/agentsWorkbenchCopy";
`;
fs.writeFileSync(src, facade.endsWith("\n") ? facade : `${facade}\n`);

const loader = `/**
 * Soft-prefetch for Agents structured workbench copy (dictionary charter C1.1).
 * Not a flat TranslationKey domain — nested tables stay typed via AgentsRouteCopy.
 */
export function prefetchAgentsWorkbenchCopy(): void {
  void import("./domains/agentsWorkbenchCopy").catch(() => {
    // Soft prefetch must not surface.
  });
}

export async function loadAgentsWorkbenchCopy() {
  return import("./domains/agentsWorkbenchCopy");
}
`;
fs.writeFileSync(loaderPath, loader.endsWith("\n") ? loader : `${loader}\n`);

console.log("wrote", domainPath);
console.log("facade", src);
console.log("loader", loaderPath);
console.log("domain lines", domain.split(/\n/).length);
