// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CliAgentRunView, CliAgentTerminalSession } from "../ChatCodingRoute";
import { CliAgentRunTerminalPanel } from "./CliAgentRunTerminalPanel";

const { terminalInstances, ensureTerminalSession } = vi.hoisted(() => ({
  terminalInstances: [] as Array<{ written: string[]; disposed: boolean }>,
  ensureTerminalSession: vi.fn(),
}));

vi.mock("../../api/cliAgents", () => ({
  ensureCliAgentTerminalSession: ensureTerminalSession,
  resizeCliAgentTerminal: vi.fn().mockResolvedValue({}),
  sendCliAgentTerminalInput: vi.fn().mockResolvedValue({}),
}));

vi.mock("@xterm/addon-fit", () => ({
  FitAddon: class {
    fit() {}
  },
}));

vi.mock("@xterm/xterm", () => ({
  Terminal: class {
    rows = 24;
    cols = 80;
    written: string[] = [];
    disposed = false;

    constructor() {
      terminalInstances.push(this);
    }

    loadAddon() {}
    open() {}
    onData() { return { dispose() {} }; }
    write(value: string) { this.written.push(value); }
    reset() {}
    focus() {}
    dispose() { this.disposed = true; }
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  readonly listeners = new Map<string, Set<EventListener>>();
  closed = false;
  closeCount = 0;
  onerror: ((event: Event) => void) | null = null;

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, callback: EventListener) {
    const listeners = this.listeners.get(type) ?? new Set<EventListener>();
    listeners.add(callback);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, callback: EventListener) {
    this.listeners.get(type)?.delete(callback);
  }

  emit(type: string, payload: unknown) {
    const event = new MessageEvent(type, { data: JSON.stringify(payload) });
    for (const listener of this.listeners.get(type) ?? []) {
      listener(event);
    }
  }

  fail() {
    this.onerror?.(new Event("error"));
  }

  close() {
    this.closed = true;
    this.closeCount += 1;
  }
}

const run = {
  id: "run-1",
  title: "CLI run",
  agentType: "codex",
  task: "inspect lifecycle",
  cwd: "C:/repo",
  mode: "readonly",
  commandLine: "codex",
  cliSessionId: "cli-1",
  result: null,
  status: "running",
} as unknown as CliAgentRunView;

function terminalSession(
  terminalSessionId: string,
  overrides: Partial<CliAgentTerminalSession> = {},
): CliAgentTerminalSession {
  return {
    terminalSessionId,
    cliSessionId: "cli-1",
    alive: true,
    canInput: false,
    canResume: true,
    canStart: false,
    resumeAction: "resume_session",
    displayMode: "readonly_replay",
    transcriptTail: "",
    transcriptTailReplayable: true,
    ...overrides,
  };
}

let roots: Root[] = [];

async function settleReact() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

function mount(session: CliAgentTerminalSession) {
  ensureTerminalSession.mockResolvedValueOnce(session);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  roots.push(root);
  act(() => {
    root.render(
      <CliAgentRunTerminalPanel
        run={run}
        sourceSessionId="source-session"
        active
        lang="en"
      />,
    );
  });
  return { container, root };
}

function unmount(root: Root) {
  act(() => root.unmount());
  roots = roots.filter((candidate) => candidate !== root);
  document.body.textContent = "";
}

describe("CliAgentRunTerminalPanel EventSource lifecycle", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    terminalInstances.length = 0;
    ensureTerminalSession.mockReset();
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
  });

  afterEach(() => {
    for (const root of [...roots]) {
      act(() => root.unmount());
    }
    roots = [];
    document.body.textContent = "";
    vi.unstubAllGlobals();
  });

  it("closes the stream when a terminal snapshot confirms the process exited", async () => {
    const { root } = mount(terminalSession("terminal-1"));
    await settleReact();
    const stream = FakeEventSource.instances[0];

    act(() => {
      stream.emit("terminal_snapshot", {
        type: "terminal_snapshot",
        session: terminalSession("terminal-1", { alive: false }),
      });
    });

    expect(stream.closed).toBe(true);
    expect(stream.closeCount).toBe(1);
    unmount(root);
  });

  it("closes the stream when a terminal status confirms the process exited", async () => {
    const { root } = mount(terminalSession("terminal-1"));
    await settleReact();
    const stream = FakeEventSource.instances[0];

    act(() => {
      stream.emit("terminal_status", {
        type: "terminal_status",
        session: terminalSession("terminal-1", { alive: false }),
      });
    });

    expect(stream.closed).toBe(true);
    expect(stream.closeCount).toBe(1);
    unmount(root);
  });

  it("keeps an active stream open after a transient transport error", async () => {
    const { root } = mount(terminalSession("terminal-1"));
    await settleReact();
    const stream = FakeEventSource.instances[0];

    act(() => stream.fail());

    expect(stream.closed).toBe(false);
    act(() => {
      stream.emit("terminal_output", { type: "terminal_output", chunk: "still connected" });
    });
    expect(terminalInstances[0]?.written).toContain("still connected");
    unmount(root);
  });

  it("closes the old stream when the terminal id changes and closes the replacement on unmount", async () => {
    const { container, root } = mount(terminalSession("terminal-1"));
    await settleReact();
    const oldStream = FakeEventSource.instances[0];
    ensureTerminalSession.mockResolvedValueOnce(terminalSession("terminal-2", {
      canInput: true,
      canResume: false,
      resumeAction: "none",
      displayMode: "live_terminal",
    }));

    const resumeButton = container.querySelector("button");
    expect(resumeButton).not.toBeNull();
    await act(async () => {
      resumeButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await settleReact();

    expect(oldStream.closed).toBe(true);
    expect(FakeEventSource.instances).toHaveLength(2);
    const replacement = FakeEventSource.instances[1];
    expect(replacement.url).toContain("terminal-2");
    expect(replacement.closed).toBe(false);
    act(() => {
      replacement.emit("terminal_output", { type: "terminal_output", chunk: "replacement stream" });
    });
    expect(terminalInstances[0]?.written).toContain("replacement stream");

    unmount(root);
    expect(replacement.closed).toBe(true);
  });

  it("reopens a closed stream when explicit resume succeeds with the same terminal id", async () => {
    const { container, root } = mount(terminalSession("terminal-1", { alive: false }));
    await settleReact();
    const oldStream = FakeEventSource.instances[0];

    act(() => {
      oldStream.emit("terminal_status", {
        type: "terminal_status",
        session: terminalSession("terminal-1", { alive: false }),
      });
    });
    expect(oldStream.closed).toBe(true);

    ensureTerminalSession.mockResolvedValueOnce(terminalSession("terminal-1", {
      alive: true,
      canInput: true,
      canResume: false,
      resumeAction: "none",
      displayMode: "live_terminal",
    }));
    const resumeButton = container.querySelector("button");
    expect(resumeButton).not.toBeNull();
    await act(async () => {
      resumeButton!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await settleReact();

    expect(FakeEventSource.instances).toHaveLength(2);
    const resumedStream = FakeEventSource.instances[1];
    expect(resumedStream.url).toContain("terminal-1");
    expect(resumedStream.closed).toBe(false);
    act(() => {
      resumedStream.emit("terminal_output", { type: "terminal_output", chunk: "resumed stream" });
    });
    expect(terminalInstances[0]?.written).toContain("resumed stream");

    unmount(root);
    expect(resumedStream.closed).toBe(true);
  });
});
