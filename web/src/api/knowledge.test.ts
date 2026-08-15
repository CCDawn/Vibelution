import { describe, expect, it } from "vitest";

import apiSource from "./knowledge.ts?raw";
import mutationsSource from "../routes/memory/useMemoryKnowledgeMutations.ts?raw";
import workbenchQueriesSource from "../routes/memory/useMemoryWorkbenchQueries.ts?raw";

describe("knowledge catalog API", () => {
  it("owns the knowledge platform transports including unused C5 routes", () => {
    const owners = [
      "fetchKnowledgeOverview",
      "fetchKnowledgeDashboardSnapshot",
      "fetchKnowledgeStewardOverview",
      "fetchKnowledgeStewardRecommendations",
      "fetchKnowledgeStewardWorkbench",
      "fetchKnowledgeOperationsHealth",
      "fetchKnowledgeAgentReadiness",
      "fetchKnowledgeGovernancePlan",
      "searchKnowledgeItems",
      "retrieveKnowledgeRag",
      "fetchKnowledgeRagHealth",
      "collectKnowledgeSourceInbox",
      "listKnowledgeSourceInbox",
      "reviewKnowledgeSourceInbox",
      "updateKnowledgeSourceGovernance",
      "listKnowledgeCentralSources",
      "fetchKnowledgePermissionAudit",
      "fetchKnowledgeGovernanceTasks",
      "listKnowledgeIngestionAdapters",
      "listTeamKnowledgeBases",
      "createTeamKnowledgeBase",
      "listAgentKnowledgeBases",
      "createAgentKnowledgeBase",
      "createKnowledgeCentralSourceArtifact",
      "createKnowledgeRefinementProposal",
      "createKnowledgeIngestionPackage",
      "reviewKnowledgeRefinementProposal",
      "listKnowledgeItems",
      "fetchKnowledgeTrace",
      "updateKnowledgeItemRating",
      "listKnowledgeRatingSuggestions",
      "createKnowledgeRatingSuggestion",
      "reviewKnowledgeRatingSuggestion",
      "bulkReviewKnowledgeRatingSuggestions",
    ];
    owners.forEach((owner) => {
      expect(apiSource).toContain(`export function ${owner}`);
    });
    expect(apiSource).toContain("/api/knowledge/dashboard-snapshot?");
    expect(apiSource).toContain("/api/knowledge/search?");
    expect(apiSource).toContain("/api/knowledge/rag/retrieve?");
    expect(apiSource).toContain("/api/knowledge/rag/health?");
    expect(apiSource).toContain("/api/knowledge/sources/inbox");
    expect(apiSource).toContain("/api/knowledge/sources/registry?");
    expect(apiSource).toContain("/api/knowledge/permissions/audit?agentId=");
    expect(apiSource).toContain("/api/knowledge/governance/tasks?");
    expect(apiSource).toContain("/api/knowledge/ingestion-adapters");
    expect(apiSource).toContain("/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}");
    expect(apiSource).toContain("/central-source-artifacts");
    expect(apiSource).toContain("/refinement-proposals");
    expect(apiSource).toContain("/ingestion-packages");
    expect(apiSource).toContain("/rating-suggestions/review-batch");
    expect(apiSource).toContain("/api/teams/${encodeURIComponent(teamId)}/knowledge-bases");
    expect(apiSource).toContain("/api/agents/${encodeURIComponent(agentId)}/knowledge-bases");
  });

  it("keeps Memory workbench queries free of knowledge transport paths", () => {
    expect(workbenchQueriesSource).toContain("fetchKnowledgeDashboardSnapshot<");
    expect(workbenchQueriesSource).toContain("listKnowledgeItems<");
    expect(workbenchQueriesSource).toContain("searchKnowledgeItems<");
    expect(workbenchQueriesSource).toContain("fetchKnowledgeRagHealth<");
    expect(workbenchQueriesSource).toContain("retrieveKnowledgeRag<");
    expect(workbenchQueriesSource).toContain("listKnowledgeRatingSuggestions<");
    expect(workbenchQueriesSource).toContain("fetchKnowledgePermissionAudit<");
    expect(workbenchQueriesSource).toContain("fetchKnowledgeGovernanceTasks<");
    expect(workbenchQueriesSource).toContain("listKnowledgeIngestionAdapters<");
    expect(workbenchQueriesSource).toContain("fetchKnowledgeTrace<");
    expect(workbenchQueriesSource).toContain("listKnowledgeSourceInbox<");
    expect(workbenchQueriesSource).toContain("listKnowledgeCentralSources<");
    expect(workbenchQueriesSource).not.toContain("/api/knowledge/");
    expect(workbenchQueriesSource).not.toContain("/api/knowledge-bases/");
  });

  it("keeps knowledge mutations free of knowledge write paths", () => {
    expect(mutationsSource).toContain("createKnowledgeRefinementProposal<");
    expect(mutationsSource).toContain("reviewKnowledgeRefinementProposal<");
    expect(mutationsSource).toContain("createKnowledgeRatingSuggestion<");
    expect(mutationsSource).toContain("reviewKnowledgeRatingSuggestion<");
    expect(mutationsSource).toContain("bulkReviewKnowledgeRatingSuggestions<");
    expect(mutationsSource).toContain("collectKnowledgeSourceInbox<");
    expect(mutationsSource).toContain("reviewKnowledgeSourceInbox<");
    expect(mutationsSource).toContain("createKnowledgeCentralSourceArtifact<");
    expect(mutationsSource).not.toContain("/api/knowledge/");
    expect(mutationsSource).not.toContain("/api/knowledge-bases/");
  });
});
