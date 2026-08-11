import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ResearchRunLaunchPanel } from "./ResearchRunLaunchPanel";

describe("ResearchRunLaunchPanel", () => {
  it("starts new research runs with the recommended phase safety limit", () => {
    const markup = renderToStaticMarkup(
      <ResearchRunLaunchPanel
        teamId="team-1"
        projectId="project-1"
        busy={false}
        onSubmit={async () => undefined}
        onCancel={() => undefined}
      />,
    );

    expect(markup).toContain("运行安全上限");
    expect(markup).toContain('value="250000"');
    expect(markup).toContain("高级运行合同");
  });
});
