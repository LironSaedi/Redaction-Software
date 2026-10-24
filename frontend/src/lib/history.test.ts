import { describe, expect, it, vi } from "vitest";
import { OpHistory, type HistoryEntry } from "./history";

function counter() {
  const log: string[] = [];
  const entry = (name: string): HistoryEntry => ({
    label: name,
    undo: async () => {
      log.push(`undo ${name}`);
    },
    redo: async () => {
      log.push(`redo ${name}`);
    },
  });
  return { log, entry };
}

describe("OpHistory", () => {
  it("undoes in reverse order and redoes forward", async () => {
    const h = new OpHistory();
    const { log, entry } = counter();
    h.push(entry("a"));
    h.push(entry("b"));
    expect(h.snapshot()).toMatchObject({ canUndo: true, canRedo: false, undoLabel: "b" });
    expect(await h.undo()).toBe(true);
    expect(await h.undo()).toBe(true);
    expect(await h.undo()).toBe(false); // nothing left
    expect(h.snapshot()).toMatchObject({ canUndo: false, canRedo: true, redoLabel: "a" });
    expect(await h.redo()).toBe(true);
    expect(log).toEqual(["undo b", "undo a", "redo a"]);
    expect(h.size).toEqual({ past: 1, future: 1 });
  });

  it("a new operation clears the redo stack", async () => {
    const h = new OpHistory();
    const { entry } = counter();
    h.push(entry("a"));
    await h.undo();
    h.push(entry("c"));
    expect(h.snapshot().canRedo).toBe(false);
    expect(h.snapshot().undoLabel).toBe("c");
  });

  it("keeps an entry whose inverse call failed, so it can be retried", async () => {
    const h = new OpHistory();
    h.push({ label: "x", undo: () => Promise.reject(new Error("offline")), redo: async () => undefined });
    await expect(h.undo()).rejects.toThrow("offline");
    expect(h.size).toEqual({ past: 1, future: 0 });
    expect(h.snapshot().busy).toBe(false);
  });

  it("ignores undo while another step runs", async () => {
    const h = new OpHistory();
    let release: () => void = () => undefined;
    h.push({ label: "slow", undo: () => new Promise<void>((r) => (release = r)), redo: async () => undefined });
    h.push({ label: "fast", undo: async () => undefined, redo: async () => undefined });
    const first = h.undo();
    expect(h.snapshot().busy).toBe(true);
    expect(await h.undo()).toBe(false);
    release();
    await first;
  });

  it("is bounded and notifies subscribers", () => {
    const h = new OpHistory(3);
    const fn = vi.fn();
    const off = h.subscribe(fn);
    const { entry } = counter();
    for (const n of ["1", "2", "3", "4", "5"]) h.push(entry(n));
    expect(h.size.past).toBe(3);
    expect(fn).toHaveBeenCalledTimes(5);
    off();
    h.clear();
    expect(fn).toHaveBeenCalledTimes(5);
    expect(h.snapshot().canUndo).toBe(false);
  });

  it("returns a stable snapshot between changes (useSyncExternalStore)", () => {
    const h = new OpHistory();
    expect(h.snapshot()).toBe(h.snapshot());
  });
});

describe("undo / redo of an add with delete + restore (same id)", () => {
  it("removes and restores the very same item", async () => {
    const server = new Map<string, { id: string; score: number }>([["d1", { id: "d1", score: 0.73 }]]);
    let snapshot: { id: string; score: number }[] = [];
    const h = new OpHistory();
    h.push({
      label: "Add rectangle",
      undo: async () => {
        snapshot = [server.get("d1")!];
        server.delete("d1");
      },
      redo: async () => {
        for (const d of snapshot) server.set(d.id, d);
      },
    });
    await h.undo();
    expect([...server.keys()]).toEqual([]);
    await h.redo();
    expect(server.get("d1")).toEqual({ id: "d1", score: 0.73 });
    await h.undo();
    await h.redo();
    expect([...server.keys()]).toEqual(["d1"]);
  });
});
