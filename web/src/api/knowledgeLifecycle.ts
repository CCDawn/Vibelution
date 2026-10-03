import { fetchJson } from "./client";
import type {
  KnowledgeItemBodyPage,
  KnowledgeItemHistoryPage,
  KnowledgeRevisionProposalPayload,
  KnowledgeRefinementProposal,
  KnowledgeSemanticIndexBuildPayload,
  KnowledgeSemanticIndexBuildResponse,
  KnowledgeSemanticIndexHealthPayload,
  KnowledgeSourceLifecycleResponse,
  KnowledgeSourceLifecycleUpdate,
} from "./types/knowledge";

const KNOWLEDGE_BODY_PAGE_CHARS = 4000;
const KNOWLEDGE_BODY_MAX_CHARS = 1_000_000;
const KNOWLEDGE_BODY_MAX_PAGES = Math.ceil(KNOWLEDGE_BODY_MAX_CHARS / KNOWLEDGE_BODY_PAGE_CHARS);

function unicodeCodePointLength(value: string): number {
  let length = 0;
  for (const _codePoint of value) {
    length += 1;
  }
  return length;
}

type KnowledgeBodyReadBase = {
  knowledgeBaseId: string;
  knowledgeItemId: string;
  agentId: string;
  offset?: number;
  maxChars?: number;
  signal?: AbortSignal;
};

export type KnowledgeItemBodyReadOptions = KnowledgeBodyReadBase & {
  readMode?: "item";
  sourceArtifactId?: never;
};

export type KnowledgeSourceBodyReadOptions = KnowledgeBodyReadBase & {
  readMode: "source";
  sourceArtifactId: string;
};

export type KnowledgeHistoryReadOptions = KnowledgeBodyReadBase & {
  readMode: "history";
  sourceArtifactId?: never;
};

function knowledgeBaseItemBodyPath(knowledgeBaseId: string, knowledgeItemId: string): string {
  return `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/items/${encodeURIComponent(knowledgeItemId)}/body`;
}

export function fetchKnowledgeItemBody(options: KnowledgeHistoryReadOptions): Promise<KnowledgeItemHistoryPage>;
export function fetchKnowledgeItemBody(options: KnowledgeItemBodyReadOptions | KnowledgeSourceBodyReadOptions): Promise<KnowledgeItemBodyPage>;
export function fetchKnowledgeItemBody(
  options: KnowledgeItemBodyReadOptions | KnowledgeSourceBodyReadOptions | KnowledgeHistoryReadOptions,
): Promise<KnowledgeItemBodyPage | KnowledgeItemHistoryPage> {
  const params = new URLSearchParams({
    agentId: options.agentId,
    readMode: options.readMode ?? "item",
    offset: String(Math.max(0, Math.floor(options.offset ?? 0))),
    maxChars: String(Math.max(1, Math.min(4000, Math.floor(options.maxChars ?? 2400)))),
  });
  if (options.readMode === "source") {
    params.set("sourceArtifactId", options.sourceArtifactId);
  }
  return fetchJson<KnowledgeItemBodyPage | KnowledgeItemHistoryPage>(
    `${knowledgeBaseItemBodyPath(options.knowledgeBaseId, options.knowledgeItemId)}?${params.toString()}`,
    { signal: options.signal },
  );
}

export async function readKnowledgeItemBodyAllPages(
  options: Omit<KnowledgeItemBodyReadOptions, "offset"> | Omit<KnowledgeSourceBodyReadOptions, "offset">,
): Promise<KnowledgeItemBodyPage & { content: string }> {
  const chunks: string[] = [];
  let offset = 0;
  let contentLength: number | undefined;
  let contentSha256: string | undefined;
  let firstPage: KnowledgeItemBodyPage | undefined;

  for (let pageIndex = 0; pageIndex < KNOWLEDGE_BODY_MAX_PAGES; pageIndex += 1) {
    const page = await fetchKnowledgeItemBody({ ...options, offset, maxChars: KNOWLEDGE_BODY_PAGE_CHARS } as KnowledgeItemBodyReadOptions | KnowledgeSourceBodyReadOptions);
    if (!firstPage) {
      firstPage = page;
      contentLength = page.contentLength;
      contentSha256 = page.contentSha256;
      if (typeof contentLength !== "number" || !Number.isSafeInteger(contentLength) || contentLength < 0 || contentLength > KNOWLEDGE_BODY_MAX_CHARS) {
        throw new Error("Knowledge body exceeds the supported pagination limit.");
      }
    } else if (page.contentLength !== contentLength || page.contentSha256 !== contentSha256) {
      throw new Error("Knowledge changed while reading; reload the latest revision before continuing.");
    }
    if (page.offset !== offset || page.returnedChars !== unicodeCodePointLength(page.content)) {
      throw new Error("Knowledge page is inconsistent; retry the read.");
    }
    chunks.push(page.content);
    if (!page.hasMore) {
      const content = chunks.join("");
      if (unicodeCodePointLength(content) !== contentLength) {
        throw new Error("Knowledge body is incomplete; retry the read.");
      }
      return { ...firstPage, content };
    }
    const nextOffset = page.nextOffset;
    if (typeof nextOffset !== "number" || nextOffset <= offset || page.content.length === 0) {
      throw new Error("Knowledge page cursor did not advance; retry the read.");
    }
    offset = nextOffset;
  }
  throw new Error("Knowledge body exceeds the supported pagination limit.");
}

export function createKnowledgeRevisionProposal(
  knowledgeBaseId: string,
  payload: KnowledgeRevisionProposalPayload,
): Promise<KnowledgeRefinementProposal> {
  return fetchJson<KnowledgeRefinementProposal>(
    `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/refinement-proposals`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function updateKnowledgeSourceLifecycle(
  knowledgeBaseId: string,
  sourceArtifactId: string,
  payload: KnowledgeSourceLifecycleUpdate,
): Promise<KnowledgeSourceLifecycleResponse> {
  return fetchJson<KnowledgeSourceLifecycleResponse>(
    `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/source-artifacts/${encodeURIComponent(sourceArtifactId)}/lifecycle`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export function fetchKnowledgeSemanticIndexHealth(options: {
  agentId: string;
  signal?: AbortSignal;
}): Promise<KnowledgeSemanticIndexHealthPayload> {
  const params = new URLSearchParams({ agentId: options.agentId });
  return fetchJson<KnowledgeSemanticIndexHealthPayload>(`/api/knowledge/semantic-index/health?${params.toString()}`, {
    signal: options.signal,
  });
}

export function buildKnowledgeSemanticIndex(
  knowledgeBaseId: string,
  payload: KnowledgeSemanticIndexBuildPayload,
): Promise<KnowledgeSemanticIndexBuildResponse> {
  return fetchJson<KnowledgeSemanticIndexBuildResponse>(
    `/api/knowledge-bases/${encodeURIComponent(knowledgeBaseId)}/semantic-index`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}
