import { createHash } from "node:crypto";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve, toNamespacedPath } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { resolveAssistantResources } from "../src/assistant/assistantResources.js";
import { sha256DirectoryTree } from "../src/packaging/frontendBundle.js";

const temporaryRoots: string[] = [];
const digest = (value: string | Buffer) => createHash("sha256").update(value).digest("hex");
const machine = process.arch === "arm64" ? "ARM64" : process.arch === "ia32" ? "x86" : "AMD64";

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    if (!resolve(root).startsWith(resolve(tmpdir()) + "/") && !resolve(root).startsWith(resolve(tmpdir()) + "\\")) {
      throw new Error("test temporary path escaped");
    }
    rmSync(root, { recursive: true, force: true });
  }
});

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "assistant-resources-test-"));
  temporaryRoots.push(root);
  const resourcesRoot = join(root, "resources");
  const payloadRoot = join(resourcesRoot, "launcher-assistant");
  const manifestPath = join(payloadRoot, "manifest.json");
  const provenancePath = join(resourcesRoot, "app.asar.unpacked", "package-provenance.json");
  const manifest: Record<string, unknown> = {
    schemaVersion: 1, protocolVersion: 1, platform: "win32", machine,
    pythonVersion: "3.12.9", pythonAbi: "cp312", entrypoint: "source/scripts/assistant_host.py",
    pythonEntrypoint: "python/pythonw.exe", sourceContentSha256: "a".repeat(64),
    runtimeContentSha256: "b".repeat(64), requirementsSha256: digest("fixture requirements\n"),
    contractsSha256: digest("fixture contracts\n"),
  };
  mkdirSync(join(payloadRoot, "source/scripts"), { recursive: true });
  mkdirSync(join(payloadRoot, "source/core/external_agent"), { recursive: true });
  mkdirSync(join(payloadRoot, "python"), { recursive: true });
  mkdirSync(dirname(provenancePath), { recursive: true });
  writeFileSync(join(payloadRoot, "source/scripts/assistant_host.py"), "# never executed\n");
  writeFileSync(join(payloadRoot, "source/requirements.txt"), "fixture requirements\n");
  writeFileSync(join(payloadRoot, "source/core/external_agent/contracts.py"), "fixture contracts\n");
  writeFileSync(join(payloadRoot, "python/pythonw.exe"), "fixture bytes, never launched\n");
  let evidence: Record<string, unknown>;
  function publish() {
    writeFileSync(manifestPath, JSON.stringify(manifest));
    evidence = { manifestSha256: digest(readFileSync(manifestPath)), contentSha256: sha256DirectoryTree(payloadRoot),
      sourceContentSha256: manifest.sourceContentSha256, runtimeContentSha256: manifest.runtimeContentSha256,
      requirementsSha256: manifest.requirementsSha256, contractsSha256: manifest.contractsSha256,
      pythonVersion: manifest.pythonVersion };
    writeFileSync(provenancePath, JSON.stringify({ schemaVersion: 1, assistant: evidence }));
    return evidence;
  }
  const initialEvidence = publish();
  const hashTree = vi.fn(async (path: string) => sha256DirectoryTree(path));
  const input = { packaged: true, resourcesRoot, developmentSourceRoot: join(root, "unrelated-project"),
    developmentPythonPath: join(root, "unrelated-python.exe"),
    env: { PYTHONPATH: "do-not-inherit", PythonHome: "do-not-inherit", API_KEY: "provider-secret",
      VIBELUTION_CONFIG_PATH: join(root, "operator/config.toml"), VIBELUTION_PROVIDER_KEY_REF: "provider-reference" }, hashTree };
  return { input, manifest, manifestPath, provenancePath, payloadRoot, initialEvidence, publish, hashTree };
}

describe("assistant development resources", () => {
  it("preserves explicit development paths and references while removing Python path injection", async () => {
    const f = fixture();
    const input = { ...f.input, packaged: false };
    const result = await resolveAssistantResources(input);
    expect(result.sourceRoot).toBe(input.developmentSourceRoot);
    expect(result.pythonPath).toBe(input.developmentPythonPath);
    expect(result.pythonArguments).toEqual([]);
    expect(result.payloadRoot).toBeNull();
    expect(result.payloadEvidence).toBeNull();
    expect(result.env).toEqual({ API_KEY: "provider-secret", VIBELUTION_CONFIG_PATH: input.env.VIBELUTION_CONFIG_PATH,
      VIBELUTION_PROVIDER_KEY_REF: "provider-reference" });
    expect(input.env.PYTHONPATH).toBe("do-not-inherit");
    expect(f.hashTree).not.toHaveBeenCalled();
  });
});

