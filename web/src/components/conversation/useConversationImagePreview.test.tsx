// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";
import conversationViewSource from "./ConversationView.tsx?raw";
import hookSource from "./useConversationImagePreview.ts?raw";
import { useConversationImagePreview } from "./useConversationImagePreview";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const IMAGE: ConversationImagePreviewRequest = {
  src: "https://example.test/preview.png",
  alt: "Generated image",
  downloadUrl: "https://example.test/original.png",
  downloadName: "original.png",
};

function Harness({
  onResult,
}: {
  onResult: (result: ReturnType<typeof useConversationImagePreview>) => void;
}) {
  const result = useConversationImagePreview();
  onResult(result);
  return null;
}

describe("useConversationImagePreview", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    root = null;
    container = null;
  });

  async function mount() {
    if (root) {
      await act(async () => root?.unmount());
    }
    container?.remove();
    const resultRef: { current: ReturnType<typeof useConversationImagePreview> | null } = { current: null };
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    await act(async () => {
      root?.render(<Harness onResult={(result) => { resultRef.current = result; }} />);
    });
    return resultRef;
  }

  function dispatchEscape() {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
  }

  it("opens the preview and clears it on close", async () => {
    const resultRef = await mount();
    expect(resultRef.current?.previewImage).toBeNull();

    await act(async () => {
      resultRef.current?.openImagePreview(IMAGE);
    });
    expect(resultRef.current?.previewImage).toEqual(IMAGE);

    await act(async () => {
      resultRef.current?.closeImagePreview();
    });
    expect(resultRef.current?.previewImage).toBeNull();
  });

  it("clears an open preview when Escape is pressed", async () => {
    const resultRef = await mount();
    await act(async () => {
      resultRef.current?.openImagePreview(IMAGE);
    });
    expect(resultRef.current?.previewImage).toEqual(IMAGE);

    await act(async () => {
      dispatchEscape();
    });
    expect(resultRef.current?.previewImage).toBeNull();
  });

  it("ignores Escape while the preview is closed", async () => {
    const resultRef = await mount();
    expect(resultRef.current?.previewImage).toBeNull();

    await act(async () => {
      dispatchEscape();
    });
    expect(resultRef.current?.previewImage).toBeNull();
  });

  it("keeps openImagePreview referentially stable across rerenders", async () => {
    const resultRef = await mount();
    const firstOpen = resultRef.current?.openImagePreview;
    expect(firstOpen).toEqual(expect.any(Function));

    await act(async () => {
      root?.render(<Harness onResult={(result) => { resultRef.current = result; }} />);
    });
    expect(resultRef.current?.openImagePreview).toBe(firstOpen);

    await act(async () => {
      resultRef.current?.openImagePreview(IMAGE);
    });
    expect(resultRef.current?.openImagePreview).toBe(firstOpen);
    expect(resultRef.current?.previewImage).toEqual(IMAGE);
  });
});

describe("ConversationView image preview ownership", () => {
  it("consumes the hook and keeps the lazy dialog mount in the shell", () => {
    expect(conversationViewSource).toContain("useConversationImagePreview()");
    expect(conversationViewSource).toContain("previewImage,");
    expect(conversationViewSource).toContain("openImagePreview,");
    expect(conversationViewSource).toContain("closeImagePreview,");
    expect(conversationViewSource).toContain('React.lazy(() =>');
    expect(conversationViewSource).toContain("{previewImage ? (");
    expect(conversationViewSource).toContain("<React.Suspense fallback={null}>");
    expect(conversationViewSource).toContain("<ConversationImagePreviewDialog image={previewImage} lang={lang} onClose={closeImagePreview} />");
    expect(conversationViewSource).not.toContain("setPreviewImage");
    expect(conversationViewSource).not.toContain("const [previewImage");
    expect(conversationViewSource).not.toContain('addEventListener("keydown"');

    expect(hookSource).toContain("useCallback((image: ConversationImagePreviewRequest) => {");
    expect(hookSource).toContain("if (!previewImage)");
    expect(hookSource).toContain('event.key === "Escape"');
    expect(hookSource).toContain('window.addEventListener("keydown", handleKeyDown)');
    expect(hookSource).toContain('window.removeEventListener("keydown", handleKeyDown)');
  });
});
