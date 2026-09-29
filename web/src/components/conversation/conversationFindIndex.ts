/**
 * 对话内全文搜索索引 —— 纯函数内核（Find in transcript，ZCode parity）。
 *
 * 覆盖三类文本（用户拍板的全量口径）：
 * - user       用户输入（UserConversationMessage.content）
 * - assistant  助手正文（turnItems 的 agent_message 文本）
 * - reasoning  思考文本（turnItems 的 reasoning 文本）
 *
 * 匹配语义：大小写不敏感的纯子串（toLocaleLowerCase 后 indexOf）。
 * 增量友好：调用方持有一个按消息 id 缓存的 ConversationFindIndexCache；
 * 稳定消息通过「角色 + turnItem id@revision 签名」直接复用上次的命中列表，
 * 流式更新只让真正变化的消息重新扫描（turnItem revision 变化 → 签名变化）。
 * 流式中的在途 assistant turn 不入索引，settled 后随签名变化自然入索引。
 *
 * DOM 无关：本模块不做任何 DOM 操作；高亮/滚动见 conversationFindHighlightDom。
 */
import type { ConversationMessage } from "../../api/types";
import { assistantTurnIsInFlight } from "../../routes/chatTurnProtocol";

export type ConversationFindSegmentKind = "user" | "assistant" | "reasoning";

export type ConversationFindSegment = {
  kind: ConversationFindSegmentKind;
  text: string;
};

export type ConversationFindMatch = {
  /** 命中在本次索引内的全局序号（与 matches 数组下标一致）。 */
  globalIndex: number;
  /** 命中所在消息 id（与行 DOM 的 data-conversation-message-id 对应）。 */
  messageId: string;
  /** 消息在 activeTimelineMessages 中的序号；历史消息即 virtualizer 行号。 */
  messageOrder: number;
  kind: ConversationFindSegmentKind;
  /** 同一消息行内的命中序号（0 起），用于行内多次命中导航。 */
  matchIndexInRow: number;
  start: number;
  end: number;
  /** 命中前后的文本片段上下文（带省略号），供无障碍/调试展示。 */
  context: string;
};

export type ConversationFindIndex = {
  /** 归一化后的查询串（trim + toLocaleLowerCase）。 */
  query: string;
  matches: ConversationFindMatch[];
  matchCount: number;
  /** 至少含一个命中的消息行数。 */
  matchedRowCount: number;
};

/** 每消息缓存的条目：签名 + 不带 globalIndex/messageOrder 的命中列表（重建时重新编号）。 */
type CachedConversationFindMessage = {
  signature: string;
  matches: Array<Omit<ConversationFindMatch, "globalIndex" | "messageOrder">>;
};

/** 调用方持有的按消息 id 缓存（跨增量重建复用；测试可直接观测）。 */
export type ConversationFindIndexCache = Map<string, CachedConversationFindMessage>;

export function createConversationFindIndexCache(): ConversationFindIndexCache {
  return new Map<string, CachedConversationFindMessage>();
}

/** 缓存上限：超限整体清空（消息 id 不可枚举回收，简单截断防无界增长）。 */
const CONVERSATION_FIND_CACHE_LIMIT = 2000;

/** 命中上下文的半径（前后各保留的字符数）。 */
const CONVERSATION_FIND_CONTEXT_RADIUS = 36;

export function normalizeConversationFindQuery(query: string): string {
  return String(query ?? "").trim().toLocaleLowerCase();
}

/**
 * 提取一条消息的可搜索文本段（顺序即阅读顺序）。
 * 在途 assistant turn（pending/running 且无终态产物）返回空列表 —— 流式中的
 * 最后一条消息不入索引，settled 后 turnItems 签名变化自然进入下一轮索引。
 */
export function collectConversationFindSegments(message: ConversationMessage): ConversationFindSegment[] {
  if (message.role === "user") {
    const content = String(message.content ?? "");
    return content.trim() ? [{ kind: "user", text: content }] : [];
  }
  if (assistantTurnIsInFlight(message)) {
    return [];
  }
  const segments: ConversationFindSegment[] = [];
  for (const item of message.turnItems) {
    if (item.type === "agent_message") {
      const text = String(item.text ?? "");
      if (text.trim()) {
        segments.push({ kind: "assistant", text });
      }
    } else if (item.type === "reasoning") {
      const text = String(item.text ?? "");
      if (text.trim()) {
        segments.push({ kind: "reasoning", text });
      }
    }
  }
  return segments;
}

/**
 * 消息内容签名：稳定消息（文本未变）跨重建保持一致，命中列表可复用。
 * assistant 用 turnItem id@revision（revision 变化即文本变化），用户消息用正文。
 */
export function buildConversationFindMessageSignature(message: ConversationMessage): string {
  if (message.role === "user") {
    return `user\u0000${message.id}\u0000${String(message.content ?? "")}`;
  }
  const parts: string[] = [];
  for (const item of message.turnItems) {
    if (item.type !== "agent_message" && item.type !== "reasoning") {
      continue;
    }
    parts.push(`${item.id}@${item.revision}`);
  }
  return `assistant\u0000${message.id}\u0000${parts.join(",")}`;
}

