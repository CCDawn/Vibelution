import { useCallback, useEffect, useState } from "react";

import type { ConversationImagePreviewRequest } from "./ConversationImagePreviewDialog";

export type UseConversationImagePreviewResult = {
  previewImage: ConversationImagePreviewRequest | null;
  openImagePreview: (image: ConversationImagePreviewRequest) => void;
  closeImagePreview: () => void;
};

/**
 * Image preview open/close state and Escape dismissal.
 * Extracted from ConversationView. The shell still gates the lazy
 * ConversationImagePreviewDialog mount.
 *
 * openImagePreview stays referentially stable: the markdown renderer is
 * content-memoized, so a fresh closure per render would re-parse every block.
 */
export function useConversationImagePreview(): UseConversationImagePreviewResult {
  const [previewImage, setPreviewImage] = useState<ConversationImagePreviewRequest | null>(null);

  const openImagePreview = useCallback((image: ConversationImagePreviewRequest) => {
    setPreviewImage(image);
  }, []);

  const closeImagePreview = useCallback(() => {
    setPreviewImage(null);
  }, []);

  useEffect(() => {
    if (!previewImage) {
      return undefined;
    }
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setPreviewImage(null);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [previewImage]);

  return {
    previewImage,
    openImagePreview,
    closeImagePreview,
  };
}
