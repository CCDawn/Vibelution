import { describe, expect, it } from "vitest";

import type { MemoryAgentMemoryItemView } from "../MemoryAgentMemoryPanel";
import { buildAgentMemoryReaderItems as buildReaderItems } from "./agentMemoryReader";

function memoryItem(overrides: Partial<MemoryAgentMemoryItemView> = {}): MemoryAgentMemoryItemView {
  return {
    id: "memory-1",
    title: "memory.json",
    updatedAtText: "",
    path: "agents/example/memory/memory.json",
    summary: "",
    sizeText: "",
    contentType: "json",
    truncated: false,
    active: false,
    content: "",
    ...overrides,
  };
}

describe("buildAgentMemoryReaderItems", () => {
  it("keeps an empty file empty and does not present its summary as body", () => {
    const [item] = buildReaderItems([memoryItem({ summary: "摘要字段" })]);

    expect(item.category).toBe("content");
    expect(item.readerTitle).toBe("memory.json");
    expect(item.blocks).toEqual([]);
    expect(item.excerpt).toBe("摘要字段");
  });

  it("recognizes only the exact default schema written by memory_tools", () => {
    const [item] = buildReaderItems([memoryItem({
      content: JSON.stringify({ core_wisdom: "初始状态", current_goal: "", last_archive_time: null }),
    })]);

    expect(item.category).toBe("initialization");
  });

  it("recognizes only the exact default schema written by WorkspaceManager", () => {
    const [item] = buildReaderItems([memoryItem({
      content: JSON.stringify({
        current_generation: 1,
        core_wisdom: "初始状态",
        current_goal: "熟悉环境",
        last_archive_time: null,
      }),
    })]);

    expect(item.category).toBe("initialization");
  });

  it("does not classify records with extra fields or new wisdom as initialization", () => {
    const [extraField] = buildReaderItems([memoryItem({
      content: JSON.stringify({
        core_wisdom: "初始状态",
        current_goal: "",
        last_archive_time: null,
        note: "用户已提供新信息",
      }),
    })]);
    const [newWisdom] = buildReaderItems([memoryItem({
      content: JSON.stringify({ core_wisdom: "用户明确要求回复简洁", current_goal: "", last_archive_time: null }),
    })]);

    expect(extraField.category).toBe("content");
    expect(newWisdom.category).toBe("content");
    expect(newWisdom.excerpt).toContain("用户明确要求回复简洁");
  });

  it("uses the first Markdown heading as the title and derives the excerpt from body text", () => {
    const [item] = buildReaderItems([memoryItem({
      title: "preferences.md",
      path: "agents/example/memory/preferences.md",
      contentType: "markdown",
      summary: "与文件正文冲突的摘要",
      content: "开头说明\n\n## 回复习惯 ##\n偏好短句和明确结论。",
    })]);

    expect(item.readerTitle).toBe("回复习惯");
    expect(item.blocks).toEqual([{ kind: "paragraph", text: "开头说明\n\n## 回复习惯 ##\n偏好短句和明确结论。" }]);
    expect(item.excerpt).toContain("偏好短句和明确结论。");
    expect(item.excerpt).not.toContain("与文件正文冲突的摘要");
  });

  it("parses JSON into readable blocks while keeping the real body as the excerpt source", () => {
    const [item] = buildReaderItems([memoryItem({
      summary: "不应覆盖正文的摘要",
      content: JSON.stringify({ preference: "先给结论", project: "Vibelution" }),
    })]);

    expect(item.blocks).toEqual([{
      kind: "fields",
      entries: [
        { label: "preference", value: "先给结论" },
        { label: "project", value: "Vibelution" },
      ],
    }]);
    expect(item.excerpt).toContain("先给结论");
    expect(item.excerpt).not.toContain("不应覆盖正文的摘要");
  });

  it("keeps HTML source as plain text for safe text rendering", () => {
    const html = "<script>alert('keep as text')</script><h1>not a parsed title</h1>";
    const [item] = buildReaderItems([memoryItem({
      title: "notes.html",
      path: "agents/example/memory/notes.html",
      contentType: "html",
      content: html,
    })]);

    expect(item.readerTitle).toBe("notes.html");
    expect(item.blocks).toEqual([{ kind: "paragraph", text: html }]);
    expect(item.excerpt).toBe(html);
  });

  it("does not classify a truncated default-shaped index or another filename as initialization", () => {
    const defaultBody = JSON.stringify({ core_wisdom: "初始状态", current_goal: "", last_archive_time: null });
    const [truncated] = buildReaderItems([memoryItem({ content: defaultBody, truncated: true })]);
    const [differentFile] = buildReaderItems([memoryItem({ title: "archive.json", content: defaultBody })]);

    expect(truncated.category).toBe("content");
    expect(differentFile.category).toBe("content");
  });
});
