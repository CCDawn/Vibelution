import React, { type ComponentProps } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import type { SessionPendingQuestion } from "../../api/types";
import { ChatSessionWorkspacePanel } from "./ChatSessionWorkspacePanel";
import type { ChatConversationSurfaceModel } from "./useChatConversationSurfaceModel";

vi.mock("./ChatConversationComposerBridge", () => ({
  ChatConversationComposerBridge: (props: { composerPrecedingContent?: React.ReactNode }) => {
    capturedComposerPreceding = props.composerPrecedingContent ?? null;
    return <div>bridge</div>;
  },
}));
vi.mock("./ChatRuntimeNoticeStack", () => ({ ChatRuntimeNoticeStack: () => null }));

let capturedComposerPreceding: React.ReactNode = null;

const QUESTION: SessionPendingQuestion = {
  id: "q-1",
  questionText: "部署到测试环境还是生产环境？",
  askedAt: "2026-05-22T10:00:00Z",
  turnId: "turn-9",
};

function conversationModel(overrides: {
  lastTurnTerminalTurnId?: string;
  activeTurnId?: string;
  currentPhase?: string;
  composerPending?: boolean;
} = {}): ChatConversationSurfaceModel {
  return {
    sessionId: "sess-1",
    messages: [],
    transcript: {
      title: "当前会话",
      phase: overrides.currentPhase ?? "idle",
      activeTurnAuthority: {
        id: "sess-1",
        status: overrides.currentPhase ? "running" : "ready",
        currentPhase: overrides.currentPhase ?? "idle",
        activeTurnId: overrides.activeTurnId ?? "",
        lastTurnTerminalTurnId: overrides.lastTurnTerminalTurnId ?? "turn-9",
        terminalReason: overrides.currentPhase ? "" : "completed",
        ledgerSeq: 5,
      },
    },
    participants: {},
    composerChrome: { composer: { pending: overrides.composerPending ?? false } },
    turnActions: {},
  } as unknown as ChatConversationSurfaceModel;
}

const props = {
  lang: "zh",
  sessionGate: {
    activeSessionId: "sess-1",
    sessionsPending: false,
    noSessionsLabel: "",
    loadingSessionLabel: "",
  },
  errorGate: {
    hasBlockingError: false,
    blockingErrorMessage: "",
    hasTransientError: false,
    invalidChildSessionLinkMessage: "",
    transientErrorMessage: "",
  },
  alternateSurface: {
    workspaceActiveTab: "agent",
    activeCliAgentRunId: "",
    activeCliAgentRunAvailable: false,
    cliAgentRunEmptyLabel: "",
    filePreview: {},
  },
  conversationFrame: {
    conversation: conversationModel(),
    conversationFocused: false,
    notices: [],
    hideExportControl: true,
  },
  toolApproval: null,
} as unknown as ComponentProps<typeof ChatSessionWorkspacePanel>;

function renderPanel(frameOverrides: Partial<ComponentProps<typeof ChatSessionWorkspacePanel>["conversationFrame"]>) {
  return renderToStaticMarkup(
    <ChatSessionWorkspacePanel
      {...props}
      conversationFrame={{ ...props.conversationFrame, ...frameOverrides }}
    />,
  );
}

describe("ChatSessionWorkspacePanel pending question banner", () => {
  // The assistant already asked this question in its reply. Mainstream chat
  // surfaces do not echo that paragraph back above the composer, and doing so
  // duplicated the raw Markdown text in a second place.
  it("does not echo the pending question above the composer", () => {
    renderPanel({ pendingQuestion: QUESTION });
    expect(capturedComposerPreceding).toBeNull();
  });

  it("hides the banner while the session owns execution", () => {
    renderPanel({
      pendingQuestion: QUESTION,
      conversation: conversationModel({ currentPhase: "running", activeTurnId: "turn-10" }),
    });
    expect(capturedComposerPreceding).toBeNull();
  });

  it("hides the banner while a send is still unfinished", () => {
    renderPanel({
      pendingQuestion: QUESTION,
      conversation: conversationModel({ composerPending: true }),
    });
    expect(capturedComposerPreceding).toBeNull();
  });

  it("hides the banner when the question belongs to an earlier turn than the terminal tail", () => {
    renderPanel({
      pendingQuestion: { ...QUESTION, turnId: "turn-old" },
    });
    expect(capturedComposerPreceding).toBeNull();
  });

  it("stays empty even when the slot carries an empty turnId", () => {
    renderPanel({ pendingQuestion: { ...QUESTION, turnId: "" } });
    expect(capturedComposerPreceding).toBeNull();
  });

  it("renders nothing when the slot is empty", () => {
    renderPanel({ pendingQuestion: null });
    expect(capturedComposerPreceding).toBeNull();
  });
});
