import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import styles from "./ChatFilePreviewPanel.styles";
import { ChatFilePreviewPanel } from "./ChatFilePreviewPanel";

describe("ChatFilePreviewPanel layout contract", () => {
  it("announces long preview errors without letting unbroken paths widen the panel", () => {
    const longPathError =
      "Unable to load C:/workspace/" +
      "nested-folder-".repeat(18) +
      "file-with-a-very-long-name-and-no-natural-breakpoints.md";

    const html = renderToStaticMarkup(
      React.createElement(ChatFilePreviewPanel, {
        changed: false,
        errorMessage: longPathError,
        file: null,
        loadingLabel: "Select a file",
        sourceLabel: "Source",
      }),
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain("Unable to load C:/workspace/");
    expect(styles.emptySurface).toContain("break-words");
    expect(styles.emptySurface).toContain("[overflow-wrap:anywhere]");
    expect(styles.emptySurface).toContain("min-h-[96px]");
    expect(styles.emptySurface).not.toContain("h-full");
    expect(styles.emptySurface).not.toContain("min-h-[min(420px,calc(100dvh_-_190px))]");
  });

  it("exposes empty and lazy loading states as polite status updates", () => {
    const emptyHtml = renderToStaticMarkup(
      React.createElement(ChatFilePreviewPanel, {
        changed: false,
        errorMessage: "",
        file: null,
        loadingLabel: "Select a file",
        sourceLabel: "Source",
      }),
    );

    expect(emptyHtml).toContain('role="status"');
    expect(emptyHtml).toContain('aria-live="polite"');
    expect(emptyHtml).toContain("Select a file");

    const fallbackHtml = renderToStaticMarkup(
      React.createElement(ChatFilePreviewPanel, {
        changed: false,
        errorMessage: "",
        file: {
          content: "hello",
          language: "markdown",
          path: "notes.md",
          type: "text",
        },
        loadingLabel: "Loading preview",
        sourceLabel: "Source",
      }),
    );

    expect(fallbackHtml).toContain('role="status"');
    expect(fallbackHtml).toContain('aria-live="polite"');
    expect(fallbackHtml).toContain("Loading preview");
  });
});
