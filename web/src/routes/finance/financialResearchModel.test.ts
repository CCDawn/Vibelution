import { describe, expect, it } from "vitest";
import type { KnowledgeItem, KnowledgeSourceArtifact } from "../../api/types/knowledge";
import { activeFinancialItems, activeFinancialSources, financialSourceMetadata, safeFinancialSourceUrl } from "./financialResearchModel";

const item = { knowledgeItemId: "i", knowledgeBaseId: "finance-kb", sourceArtifactIds: ["s"], knowledgeState: "active" } as KnowledgeItem;
const source = { sourceArtifactId: "s", knowledgeBaseId: "finance-kb", sourceType: "pdf_refinement", status: "active", sourceRef: { financialEvidence: { company: "真实公司", ticker: "600001", reportPeriod: "2025FY", reportVersion: "v2", page: 12, sourceUrl: "https://example.com/report.pdf" } } } as KnowledgeSourceArtifact;
describe("financial source projection", () => {
  it("matches local library ids only when their Agent owner matches the scoped request", () => {
    const local = { ...item, knowledgeBaseId: "kb-financial-reports", ownerType: "agent", ownerId: "finance", agentId: "finance" };
    const rejected = [
      { ...local, ownerId: "another-agent", agentId: "another-agent" },
      { ...local, ownerId: undefined },
      { ...local, ownerType: "team" },
      { ...local, agentId: "another-agent" },
      { ...local, knowledgeBaseId: "another-library" },
    ];
    expect(activeFinancialItems([local, ...rejected], "agent:finance:kb-financial-reports")).toEqual([local]);
  });
  it("rejects a source artifact with a different owner even when the local library id matches", () => {
    const ownedItem = { ...item, ownerType: "agent", ownerId: "finance", agentId: "finance" };
    const ownedSource = { ...source, ownerType: "agent", ownerId: "finance", agentId: "finance" };
    expect(activeFinancialSources(ownedItem, [ownedSource, { ...ownedSource, ownerId: "another-agent" }])).toEqual([ownedSource]);
  });
  it("uses provenance metadata and never infers scope from a free-form title", () => {
    expect(financialSourceMetadata(source)).toMatchObject({ company: "真实公司", ticker: "600001", period: "2025FY", page: "12" });
    expect(financialSourceMetadata({ ...source, title: "Fake ticker 123456 P.88", sourceRef: {} })).toMatchObject({ ticker: "", page: "", url: "" });
  });
  it("excludes withdrawn, expired, unrelated and superseded material", () => {
    expect(activeFinancialItems([item, { ...item, knowledgeState: "superseded" }, { ...item, knowledgeBaseId: "other" }], "finance-kb")).toEqual([item]);
    const invalid = [
      { ...source, status: "withdrawn" },
      { ...source, expiresAt: "2020-01-01" },
      { ...source, sourceRef: { financialEvidence: { expiresAt: "2020-01-01" } } },
      { ...source, sourceArtifactId: "other" },
      { ...source, knowledgeBaseId: "other" },
      { ...source, sourceType: "news" },
    ];
    expect(activeFinancialSources(item, [source, ...invalid], Date.parse("2026-10-04"))).toEqual([source]);
  });
  it("allows only credential-free HTTP sources and valid page numbers", () => {
    for (const url of ["javascript:alert(1)", "file:///C:/private", "data:text/html,test", "https://user:pass@example.com", "/local"]) expect(safeFinancialSourceUrl(url)).toBe("");
    expect(safeFinancialSourceUrl("https://example.com/report.pdf")).toBe("https://example.com/report.pdf");
    expect(financialSourceMetadata({ ...source, sourceRef: { financialEvidence: { page: "12 <script>" } } }).page).toBe("");
  });
});
