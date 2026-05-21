import { describe, expect, it } from "vitest";

import { applyWorkbenchDocumentLanguage } from "./documentLanguage";

function elementStub() {
  const classes = new Set<string>();

  return {
    classList: {
      add(value: string) {
        classes.add(value);
      },
      contains(value: string) {
        return classes.has(value);
      },
    },
    getAttribute(name: string) {
      return this.attributes.get(name) ?? null;
    },
    lang: "",
    setAttribute(name: string, value: string) {
      this.attributes.set(name, value);
    },
    attributes: new Map<string, string>(),
    translate: true,
  };
}

describe("documentLanguage", () => {
  it("marks the workbench document as Chinese application chrome without browser translation", () => {
    const documentElement = elementStub();
    const body = elementStub();

    applyWorkbenchDocumentLanguage({ documentElement, body } as unknown as Document, "zh");

    expect(documentElement.lang).toBe("zh-CN");
    expect(documentElement.translate).toBe(false);
    expect(documentElement.getAttribute("translate")).toBe("no");
    expect(documentElement.classList.contains("notranslate")).toBe(true);
    expect(body.translate).toBe(false);
    expect(body.getAttribute("translate")).toBe("no");
    expect(body.classList.contains("notranslate")).toBe(true);
  });

  it("keeps English UI selectable while still suppressing browser translation", () => {
    const documentElement = elementStub();
    const body = elementStub();

    applyWorkbenchDocumentLanguage({ documentElement, body } as unknown as Document, "en");

    expect(documentElement.lang).toBe("en");
    expect(documentElement.translate).toBe(false);
    expect(documentElement.getAttribute("translate")).toBe("no");
    expect(documentElement.classList.contains("notranslate")).toBe(true);
    expect(body.translate).toBe(false);
    expect(body.getAttribute("translate")).toBe("no");
    expect(body.classList.contains("notranslate")).toBe(true);
  });
});
