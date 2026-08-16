import { describe, expect, it } from "vitest";

import apiSource from "./git.ts?raw";
import routeSource from "../routes/GitRoute.tsx?raw";

describe("git catalog API", () => {
  it("owns the Git JSON transports", () => {
    expect(apiSource).toContain("export function fetchGitStatus");
    expect(apiSource).toContain("export function fetchGitCommits");
    expect(apiSource).toContain("export function fetchGitFileDiff");
    expect(apiSource).toContain("export function fetchGitObjectDetail");
    expect(apiSource).toContain("export function generateGitCommitMessage");
    expect(apiSource).toContain("export function updateGitCommitMessageDefaultModel");
    expect(apiSource).toContain("export function updateGitCommitMessagePrompt");
    expect(apiSource).toContain("export function createGitCommit");
    expect(apiSource).toContain("/api/git/status?limit=");
    expect(apiSource).toContain("/api/git/commits?limit=");
    expect(apiSource).toContain("/api/git/diff?path=${encodeURIComponent(path)}");
    expect(apiSource).toContain("/api/git/object-detail?");
    expect(apiSource).toContain('"/api/git/commit-message"');
    expect(apiSource).toContain('"/api/git/commit-message/default-model"');
    expect(apiSource).toContain('"/api/git/commit-message/prompt"');
    expect(apiSource).toContain('"/api/git/commit"');
  });

  it("keeps GitRoute free of Git JSON paths", () => {
    expect(routeSource).toContain("fetchGitStatus(");
    expect(routeSource).toContain("fetchGitCommits(");
    expect(routeSource).toContain("fetchGitFileDiff(");
    expect(routeSource).toContain("fetchGitObjectDetail(");
    expect(routeSource).toContain("generateGitCommitMessage(");
    expect(routeSource).toContain("updateGitCommitMessageDefaultModel(");
    expect(routeSource).toContain("updateGitCommitMessagePrompt(");
    expect(routeSource).toContain("createGitCommit(");
    expect(routeSource).not.toContain("/api/git/");
    expect(routeSource).not.toContain('from "../api/client"');
  });
});
