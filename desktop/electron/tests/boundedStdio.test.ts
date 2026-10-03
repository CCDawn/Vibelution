import { spawn } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { describe, expect, it } from "vitest";
import { BoundedStdioSink } from "../src/process/boundedStdio.js";

describe("bounded backend stdio", () => {
  it("keeps the newest output across rotations and converges oversized history", async () => {
    const root = await mkdtemp(join(tmpdir(), "vibelution-stdio-"));
    try {
      const path = join(root, "stdout.log");
      for (let index = 0; index <= 3; index++) {
        await writeFile(index ? `${path}.${index}` : path, "old-prefix-".repeat(12) + "LATEST-HISTORY");
      }
      const sink = new BoundedStdioSink(path, { maxBytes: 32 });
      const output = Buffer.from("new-output-".repeat(24) + "LATEST-OUTPUT");
      sink.end(output);
      expect(await sink.completion).toMatchObject({ complete: true, errorCode: null, droppedBytes: 0 });
      const files = await readdir(root);
      expect(files.sort()).toEqual(["stdout.log", "stdout.log.1", "stdout.log.2", "stdout.log.3"]);
      for (const file of files) expect((await stat(join(root, file))).size).toBeLessThanOrEqual(32);
      const retained = Buffer.concat(await Promise.all([3, 2, 1, 0].map((index) => readFile(index ? `${path}.${index}` : path))));
      expect(retained).toEqual(output.subarray(output.length - retained.length));
    } finally { await rm(root, { recursive: true, force: true }); }
  });

  it("continues consuming output after rotation fails and closes the file", async () => {
    const root = await mkdtemp(join(tmpdir(), "vibelution-stdio-failure-"));
    try {
      const path = join(root, "stdout.log");
      const source = new PassThrough({ highWaterMark: 32 * 1024 });
      const sink = new BoundedStdioSink(path, { maxBytes: 32 });
      await new Promise<void>((resolveWrite) => sink.write(Buffer.alloc(32), () => resolveWrite()));
      await mkdir(`${path}.3`);
      source.pipe(sink);
      for (let index = 0; index < 24; index++) {
        if (!source.write(Buffer.alloc(32 * 1024, index))) await once(source, "drain");
        expect(sink.writableLength).toBeLessThanOrEqual(64 * 1024);
      }
      source.end();
      const result = await sink.completion;
      expect(result.complete).toBe(true);
      expect(result.errorCode).toBeTruthy();
      expect(result.droppedBytes).toBe(24 * 32 * 1024);
      expect((await stat(path)).size).toBe(32);
      // Removal after EOF proves the writer relinquished its handle on Windows.
      await rm(path);
    } finally { await rm(root, { recursive: true, force: true }); }
  });

  it("drains simultaneous real child stdout and stderr through EOF and file close", async () => {
    const root = await mkdtemp(join(tmpdir(), "vibelution-stdio-child-"));
    const child = spawn(process.execPath, ["-e", `
      const { once } = require('node:events');
      async function emit(stream, character) {
        for (let index = 0; index < 256; index++) {
          if (!stream.write(Buffer.alloc(4096, character))) await once(stream, 'drain');
        }
        stream.write('LATEST-' + character);
      }
      Promise.all([emit(process.stdout, 'o'), emit(process.stderr, 'e')]);
    `], { windowsHide: true, stdio: ["ignore", "pipe", "pipe"] });
    try {
      const stdout = new BoundedStdioSink(join(root, "stdout.log"), { maxBytes: 8192 });
      const stderr = new BoundedStdioSink(join(root, "stderr.log"), { maxBytes: 8192 });
      child.stdout.pipe(stdout);
      child.stderr.pipe(stderr);
      const exited = once(child, "close");
      expect(await exited).toEqual([0, null]);
      for (const sink of [stdout, stderr]) {
        expect(await sink.completion).toMatchObject({ complete: true, errorCode: null, droppedBytes: 0 });
      }
      expect((await readFile(stdout.path, "utf8")).endsWith("LATEST-o")).toBe(true);
      expect((await readFile(stderr.path, "utf8")).endsWith("LATEST-e")).toBe(true);
      for (const file of await readdir(root)) expect((await stat(join(root, file))).size).toBeLessThanOrEqual(8192);
    } finally {
      if (child.exitCode === null) { child.kill(); await once(child, "close"); }
      await rm(root, { recursive: true, force: true });
    }
  }, 15_000);
});
