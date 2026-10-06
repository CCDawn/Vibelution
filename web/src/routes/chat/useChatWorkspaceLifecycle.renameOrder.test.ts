import { QueryClient, type MutationOptions } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionSummary } from "../../api/types";
import { markSessionDeleteTombstone, resetSessionDeleteTombstonesForTests } from "../sessionDeleteTombstone";
import { useChatWorkspaceLifecycle, type UseChatWorkspaceLifecycleOptions, type UseChatWorkspaceLifecycleResult } from "./useChatWorkspaceLifecycle";

// Exercise the real mutation callbacks and QueryClient, while replacing only
// React hook registration and transport/telemetry boundaries.
vi.mock("react", async (original) => ({
  ...await original<typeof import("react")>(),
  useRef: (current: unknown) => ({ current }),
}));
vi.mock("@tanstack/react-query", async (original) => ({
  ...await original<typeof import("@tanstack/react-query")>(),
  useMutation: (options: unknown) => ({ options }),
}));
vi.mock("../../app/userActionTelemetry", () => ({
  startUserAction: () => ({ succeeded: vi.fn(), failed: vi.fn(), blocked: vi.fn() }),
}));

type Variables = { sessionId: string; title: string };
type Context = NonNullable<UseChatWorkspaceLifecycleResult["renameSessionMutation"]["context"]>;
type RenameOptions = MutationOptions<SessionDetail, Error, Variables, Context>;
const clients: QueryClient[] = [];
afterEach(() => {
  clients.splice(0).forEach((client) => client.clear());
  resetSessionDeleteTombstonesForTests();
});

function summary(id: string, title: string): SessionSummary {
  return { id, title, status: "ready", currentPhase: "ready", taskSummary: "", lastActive: "", updatedAt: "2026-10-07T00:00:00Z" };
}

function detail(title: string): SessionDetail {
  return { ...summary("a", title), readOnly: false, archiveState: {}, hiddenFromIndex: false, messages: [], defaultFileContext: "", previewTabs: [], activePreviewPath: "", changedFiles: [], readFiles: [] } as SessionDetail;
}

function arrange() {
  const client = new QueryClient();
  clients.push(client);
  client.setQueryData(queryKeys.sessions(), [summary("a", "Original"), summary("b", "Other session")]);
  client.setQueryData(queryKeys.session("a"), detail("Original"));
  const editingId = { current: null as string | null };
  const editingTitle = { current: "" };
  let errors: Record<string, string> = {};
  const result = useChatWorkspaceLifecycle({
    queryClient: client,
    editingSessionIdRef: editingId,
    editingSessionTitleRef: editingTitle,
    setEditingSessionId: (next) => { editingId.current = typeof next === "function" ? next(editingId.current) : next; },
    setEditingSessionTitle: (next) => { editingTitle.current = typeof next === "function" ? next(editingTitle.current) : next; },
    setSessionComposerErrors: (next) => { errors = typeof next === "function" ? next(errors) : next; },
    describeError: (error: unknown) => error instanceof Error ? error.message : String(error),
    t: (key) => key,
  } as UseChatWorkspaceLifecycleOptions);
  const options = (result.renameSessionMutation as unknown as { options: RenameOptions }).options;
  const start = async (title: string) => {
    const variables = { sessionId: "a", title };
    const context = await options.onMutate!(variables);
    if (!context) throw new Error("Missing rename snapshot");
    return { variables, context };
  };
  const succeed = (attempt: Awaited<ReturnType<typeof start>>) => options.onSuccess!(detail(attempt.variables.title), attempt.variables, attempt.context);
  const fail = (attempt: Awaited<ReturnType<typeof start>>, message: string) => options.onError!(new Error(message), attempt.variables, attempt.context);
  return { client, editingId, editingTitle, errors: () => errors, start, succeed, fail };
}

