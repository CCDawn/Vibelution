import { describe, expect, it } from "vitest";
import { applyProjectSlot, instanceWorkbenchUrl } from "../src/protocol/applyProjectSlot.js";
import {
  matchBranchInstanceByProjectRoot,
  parseBranchInstanceRecords
} from "../src/protocol/launcherControlClient.js";

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "content-type": "application/json" }
  });
}

const listed = {
  items: [
    {
      id: "main",
      path: "C:/repo",
      slotKey: "c:\\repo",
      url: "http://127.0.0.1:8000",
      port: 8000,
      alive: true,
      current: true,
      checkedOut: true,
      kind: "main"
    },
    {
      id: "worktree:task",
      path: "C:/repo/.worktrees/task",
      slotKey: "c:\\repo\\.worktrees\\task",
      url: "",
      port: 8001,
      alive: false,
      current: false,
      checkedOut: true,
      kind: "worktree"
    }
  ]
};

describe("applyProjectSlot", () => {
  it("matches a path or slotKey without treating slash differences as a new slot", () => {
    const items = parseBranchInstanceRecords(listed);
    expect(matchBranchInstanceByProjectRoot(items, "C:\\repo\\.worktrees\\task")?.id).toBe("worktree:task");
    expect(matchBranchInstanceByProjectRoot(items, "C:/repo/.worktrees/task")?.id).toBe("worktree:task");
    expect(matchBranchInstanceByProjectRoot(items, "c:\\repo")?.id).toBe("main");
  });

  it("opens a live slot URL without starting it again", async () => {
    const requests: string[] = [];
    const result = await applyProjectSlot({
      projectRoot: "C:/repo",
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      fetchImpl: async (url) => {
        requests.push(String(url));
        return jsonResponse(listed);
      }
    });
    expect(result).toEqual({
      instanceId: "main",
      url: "http://127.0.0.1:8000/",
      started: false
    });
    expect(requests).toEqual(["http://127.0.0.1:8765/api/launcher/branch-instances"]);
  });

  it("starts an idle matched worktree then opens the reserved URL", async () => {
    const requests: Array<{ url: string; method: string }> = [];
    const result = await applyProjectSlot({
      projectRoot: "C:/repo/.worktrees/task",
      launcherOrigin: "http://127.0.0.1:8765/launcher",
      controlToken: "token",
      fetchImpl: async (url, init) => {
        requests.push({ url: String(url), method: String(init?.method || "GET") });
        if (String(init?.method || "GET") === "POST") {
          return jsonResponse({ accepted: true, url: "http://127.0.0.1:8001" }, 202);
        }
        if (requests.filter((item) => item.method === "GET").length > 1) {
          return jsonResponse({
            items: [
              {
                ...listed.items[1],
                alive: true,
                url: "http://127.0.0.1:8001"
              }
            ]
          });
        }
        return jsonResponse(listed);
      }
    });
    expect(result).toEqual({
      instanceId: "worktree:task",
      url: "http://127.0.0.1:8001/",
      started: true
    });
    expect(requests.map((item) => item.method)).toEqual(["GET", "POST", "GET"]);
  });

  it("rejects an unknown project path", async () => {
    await expect(
      applyProjectSlot({
        projectRoot: "C:/missing",
        launcherOrigin: "http://127.0.0.1:8765/launcher",
        controlToken: "token",
        fetchImpl: async () => jsonResponse(listed)
      })
    ).rejects.toThrow("找不到对应工作区");
  });

  it("builds a loopback workbench URL from the reserved port", () => {
    expect(instanceWorkbenchUrl({ url: "", port: 8002 })).toBe("http://127.0.0.1:8002/");
  });
});
