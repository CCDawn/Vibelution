import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

import { VuiProvider } from "../components/vui";
import { ConfigDecisionModelsPanel, readDecisionModelMap } from "./ConfigDecisionModelsPanel";

const presets = [
  {
    presetId: "d1-3b",
    label: "d1-3B",
    modelId: "LiquidAI/d1-3B",
    baseUrl: "http://127.0.0.1:8088/v1/systemone",
    noteZh: "本机可跑",
    noteEn: "fits this machine",
  },
  {
    presetId: "openjev",
    label: "OpenJev",
    modelId: "ggml-org/OpenJev-GGUF",
    baseUrl: "http://127.0.0.1:8093/v1/systemone",
    noteZh: "27B，只允许非商用",
    noteEn: "27B, non-commercial only",
  },
];

describe("ConfigDecisionModelsPanel", () => {
  it("renders the decision class without a chat slot", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <ConfigDecisionModelsPanel
          models={readDecisionModelMap({
            "d1-3b": {
              label: "d1-3B",
              model_id: "LiquidAI/d1-3B",
              base_url: "http://127.0.0.1:8088/v1/systemone",
              min_probability: 0.8,
              enabled: true,
              note: "本机可跑",
            },
          })}
          handoffModelId=""
          presets={presets}
          disabled={false}
          lang="zh"
          onCommit={() => undefined}
        />
      </VuiProvider>,
    );
    expect(markup).toContain("决策模型");
    expect(markup).toContain("OpenJev");
    expect(markup).toContain("不绑定");
    expect(markup).toContain("检查连通");
    expect(markup).toContain("不进入对话槽");
    expect(markup).not.toContain("renderers/shadcn");
  });

  it("is mounted from the models section and stays on the VUI API", () => {
    const route = readFileSync(resolve(import.meta.dirname, "ConfigRoute.tsx"), "utf8");
    const panel = readFileSync(resolve(import.meta.dirname, "ConfigDecisionModelsPanel.tsx"), "utf8");
    expect(route).toContain("ConfigDecisionModelsPanel");
    expect(route).toContain("decision_models");
    expect(route).toContain("decision_handoff_model_id");
    expect(panel).not.toContain("renderers/shadcn");
    expect(panel).not.toContain("@heroui/react");
  });
});
