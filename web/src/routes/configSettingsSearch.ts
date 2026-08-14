import type { ConfigEditorMeta, ConfigEditorSection } from "../api/types";

import type { ConfigSettingsGroup, ConfigSettingsGroupId } from "./ConfigSettingsNavigation";

export type ConfigSettingsSearchHit = {
  groupId: ConfigSettingsGroupId;
  pageId: string;
  sectionId?: string;
  title: string;
  detail: string;
};

export type ConfigSettingsSearchDocument = ConfigSettingsSearchHit & {
  haystack: string;
};

function normalizeSearchText(value: string): string {
  return value.trim().toLowerCase();
}

function pageForSection(
  groups: ConfigSettingsGroup[],
  sectionId: string,
): { groupId: ConfigSettingsGroupId; pageId: string; groupTitle: string; pageTitle: string } | null {
  for (const group of groups) {
    for (const page of group.pages) {
      if (page.memberSectionIds.includes(sectionId)) {
        return { groupId: group.id, pageId: page.id, groupTitle: group.title, pageTitle: page.title };
      }
    }
  }
  return null;
}

function sectionForMetaPath(
  editorSections: ConfigEditorSection[],
  path: string,
): ConfigEditorSection | null {
  const matches = editorSections.filter((section) => path === section.path || path.startsWith(`${section.path}.`));
  if (!matches.length) return null;
  return matches.sort((left, right) => right.path.length - left.path.length)[0] ?? null;
}

export function buildConfigSettingsSearchIndex(options: {
  groups: ConfigSettingsGroup[];
  editorSections?: ConfigEditorSection[];
  editorMeta?: Record<string, ConfigEditorMeta>;
}): ConfigSettingsSearchDocument[] {
  const { groups, editorSections = [], editorMeta = {} } = options;
  const documents: ConfigSettingsSearchDocument[] = [];

  for (const group of groups) {
    documents.push({
      groupId: group.id,
      pageId: group.pages[0]?.id ?? group.id,
      title: group.title,
      detail: group.summary,
      haystack: [group.id, group.title, group.summary].join(" "),
    });
    for (const page of group.pages) {
      documents.push({
        groupId: group.id,
        pageId: page.id,
        title: page.title,
        detail: group.title,
        haystack: [page.id, page.title, page.summary, group.title, ...page.memberSectionIds].join(" "),
      });
    }
  }

  for (const section of editorSections) {
    const located = pageForSection(groups, section.id);
    if (!located) continue;
    documents.push({
      groupId: located.groupId,
      pageId: located.pageId,
      sectionId: section.id,
      title: section.title,
      detail: located.pageTitle,
      haystack: [section.id, section.path, section.title, section.summary, located.pageTitle, located.groupTitle].join(" "),
    });
  }

  for (const [path, meta] of Object.entries(editorMeta)) {
    const section = sectionForMetaPath(editorSections, path);
    const located = section ? pageForSection(groups, section.id) : null;
    if (!located) continue;
    const label = String(meta.label || path);
    const hint = String(meta.hint || "");
    documents.push({
      groupId: located.groupId,
      pageId: located.pageId,
      sectionId: section?.id,
      title: label,
      detail: located.pageTitle,
      haystack: [path, label, hint, located.pageTitle, located.groupTitle].join(" "),
    });
  }

  return documents;
}

export function searchConfigSettings(
  documents: ConfigSettingsSearchDocument[],
  query: string,
  limit = 8,
): ConfigSettingsSearchHit[] {
  const normalized = normalizeSearchText(query);
  if (!normalized) return [];
  const tokens = normalized.split(/\s+/).filter(Boolean);
  const seen = new Set<string>();
  const hits: ConfigSettingsSearchHit[] = [];
  for (const document of documents) {
    const haystack = normalizeSearchText(document.haystack);
    if (!tokens.every((token) => haystack.includes(token))) continue;
    const key = `${document.groupId}:${document.pageId}:${document.sectionId ?? ""}:${document.title}`;
    if (seen.has(key)) continue;
    seen.add(key);
    hits.push({
      groupId: document.groupId,
      pageId: document.pageId,
      sectionId: document.sectionId,
      title: document.title,
      detail: document.detail,
    });
    if (hits.length >= limit) break;
  }
  return hits;
}
