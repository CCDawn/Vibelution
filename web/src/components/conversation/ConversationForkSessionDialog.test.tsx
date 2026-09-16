import { describe, expect, it } from "vitest";

import dialogSource from "./ConversationForkSessionDialog.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";

describe("ConversationForkSessionDialog", () => {
  it("composes VConfirmDialog and VSelect without a hand-rolled overlay", () => {
    expect(dialogSource).toContain("<VConfirmDialog");
    expect(dialogSource).toContain("<VSelect");
    expect(dialogSource).not.toContain("createPortal");
    expect(dialogSource).not.toContain("fixed inset-0");
    expect(dialogSource).toContain("onOpenChange=");
  });

  it("wires both fork scopes and the pending confirm state", () => {
    expect(dialogSource).toContain('"visible_path"');
    expect(dialogSource).toContain('"with_branches"');
    expect(dialogSource).toContain("labels.scopeVisiblePath");
    expect(dialogSource).toContain("labels.scopeWithBranches");
    expect(dialogSource).toContain("labels.pending");
    expect(dialogSource).toContain("confirmPending={pending}");
    // While pending the dialog must not close via backdrop/cancel paths.
    expect(dialogSource).toContain("!nextOpen && !pending");
    expect(dialogSource).toContain("!pending");
  });

  it("stays mounted from ConversationView with route-owned confirm flow", () => {
    expect(conversationViewSource).toContain('from "./ConversationForkSessionDialog"');
    expect(conversationViewSource).toContain("<ConversationForkSessionDialog");
    expect(conversationViewSource).toContain("onForkSessionFromNode");
    // Confirm executes through the route handler; failures keep the dialog open.
    expect(conversationViewSource).toContain("Promise.resolve(onForkSessionFromNode(message, forkScope))");
  });
});
