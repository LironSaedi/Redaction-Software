import { describe, expect, it, vi } from "vitest";
import { changeCount, changesOf, redoCaseRedaction, undoCaseRedaction, type CaseUndoClient } from "./caseRedaction";
import type { Detection, RedactTextOut } from "../types";

const det = (id: string): Detection => ({
  id, entity: "CUSTOM", text: "", score: 1, source: "term", boxes: [], page: 0, start: 1, end: 4, explanation: "",
  selected: true, exemption: "", partial: null, kind: "text", meta: {},
});

function run(): RedactTextOut {
  return {
    preview: false,
    total_matches: 4,
    total_added: 3,
    remembered: true,
    list_id: 9,
    files: [
      { file_id: 1, name: "a.pdf", matches: 2, added: 2, added_ids: ["n1", "s1"], new_ids: ["n1"], switched_ids: ["s1"] },
      { file_id: 2, name: "b.docx", matches: 1, added: 1, added_ids: ["n2"], new_ids: ["n2"], switched_ids: [] },
      { file_id: 3, name: "c.txt", matches: 1, added: 0, added_ids: [], new_ids: [], switched_ids: [] },
      { file_id: 4, name: "d.pdf", matches: 0, added: 0, added_ids: [], skipped: "not analysed yet" },
    ],
  };
}

function fakeClient() {
  const calls: string[] = [];
  const client: CaseUndoClient = {
    getDetections: vi.fn(async (f: number) => (f === 1 ? [det("n1"), det("s1"), det("old")] : [det("n2")])),
    deleteDetections: vi.fn(async (f: number, ids: string[]) => void calls.push(`delete ${f} ${ids.join(",")}`)),
    setSelected: vi.fn(async (f: number, ids: string[], sel: boolean) => void calls.push(`select ${f} ${ids.join(",")} ${sel}`)),
    restore: vi.fn(async (f: number, ds: Detection[]) => void calls.push(`restore ${f} ${ds.map((d) => d.id).join(",")}`)),
  };
  return { client, calls };
}

describe("undo of a case-wide redaction", () => {
  it("lists only the files it changed", () => {
    expect(changesOf(run())).toEqual([
      { fileId: 1, newIds: ["n1"], switchedIds: ["s1"] },
      { fileId: 2, newIds: ["n2"], switchedIds: [] },
    ]);
    expect(changeCount(changesOf(run()))).toBe(3);
    expect(changesOf({ ...run(), preview: true })).toEqual([]);
  });

  it("deletes the new detections and only un-selects suggestions that existed before", async () => {
    const { client, calls } = fakeClient();
    const snaps = await undoCaseRedaction(changesOf(run()), client);
    expect(calls).toEqual(["delete 1 n1", "select 1 s1 false", "delete 2 n2"]);
    expect(snaps.get(1)?.map((d) => d.id)).toEqual(["n1"]);
    calls.length = 0;
    await redoCaseRedaction(changesOf(run()), snaps, client);
    expect(calls).toEqual(["restore 1 n1", "select 1 s1 true", "restore 2 n2"]);
  });

  it("never deletes anything when an older server does not split the ids", () => {
    const old = run();
    old.files = [{ file_id: 1, name: "a.pdf", matches: 2, added: 2, added_ids: ["x", "y"] }];
    expect(changesOf(old)).toEqual([{ fileId: 1, newIds: [], switchedIds: ["x", "y"] }]);
  });
});
