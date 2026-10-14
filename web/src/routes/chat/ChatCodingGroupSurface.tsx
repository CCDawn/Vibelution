/**
 * Group / project-bus center surface, including the room plus menu.
 * Lazy so the direct-chat first paint does not pull the group graph.
 */
import { lazy } from "react";

import type { Team } from "../../api/types";
import { ChatComposerPlusMenu } from "./ChatComposerPlusMenu";
import type { ChatGroupCenterSurfaceProps } from "./ChatGroupCenterSurface";

const ChatGroupCenterSurface = lazy(() =>
  import("./ChatGroupCenterSurface").then((module) => ({ default: module.ChatGroupCenterSurface })),
);

export type ChatCodingGroupSurfaceProps = Omit<
  ChatGroupCenterSurfaceProps,
  "composerLeadingControl" | "userDisplayName" | "onOpenGroupTeam" | "artifactTeamId"
> & {
  runtimeUserName?: string | null;
  mentalModelEnabled: boolean;
  runtimeStatusEnabled: boolean;
  promptSuggestionEnabled: boolean;
  onMentalModelEnabledChange: (enabled: boolean) => void;
  onRuntimeStatusEnabledChange: (enabled: boolean) => void;
  onPromptSuggestionEnabledChange: (enabled: boolean) => void;
  chatReturnTarget: string | null;
  activeGroupTeam: Team | null | undefined;
  activeGroupTeamOwned: boolean;
  onManageGroupRoom: () => void;
  onNavigateTeam: (teamId: string) => void;
};

export function ChatCodingGroupSurface({
  runtimeUserName,
  mentalModelEnabled,
  runtimeStatusEnabled,
  promptSuggestionEnabled,
  onMentalModelEnabledChange,
  onRuntimeStatusEnabledChange,
  onPromptSuggestionEnabledChange,
  chatReturnTarget,
  activeGroupTeam,
  activeGroupTeamOwned,
  onNavigateTeam,
  onManageGroupRoom,
  lang,
  standardGroupRoomActive,
  activeGroupRoom,
  ...surfaceProps
}: ChatCodingGroupSurfaceProps) {
  const userDisplayName = runtimeUserName || (lang === "zh" ? "我" : "Me");
  const artifactTeamId = activeGroupTeamOwned ? activeGroupTeam?.teamId : undefined;
  const onOpenGroupTeam = !chatReturnTarget && activeGroupTeam
    ? () => onNavigateTeam(activeGroupTeam.teamId)
    : undefined;
  const composerLeadingControl = standardGroupRoomActive && activeGroupRoom ? (
    <ChatComposerPlusMenu
      lang={lang}
      showAddReference={false}
      showCapabilities={false}
      attachmentDisabled
      sessionReferences={[]}
      mentalModelEnabled={mentalModelEnabled}
      runtimeStatusEnabled={runtimeStatusEnabled}
      promptSuggestionEnabled={promptSuggestionEnabled}
      capabilityDisabled
      onMentalModelEnabledChange={onMentalModelEnabledChange}
      onRuntimeStatusEnabledChange={onRuntimeStatusEnabledChange}
      onPromptSuggestionEnabledChange={onPromptSuggestionEnabledChange}
      group={{
        title: activeGroupRoom.title,
        onManage: onManageGroupRoom,
        teamId: activeGroupTeamOwned ? activeGroupTeam?.teamId : undefined,
        onOpenTeam: activeGroupTeamOwned && activeGroupTeam
          ? () => onNavigateTeam(activeGroupTeam.teamId)
          : undefined,
      }}
    />
  ) : undefined;

  return (
    <ChatGroupCenterSurface
      {...surfaceProps}
      lang={lang}
      standardGroupRoomActive={standardGroupRoomActive}
      activeGroupRoom={activeGroupRoom}
      onManageGroupRoom={onManageGroupRoom}
      userDisplayName={userDisplayName}
      onOpenGroupTeam={onOpenGroupTeam}
      artifactTeamId={artifactTeamId}
      composerLeadingControl={composerLeadingControl}
    />
  );
}
