import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VSettingsGroupCard, VSettingsRow } from "./forms/VSettingsRow";

describe("VSettingsRow", () => {
  it("renders label/description on the left with a fixed 192px control column by default", () => {
    const markup = renderToStaticMarkup(
      <VSettingsRow testId="row-x" label="标签" description="一行说明" control={<span>值</span>} />,
    );
    expect(markup).toContain('data-vui="settings-row"');
    expect(markup).toContain('data-testid="row-x"');
    expect(markup).toContain("grid-cols-[minmax(0,1fr)_192px]");
    expect(markup).toContain("标签");
    expect(markup).toContain("一行说明");
    expect(markup).toContain("值");
  });

  it("uses the 280px wide layout and keeps detail inline beside the control", () => {
    const markup = renderToStaticMarkup(
      <VSettingsRow controlLayout="wide" label="L" detail={<span>hint</span>} control={<span>C</span>} />,
    );
    expect(markup).toContain("grid-cols-[minmax(0,1fr)_280px]");
    const controlArea = markup.indexOf("hint");
    expect(controlArea).toBeGreaterThan(-1);
    expect(markup).toContain("C");
  });

  it("moves detail below the row for the default layout and renders footer blocks", () => {
    const markup = renderToStaticMarkup(
      <VSettingsRow
        label="L"
        detail={<span>below</span>}
        control={<span>C</span>}
        footer={<div>wide-editor</div>}
      />,
    );
    expect(markup).toContain("below");
    expect(markup).toContain("wide-editor");
    expect(markup).not.toContain("grid-cols-[minmax(0,1fr)_280px]");
  });

  it("renders the status slot in the control column", () => {
    const markup = renderToStaticMarkup(
      <VSettingsRow label="L" control={<span>C</span>} status={<span data-testid="badge">已生效</span>} />,
    );
    expect(markup).toContain('data-testid="badge"');
    expect(markup.indexOf("已生效")).toBeGreaterThan(markup.indexOf('data-vui="settings-row"'));
  });

  it("renders the group card container with card surface tokens", () => {
    const markup = renderToStaticMarkup(
      <VSettingsGroupCard testId="settings-group">
        <VSettingsRow label="L" />
      </VSettingsGroupCard>,
    );
    expect(markup).toContain('data-vui="settings-group"');
    expect(markup).toContain('data-testid="settings-group"');
    expect(markup).toContain("rounded-vui-panel");
    expect(markup).toContain("border-vui-border-subtle");
    expect(markup).toContain("bg-vui-surface-card");
  });
});
