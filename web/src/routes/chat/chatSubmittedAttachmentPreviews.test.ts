/** @vitest-environment happy-dom */
import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail } from "../../api/types";
import { appendOptimisticUserMessage } from "../chatSessionState";
import { createSubmittedAttachmentPreviews } from "./chatSubmittedAttachmentPreviews";

afterEach(() => vi.restoreAllMocks());

describe("submitted attachment preview leases", () => {
  it("keeps previews through unrelated updates and releases them when the session cache is removed", () => {
    const client = new QueryClient();
    client.setQueryData(queryKeys.session("s1"), { id: "s1", messages: [] });
    const revoke = vi.spyOn(URL, "revokeObjectURL");
    const file = new File(["bytes"], "image.png", { type: "image/png" });
    const attachments = createSubmittedAttachmentPreviews(client, "s1", "submit-1", [{ id: "a1", file, filename: file.name, previewUrl: "blob:composer", contentType: file.type, sizeBytes: file.size, kind: "image" }]);
    client.setQueryData<SessionDetail>(queryKeys.session("s1"), (detail) => appendOptimisticUserMessage(detail, { sessionId: "s1", clientSubmissionId: "submit-1", content: "", attachments }));
    client.setQueryData(queryKeys.session("s2"), { id: "s2", messages: [] });
    client.removeQueries({ queryKey: queryKeys.session("s2") });
    expect(revoke).not.toHaveBeenCalledWith(attachments[0].url);
    client.removeQueries({ queryKey: queryKeys.session("s1") });
    expect(revoke).toHaveBeenCalledExactlyOnceWith(attachments[0].url);
    client.clear();
  });
});
