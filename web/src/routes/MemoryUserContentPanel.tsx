import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch, FolderCog, Import, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import type {
  UserMarkdownPageSummary,
  UserMarkdownSearchResult,
  UserMarkdownSpaceImportPayload,
  UserMarkdownSpaceImportPreviewPayload,
  UserMarkdownSpaceCounts,
  UserMarkdownSpaceListPayload,
  UserMarkdownSpacePageListPayload,
  UserMarkdownSpacePagePayload,
  UserMarkdownSpaceSearchPayload,
  UserMarkdownSpaceSummary,
} from "../api/types";
import { VButton, VNativeInput, VNativeSelect } from "../components/vui";
import styles from "./MemoryUserContentPanel.styles";

export interface MemoryUserContentPanelProps {
  defaultUserId?: string;
}

type NormalizedSpaceSummary = UserMarkdownSpaceSummary & {
  userId: string;
  sourceRef: Record<string, unknown>;
  counts: UserMarkdownSpaceCounts;
};

function endpointWithUserId(path: string, userId: string, extras?: Record<string, string | number>) {
  const params = new URLSearchParams({ userId });
  for (const [key, value] of Object.entries(extras ?? {})) {
    const text = String(value ?? "").trim();
    if (text) {
      params.set(key, text);
    }
  }
  return `${path}?${params.toString()}`;
}

function errorText(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return error ? String(error) : "";
}

function normalizeSpaceSummary(space: UserMarkdownSpaceSummary): NormalizedSpaceSummary {
  const rawPageCount = Number(space.pageCount ?? 0);
  const rawCounts = space.counts as unknown;
  const countsRecord = rawCounts && typeof rawCounts === "object" ? rawCounts as Record<string, unknown> : null;
  const counts = countsRecord
    ? {
      markdownFileCount: Number(countsRecord.markdownFileCount ?? rawPageCount),
      pageCount: Number(countsRecord.pageCount ?? rawPageCount),
      linkCount: Number(countsRecord.linkCount ?? 0),
      taskCount: Number(countsRecord.taskCount ?? 0),
      tagCount: Number(countsRecord.tagCount ?? 0),
    }
    : {
      markdownFileCount: rawPageCount,
      pageCount: rawPageCount,
      linkCount: 0,
      taskCount: 0,
      tagCount: 0,
    };
  return {
    spaceId: String(space.spaceId ?? ""),
    spaceName: String(space.spaceName ?? ""),
    userId: String(space.userId ?? "default"),
    canonicalPagesRoot: String(space.canonicalPagesRoot ?? ""),
    indexRoot: String(space.indexRoot ?? ""),
    sourceRef: (space.sourceRef && typeof space.sourceRef === "object" ? space.sourceRef : {}) as Record<string, unknown>,
    counts,
    updatedAt: String(space.updatedAt ?? ""),
    pageCount: rawPageCount || counts.pageCount,
  };
}

function pageContent(payload?: UserMarkdownSpacePagePayload) {
  if (!payload) {
    return "";
  }
  if (payload.content) {
    return payload.content;
  }
  return payload.page?.content ?? "";
}

function sourceRefPreview(sourceRef?: Record<string, unknown>) {
  if (!sourceRef) {
    return "";
  }
  const path = typeof sourceRef.path === "string" ? sourceRef.path : "";
  const sha256 = typeof sourceRef.sha256 === "string" ? sourceRef.sha256 : "";
  return [path, sha256].filter(Boolean).join(" | ");
}

