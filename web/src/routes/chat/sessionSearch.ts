/**
 * Session search ranking.
 *
 * Shape borrowed from ZCode's side-pane tab search
 * (zai-org/ZCode @ 872ad960, packages/ui/src/app-shell/sidePaneTabSearch.ts and
 * sidePaneTabPresentation.ts): every entry exposes a small set of named text
 * fields, ids are part of the searchable surface, and matches are scored by
 * field with the strongest intent first.
 *
 * Reuse boundary: the ranking idea only. Weights, field names and API are ours;
 * no upstream code is copied. Callers own visibility rules — this module never
 * decides which sessions a user may see (ACL, archived, agent scope stay with the
 * owning surface).
 *
 * Why ids are searchable: during incident triage the only thing at hand is often
 * a session id copied from a log line or journal. Title-only search cannot find
 * it, which is the single most expensive miss in a long conversation list.
 */

export type SessionSearchFields = {
  /** Lowercased session title. */
  title: string;
  /** Lowercased session id — exact or prefix match means "you pasted an id". */
  id: string;
  /** Lowercased human label of the owning agent (empty when unknown). */
  agent: string;
  /** Lowercased free-form keywords (model name, workspace, branch, ...). */
  keywords: string;
};

export type SessionSearchTarget = {
  id: string;
  title: string;
  agentLabel?: string;
  keywords?: readonly string[];
};

export type SessionSearchScored<T> = {
  item: T;
  score: number;
  /** Original index, used to keep ranking stable when scores tie. */
  index: number;
};

/** Query split on whitespace; empty entries dropped. */
export function splitSearchQuery(query: string): string[] {
  return normalizeSearchText(query).split(/\s+/).filter(Boolean);
}

export function normalizeSearchText(value: string): string {
  return String(value ?? "").trim().toLowerCase();
}

/** Word boundary split shared by prefix scoring: `fix: chat/rail_v2` -> 4 words. */
function splitWords(value: string): string[] {
  return value.split(/[\s/_.:-]+/).filter(Boolean);
}

export function buildSessionSearchFields(target: SessionSearchTarget): SessionSearchFields {
  return {
    title: normalizeSearchText(target.title),
    id: normalizeSearchText(target.id),
    agent: normalizeSearchText(target.agentLabel ?? ""),
    keywords: normalizeSearchText((target.keywords ?? []).join(" ")),
  };
}

/**
 * Score one query term against one entry. Every field is optional; a term that
 * matches nothing scores 0 and the caller drops the entry (AND semantics).
 */
export function scoreSearchTerm(fields: SessionSearchFields, term: string): number {
  if (!term) {
    return 0;
  }
  if (fields.id === term) {
    return 200;
  }
  if (fields.id.startsWith(term)) {
    return 160;
  }
  if (fields.title.startsWith(term)) {
    return 120;
  }
  if (splitWords(fields.title).some((word) => word.startsWith(term))) {
    return 90;
  }
  if (fields.title.includes(term)) {
    return 70;
  }
  if (fields.keywords.includes(term)) {
    return 40;
  }
  if (fields.agent.includes(term)) {
    return 30;
  }
  if (fields.id.includes(term)) {
    return 20;
  }
  return 0;
}

export function buildSearchFields(target: SessionSearchTarget): SessionSearchFields {
  return buildSessionSearchFields(target);
}

/**
 * Rank entries against a query. Empty query returns the input order untouched so
 * callers can fall back to their own default ordering (pinned, recent, manual).
 */
export function rankSessionSearch<T extends SessionSearchTarget>(
  items: readonly T[],
  query: string,
): T[] {
  const terms = splitSearchQuery(query);
  if (!terms.length) {
    return [...items];
  }
  const scored: SessionSearchScored<T>[] = [];
  items.forEach((item, index) => {
    const fields = buildSessionSearchFields(item);
    let total = 0;
    for (const term of terms) {
      const score = scoreSearchTerm(fields, term);
      if (!score) {
        return;
      }
      total += score;
    }
    scored.push({ item, score: total, index });
  });
  scored.sort((left, right) => right.score - left.score || left.index - right.index);
  return scored.map((entry) => entry.item);
}

/**
 * Order already-filtered results by relevance without dropping anything.
 *
 * The index panel filters on fields this module does not model (teams, group
 * rooms, folder labels), so a second filter pass would silently hide rows that
 * the panel deliberately kept. Unmatched targets keep their incoming order and
 * sink below every match; equal scores stay stable.
 */
export function orderSessionSearchResults<T extends SessionSearchTarget>(
  targets: readonly T[],
  query: string,
): T[] {
  const folders = targets.map((target, index) => ({
    target,
    index,
    fields: buildSessionSearchFields(target),
  }));
  const terms = splitSearchQuery(query);
  if (!terms.length) {
    return [...targets];
  }
  const ranked = folders.map((entry) => ({
    index: entry.index,
    score: terms.reduce((total, term) => total + scoreSearchTerm(entry.fields, term), 0),
  }));
  ranked.sort((left, right) => right.score - left.score || left.index - right.index);
  return ranked.map((entry) => targets[entry.index]);
}
