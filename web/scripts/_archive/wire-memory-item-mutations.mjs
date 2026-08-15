/**
 * Wire useMemoryItemMutations into MemoryRoute (R4).
 * Usage from web/: node scripts/wire-memory-item-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/MemoryRoute.tsx";
let src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const memoryMutation = useMutation({");
const end = src.indexOf("  const proposalMutation = useMutation({");
if (start < 0 || end <= start) {
  console.error("markers", start, end);
  process.exit(1);
}

const hook = `  const {
    memoryMutation,
    deleteMemoryMutation,
    restoreMemoryMutation,
    projectMemoryUpdateResolveMutation,
    cleanupPreviewMutation,
    cleanupExecuteMutation,
  } = useMemoryItemMutations({
    copy,
    setEditDraft,
    setActiveSectionId,
    setActiveItemId,
    setMutationFeedback,
    setMemoryProposalResolutionNotes,
    setCleanupPreview,
    setCleanupExecution,
    setCleanupConfirmationText,
    setCleanupFeedback,
    fallbackKnowledgeActorAgentId,
    requestedTeamId,
    memoryMutationEndpoint,
    projectMemoryProposalResolveEndpoint,
    invalidateMemoryQueries,
    invalidateKnowledgeDashboard,
  });

`;

src = src.slice(0, start) + hook + src.slice(end);

if (!src.includes("./memory/useMemoryItemMutations")) {
  src = src.replace(
    'import { useShellI18n } from "../i18n/useShellI18n";',
    'import { useShellI18n } from "../i18n/useShellI18n";\nimport { useMemoryItemMutations } from "./memory/useMemoryItemMutations";',
  );
}

writeFileSync(routePath, src);
console.log("wired memory item mutations");