describe("session rename callback ordering", () => {
  it("confirms only rename fields and keeps a later archive and live messages", async () => {
    const fixture = arrange();
    const attempt = await fixture.start("Renamed");
    const liveMessages = [{ id: "live-message", role: "assistant", content: "Arrived after rename" }] as SessionDetail["messages"];
    const archived = {
      ...detail("Renamed"),
      readOnly: true,
      hiddenFromIndex: true,
      archiveState: { status: "archived", source: "session_archive" },
      messages: liveMessages,
    };
    fixture.client.setQueryData(queryKeys.session("a"), archived);
    await fixture.succeed(attempt);
    expect(fixture.client.getQueryData(queryKeys.session("a"))).toMatchObject({
      title: "Renamed", readOnly: true, hiddenFromIndex: true,
      archiveState: { status: "archived" }, messages: liveMessages,
    });
  });

  it.each(["success", "failure"])("ignores rename %s after deletion", async (outcome) => {
    const fixture = arrange();
    const attempt = await fixture.start("Renamed");
    markSessionDeleteTombstone("a", { confirmed: true });
    fixture.client.removeQueries({ queryKey: queryKeys.session("a"), exact: true });
    fixture.client.setQueryData(queryKeys.sessions(), [summary("b", "Other session")]);
    if (outcome === "success") await fixture.succeed(attempt);
    else await fixture.fail(attempt, "late failure after deletion");
    expect(fixture.client.getQueryData(queryKeys.session("a"))).toBeUndefined();
    expect(fixture.editingId.current).toBeNull();
    expect(fixture.errors().a).toBe("");
    expect(fixture.client.getQueryData<SessionSummary[]>(queryKeys.sessions())).toEqual([summary("b", "Other session")]);
  });

  it("can seed a missing valid detail from its successful response", async () => {
    const fixture = arrange();
    const attempt = await fixture.start("Renamed");
    fixture.client.removeQueries({ queryKey: queryKeys.session("a"), exact: true });
    await fixture.succeed(attempt);
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Renamed");
  });

  it("ignores an older success after a newer success", async () => {
    const fixture = arrange();
    const old = await fixture.start("First");
    const latest = await fixture.start("Latest");
    await fixture.succeed(latest);
    await fixture.succeed(old);
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Latest");
    expect(fixture.client.getQueryData<SessionSummary[]>(queryKeys.sessions())?.[0].title).toBe("Latest");
    expect(fixture.editingId.current).toBeNull();
  });

  it("does not reopen a stale editor or error after a newer success", async () => {
    const fixture = arrange();
    const old = await fixture.start("First");
    const latest = await fixture.start("Latest");
    await fixture.succeed(latest);
    await fixture.fail(old, "obsolete failure");
    expect(fixture.editingId.current).toBeNull();
    expect(fixture.errors().a).toBe("");
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Latest");
  });

  it("keeps the newer title being typed while an in-flight attempt fails", async () => {
    const fixture = arrange();
    const old = await fixture.start("First");
    fixture.editingId.current = "a";
    fixture.editingTitle.current = "New unsaved text";
    await fixture.fail(old, "save failed");
    expect(fixture.editingTitle.current).toBe("New unsaved text");
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Original");
  });

  it.each([true, false])("unwinds both failed titles while keeping the latest retry draft (latest fails first: %s)", async (latestFirst) => {
    const fixture = arrange();
    const old = await fixture.start("First");
    const latest = await fixture.start("Latest");
    if (latestFirst) {
      await fixture.fail(latest, "latest failure");
      await fixture.fail(old, "older failure");
    } else {
      await fixture.fail(old, "older failure");
      await fixture.fail(latest, "latest failure");
    }
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Original");
    expect(fixture.editingTitle.current).toBe("Latest");
    expect(fixture.errors().a).toBe("latest failure");
  });

  it.each([true, false])("keeps a newer identical title when the older attempt fails (old fails first: %s)", async (oldFirst) => {
    const fixture = arrange();
    const old = await fixture.start("Latest");
    const latest = await fixture.start("Latest");
    if (oldFirst) {
      await fixture.fail(old, "older failure");
      expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Latest");
      await fixture.succeed(latest);
    } else {
      await fixture.succeed(latest);
      await fixture.fail(old, "older failure");
    }
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("Latest");
    expect(fixture.errors().a).toBe("");
    expect(fixture.editingId.current).toBeNull();
  });

  it("keeps a newer failure visible when an earlier successful acknowledgement arrives", async () => {
    const fixture = arrange();
    const old = await fixture.start("First");
    const latest = await fixture.start("Latest");
    await fixture.fail(latest, "latest failure");
    await fixture.succeed(old);
    expect(fixture.errors().a).toBe("latest failure");
    expect(fixture.editingTitle.current).toBe("Latest");
    expect(fixture.client.getQueryData<SessionDetail>(queryKeys.session("a"))?.title).toBe("First");
  });
});
