import { lazy, Suspense, type ReactNode } from "react";

import type { FilePreviewProps } from "./FilePreview";

const FilePreview = lazy(async () => {
  const module = await import("./FilePreview");
  return { default: module.FilePreview };
});

type LazyFilePreviewProps = FilePreviewProps & {
  fallback: ReactNode;
};

export function LazyFilePreview({ fallback, ...props }: LazyFilePreviewProps) {
  return (
    <Suspense fallback={fallback}>
      <FilePreview {...props} />
    </Suspense>
  );
}