describe.skipIf(process.platform !== "win32")("assistant packaged resources", () => {
  it("pins package-local paths and every published digest without consulting a development project", async () => {
    const f = fixture();
    const result = await resolveAssistantResources(f.input);
    expect(result.sourceRoot).toBe(toNamespacedPath(join(f.payloadRoot, "source")));
    expect(result.pythonPath).toBe(toNamespacedPath(join(f.payloadRoot, "python/pythonw.exe")));
    expect(result.payloadRoot).toBe(toNamespacedPath(f.payloadRoot));
    expect(result.pythonArguments).toEqual(["-I", "-B", "-X", "utf8"]);
    expect(result.payloadEvidence).toEqual(f.initialEvidence);
    expect(result.env.API_KEY).toBe("provider-secret");
    expect(result.env).not.toHaveProperty("PYTHONPATH");
    expect(result.env).not.toHaveProperty("PythonHome");
    expect(f.hashTree).toHaveBeenCalledExactlyOnceWith(toNamespacedPath(f.payloadRoot));
    expect(JSON.stringify(result.payloadEvidence)).not.toContain("provider-secret");
    expect(JSON.stringify(result.payloadEvidence)).not.toContain(f.payloadRoot);
  });

  it("rejects unavailable package resources rather than falling back to valid development paths", async () => {
    const f = fixture();
    const input = { ...f.input, resourcesRoot: join(f.input.resourcesRoot, "missing"),
      developmentSourceRoot: join(f.payloadRoot, "source"), developmentPythonPath: join(f.payloadRoot, "python/pythonw.exe") };
    await expect(resolveAssistantResources(input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_RESOURCE_UNAVAILABLE" });
    expect(f.hashTree).not.toHaveBeenCalled();
  });

  it("rejects manifest byte changes even when JSON metadata still looks valid", async () => {
    const f = fixture();
    writeFileSync(f.manifestPath, readFileSync(f.manifestPath, "utf8") + " ");
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_MANIFEST_INVALID" });
    expect(f.hashTree).not.toHaveBeenCalled();
  });

  it.each(["entrypoint", "pythonEntrypoint", "schemaVersion", "protocolVersion", "platform", "pythonAbi", "machine"])(
    "rejects incompatible %s metadata pinned by provenance", async field => {
      const f = fixture();
      f.manifest[field] = field === "protocolVersion" ? 2 : field === "entrypoint" ? "../outside.py" : "incompatible";
      f.publish();
      await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_MANIFEST_INVALID" });
      expect(f.hashTree).not.toHaveBeenCalled();
    });

  it("checks the CPython ABI against the pinned Python version", async () => {
    const f = fixture();
    f.manifest.pythonVersion = "3.13.1";
    f.publish();
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_MANIFEST_INVALID" });
    expect(f.hashTree).not.toHaveBeenCalled();
  });

  it.each(["sourceContentSha256", "runtimeContentSha256", "requirementsSha256", "contractsSha256", "pythonVersion"])(
    "rejects a manifest whose %s disagrees with package provenance", async field => {
      const f = fixture();
      const evidence = { ...f.initialEvidence, [field]: field === "pythonVersion" ? "3.13.1" : "f".repeat(64) };
      writeFileSync(f.provenancePath, JSON.stringify({ assistant: evidence }));
      await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_MANIFEST_INVALID" });
      expect(f.hashTree).not.toHaveBeenCalled();
    });

  it.each(["runtime bytes", "extra file"])("rejects changed %s through the full directory digest", async changed => {
    const f = fixture();
    writeFileSync(join(f.payloadRoot, changed === "runtime bytes" ? "python/pythonw.exe" : "python/extra.pth"), "tampered\n");
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_PAYLOAD_INTEGRITY_FAILED" });
    expect(f.hashTree).toHaveBeenCalledOnce();
  });

  it("returns only a bounded error when hashing fails with sensitive transport details", async () => {
    const f = fixture();
    f.hashTree.mockRejectedValue(new Error("provider-secret " + f.payloadRoot));
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({
      message: "ASSISTANT_PAYLOAD_HASH_FAILED", boundedCode: "ASSISTANT_PAYLOAD_HASH_FAILED" });
  });

  it("bounds JSON inputs before invoking the payload hash worker", async () => {
    const f = fixture();
    writeFileSync(f.provenancePath, " ".repeat(256 * 1024 + 1));
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_PROVENANCE_INVALID" });
    expect(f.hashTree).not.toHaveBeenCalled();
  });

  it("rejects missing assistant provenance without reading the payload", async () => {
    const f = fixture();
    writeFileSync(f.provenancePath, JSON.stringify({ schemaVersion: 1 }));
    await expect(resolveAssistantResources(f.input)).rejects.toMatchObject({ boundedCode: "ASSISTANT_PROVENANCE_INVALID" });
    expect(f.hashTree).not.toHaveBeenCalled();
  });
});
