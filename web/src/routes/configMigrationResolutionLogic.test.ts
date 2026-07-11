import { describe, expect, it } from "vitest";

import type { ConfigMigrationArtifactConflict } from "../api/types";
import {
  buildArtifactResolutions,
  createArtifactResolutionDrafts,
  isValidSplitUpstreamId,
  updateArtifactResolutionDraft,
} from "./configMigrationResolutionLogic";

function artifactConflict(
  modelId: string,
  allowedResolutions: ConfigMigrationArtifactConflict["allowedResolutions"] = [
    "preserve_upstream_id",
    "split_deployment_artifact",
  ],
): ConfigMigrationArtifactConflict {
  return {
    code: "artifact_path_suspected",
    modelId,
    requiresExplicitResolution: true,
    allowedResolutions,
    verificationState: "unverified_offline",
  };
}

describe("config migration artifact resolution logic", () => {
  it("requires explicit preserve confirmation before constructing a resolution", () => {
    const drafts = createArtifactResolutionDrafts([artifactConflict("local-a")]);
    const selected = updateArtifactResolutionDraft(drafts, "local-a", {
      decision: "preserve_upstream_id",
    });

    expect(buildArtifactResolutions(selected)).toBeNull();

    const confirmed = updateArtifactResolutionDraft(selected, "local-a", {
      preserveConfirmed: true,
    });
    expect(buildArtifactResolutions(confirmed)).toEqual([
      { modelId: "local-a", decision: "preserve_upstream_id" },
    ]);
  });

  it("never permits preserve when the server does not allow it", () => {
    const drafts = createArtifactResolutionDrafts([
      artifactConflict("remote-a", ["split_deployment_artifact"]),
    ]);
    const attempted = updateArtifactResolutionDraft(drafts, "remote-a", {
      decision: "preserve_upstream_id",
      preserveConfirmed: true,
    });

    expect(attempted[0]?.decision).toBe("");
    expect(buildArtifactResolutions(attempted)).toBeNull();
  });

  it.each([
    "",
    "./model-a",
    "../model-a",
    ".\\model-a",
    "..\\model-a",
    "/models/model-a",
    "C:\\models\\model-a",
    "\\\\server\\models\\model-a",
    "weights.gguf",
    "weights.safetensors",
    "weights.bin",
  ])("rejects path-like split upstreamId %j", (upstreamId) => {
    expect(isValidSplitUpstreamId(upstreamId)).toBe(false);
  });

  it("accepts a namespace-qualified split upstreamId and constructs the exact union item", () => {
    expect(isValidSplitUpstreamId("namespace/model-a")).toBe(true);

    const drafts = createArtifactResolutionDrafts([artifactConflict("local-a")]);
    const split = updateArtifactResolutionDraft(drafts, "local-a", {
      decision: "split_deployment_artifact",
      upstreamId: " namespace/model-a ",
    });

    expect(buildArtifactResolutions(split)).toEqual([
      {
        modelId: "local-a",
        decision: "split_deployment_artifact",
        upstreamId: "namespace/model-a",
      },
    ]);
  });

  it("emits at most one resolution per modelId in first-conflict order", () => {
    const drafts = createArtifactResolutionDrafts([
      artifactConflict("model-b"),
      artifactConflict("model-a"),
      artifactConflict("model-b"),
    ]);
    const selectedB = updateArtifactResolutionDraft(drafts, "model-b", {
      decision: "preserve_upstream_id",
      preserveConfirmed: true,
    });
    const selectedA = updateArtifactResolutionDraft(selectedB, "model-a", {
      decision: "split_deployment_artifact",
      upstreamId: "namespace/model-a",
    });

    expect(buildArtifactResolutions(selectedA)).toEqual([
      { modelId: "model-b", decision: "preserve_upstream_id" },
      {
        modelId: "model-a",
        decision: "split_deployment_artifact",
        upstreamId: "namespace/model-a",
      },
    ]);
  });
});
