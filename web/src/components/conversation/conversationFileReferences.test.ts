import { describe, expect, it } from "vitest";

import {
  conversationFileReferenceName,
  extractConversationFileReferences,
} from "./conversationFileReferences";

const ROOT = "C:\\workspace\\sessions\\abc";

describe("extractConversationFileReferences", () => {
  it("extracts a fenced code block that is a single absolute path", () => {
    const refs = extractConversationFileReferences(
      "产物已生成：\n```text\nC:\\workspace\\sessions\\abc\\output\\report.html\n```",
      ROOT,
    );
    expect(refs).toHaveLength(1);
    expect(refs[0].absolutePath).toBe("C:\\workspace\\sessions\\abc\\output\\report.html");
    expect(refs[0].extension).toBe("html");
    expect(refs[0].family).toBe("document");
  });

  it("extracts every path line from a multi-line fenced path block", () => {
    const refs = extractConversationFileReferences(
      "```\nC:\\out\\a.md\nC:\\out\\b.png\n```",
      ROOT,
    );
    expect(refs.map((ref) => ref.absolutePath)).toEqual([
      "C:\\out\\a.md",
      "C:\\out\\b.png",
    ]);
  });

  it("does not treat mixed fenced blocks as path listings but still surfaces their absolute paths", () => {
    const refs = extractConversationFileReferences(
      "```html\n<div>not a path listing</div>\nC:\\out\\a.md\n```",
      ROOT,
    );
    // Whole-block listing rule does not fire (relative-only lines in a mixed
    // block stay unextracted), but an absolute whitelisted path inside the
    // block is a real reference and matches via the bare-path scan.
    expect(refs.map((ref) => ref.absolutePath)).toEqual(["C:\\out\\a.md"]);
  });

  it("extracts bare absolute drive and UNC paths from body text", () => {
    const refs = extractConversationFileReferences(
      "报告在 C:\\out\\weekly.pdf 完成，共享目录副本在 \\\\nas\\share\\deck.pptx。",
      ROOT,
    );
    expect(refs.map((ref) => ref.absolutePath)).toEqual([
      "C:\\out\\weekly.pdf",
      "\\\\nas\\share\\deck.pptx",
    ]);
  });

  it("extracts quoted paths and resolves relative ones against the workspace root", () => {
    const refs = extractConversationFileReferences(
      '主产物是 "output/result.xlsx"，绝对路径版在 \'C:\\abs\\note.md\'。',
      ROOT,
    );
    expect(refs.map((ref) => ref.absolutePath)).toEqual([
      "C:\\workspace\\sessions\\abc\\output\\result.xlsx",
      "C:\\abs\\note.md",
    ]);
  });

  it("suppresses markdown-linked workspace files from the chip list", () => {
    const refs = extractConversationFileReferences(
      "详见 [报告](C:\\out\\report.md) 与正文裸路径 C:\\out\\report.md。",
      ROOT,
    );
    expect(refs).toHaveLength(0);
  });

  it("drops non-whitelisted extensions", () => {
    const refs = extractConversationFileReferences(
      "脚本 C:\\scripts\\run.py 与配置 C:\\app\\config.json 不应出现。",
      ROOT,
    );
    expect(refs).toHaveLength(0);
  });

  it("drops relative references when no workspace root is available", () => {
    const refs = extractConversationFileReferences(
      '相对引用 "output/result.xlsx" 与路径块：\n```\noutput/result.xlsx\n```',
    );
    expect(refs).toHaveLength(0);
  });

  it("deduplicates identical paths across shapes and keeps first-appearance order", () => {
    const refs = extractConversationFileReferences(
      "```\nC:\\out\\a.md\n```\n再提一次 \"C:\\out\\a.md\" 与 C:\\out\\a.md，最后 C:\\out\\b.pdf。",
      ROOT,
    );
    expect(refs.map((ref) => ref.absolutePath)).toEqual([
      "C:\\out\\a.md",
      "C:\\out\\b.pdf",
    ]);
  });

  it("returns nothing for empty or whitespace-only input", () => {
    expect(extractConversationFileReferences("", ROOT)).toEqual([]);
    expect(extractConversationFileReferences("   \n  ", ROOT)).toEqual([]);
  });

  it("resolves the same file across separator styles to one chip", () => {
    const refs = extractConversationFileReferences(
      '见 "C:\\out\\a.md"，也可打开 C:/out/a.md。',
      ROOT,
    );
    expect(refs).toHaveLength(1);
    expect(refs[0].absolutePath).toBe("C:\\out\\a.md");
  });
});

describe("conversationFileReferenceName", () => {
  it("returns the leaf segment of windows and posix paths", () => {
    expect(conversationFileReferenceName("C:\\a\\b\\report.html")).toBe("report.html");
    expect(conversationFileReferenceName("/var/log/app.log.txt")).toBe("app.log.txt");
  });
});