export function MemoryUserContentPanel({ defaultUserId = "default" }: MemoryUserContentPanelProps) {
  const queryClient = useQueryClient();
  const userId = String(defaultUserId || "default").trim() || "default";
  const [sourcePath, setSourcePath] = useState("");
  const [spaceName, setSpaceName] = useState("");
  const [selectedSpaceId, setSelectedSpaceId] = useState("");
  const [selectedPageId, setSelectedPageId] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("");

  const spacesQuery = useQuery({
    queryKey: queryKeys.userMarkdownSpaces(),
    queryFn: () => fetchJson<UserMarkdownSpaceListPayload>(endpointWithUserId("/api/user-content/markdown-spaces", userId)),
  });

  const spaces = useMemo(
    () => (spacesQuery.data?.spaces ?? []).map((space) => normalizeSpaceSummary(space)),
    [spacesQuery.data?.spaces],
  );

  useEffect(() => {
    if (!spaces.length) {
      setSelectedSpaceId("");
      return;
    }
    if (!selectedSpaceId || !spaces.some((space) => space.spaceId === selectedSpaceId)) {
      setSelectedSpaceId(spaces[0]?.spaceId ?? "");
    }
  }, [selectedSpaceId, spaces]);

  const pagesQuery = useQuery({
    enabled: Boolean(selectedSpaceId),
    queryKey: queryKeys.userMarkdownSpacePages(selectedSpaceId, searchQuery, tagFilter),
    queryFn: () =>
      fetchJson<UserMarkdownSpacePageListPayload>(
        endpointWithUserId(
          `/api/user-content/markdown-spaces/${encodeURIComponent(selectedSpaceId)}/pages`,
          userId,
          {
            query: searchQuery,
            tag: tagFilter,
          },
        ),
      ),
  });

  const pages = pagesQuery.data?.pages ?? [];

  useEffect(() => {
    if (!pages.length) {
      setSelectedPageId("");
      return;
    }
    if (!selectedPageId || !pages.some((page) => page.pageId === selectedPageId)) {
      setSelectedPageId(pages[0]?.pageId ?? "");
    }
  }, [pages, selectedPageId]);

  const pageQuery = useQuery({
    enabled: Boolean(selectedSpaceId && selectedPageId),
    queryKey: queryKeys.userMarkdownSpacePage(selectedSpaceId, selectedPageId),
    queryFn: () =>
      fetchJson<UserMarkdownSpacePagePayload>(
        endpointWithUserId(
          `/api/user-content/markdown-spaces/${encodeURIComponent(selectedSpaceId)}/pages/${encodeURIComponent(selectedPageId)}`,
          userId,
        ),
      ),
  });

  const searchResultsQuery = useQuery({
    enabled: Boolean(searchQuery.trim()),
    queryKey: queryKeys.userMarkdownSpaceSearch(searchQuery, selectedSpaceId, 10),
    queryFn: () =>
      fetchJson<UserMarkdownSpaceSearchPayload>(
        endpointWithUserId("/api/user-content/markdown-spaces/search", userId, {
          query: searchQuery,
          spaceId: selectedSpaceId,
          limit: 10,
        }),
      ),
  });

  const previewMutation = useMutation({
    mutationFn: () =>
      fetchJson<UserMarkdownSpaceImportPreviewPayload>("/api/user-content/markdown-spaces/import-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourcePath,
          userId,
        }),
      }),
  });

  const importMutation = useMutation({
    mutationFn: () =>
      fetchJson<UserMarkdownSpaceImportPayload>("/api/user-content/markdown-spaces/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sourcePath,
          spaceName,
          userId,
        }),
      }),
    onSuccess: async (payload) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.userMarkdownSpaces() });
      setSelectedSpaceId(payload.space.spaceId);
      setSelectedPageId("");
      if (!spaceName.trim()) {
        setSpaceName(payload.space.spaceName);
      }
    },
  });

  const selectedSpace = useMemo(
    () => spaces.find((space) => space.spaceId === selectedSpaceId) ?? null,
    [selectedSpaceId, spaces],
  );
  const preview = previewMutation.data;
  const selectedPagePayload = pageQuery.data;
  const selectedPageContent = pageContent(selectedPagePayload);
  const visibleTags = useMemo(() => {
    const tagSet = new Set<string>();
    for (const page of pages) {
      for (const tag of page.tags ?? []) {
        if (tag) {
          tagSet.add(tag);
        }
      }
    }
    return Array.from(tagSet).sort((left, right) => left.localeCompare(right));
  }, [pages]);

  return (
    <section className={styles.root}>
      <div className={styles.header}>
        <div>
          <p className={styles.panelEyebrow}>User Markdown</p>
          <h2>用户内容</h2>
        </div>
        <span className={styles.badge}>{spacesQuery.data?.summary.spaceCount ?? spaces.length}</span>
      </div>

      <div className={styles.toolbar}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <strong>导入托管副本</strong>
            <span className={styles.badge}>{userId}</span>
          </div>
          <div className={styles.formRow}>
            <label>
              <span>来源目录</span>
              <VNativeInput value={sourcePath} onChange={(event) => setSourcePath(event.target.value)} placeholder="C:\\notes\\project" />
            </label>
            <label>
              <span>空间名</span>
              <VNativeInput value={spaceName} onChange={(event) => setSpaceName(event.target.value)} placeholder="自动取目录名" />
            </label>
            <div className={styles.actionRow}>
              <VButton
                type="button"
                icon={<FileSearch size={16} />}
                onPress={() => previewMutation.mutate()}
                isDisabled={!sourcePath.trim() || previewMutation.isPending}
              >
                预检
              </VButton>
              <VButton
                type="button"
                variant="primary"
                icon={<Import size={16} />}
                onPress={() => importMutation.mutate()}
                isDisabled={!sourcePath.trim() || importMutation.isPending}
              >
                导入
              </VButton>
            </div>
          </div>
          {previewMutation.error ? <div className={styles.error}>{errorText(previewMutation.error)}</div> : null}
          {importMutation.error ? <div className={styles.error}>{errorText(importMutation.error)}</div> : null}
          {preview ? (
            <>
              <div className={styles.actionRow}>
                <span className={styles.badge}>{preview.summary.markdownFileCount} pages</span>
                <span className={styles.badge}>{preview.summary.wikilinkCount} links</span>
                <span className={styles.badge}>{preview.summary.taskCount} tasks</span>
                <span className={styles.badge}>{preview.summary.tagCount} tags</span>
              </div>
              <div className={styles.metaWrap}>{preview.source.managedRoot}</div>
              <div className={styles.previewList}>
                {(preview.pages ?? []).slice(0, 6).map((page) => (
                  <div key={`${page.relativePath}:${page.title}`}>
                    <strong>{page.title}</strong>
                    <div className={styles.metaWrap}>{page.relativePath}</div>
                  </div>
                ))}
                {preview.ignoredFiles.length ? (
                  <div className={styles.metaWrap}>ignored: {preview.ignoredFiles.slice(0, 3).map((row) => row.relativePath).join(", ")}</div>
                ) : null}
              </div>
            </>
          ) : null}
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <strong>浏览与检索</strong>
            <span className={styles.badge}>{pagesQuery.data?.summary.pageCount ?? 0}</span>
          </div>
          <div className={styles.formRow}>
            <label>
              <span>搜索</span>
              <VNativeInput value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} placeholder="标题、路径、正文检索" />
            </label>
            <label>
              <span>标签</span>
              <VNativeSelect value={tagFilter} onChange={(event) => setTagFilter(event.target.value)}>
                <option value="">全部</option>
                {visibleTags.map((tag) => (
                  <option key={tag} value={tag}>{tag}</option>
                ))}
              </VNativeSelect>
            </label>
            <div className={styles.actionRow}>
              <span className={styles.badge}>{searchResultsQuery.data?.summary.resultCount ?? 0} hits</span>
              <span className={styles.badge}>{selectedSpace ? selectedSpace.counts.pageCount : 0} pages</span>
            </div>
          </div>
          {spacesQuery.error ? <div className={styles.error}>{errorText(spacesQuery.error)}</div> : null}
          {pagesQuery.error ? <div className={styles.error}>{errorText(pagesQuery.error)}</div> : null}
          {selectedSpace ? (
            <>
              <div className={styles.metaWrap}>{selectedSpace.canonicalPagesRoot}</div>
              <div className={styles.code}>{sourceRefPreview(selectedSpace.sourceRef) || "sourceRef unavailable"}</div>
            </>
          ) : (
            <div className={styles.emptyState}>还没有可浏览的托管 Markdown 空间。</div>
          )}
        </section>
      </div>

      <div className={styles.body}>
        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <strong>空间</strong>
            <span className={styles.badge}>{spaces.length}</span>
          </div>
          <div className={styles.list}>
            {spaces.map((space) => (
              <button
                key={space.spaceId}
                type="button"
                className={`${styles.listButton} ${space.spaceId === selectedSpaceId ? styles.listButtonActive : ""}`.trim()}
                onClick={() => {
                  setSelectedSpaceId(space.spaceId);
                  setSelectedPageId("");
                }}
              >
                <strong>{space.spaceName || space.spaceId}</strong>
                <span className={styles.metaWrap}>{space.canonicalPagesRoot}</span>
                <div className={styles.actionRow}>
                  <span className={styles.badge}>{space.counts.pageCount} pages</span>
                  <span className={styles.badge}>{space.counts.taskCount} tasks</span>
                </div>
              </button>
            ))}
            {!spaces.length ? <div className={styles.emptyState}>导入后，这里会显示受管空间。</div> : null}
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <strong>页面</strong>
            <span className={styles.badge}>{pages.length}</span>
          </div>
          <div className={styles.list}>
            {pages.map((page) => (
              <button
                key={page.pageId}
                type="button"
                className={`${styles.listButton} ${page.pageId === selectedPageId ? styles.listButtonActive : ""}`.trim()}
                onClick={() => setSelectedPageId(page.pageId)}
              >
                <strong>{page.title}</strong>
                <span className={styles.metaWrap}>{page.relativePath}</span>
                <div className={styles.actionRow}>
                  <span className={styles.badge}>{page.tags.length} tags</span>
                  <span className={styles.badge}>{page.taskCounts.total} tasks</span>
                </div>
              </button>
            ))}
            {!pages.length ? <div className={styles.emptyState}>当前筛选下没有页面。</div> : null}
          </div>
        </section>

        <section className={styles.panel}>
          <div className={styles.panelHeader}>
            <strong>页面内容与检索结果</strong>
            <div className={styles.actionRow}>
              <span className={styles.badge}>{pageQuery.data?.page?.title ? "selected" : "idle"}</span>
              <span className={styles.badge}>{searchResultsQuery.data?.results.length ?? 0}</span>
            </div>
          </div>
          <section className={styles.selectedPage}>
            {selectedPagePayload?.page ? (
              <>
                <div className={styles.header}>
                  <div>
                    <strong>{selectedPagePayload.page.title}</strong>
                    <div className={styles.metaWrap}>{selectedPagePayload.page.relativePath}</div>
                  </div>
                  <div className={styles.actionRow}>
                    <span className={styles.badge}>{selectedPagePayload.page.tags.length} tags</span>
                    <span className={styles.badge}>{selectedPagePayload.page.taskCounts.total} tasks</span>
                  </div>
                </div>
                <div className={styles.pre}>{selectedPageContent || "No content."}</div>
              </>
            ) : pageQuery.isPending ? (
              <div className={styles.emptyState}>正在读取页面...</div>
            ) : (
              <div className={styles.emptyState}>选择页面后会在这里显示托管副本正文。</div>
            )}
            {pageQuery.error ? <div className={styles.error}>{errorText(pageQuery.error)}</div> : null}
          </section>
          <div className={styles.resultList}>
            {(searchResultsQuery.data?.results ?? []).map((result: UserMarkdownSearchResult) => (
              <button
                key={result.resultId}
                type="button"
                className={styles.listButton}
                onClick={() => {
                  setSelectedSpaceId(result.spaceId);
                  setSelectedPageId(result.pageId);
                }}
              >
                <div className={styles.header}>
                  <strong>{result.title}</strong>
                  <span className={styles.badge}>#{result.rank}</span>
                </div>
                <span className={styles.metaWrap}>{result.spaceName} · {result.pageRelativePath}</span>
                <span>{result.excerpt}</span>
              </button>
            ))}
            {searchQuery.trim() && !searchResultsQuery.isPending && !(searchResultsQuery.data?.results.length ?? 0) ? (
              <div className={styles.emptyState}>
                <Search size={18} />
                没有命中当前检索词。
              </div>
            ) : null}
            {!searchQuery.trim() ? (
              <div className={styles.emptyState}>
                <FolderCog size={18} />
                输入检索词后，这里会显示 Agent 可只读引用的命中页面。
              </div>
            ) : null}
          </div>
        </section>
      </div>
    </section>
  );
}
