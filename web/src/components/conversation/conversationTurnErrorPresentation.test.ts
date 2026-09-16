import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import type { ConversationMessage, SessionTurnError } from "../../api/types";
import { dictionaryChat } from "../../i18n/domains/dictionaryChat";
import {
  CONVERSATION_TURN_ERROR_TYPE_LABEL_KEYS,
  buildConversationTurnErrorReasonRows,
  buildCurrentTurnErrorRows,
  buildTurnErrorDiagnosticRows,
  resolveConversationTurnErrorRecoveryAction,
  resolveConversationTurnErrorType,
  resolveSessionTurnErrorRecoveryAction,
  resolveTurnErrorTypeLabelKey,
  summarizeCurrentTurnError,
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

  it("renders the turn-error block inside the timeline instead of pinning it above the composer", () => {
    const pinnedSlot = conversationViewSource.slice(
      conversationViewSource.indexOf("data-codex-tool-approval-fallback"),
      conversationViewSource.indexOf("{showComposer ? ("),
    );
    expect(pinnedSlot).not.toContain("styles.turnError");

    const virtualSpacerIndex = conversationViewSource.indexOf("timelineVirtualRange.bottomSpacerPx > 0");
    const inlineTurnErrorIndex = conversationViewSource.indexOf("turnErrorSupersededByFinalAnswer ? (");
    expect(virtualSpacerIndex).toBeGreaterThan(-1);
    expect(inlineTurnErrorIndex).toBeGreaterThan(virtualSpacerIndex);
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

  it("maps the full errorType enum to dictionary keys present in both languages", () => {
    // Exhaustive over the backend errorType vocabulary; the mapping must stay
    // total so a chip never regresses to a raw English code.
    expect(Object.keys(CONVERSATION_TURN_ERROR_TYPE_LABEL_KEYS).sort()).toEqual([
      "StaleChatTurnSettled",
      "agent_llm_resolution_failed",
      "prompt_cache_unsupported",
      "provider_error",
      "provider_protocol_error",
      "provider_upstream_error",
      "resource_lease_conflict",
      "runtime_error",
      "turn_persistence_failed",
    ]);
    for (const key of Object.values(CONVERSATION_TURN_ERROR_TYPE_LABEL_KEYS)) {
      expect(dictionaryChat.zh[key], `zh missing for ${key}`).toBeTruthy();
      expect(dictionaryChat.en[key], `en missing for ${key}`).toBeTruthy();
    }
  });

  it("falls back to the runtime label for unknown or exception-class errorTypes", () => {
    expect(resolveTurnErrorTypeLabelKey("")).toBe("");
    expect(resolveTurnErrorTypeLabelKey("provider_protocol_error")).toBe("turnErrorTypeProviderProtocolError");
    expect(resolveTurnErrorTypeLabelKey("TimeoutError")).toBe("turnErrorTypeRuntimeError");
    expect(resolveTurnErrorTypeLabelKey("some_future_code")).toBe("turnErrorTypeRuntimeError");
  });

  it("points budget-family failed turns at the compress-context recovery action", () => {
    expect(resolveConversationTurnErrorRecoveryAction({
      metadata: { failureDisposition: "budget_or_context" },
    } as ConversationMessage)).toBe("compress_context");
    expect(resolveConversationTurnErrorRecoveryAction({
      metadata: { reason_code: "context_budget_exhausted" },
    } as ConversationMessage)).toBe("compress_context");
    expect(resolveConversationTurnErrorRecoveryAction({
      metadata: { failureCategory: "budget_or_context", errorType: "runtime_error" },
    } as ConversationMessage)).toBe("compress_context");
    expect(resolveConversationTurnErrorRecoveryAction({
      metadata: { errorType: "provider_upstream_error", reasonCode: "upstream_unavailable" },
    } as ConversationMessage)).toBe("");

    expect(resolveSessionTurnErrorRecoveryAction({
      failureDisposition: "budget_or_context",
    } as unknown as Record<string, unknown>)).toBe("compress_context");
    expect(resolveSessionTurnErrorRecoveryAction({
      reasonCode: "context_limit",
    } as unknown as Record<string, unknown>)).toBe("compress_context");
    expect(resolveSessionTurnErrorRecoveryAction({
      reasonCode: "upstream_unavailable",
      failureDisposition: "transient",
    } as unknown as Record<string, unknown>)).toBe("");
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

  it("keeps the settled failure to one plain line and files the retry count under diagnostics", () => {
    const turnError = {
      reasonSummary: "upstream unavailable",
      retryHistory: [
        { attempt: 1, maxAttempts: 5, category: "server_error" },
        { attempt: 2, maxAttempts: 5, category: "server_error" },
        { attempt: 5, maxAttempts: 5, category: "server_error" },
      ],
    } as SessionTurnError;

    // Codex parity: the summary line never carries a retry trail.
    expect(summarizeCurrentTurnError(turnError, "zh")).toBe("upstream unavailable");
    expect(summarizeCurrentTurnError({ ...turnError, reasonSummary: "" } as SessionTurnError, "zh"))
      .not.toContain("已重试");
    const retryRow = { label: "重试", value: "5 次" };
    expect(buildCurrentTurnErrorRows(turnError, "zh")).toContainEqual(retryRow);
    expect(buildCurrentTurnErrorRows(turnError, "en")).toContainEqual({ label: "Retries", value: "5" });
    // Per-attempt retry rows stay out of diagnostics.
    expect(buildCurrentTurnErrorRows(turnError, "zh")).not.toContainEqual(
      expect.objectContaining({ label: "重试记录" }),
    );
    expect(buildCurrentTurnErrorRows({ reasonSummary: "upstream unavailable" } as SessionTurnError, "en"))
      .not.toContainEqual(expect.objectContaining({ label: "Retries" }));
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

  it("keeps protocol diagnostics out of the collapsed current-turn summary", () => {
    const turnError = {
      message: "网页工作台这一轮执行失败，请检查配置或稍后重试。 Cannot append assistant_delta_committed after terminal event for turn session-live-1.",
      errorType: "ValueError",
    } as SessionTurnError;

    expect(summarizeCurrentTurnError(turnError, "zh")).toBe(
      "网页工作台这一轮执行失败，请检查配置或稍后重试。",
    );
    expect(summarizeCurrentTurnError({
      ...turnError,
      reasonSummary: "活动轮次被提前终结",
    }, "zh")).toBe("活动轮次被提前终结");
  });
});
