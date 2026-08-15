import { describe, expect, it } from "vitest";

import apiSource from "./userContent.ts?raw";
import panelSource from "../routes/MemoryUserContentPanel.tsx?raw";

describe("user-content catalog API", () => {
  it("owns the markdown-space list, page, search, and import transports", () => {
    expect(apiSource).toContain("export function listUserMarkdownSpaces");
    expect(apiSource).toContain("export function listUserMarkdownSpacePages");
    expect(apiSource).toContain("export function fetchUserMarkdownSpacePage");
    expect(apiSource).toContain("export function searchUserMarkdownSpaces");
    expect(apiSource).toContain("export function previewUserMarkdownSpaceImport");
    expect(apiSource).toContain("export function importUserMarkdownSpace");
    expect(apiSource).toContain("/api/user-content/markdown-spaces");
    expect(apiSource).toContain("/api/user-content/markdown-spaces/${encodeURIComponent(spaceId)}/pages");
    expect(apiSource).toContain("/pages/${encodeURIComponent(pageId)}");
    expect(apiSource).toContain("/api/user-content/markdown-spaces/search");
    expect(apiSource).toContain("/api/user-content/markdown-spaces/import-preview");
    expect(apiSource).toContain("/api/user-content/markdown-spaces/import");
  });

  it("keeps MemoryUserContentPanel free of user-content transport paths", () => {
    expect(panelSource).toContain("listUserMarkdownSpaces<");
    expect(panelSource).toContain("listUserMarkdownSpacePages<");
    expect(panelSource).toContain("fetchUserMarkdownSpacePage<");
    expect(panelSource).toContain("searchUserMarkdownSpaces<");
    expect(panelSource).toContain("previewUserMarkdownSpaceImport<");
    expect(panelSource).toContain("importUserMarkdownSpace<");
    expect(panelSource).not.toContain("/api/user-content/");
  });
});
