import { describe, expect, it } from "vitest";
import { waitForRestart, type HealthPing } from "./restart";

function clock() {
  let t = 0;
  return { now: () => t, sleep: async (ms: number) => void (t += ms) };
}

function pings(list: HealthPing[]) {
  let i = 0;
  return { ping: async () => list[Math.min(i++, list.length - 1)], count: () => i };
}

describe("waiting for a restart", () => {
  it("waits until a different boot id answers", async () => {
    const p = pings([
      { up: true, boot: "b1" }, // the old process is still answering
      { up: true, boot: "b1" },
      { up: false },
      { up: true, boot: "b2" },
    ]);
    const r = await waitForRestart({ ping: p.ping, previousBoot: "b1", ...clock(), intervalMs: 1000 });
    expect(r).toBe("up");
    expect(p.count()).toBe(4);
  });

  it("does not stop at an old answer, however long the old process keeps running", async () => {
    const p = pings([{ up: true, boot: "b1" }]);
    const r = await waitForRestart({ ping: p.ping, previousBoot: "b1", ...clock(), timeoutMs: 20_000, downWithinMs: 1000 });
    expect(r).toBe("timeout");
  });

  it("falls back to seeing the server go down when there is no boot id", async () => {
    const p = pings([{ up: true }, { up: false }, { up: true }]);
    const r = await waitForRestart({ ping: p.ping, ...clock(), intervalMs: 1000, downWithinMs: 10_000 });
    expect(r).toBe("up");
    expect(p.count()).toBe(3);
  });

  it("treats errors as down, times out and can be aborted", async () => {
    expect(await waitForRestart({ ping: () => Promise.reject(new Error("offline")), ...clock(), timeoutMs: 5000 })).toBe("timeout");
    const ctl = new AbortController();
    ctl.abort();
    expect(await waitForRestart({ ping: async () => ({ up: false }), signal: ctl.signal })).toBe("aborted");
  });
});
