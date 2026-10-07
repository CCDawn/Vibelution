import { describe, expect, it } from "vitest";

import {
  clearSessionCreateAttempt,
  markSessionCreateAttempt,
  resetSessionCreateAttemptsForTests,
  sessionCreateAttemptState,
  tempSessionSendBlockedMessage,
} from "./sessionCreateAttempt";

describe("sessionCreateAttempt", () => {
  it("keeps the waiting copy until the create has failed", () => {
    resetSessionCreateAttemptsForTests();
    expect(tempSessionSendBlockedMessage(undefined, "zh")).toBe("新会话正在创建，请稍候再发送。");
    markSessionCreateAttempt("temp-session-a", "pending");
    expect(sessionCreateAttemptState("temp-session-a")).toBe("pending");
    expect(tempSessionSendBlockedMessage("pending", "zh")).toBe("新会话正在创建，请稍候再发送。");
    markSessionCreateAttempt("temp-session-a", "failed");
    expect(tempSessionSendBlockedMessage(sessionCreateAttemptState("temp-session-a"), "zh")).toBe(
      "会话还没创建成功。请再点一次新建会话，这段草稿会保留。",
    );
    clearSessionCreateAttempt("temp-session-a");
    expect(sessionCreateAttemptState("temp-session-a")).toBeUndefined();
  });
});
