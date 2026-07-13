import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnError } from "../../api/types";
import {
  buildConversationTurnErrorReasonRows,
  buildCurrentTurnErrorRows,
  buildTurnErrorDiagnosticRows,
  resolveConversationTurnErrorType,
} from "./conversationTurnErrorPresentation";

const conversationViewSource = readFileSync(
  new URL("./ConversationView.tsx", import.meta.url),
  "utf8",
);

describe("conversationTurnErrorPresentation", () => {
  it("keeps turn-error presentation helpers outside ConversationView", () => {
    expect(conversationViewSource).toContain("from \"./conversationTurnErrorPresentation\"");
    expect(conversationViewSource).not.toContain("function turnErrorType(");
    expect(conversationViewSource).not.toContain("function turnErrorReasonRows(");
    expect(conversationViewSource).not.toContain("function turnErrorBannerRows(");
  });

  it("resolves trimmed turn-error type from camelCase or snake_case metadata", () => {
    expect(resolveConversationTurnErrorType({
      metadata: { errorType: " provider_failure " },
    } as ConversationMessage)).toBe("provider_failure");
    expect(resolveConversationTurnErrorType({
      metadata: { error_type: "tool_timeout" },
    } as ConversationMessage)).toBe("tool_timeout");
    expect(resolveConversationTurnErrorType({
      metadata: { errorType: 404 },
    } as unknown as ConversationMessage)).toBe("");
  });

  it("builds localized persisted turn-error diagnostic rows in stable priority order", () => {
    const rows = buildConversationTurnErrorReasonRows({
      metadata: {
        http_status: 429,
        reason_summary: "provider 正在限流",
        reason_detail: "每分钟请求数超限",
        provider_error_type: "rate_limit_exceeded",
        provider_error_message: "group requests-per-minute limit exceeded",
        provider: "anthropic",
        provider_host: "www.atpify.cn",
        model: "claude-3",
        reason_code: "rate_limit",
        chain_stage: "llm_response_normalization",
        protocol: "responses",
        trace_id: "trace-runtime-1",
      },
    } as unknown as ConversationMessage, "zh");

    expect(rows).toEqual([
      { label: "状态码", value: "429" },
      { label: "原因", value: "provider 正在限流" },
      { label: "详情", value: "每分钟请求数超限" },
      { label: "阶段", value: "llm_response_normalization" },
      { label: "协议", value: "responses" },
      { label: "类型", value: "rate_limit_exceeded" },
      { label: "上游", value: "group requests-per-minute limit exceeded" },
      { label: "通道", value: "anthropic · www.atpify.cn" },
      { label: "模型", value: "claude-3" },
      { label: "代码", value: "rate_limit" },
      { label: "Trace", value: "trace-runtime-1" },
    ]);
  });

  it("builds localized current turn-error diagnostic rows from SessionTurnError", () => {
    const rows = buildCurrentTurnErrorRows({
      httpStatus: 503,
      reasonSummary: "upstream unavailable",
      reasonDetail: "gateway failed",
      providerErrorType: "api_error",
      providerErrorMessage: "No available accounts",
      provider: "anthropic",
      providerHost: "www.atpify.cn",
      model: "claude-3",
      reasonCode: "no_account",
      chainStage: "agent_outcome_evaluation",
      protocol: "chat_completions",
      traceId: "trace-runtime-2",
    } as SessionTurnError, "en");

    expect(rows).toEqual([
      { label: "Status", value: "503" },
      { label: "Reason", value: "upstream unavailable" },
      { label: "Detail", value: "gateway failed" },
      { label: "Stage", value: "agent_outcome_evaluation" },
      { label: "Protocol", value: "chat_completions" },
      { label: "Type", value: "api_error" },
      { label: "Upstream", value: "No available accounts" },
      { label: "Provider", value: "anthropic · www.atpify.cn" },
      { label: "Model", value: "claude-3" },
      { label: "Code", value: "no_account" },
      { label: "Trace", value: "trace-runtime-2" },
    ]);
  });

  it("builds bounded diagnostic rows directly from a canonical error cell summary", () => {
    expect(buildTurnErrorDiagnosticRows({
      httpStatus: 502,
      reasonCode: "upstream_unavailable",
      reasonSummary: "provider 上游服务不可用",
      provider: "ai-pixel",
      ignoredRawError: "must not render",
    }, "zh")).toEqual([
      { label: "状态码", value: "502" },
      { label: "原因", value: "provider 上游服务不可用" },
      { label: "通道", value: "ai-pixel" },
      { label: "代码", value: "upstream_unavailable" },
    ]);
  });
});
