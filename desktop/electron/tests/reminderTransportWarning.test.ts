import { describe, expect, it, vi } from "vitest";
import { createReminderTransportWarningGate } from "../src/assistant/reminderPump.js";

describe("reminder transport warning gate", () => {
  it("stays silent on a single transient transport failure", () => {
    const warn = vi.fn(() => undefined);
    const gate = createReminderTransportWarningGate({ warn });
    expect(gate.transportFailure()).toBe(1);
    expect(warn).not.toHaveBeenCalled();
  });

  it("warns once when the consecutive failure limit is reached", () => {
    const warn = vi.fn(() => undefined);
    const gate = createReminderTransportWarningGate({ warn });
    expect(gate.transportFailure()).toBe(1);
    expect(gate.transportFailure()).toBe(2);
    expect(gate.transportFailure()).toBe(3);
    expect(warn).toHaveBeenCalledOnce();
  });

  it("keeps the streak latched so a continuing outage cannot spam dialogs", () => {
    const warn = vi.fn(() => undefined);
    const gate = createReminderTransportWarningGate({ warn });
    for (let failures = 0; failures < 6; failures++) gate.transportFailure();
    expect(warn).toHaveBeenCalledOnce();
  });

  it("clears the consecutive streak on any successful reminder RPC", () => {
    const warn = vi.fn(() => undefined);
    const gate = createReminderTransportWarningGate({ warn });
    gate.transportFailure();
    gate.transportFailure();
    gate.transportSuccess();
    expect(gate.transportFailure()).toBe(1);
    gate.transportSuccess();
    gate.transportFailure();
    gate.transportFailure();
    expect(warn).not.toHaveBeenCalled();
    gate.transportFailure();
    expect(warn).toHaveBeenCalledOnce();
  });

  it("does not duplicate the dialog while one is still open", async () => {
    let closeDialog!: () => void;
    const warn = vi.fn(() => new Promise<void>(resolve => { closeDialog = resolve; }));
    const gate = createReminderTransportWarningGate({ warn });
    gate.transportFailure();
    gate.transportFailure();
    gate.transportFailure();
    expect(warn).toHaveBeenCalledOnce();
    // Recovery re-arms the gate while the user has not closed the dialog yet.
    gate.transportSuccess();
    gate.transportFailure();
    gate.transportFailure();
    gate.transportFailure();
    expect(warn).toHaveBeenCalledOnce();
    closeDialog();
    await Promise.resolve();
    gate.transportFailure();
    expect(warn).toHaveBeenCalledTimes(2);
  });

  it("honors a custom limit", () => {
    const warn = vi.fn(() => undefined);
    const gate = createReminderTransportWarningGate({ warn, limit: 2 });
    gate.transportFailure();
    expect(warn).not.toHaveBeenCalled();
    gate.transportFailure();
    expect(warn).toHaveBeenCalledOnce();
  });
});
