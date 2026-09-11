import type { ConversationIndexGroup } from "../conversationIndexModel";

/**
 * Tree-side group rooms. Team groups owned by the Agent directory team blocks
 * are excluded: the directory owns the linked room plus the folded history, so
 * rendering the same team here only duplicated team identity. Team groups for
 * teams without a directory block stay visible so their rooms remain reachable.
 */
export function buildGroupedGroupConversations(
  groupedConversations: readonly ConversationIndexGroup[],
  directoryTeamIds: ReadonlySet<string> = new Set<string>(),
): ConversationIndexGroup[] {
  return groupedConversations
    .filter((group) => {
      if (group.groupKind !== "team") return true;
      const teamId = String(group.teamId || "").trim();
      return !teamId || !directoryTeamIds.has(teamId);
    })
    .map((group) => ({
      ...group,
      items: group.items.filter((conversation) => conversation.type === "group_room"),
    }))
    .filter((group) => group.items.length > 0);
}

export function countGroupedGroupConversations(groups: readonly ConversationIndexGroup[]): number {
  return groups.reduce((count, group) => count + group.items.length, 0);
}
