import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

import { FilePreview } from "./FilePreview";

vi.mock("../../i18n/useAppI18n", () => ({
  useAppI18n: () => ({ lang: "zh", t: (key: string) => key }),
}));

vi.mock("@uiw/react-codemirror", () => ({
  default: () => <pre>read-only content</pre>,
}));

const file = {
  path: ".worktrees/task-review/web/src/routes/chat/example.tsx",
  language: "typescript",
  content: "export const ready = true;",
  truncated: false,
};

describe("FilePreview header density", () => {
  it("shows one readable project path and keeps the full workspace path available", () => {
    const html = renderToStaticMarkup(
      <FilePreview file={file} changed compactHeader sourceLabel="当前任务工作区" />,
    );

    expect(html).toContain('title=".worktrees/task-review/web/src/routes/chat/example.tsx"');
    expect(html).toContain(">web/src/routes/chat/example.tsx</h2>");
    expect(html).toContain("当前任务工作区");
    expect(html).not.toContain("readonlyPreview");
    expect(html).not.toContain(">changed</span>");
    expect(html).not.toContain(`>${file.path}</p>`);
  });

  it("preserves the default preview title, full path and change indicator", () => {
    const html = renderToStaticMarkup(
      <FilePreview file={file} changed sourceLabel="项目文件" />,
    );

    expect(html).toContain(">example.tsx</h2>");
    expect(html).toContain(`>${file.path}</p>`);
    expect(html).toContain("readonlyPreview");
    expect(html).toContain(">changed</span>");
  });
});
