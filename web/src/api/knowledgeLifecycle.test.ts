import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "./client";
import {
  createKnowledgeRevisionProposal,
  buildKnowledgeSemanticIndex,
  fetchKnowledgeSemanticIndexHealth,
  fetchKnowledgeItemBody,
  readKnowledgeItemBodyAllPages,
  updateKnowledgeSourceLifecycle,
} from "./knowledgeLifecycle";

function response(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function bodyPage(overrides: Record<string, unknown> = {}) {
  const content = String(overrides.content ?? "正文");
  return {
    knowledgeBaseId: "kb/a",
    knowledgeItemId: "item/b",
    title: "条目",
    content,
    contentLength: content.length,
    offset: 0,
    returnedChars: content.length,
    hasMore: false,
    nextOffset: null,
    sourceArtifactIds: [],
    centralSourceIds: [],
    citations: [],
    sourceBodyStatus: "source_body_unavailable",
    contentSha256: "a".repeat(64),
    revision: 1,
    untrusted: true,
    contentTrust: "untrusted_reference_material",
    embeddedInstructionsAreData: true,
    ...overrides,
  };
}

describe("knowledge lifecycle API", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    resetControlTokenForTests();
    seedControlTokenForTests();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("reads body pages with encoded IDs and bounded pagination parameters", async () => {
    fetchMock.mockResolvedValueOnce(response(bodyPage()));

    await fetchKnowledgeItemBody({
      knowledgeBaseId: "kb/a",
      knowledgeItemId: "item b",
      agentId: "agent 1",
      offset: 7.9,
      maxChars: 99_000,
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/knowledge-bases/kb%2Fa/items/item%20b/body?agentId=agent+1&readMode=item&offset=7&maxChars=4000");
    expect(init?.method).toBeUndefined();
  });

  it("requires an explicit linked source ID when reading the original source", async () => {
    fetchMock.mockResolvedValueOnce(response(bodyPage({
      readMode: "source",
      sourceBodyStatus: "source_body_available",
    })));

    await fetchKnowledgeItemBody({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
      readMode: "source",
      sourceArtifactId: "source 4",
    });

    const [url] = fetchMock.mock.calls[0];
    expect(new URL(String(url), "http://localhost").searchParams.get("sourceArtifactId")).toBe("source 4");
  });

  it("assembles the complete body from stable, advancing pages", async () => {
    const hash = "b".repeat(64);
    fetchMock
      .mockResolvedValueOnce(response(bodyPage({ content: "甲乙", contentLength: 4, returnedChars: 2, hasMore: true, nextOffset: 2, contentSha256: hash })))
      .mockResolvedValueOnce(response(bodyPage({ content: "丙丁", contentLength: 4, offset: 2, returnedChars: 2, contentSha256: hash })));

    const result = await readKnowledgeItemBodyAllPages({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
    });

    expect(result.content).toBe("甲乙丙丁");
    expect(fetchMock.mock.calls.map(([url]) => new URL(String(url), "http://localhost").searchParams.get("offset"))).toEqual(["0", "2"]);
  });

  it("stops full-body reads if the content hash changes mid-pagination", async () => {
    fetchMock
      .mockResolvedValueOnce(response(bodyPage({ content: "甲乙", contentLength: 4, returnedChars: 2, hasMore: true, nextOffset: 2 })))
      .mockResolvedValueOnce(response(bodyPage({ content: "丙丁", contentLength: 4, offset: 2, returnedChars: 2, contentSha256: "c".repeat(64) })));

    await expect(readKnowledgeItemBodyAllPages({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
    })).rejects.toThrow("Knowledge changed while reading");
  });

  it("paginates by Unicode code points so a page ending in emoji remains valid", async () => {
    const content = `${"a".repeat(3999)}🙂bc`;
    const codePoints = Array.from(content);
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const offset = Number(url.searchParams.get("offset") || 0);
      const pageContent = codePoints.slice(offset, offset + 4000).join("");
      const nextOffset = offset + Array.from(pageContent).length;
      return response(bodyPage({
        content: pageContent,
        contentLength: codePoints.length,
        offset,
        returnedChars: Array.from(pageContent).length,
        hasMore: nextOffset < codePoints.length,
        nextOffset: nextOffset < codePoints.length ? nextOffset : null,
      }));
    });

    const result = await readKnowledgeItemBodyAllPages({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
    });

    expect(result.content).toBe(content);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("reads full bodies beyond one hundred pages within the governed snapshot bound", async () => {
    const content = "x".repeat(400_001);
    fetchMock.mockImplementation(async (input) => {
      const url = new URL(String(input), "http://localhost");
      const offset = Number(url.searchParams.get("offset") || 0);
      const pageContent = content.slice(offset, offset + 4000);
      const nextOffset = offset + pageContent.length;
      return response(bodyPage({
        content: pageContent,
        contentLength: content.length,
        offset,
        returnedChars: pageContent.length,
        hasMore: nextOffset < content.length,
        nextOffset: nextOffset < content.length ? nextOffset : null,
      }));
    });

    const result = await readKnowledgeItemBodyAllPages({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
      readMode: "source",
      sourceArtifactId: "source-1",
    });

    expect(result.content).toBe(content);
    expect(fetchMock).toHaveBeenCalledTimes(101);
  });

  it("rejects source bodies beyond the server's one-million-character reader bound", async () => {
    fetchMock.mockResolvedValueOnce(response(bodyPage({
      content: "first page",
      contentLength: 1_000_001,
      returnedChars: 10,
      hasMore: true,
      nextOffset: 4000,
    })));

    await expect(readKnowledgeItemBodyAllPages({
      knowledgeBaseId: "kb-1",
      knowledgeItemId: "item-1",
      agentId: "agent-1",
    })).rejects.toThrow("supported pagination limit");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("submits revisions with the exact current-parent and expected-hash contract", async () => {
    fetchMock.mockResolvedValueOnce(response({ proposalId: "proposal-1" }));
    const payload = {
      sourceArtifactIds: ["source-1"],
      title: "修订标题",
      summary: "修订摘要",
      content: "完整正文",
      proposedByAgentId: "agent-1",
      supersedesKnowledgeItemId: "item-old",
      expectedContentSha256: "d".repeat(64),
      revisionReason: "补充来源证据",
      tags: ["evidence"],
    };

    await createKnowledgeRevisionProposal("kb/1", payload);

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/knowledge-bases/kb%2F1/refinement-proposals");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual(payload);
  });

  it("updates only the local source artifact lifecycle using the reviewer actor", async () => {
    fetchMock.mockResolvedValueOnce(response({ sourceArtifact: { sourceArtifactId: "source-1", status: "withdrawn" } }));

    await updateKnowledgeSourceLifecycle("kb-1", "source/1", {
      status: "withdrawn",
      reason: "来源已撤回",
      actorAgentId: "reviewer-1",
    });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/knowledge-bases/kb-1/source-artifacts/source%2F1/lifecycle");
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse(String(init?.body))).toEqual({
      status: "withdrawn",
      reason: "来源已撤回",
      actorAgentId: "reviewer-1",
    });
  });

  it("reads semantic-index readiness for the current Agent", async () => {
    fetchMock.mockResolvedValueOnce(response({
      status: "degraded",
      modelPrepared: true,
      modelLoaded: false,
      embeddingModel: "BAAI/bge-small-zh-v1.5",
      indexedItemCount: 3,
      missingItemCount: 2,
      indexableItemCount: 5,
      vectorEnabled: true,
    }));

    await fetchKnowledgeSemanticIndexHealth({ agentId: "agent/one" });

    expect(fetchMock.mock.calls[0][0]).toBe("/api/knowledge/semantic-index/health?agentId=agent%2Fone");
  });

  it("requests local model preparation only when explicitly selected", async () => {
    fetchMock.mockResolvedValueOnce(response({
      status: "ready",
      indexedItemCount: 8,
      failedItemCount: 0,
      candidateItemCount: 8,
      embeddingModel: "BAAI/bge-small-zh-v1.5",
      knowledgeBaseId: "kb-1",
    }));

    await buildKnowledgeSemanticIndex("kb/1", { actorAgentId: "reviewer-1", prepareModel: true });

    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/knowledge-bases/kb%2F1/semantic-index");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ actorAgentId: "reviewer-1", prepareModel: true });
  });
});
