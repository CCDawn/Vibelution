import {
  useEffect,
  useMemo,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

import type { ChatRoomDetail, SessionSummary } from "../../api/types";

export type UseChatGroupDraftStateResult = {
  groupComposerOpen: boolean;
  setGroupComposerOpen: Dispatch<SetStateAction<boolean>>;
  groupTitleDraft: string;
  setGroupTitleDraft: Dispatch<SetStateAction<string>>;
  groupModeDraft: string;
  setGroupModeDraft: Dispatch<SetStateAction<string>>;
  groupPurposeDraft: string;
  setGroupPurposeDraft: Dispatch<SetStateAction<string>>;
  groupSelectedAgentIds: string[];
  setGroupSelectedAgentIds: Dispatch<SetStateAction<string[]>>;
  groupTopicDraft: string;
  setGroupTopicDraft: Dispatch<SetStateAction<string>>;
  projectBusDraft: string;
  setProjectBusDraft: Dispatch<SetStateAction<string>>;
  projectBusInterruptTargets: boolean;
  setProjectBusInterruptTargets: Dispatch<SetStateAction<boolean>>;
  groupRoomActionError: string;
  setGroupRoomActionError: Dispatch<SetStateAction<string>>;
  groupManageTitleDraft: string;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  groupManageSessionIds: string[];
  setGroupManageSessionIds: Dispatch<SetStateAction<string[]>>;
  groupManageModeDraft: string;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  groupManagePurposeDraft: string;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
  groupManageSessionSet: Set<string>;
};

/**
 * Group composer / manage / project-bus draft fields.
 * Called before catalog queries because `groupComposerOpen` gates teams polling.
 * Room → manage-draft sync is `useSyncChatGroupManageDrafts` after room/session data exists.
 */
export function useChatGroupDraftState(): UseChatGroupDraftStateResult {
  const [groupComposerOpen, setGroupComposerOpen] = useState(false);
  const [groupTitleDraft, setGroupTitleDraft] = useState("");
  const [groupModeDraft, setGroupModeDraft] = useState("round_robin");
  const [groupPurposeDraft, setGroupPurposeDraft] = useState("discussion");
  const [groupSelectedAgentIds, setGroupSelectedAgentIds] = useState<string[]>([]);
  const [groupTopicDraft, setGroupTopicDraft] = useState("");
  const [projectBusDraft, setProjectBusDraft] = useState("");
  const [projectBusInterruptTargets, setProjectBusInterruptTargets] = useState(false);
  const [groupRoomActionError, setGroupRoomActionError] = useState("");
  const [groupManageTitleDraft, setGroupManageTitleDraft] = useState("");
  const [groupManageSessionIds, setGroupManageSessionIds] = useState<string[]>([]);
  const [groupManageModeDraft, setGroupManageModeDraft] = useState("round_robin");
  const [groupManagePurposeDraft, setGroupManagePurposeDraft] = useState("discussion");
  const groupManageSessionSet = useMemo(() => new Set(groupManageSessionIds), [groupManageSessionIds]);

  return {
    groupComposerOpen,
    setGroupComposerOpen,
    groupTitleDraft,
    setGroupTitleDraft,
    groupModeDraft,
    setGroupModeDraft,
    groupPurposeDraft,
    setGroupPurposeDraft,
    groupSelectedAgentIds,
    setGroupSelectedAgentIds,
    groupTopicDraft,
    setGroupTopicDraft,
    projectBusDraft,
    setProjectBusDraft,
    projectBusInterruptTargets,
    setProjectBusInterruptTargets,
    groupRoomActionError,
    setGroupRoomActionError,
    groupManageTitleDraft,
    setGroupManageTitleDraft,
    groupManageSessionIds,
    setGroupManageSessionIds,
    groupManageModeDraft,
    setGroupManageModeDraft,
    groupManagePurposeDraft,
    setGroupManagePurposeDraft,
    groupManageSessionSet,
  };
}

export type UseSyncChatGroupManageDraftsOptions = {
  activeGroupRoom: ChatRoomDetail | null | undefined;
  sessions: Array<Pick<SessionSummary, "id">> | undefined;
  setGroupManageSessionIds: Dispatch<SetStateAction<string[]>>;
  setGroupManageTitleDraft: Dispatch<SetStateAction<string>>;
  setGroupManageModeDraft: Dispatch<SetStateAction<string>>;
  setGroupManagePurposeDraft: Dispatch<SetStateAction<string>>;
};

/** Copy the active room's title/mode/purpose/members into manage drafts. */
export function useSyncChatGroupManageDrafts({
  activeGroupRoom,
  sessions,
  setGroupManageSessionIds,
  setGroupManageTitleDraft,
  setGroupManageModeDraft,
  setGroupManagePurposeDraft,
}: UseSyncChatGroupManageDraftsOptions): void {
  useEffect(() => {
    if (!activeGroupRoom) {
      return;
    }
    const existingSessionIds = new Set((sessions ?? []).map((session) => session.id));
    setGroupManageSessionIds(
      activeGroupRoom.participants
        .map((participant) => participant.sessionId)
        .filter((sessionId) => existingSessionIds.has(sessionId)),
    );
    setGroupManageTitleDraft(activeGroupRoom.title || "");
    setGroupManageModeDraft(activeGroupRoom.mode || "round_robin");
    setGroupManagePurposeDraft(activeGroupRoom.purpose || "discussion");
  }, [
    activeGroupRoom,
    sessions,
    setGroupManageModeDraft,
    setGroupManagePurposeDraft,
    setGroupManageSessionIds,
    setGroupManageTitleDraft,
  ]);
}
