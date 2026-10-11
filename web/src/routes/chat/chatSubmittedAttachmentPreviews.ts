import type { QueryClient } from "@tanstack/react-query";
import type { ConversationAttachment, SessionDetail } from "../../api/types";
import { queryKeys } from "../../api/queryKeys";
import type { ComposerImageAttachment } from "./chatComposerSubmitModel";

// Message previews have their own URL lease: clearing or switching the composer
// must not invalidate an optimistic message still held in the session cache.
const owners = new WeakMap<QueryClient, Map<string, { sessionId: string; urls: string[] }>>();

export function createSubmittedAttachmentPreviews(
  client: QueryClient,
  sessionId: string,
  submissionId: string,
  attachments: readonly ComposerImageAttachment[],
): ConversationAttachment[] {
  if (!attachments.length || !client.getQueryData(queryKeys.session(sessionId))) return [];
  let leases = owners.get(client);
  if (!leases) {
    leases = new Map();
    owners.set(client, leases);
    const owned = leases;
    client.getQueryCache().subscribe((event) => {
      if (event.type !== "updated" && event.type !== "removed") return;
      for (const [id, lease] of owned) {
        const key = queryKeys.session(lease.sessionId);
        if (event.query.queryKey.length !== key.length || key.some((part, index) => part !== event.query.queryKey[index])) continue;
        const detail = client.getQueryData<SessionDetail>(queryKeys.session(lease.sessionId));
        const inUse = detail?.messages.some((message) =>
          message.role === "user"
          && message.metadata?.clientSubmissionId === id
          && message.attachments?.some((attachment) => lease.urls.includes(attachment.url)),
        );
        if (inUse) continue;
        lease.urls.forEach((url) => URL.revokeObjectURL(url));
        owned.delete(id);
      }
    });
  }
  const urls: string[] = [];
  try {
    const previews = attachments.map((attachment): ConversationAttachment => {
      const url = URL.createObjectURL(attachment.file);
      urls.push(url);
      return {
        artifactId: `local-${submissionId}-${attachment.id}`,
        filename: attachment.filename,
        url,
        imageUrl: attachment.kind === "image" ? url : "",
        downloadUrl: url,
        contentType: attachment.contentType,
        sizeBytes: attachment.sizeBytes,
        kind: attachment.kind === "image" ? "user_image" : "user_document",
        status: "pending",
      };
    });
    leases.set(submissionId, { sessionId, urls });
    return previews;
  } catch (error) {
    urls.forEach((url) => URL.revokeObjectURL(url));
    throw error;
  }
}
