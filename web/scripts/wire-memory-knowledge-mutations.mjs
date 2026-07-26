/**
 * Wire useMemoryKnowledgeMutations into MemoryRoute (S3).
 * Usage from web/: node scripts/wire-memory-knowledge-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/MemoryRoute.tsx";
let src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const proposalMutation = useMutation({");
const end = src.indexOf("  const overview = overviewQuery.data;");
if (start < 0 || end <= start) {
  console.error("proposal markers", start, end);
  process.exit(1);
}

const hook = `  const {
    proposalMutation,
    reviewMutation,
    ratingMutation,
    ratingSuggestionReviewMutation,
    ratingSuggestionBulkReviewMutation,
    sourceInboxCollectMutation,
    sourceInboxReviewMutation,
    centralSourceAttachMutation,
  } = useMemoryKnowledgeMutations({
    copy,
    setProposalDraft,
    setOwnerSourceDraft,
    setKnowledgeFeedback,
    setSelectedRatingSuggestionIds,
    newProposalDraft,
    newOwnerSourceDraft,
    commaList,
    parseJsonObject,
    getActiveKnowledgeActorAgentId: () => activeKnowledgeActorAgentId,
    getActiveKnowledgeBaseForItems: () => activeKnowledgeBaseForItems,
    getKnowledgeSearchDraft: () => knowledgeSearchDraft,
    getActiveSourceOwnerType: () => activeSourceOwnerType,
    getActiveSourceOwnerId: () => activeSourceOwnerId,
    getActiveSourceInboxStatus: () => activeSourceInboxStatus,
    getSourceReviewNote: () => sourceReviewNote,
    getDuplicateCentralSourceId: () => duplicateCentralSourceId,
    invalidateMemoryQueries,
    invalidateKnowledgeDashboard,
  });

`;

src = src.slice(0, start) + hook + src.slice(end);

const sourceStart = src.indexOf("  const sourceInboxCollectMutation = useMutation({");
if (sourceStart >= 0) {
  const after = src.indexOf("  const knowledgeSearchResults = knowledgeSearchQuery.data");
  if (after <= sourceStart) {
    console.error("source end missing");
    process.exit(1);
  }
  src = src.slice(0, sourceStart) + src.slice(after);
  console.log("removed source inbox inline mutations");
}

if (!src.includes("./memory/useMemoryKnowledgeMutations")) {
  src = src.replace(
    'import { useMemoryItemMutations } from "./memory/useMemoryItemMutations";',
    'import { useMemoryItemMutations } from "./memory/useMemoryItemMutations";\nimport { useMemoryKnowledgeMutations } from "./memory/useMemoryKnowledgeMutations";',
  );
}

writeFileSync(routePath, src);
console.log("wired knowledge mutations");
