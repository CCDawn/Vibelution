import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import type { ConfigProviderPresetOption } from "../api/types";
import { ConfigQuickSetupPanel, type ConfigQuickSetupPanelProps } from "./ConfigQuickSetupPanel";
import { initialProviderQuickSetupState, initialProviderWizardState } from "./configProviderLogic";

const templates: ConfigProviderPresetOption[] = [{
  provider_preset_id: "openai",
  label: "OpenAI 官方 API",
  vendor_id: "openai",
  vendor_label: "OpenAI",
  category: "official",
  provider_id: "openai",
  source_preset_id: "openai",
  provider: {
    service_class: "official_api",
    base_url: "https://api.openai.com/v1",
    auth_kind: "api_key",
    credential_ref: "env:OPENAI_API_KEY",
    driver: "openai",
    protocols: { default: "responses", allowed: ["responses"] },
  },
  default_model: { model_ref: "openai/gpt-5" },
}];

function props(overrides: Partial<ConfigQuickSetupPanelProps> = {}): ConfigQuickSetupPanelProps {
  return {
    state: initialProviderQuickSetupState(),
    templates,
    credentialValue: "",
    disabled: false,
    onCredentialChange: () => undefined,
    onProviderChange: () => undefined,
    onDetect: () => undefined,
    onModelChange: () => undefined,
    onConfirm: () => undefined,
    onReset: () => undefined,
    ...overrides,
  };
}

describe("ConfigQuickSetupPanel", () => {
  it("renders one Provider selector, one password input, and collapsed advanced settings", () => {
    const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props()} />);

    expect(markup).toContain("选择服务商");
    expect(markup).toContain('type="password"');
    expect(markup.match(/type="password"/g)).toHaveLength(1);
    expect(markup).toContain("高级参数");
    expect(markup).not.toContain("<details open");
    expect(markup).toContain("检测并生成配置");
  });

  it("hides the credential input for a no-auth Provider", () => {
    const state = {
      ...initialProviderQuickSetupState(),
      provider: {
        ...initialProviderWizardState(),
        templateId: "local",
        serviceClass: "local_runtime",
        authKind: "none" as const,
        credentialRef: "none",
      },
    };

    const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props({ state })} />);

    expect(markup).not.toContain('type="password"');
    expect(markup).toContain("无需凭据");
  });

  it.each([
    ["checking", "正在检测连接"],
    ["review", "确认生成的配置"],
    ["saving", "正在保存配置"],
    ["success", "配置已保存"],
    ["error", "需要处理后重试"],
  ] as const)("keeps the result surface mounted for %s", (phase, title) => {
    const state = {
      ...initialProviderQuickSetupState(),
      phase,
      errorKind: phase === "error" ? "auth" as const : "" as const,
      errorMessage: phase === "error" ? "认证失败" : "",
    };
    const markup = renderToStaticMarkup(<ConfigQuickSetupPanel {...props({ state })} />);

    expect(markup).toContain('data-quick-setup-result="true"');
    expect(markup).toContain(title);
  });

  it("never renders a credential value in result or error copy", () => {
    const secret = "sk-never-render-this";
    const state = {
      ...initialProviderQuickSetupState(),
      phase: "error" as const,
      errorKind: "auth" as const,
      errorMessage: "认证失败，请替换凭据",
    };
    const markup = renderToStaticMarkup(
      <ConfigQuickSetupPanel {...props({ state, credentialValue: secret })} />,
    );
    const resultMarkup = markup.slice(markup.indexOf('data-quick-setup-result="true"'));

    expect(resultMarkup).not.toContain(secret);
  });
});
