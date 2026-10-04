// @vitest-environment happy-dom
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";

import { VListDetailPage } from "./VListDetailPage";

function renderPage(props: Parameters<typeof VListDetailPage>[0]) {
  document.body.innerHTML = renderToStaticMarkup(<VListDetailPage {...props} />);
  return document.querySelector('[data-vui-recipe="list-detail-page"]')!;
}

afterEach(() => { document.body.innerHTML = ""; });

describe("VListDetailPage chrome geometry", () => {
  it("keeps the header and toolbar in one chrome row before the fill body", () => {
    const page = renderPage({
      title: "Agents",
      toolbar: <button type="button">Refresh</button>,
      list: <nav>Directory</nav>,
      detail: <main>Details</main>,
    });

    expect(Array.from(page.children, (child) => child.getAttribute("data-vui")))
      .toEqual(["list-detail-chrome", "list-detail-body"]);
    const chrome = page.children[0];
    expect(chrome.querySelector('[data-vui="route-header"]')).not.toBeNull();
    expect(chrome.querySelector('[data-vui="list-detail-toolbar"]')?.textContent).toBe("Refresh");
    expect(page.getAttribute("data-fill-layout")).toBe("header-body");
  });

  it("omits redundant headers without hiding the module toolbar", () => {
    const page = renderPage({
      title: "Redundant title",
      hideHeader: true,
      toolbar: <button type="button">New Agent</button>,
      list: "Directory",
      detail: "Details",
    });

    expect(page.querySelector('[data-vui="route-header"]')).toBeNull();
    expect(page.textContent).not.toContain("Redundant title");
    expect(page.children).toHaveLength(2);
    expect(page.children[0].textContent).toBe("New Agent");
  });

  it("fills the body with the existing stack recipe when chrome is absent", () => {
    const page = renderPage({ title: "Hidden", hideHeader: true, list: "List", detail: "Detail" });

    expect(page.getAttribute("data-fill-layout")).toBe("stack");
    expect(page.children).toHaveLength(1);
    expect(page.children[0].getAttribute("data-vui")).toBe("list-detail-body");
    expect(page.querySelector('[data-vui="split-workspace"]')).not.toBeNull();
  });

  it("preserves content-height pages and their accessible landmark", () => {
    const page = renderPage({ ariaLabel: "Skills", title: "Skills", fill: false, list: "List", detail: "Detail" });

    expect(page.getAttribute("aria-label")).toBe("Skills");
    expect(page.getAttribute("data-fill")).toBe("false");
    expect(page.getAttribute("data-fill-layout")).toBeNull();
    expect(page.children[1].className).toBe("min-h-0 min-w-0");
  });
});
