import { describe, expect, it } from "vitest";

import { COMPOSER_SESSION_REFERENCE_MIME } from "./conversationConstants";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  extractComposerImageDropFiles,
  extractComposerSessionReferenceDrop,
  hasComposerImageDragPayload,
  hasComposerSessionReferenceDragPayload,
} from "./conversationComposerDropPayload";

describe("conversation composer drop payload", () => {
  it("keeps composer drop helpers outside the React component file", () => {
    expect(conversationViewSource).toContain("from \"./conversationComposerDropPayload\"");
    expect(conversationViewSource).not.toContain("export { COMPOSER_SESSION_REFERENCE_MIME } from \"./conversationConstants\"");
    expect(conversationViewSource).not.toContain("export function extractComposerImageDropFiles");
    expect(conversationViewSource).not.toContain("export function hasComposerImageDragPayload");
    expect(conversationViewSource).not.toContain("export function extractComposerSessionReferenceDrop");
    expect(conversationViewSource).not.toContain("export function hasComposerSessionReferenceDragPayload");
    expect(conversationViewSource).not.toContain("type ComposerDragData =");
  });

  it("filters composer drag payloads down to image files", () => {
    const png = { name: "sketch.png", type: "image/png" } as File;
    const text = { name: "notes.txt", type: "text/plain" } as File;

    expect(extractComposerImageDropFiles({ files: [png, text] })).toEqual([png]);
    expect(
      hasComposerImageDragPayload({
        items: [
          { kind: "file", type: "text/plain" } as DataTransferItem,
          { kind: "file", type: "image/webp" } as DataTransferItem,
        ],
      }),
    ).toBe(true);
    expect(hasComposerImageDragPayload({ files: [text] })).toBe(false);
  });

  it("extracts structured session reference drag payloads", () => {
    const payload = {
      referenceId: "session:ref-1",
      kind: "session",
      sessionId: "ref-1",
      title: "Reference session",
    };

    const reference = extractComposerSessionReferenceDrop({
      types: [COMPOSER_SESSION_REFERENCE_MIME],
      getData: (format) => (format === COMPOSER_SESSION_REFERENCE_MIME ? JSON.stringify(payload) : ""),
    });

    expect(reference?.sessionId).toBe("ref-1");
    expect(reference?.referenceId).toBe("session:ref-1");
    expect(reference?.title).toBe("Reference session");
  });

  it("detects session references only when the drag payload has a valid session id", () => {
    expect(hasComposerSessionReferenceDragPayload({
      types: [COMPOSER_SESSION_REFERENCE_MIME],
      getData: () => JSON.stringify({ sessionId: "session-1" }),
    })).toBe(true);

    expect(hasComposerSessionReferenceDragPayload({
      types: [COMPOSER_SESSION_REFERENCE_MIME],
      getData: () => JSON.stringify({ sessionId: " " }),
    })).toBe(false);

    expect(hasComposerSessionReferenceDragPayload({
      types: [COMPOSER_SESSION_REFERENCE_MIME],
      getData: () => "{",
    })).toBe(false);
  });
});
