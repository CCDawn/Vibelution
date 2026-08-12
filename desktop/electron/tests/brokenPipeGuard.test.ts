import { describe, expect, it, vi } from "vitest";
import { installBrokenPipeGuards, isBrokenPipeError } from "../src/runtime/brokenPipeGuard.js";

function epipeError(): NodeJS.ErrnoException {
  const error = new Error("EPIPE: broken pipe, write") as NodeJS.ErrnoException;
  error.code = "EPIPE";
  return error;
}

describe("broken pipe console guard", () => {
  it("recognizes EPIPE errors", () => {
    expect(isBrokenPipeError(epipeError())).toBe(true);
    expect(isBrokenPipeError(new Error("other"))).toBe(false);
    expect(isBrokenPipeError("EPIPE")).toBe(false);
  });

  it("swallows console.warn EPIPE so heartbeat and shutdown cannot crash Electron", () => {
    const warn = vi.fn(() => {
      throw epipeError();
    });
    const target = {
      console: {
        log: vi.fn(),
        info: vi.fn(),
        warn,
        error: vi.fn()
      }
    };

    installBrokenPipeGuards(target);
    expect(() => target.console.warn("desktop session heartbeat failed")).not.toThrow();
    expect(warn).toHaveBeenCalledWith("desktop session heartbeat failed");
  });

  it("still throws non-EPIPE console failures", () => {
    const warn = vi.fn(() => {
      throw new Error("disk full");
    });
    const target = {
      console: {
        log: vi.fn(),
        info: vi.fn(),
        warn,
        error: vi.fn()
      }
    };

    installBrokenPipeGuards(target);
    expect(() => target.console.warn("still visible")).toThrow("disk full");
  });

  it("ignores stdout and stderr EPIPE events without rethrowing", () => {
    const listeners: Array<(error: Error) => void> = [];
    const stream = {
      on: (_event: "error", listener: (error: Error) => void) => {
        listeners.push(listener);
      }
    };

    installBrokenPipeGuards({
      stdout: stream,
      stderr: stream,
      console: {
        log: vi.fn(),
        info: vi.fn(),
        warn: vi.fn(),
        error: vi.fn()
      }
    });

    expect(listeners).toHaveLength(2);
    expect(() => listeners[0]?.(epipeError())).not.toThrow();
    expect(() => listeners[1]?.(new Error("disk full"))).toThrow("disk full");
  });
});
