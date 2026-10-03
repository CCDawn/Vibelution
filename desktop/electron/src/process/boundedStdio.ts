import { open, rename, rm, type FileHandle } from "node:fs/promises";
import { Writable } from "node:stream";

export const BACKEND_LOG_MAX_BYTES = 64 * 1024 * 1024;
export const BACKEND_LOG_BACKUPS = 3;
const COPY_BUFFER_BYTES = 32 * 1024;

export type BoundedStdioStatus = {
  complete: boolean;
  errorCode: string | null;
  droppedBytes: number;
  rotations: number;
};

/** One writer per file; stream backpressure bounds pending output in memory. */
export class BoundedStdioSink extends Writable {
  readonly completion: Promise<BoundedStdioStatus>;
  private resolveCompletion!: (status: BoundedStdioStatus) => void;
  private file: FileHandle | null = null;
  private readonly ownedFiles = new Set<FileHandle>();
  private size = 0;
  private initialized = false;
  private discarding = false;
  private status: BoundedStdioStatus = {
    complete: false, errorCode: null, droppedBytes: 0, rotations: 0
  };
  private readonly maxBytes: number;
  private readonly backupCount: number;

  constructor(readonly path: string, options: { maxBytes?: number; backupCount?: number } = {}) {
    super({ highWaterMark: COPY_BUFFER_BYTES });
    this.maxBytes = options.maxBytes ?? BACKEND_LOG_MAX_BYTES;
    this.backupCount = options.backupCount ?? BACKEND_LOG_BACKUPS;
    if (!Number.isSafeInteger(this.maxBytes) || this.maxBytes < 1
      || !Number.isSafeInteger(this.backupCount) || this.backupCount < 1) {
      throw new RangeError("Log limits must be positive integers");
    }
    this.completion = new Promise((resolveCompletion) => { this.resolveCompletion = resolveCompletion; });
  }

  snapshot(): BoundedStdioStatus { return { ...this.status }; }

  async retire(): Promise<BoundedStdioStatus> {
    await this.completion;
    if (!this.status.complete && this.writableFinished) this.status.complete = await this.closeFile();
    return this.snapshot();
  }

  recordError(error: unknown): void {
    this.status.errorCode ??= String((error as NodeJS.ErrnoException)?.code || "stdio_io_error").slice(0, 80);
  }

  private async closeHandle(file: FileHandle): Promise<boolean> {
    try {
      await file.close();
      this.ownedFiles.delete(file);
      return true;
    } catch (error) {
      this.recordError(error);
      if (file.fd === -1) this.ownedFiles.delete(file);
      return !this.ownedFiles.has(file);
    }
  }

  private async closeFile(): Promise<boolean> {
    for (const file of this.ownedFiles) await this.closeHandle(file);
    if (this.file && !this.ownedFiles.has(this.file)) this.file = null;
    return this.ownedFiles.size === 0;
  }

  private async trimHistoricalFile(path: string): Promise<void> {
    let file: FileHandle;
    try { file = await open(path, "r+"); }
    catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return;
      throw error;
    }
    this.ownedFiles.add(file);
    try {
      const size = (await file.stat()).size;
      if (size <= this.maxBytes) return;
      const buffer = Buffer.allocUnsafe(Math.min(COPY_BUFFER_BYTES, this.maxBytes));
      let offset = 0;
      while (offset < this.maxBytes) {
        const { bytesRead } = await file.read(buffer, 0,
          Math.min(buffer.length, this.maxBytes - offset), size - this.maxBytes + offset);
        if (!bytesRead) throw new Error("Log tail changed during normalization");
        let written = 0;
        while (written < bytesRead) {
          const { bytesWritten } = await file.write(buffer, written, bytesRead - written, offset + written);
          if (!bytesWritten) throw new Error("Log tail write made no progress");
          written += bytesWritten;
        }
        offset += bytesRead;
      }
      await file.truncate(this.maxBytes);
    } finally {
      if (!(await this.closeHandle(file))) throw new Error("Historical log handle did not close");
    }
  }

  private async initialize(): Promise<void> {
    if (this.initialized) return;
    // Converge logs left by earlier unlimited writers without reading them all.
    for (let index = 0; index <= this.backupCount; index++) {
      await this.trimHistoricalFile(index ? `${this.path}.${index}` : this.path);
    }
    this.file = await open(this.path, "a");
    this.ownedFiles.add(this.file);
    this.size = (await this.file.stat()).size;
    this.initialized = true;
  }

  private async rotate(): Promise<void> {
    if (!(await this.closeFile())) throw new Error("Log writer did not close before rotation");
    await rm(`${this.path}.${this.backupCount}`, { force: true });
    for (let index = this.backupCount - 1; index >= 0; index--) {
      try { await rename(index ? `${this.path}.${index}` : this.path, `${this.path}.${index + 1}`); }
      catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
      }
    }
    this.file = await open(this.path, "a");
    this.ownedFiles.add(this.file);
    this.size = 0;
    this.status.rotations++;
  }

  private async writeChunk(chunk: Buffer): Promise<void> {
    let offset = 0;
    try {
      if (this.discarding) { this.status.droppedBytes += chunk.length; return; }
      await this.initialize();
      while (offset < chunk.length) {
        if (this.size >= this.maxBytes) await this.rotate();
        const count = Math.min(chunk.length - offset, this.maxBytes - this.size, COPY_BUFFER_BYTES);
        const { bytesWritten } = await this.file!.write(chunk, offset, count, null);
        if (!bytesWritten) throw new Error("Log writer made no progress");
        this.size += bytesWritten;
        offset += bytesWritten;
      }
    } catch (error) {
      // Logging failure must not fill the OS pipe and wedge backend shutdown.
      this.recordError(error);
      this.status.droppedBytes += chunk.length - offset;
      this.discarding = true;
      await this.closeFile();
    }
  }

  override _write(chunk: Buffer, _encoding: BufferEncoding, callback: (error?: Error | null) => void): void {
    void this.writeChunk(chunk).then(() => callback(), (error) => {
      this.recordError(error); callback();
    });
  }

  override _final(callback: (error?: Error | null) => void): void {
    void this.closeFile().then((closed) => {
      this.status.complete = closed;
      this.resolveCompletion(this.snapshot());
      callback();
    });
  }
}
