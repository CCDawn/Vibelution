import type { ChatRoomDetail, Team } from "../../api/types";

export function buildLinkedTeamRoomIds(teams: readonly Team[]): Set<string> {
  const ids = new Set<string>();
  for (const team of teams) {
    const roomId = String(team.linkedChatRoomId || team.linkedChatRoom?.roomId || "").trim();
    if (roomId) {
      ids.add(roomId);
    }
  }
  return ids;
}

export function resolveActiveGroupTeam(
  teams: readonly Team[],
  activeGroupRoom: ChatRoomDetail | null | undefined,
  activeGroupRoomId: string,
): Team | null {
  const roomId = String(activeGroupRoom?.roomId || activeGroupRoomId || "").trim();
  const configTeamId = String((activeGroupRoom?.config ?? {}).teamId ?? "").trim();
  return teams.find((team) => {
    const teamId = String(team.teamId ?? "").trim();
    const linkedRoomId = String(team.linkedChatRoomId ?? team.linkedChatRoom?.roomId ?? "").trim();
    return (configTeamId && teamId === configTeamId) || (roomId && linkedRoomId === roomId);
  }) ?? null;
}