function buildMatchContext(text: string, start: number, end: number): string {
  const from = Math.max(0, start - CONVERSATION_FIND_CONTEXT_RADIUS);
  const to = Math.min(text.length, end + CONVERSATION_FIND_CONTEXT_RADIUS);
  const body = text.slice(from, to).replace(/\s+/gu, " ").trim();
  const prefix = from > 0 ? "…" : "";
  const suffix = to < text.length ? "…" : "";
  return `${prefix}${body}${suffix}`;
}

/** 扫描单条消息：大小写不敏感纯子串，段内多次命中全部收录。 */
function scanConversationFindMessage(
  message: ConversationMessage,
  normalizedQuery: string,
): Array<Omit<ConversationFindMatch, "globalIndex" | "messageOrder">> {
  const messageId = message.id;
  const rowMatches: Array<Omit<ConversationFindMatch, "globalIndex" | "messageOrder">> = [];
  let matchIndexInRow = 0;
  for (const segment of collectConversationFindSegments(message)) {
    const normalizedText = segment.text.toLocaleLowerCase();
    let searchStart = 0;
    while (searchStart < normalizedText.length) {
      const foundAt = normalizedText.indexOf(normalizedQuery, searchStart);
      if (foundAt === -1) {
        break;
      }
      const end = foundAt + normalizedQuery.length;
      rowMatches.push({
        messageId,
        kind: segment.kind,
        matchIndexInRow,
        start: foundAt,
        end,
        context: buildMatchContext(segment.text, foundAt, end),
      });
      matchIndexInRow += 1;
      searchStart = end;
    }
  }
  return rowMatches;
}

export type BuildConversationFindIndexOptions = {
  /** 调用方持有的增量缓存；缺省每次全量扫描。 */
  cache?: ConversationFindIndexCache;
  /** 每消息扫描回调：reused=true 表示签名命中缓存，未重新扫描文本。 */
  onMessageScan?: (messageId: string, reused: boolean) => void;
};

/**
 * 从消息列表构建命中索引。顺序：消息序（messageOrder）× 段序 × 段内出现序，
 * 与转录阅读顺序一致，prev/next 导航自然沿时间轴走。
 */
export function buildConversationFindIndex(
  messages: readonly ConversationMessage[],
  query: string,
  options: BuildConversationFindIndexOptions = {},
): ConversationFindIndex {
  const normalizedQuery = normalizeConversationFindQuery(query);
  if (!normalizedQuery) {
    return { query: normalizedQuery, matches: [], matchCount: 0, matchedRowCount: 0 };
  }
  const cache = options.cache;
  if (cache && cache.size > CONVERSATION_FIND_CACHE_LIMIT) {
    cache.clear();
  }

  const matches: ConversationFindMatch[] = [];
  const matchedRowIds = new Set<string>();
  for (let order = 0; order < messages.length; order += 1) {
    const message = messages[order];
    if (!message) {
      continue;
    }
    const messageId = message.id;
    let rowMatches: Array<Omit<ConversationFindMatch, "globalIndex" | "messageOrder">> | undefined;
    let reused = false;
    if (cache) {
      const signature = buildConversationFindMessageSignature(message);
      const cached = cache.get(messageId);
      if (cached && cached.signature === signature) {
        rowMatches = cached.matches;
        reused = true;
      } else {
        rowMatches = scanConversationFindMessage(message, normalizedQuery);
        cache.set(messageId, { signature, matches: rowMatches });
      }
    } else {
      rowMatches = scanConversationFindMessage(message, normalizedQuery);
    }
    options.onMessageScan?.(messageId, reused);
    if (!rowMatches.length) {
      continue;
    }
    matchedRowIds.add(messageId);
    for (const rowMatch of rowMatches) {
      // messageOrder/globalIndex 每次构建重新盖章：前插/增删后缓存命中也不漂移。
      matches.push({ ...rowMatch, messageOrder: order, globalIndex: matches.length });
    }
  }

  return {
    query: normalizedQuery,
    matches,
    matchCount: matches.length,
    matchedRowCount: matchedRowIds.size,
  };
}

/**
 * 解析生效的当前命中序号：0 命中 → -1；越界偏好 → 首个命中；否则保持偏好。
 */
export function resolveConversationFindActiveIndex(matchCount: number, preferred: number): number {
  if (matchCount <= 0) {
    return -1;
  }
  if (preferred >= 0 && preferred < matchCount) {
    return preferred;
  }
  return 0;
}

/**
 * prev/next 环回导航：最后一个 → 第一个，第一个 → 最后一个。
 * 0 命中时维持 -1。
 */
export function stepConversationFindActiveIndex(
  current: number,
  delta: 1 | -1,
  matchCount: number,
): number {
  if (matchCount <= 0) {
    return -1;
  }
  if (current < 0 || current >= matchCount) {
    return delta === 1 ? 0 : matchCount - 1;
  }
  return (current + delta + matchCount) % matchCount;
}

/** 跳转策略：历史虚拟行走 virtualizer.scrollToIndex；在途尾部钉到底部。 */
export function resolveConversationFindJumpPlan(
  messageOrder: number,
  liveTailStartIndex: number,
): "virtual" | "liveTail" {
  return messageOrder < liveTailStartIndex ? "virtual" : "liveTail";
}
