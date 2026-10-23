import { afterEach, expect, it, vi } from "vitest";
import { seedControlTokenForTests } from "./client";
import { archiveChatSession, unarchiveChatSession } from "./sessionArchive";
import { deleteChatRoom, resetChatRoom, startChatRoomRound, stopChatRoomRound, updateChatRoom } from "./chat";

afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it.each([
  ["archive", () => archiveChatSession("A")],
  ["unarchive", () => unarchiveChatSession("A")],
  ["update room", () => updateChatRoom("A", { title: "A", participantSessionIds: ["a", "b"], mode: "round_robin", purpose: "discussion" })],
  ["delete room", () => deleteChatRoom("A")],
  ["reset room", () => resetChatRoom("A")],
  ["stop room", () => stopChatRoomRound("A")],
  ["start room", () => startChatRoomRound("A", { topic: "topic", mode: "round_robin", purpose: "discussion" }, { preferAsync: true })],
] as const)("bounds %s even when fetch ignores abort, without retrying the write", async (_name, execute) => {
  vi.useFakeTimers(); seedControlTokenForTests();
  const fetchMock = vi.fn(() => new Promise<Response>(() => undefined)); vi.stubGlobal("fetch", fetchMock);
  const pending = execute();
  const rejected = expect(pending).rejects.toMatchObject({ name: "TimeoutError" });
  await vi.advanceTimersByTimeAsync(30_000); await rejected;
  expect(fetchMock).toHaveBeenCalledTimes(1);
  expect((fetchMock.mock.calls[0] as unknown as [string, RequestInit])[1].signal?.aborted).toBe(true);
});
