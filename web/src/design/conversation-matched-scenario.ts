import type { ConversationMessage, SessionTurnItem, SessionTurnItemStatus } from "../api/types";
import fixture from "./fixtures/conversation-matched-scenario.json";

export type MatchedToolState = "running" | "completed" | "failed" | "stopped";
export type MatchedStage = {
  id: string;
  label: string;
  elapsedMs: number;
  isStreaming: boolean;
  reasoningStreaming: boolean;
  reasoningDurationMs: number;
  workStatus: MatchedToolState;
  messageField: string;
  toolStates: Partial<Record<string, MatchedToolState>>;
};
export type MatchedScenario = {
  schemaVersion: number;
  id: string;
  turnId: string;
  startedAt: string;
  userText: string;
  reasoningText: string;
  progressText: string;
  executionText: string;
  finalText: string;
  failedText: string;
  stoppedText: string;
  tools: Array<{
    toolCallId: string;
    kind: "read" | "search" | "execute";
    name: string;
    title: string;
    input: Partial<Record<string, string>>;
    output: string;
    startedAtMs: number;
    completedAtMs: number;
  }>;
  stages: MatchedStage[];
  autoSequence: Array<{ atMs: number; stageId: string }>;
};

/** Same byte-identical fixture is consumed by the isolated ZCode reference. */
export const matchedScenario = fixture as MatchedScenario;

export function matchedStage(id: string): MatchedStage {
  const stage = matchedScenario.stages.find((item) => item.id === id);
  if (!stage) throw new Error(`Unknown matched conversation stage: ${id}`);
  return stage;
}

/** Native vocabulary adaptation only; no second transcript store or live endpoint. */
const nativeTools = { read: "read_file_tool", search: "grep_search_tool", execute: "cli_tool" } as const;

export function matchedConversationMessage(stageId: string, startedAtMs: number, sessionId: string): ConversationMessage {
  const stage = matchedStage(stageId);
  const revision = matchedScenario.stages.indexOf(stage) + 1;
  const stamp = (offset: number) => new Date(startedAtMs + offset).toISOString();
  const base = { version: 3 as const, sessionId, turnId: matchedScenario.turnId, revision };
  const items: SessionTurnItem[] = [{
    ...base, id: `matched-reasoning:r${revision}`, itemId: "matched-reasoning", sequence: 1,
    type: "reasoning", status: stage.reasoningStreaming ? "running" : "completed",
    text: matchedScenario.reasoningText, createdAt: stamp(0), updatedAt: stamp(stage.reasoningDurationMs),
    terminal: !stage.reasoningStreaming,
  }];
  for (const [index, tool] of matchedScenario.tools.entries()) {
    const state = stage.toolStates[tool.toolCallId];
    if (!state) continue;
    const status: SessionTurnItemStatus = state === "stopped" ? "completed" : state;
    items.push({
      ...base, id: `${tool.toolCallId}:r${revision}`, itemId: tool.toolCallId, sequence: 10 + index,
      type: "tool_call", callId: tool.toolCallId, toolName: nativeTools[tool.kind], status,
      input: JSON.stringify(tool.input),
      output: state === "running" ? undefined : state === "failed" ? matchedScenario.failedText
        : state === "stopped" ? matchedScenario.stoppedText : tool.output,
      ...(state === "failed" ? { error: { code: "MATCHED_READONLY_CHECK_FAILED", message: matchedScenario.failedText } } : {}),
      semanticStatus: state === "stopped" ? "cancelled" : undefined,
      createdAt: stamp(tool.startedAtMs),
      updatedAt: stamp(state === "completed" ? tool.completedAtMs : stage.elapsedMs),
      terminal: state !== "running",
      metadata: {
        executionStartedAtEpochMs: startedAtMs + tool.startedAtMs,
        ...(state === "running" ? {} : { durationMs: Math.max(0, (state === "completed" ? tool.completedAtMs : stage.elapsedMs) - tool.startedAtMs) }),
      },
    });
  }
  const progress = stage.elapsedMs >= 8000 ? matchedScenario.executionText
    : stage.elapsedMs >= 5000 ? matchedScenario.progressText : "";
  if (progress) items.push({
    ...base, id: `matched-progress:r${revision}`, itemId: "matched-progress", sequence: 20,
    type: "agent_message", phase: "commentary", status: "completed", text: progress,
    createdAt: stamp(5000), updatedAt: stamp(stage.elapsedMs), terminal: true,
  });
  if (!stage.isStreaming) {
    const text = stage.workStatus === "failed" ? matchedScenario.failedText
      : stage.workStatus === "stopped" ? matchedScenario.stoppedText : matchedScenario.finalText;
    items.push({
      ...base, id: `matched-final:r${revision}`, itemId: "matched-final", sequence: 30,
      type: "agent_message", phase: "final_answer", status: "completed", text,
      createdAt: stamp(stage.elapsedMs), updatedAt: stamp(stage.elapsedMs), terminal: true,
    });
  }
  return {
    id: "matched-assistant", role: "assistant", turnId: matchedScenario.turnId,
    timestamp: stamp(0), status: stage.isStreaming ? "running" : stage.workStatus === "failed" ? "failed" : "completed",
    metadata: { ...(stage.isStreaming ? { kind: "session_live_overlay" } : {}),
      ...(stage.workStatus === "stopped" ? { interrupted: true } : {}),
      matchedFixture: matchedScenario.id },
    turnItems: items, turnState: stage.workStatus === "stopped" ? "interrupted" : stage.workStatus,
    turnStartedAt: stamp(0), turnEndedAt: stage.isStreaming ? undefined : stamp(stage.elapsedMs),
    turnActiveMs: stage.isStreaming ? undefined : stage.elapsedMs,
  } as ConversationMessage;
}
