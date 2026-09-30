import type { ConversationMessage } from "../../api/types";
import { conversationChangedFilesFromMetadata } from "../../components/conversation/conversationFileDeliveryModel";
import { editMessageTurnId } from "./chatEditResubmitState";

/** Turns whose disk-truth files can be restored before a chat rerun, oldest first. */
export type RerunFileRestorePlan = {
  turnIds: string[];
  paths: string[];
};

/**
 * Files the loaded tail will replace.
 * A turn counts only when `metadata.changedFiles` has a path and the message
 * has a turn id. Partial windows are the caller's limit: this does not fetch.
 */
export function rerunFileRestorePlan(
  messages: readonly ConversationMessage[],
  startIndex: number,
): RerunFileRestorePlan {
  if (!Number.isInteger(startIndex) || startIndex < 0) {
    return { turnIds: [], paths: [] };
  }
  const turnIds: string[] = [];
  const paths: string[] = [];
  const seenTurns = new Set<string>();
  const seenPaths = new Set<string>();
  for (let index = startIndex; index < messages.length; index += 1) {
    const message = messages[index];
    if (!message) continue;
    const files = conversationChangedFilesFromMetadata(message.metadata);
    if (files.length === 0) continue;
    const turnId = editMessageTurnId(message);
    if (!turnId) continue;
    if (!seenTurns.has(turnId)) {
      seenTurns.add(turnId);
      turnIds.push(turnId);
    }
    for (const file of files) {
      if (seenPaths.has(file.path)) continue;
      seenPaths.add(file.path);
      paths.push(file.path);
    }
  }
  return { turnIds, paths };
}
