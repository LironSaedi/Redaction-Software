// Undo / redo of a case-wide "redact additional text" run (POST /api/cases/{id}/redact-text).
//
// Each file row says which detections were created (`new_ids`) and which existing suggestions were switched to
// redacted (`switched_ids`). Undo deletes the new ones and un-selects the switched ones — it never deletes a
// suggestion that existed before. Redo restores the deleted ones exactly (same ids) and re-selects the others.

import * as api from "../api";
import type { Detection, RedactTextFile, RedactTextOut } from "../types";

export interface FileChange {
  fileId: number;
  newIds: string[];
  switchedIds: string[];
}

/** The undoable changes of a run, per file (files without changes are left out). */
export function changesOf(res: Pick<RedactTextOut, "files" | "preview">): FileChange[] {
  if (res.preview) return [];
  return res.files
    .map((f: RedactTextFile) => {
      const newIds = f.new_ids ?? [];
      // an older server without the split: never delete — only un-select what it reported
      const switchedIds = f.switched_ids ?? (f.new_ids ? [] : (f.added_ids ?? []));
      return { fileId: f.file_id, newIds, switchedIds };
    })
    .filter((c) => c.newIds.length > 0 || c.switchedIds.length > 0);
}

export interface CaseUndoClient {
  getDetections: (fileId: number) => Promise<Detection[]>;
  deleteDetections: (fileId: number, ids: string[]) => Promise<unknown>;
  setSelected: (fileId: number, ids: string[], selected: boolean) => Promise<unknown>;
  restore: (fileId: number, dets: Detection[]) => Promise<unknown>;
}

export const apiCaseClient: CaseUndoClient = {
  getDetections: async (fileId) => (await api.getDetections(fileId)).detections,
  deleteDetections: (fileId, ids) => api.deleteDetections(fileId, ids),
  setSelected: (fileId, ids, selected) => api.patchDetections(fileId, { updates: ids.map((id) => ({ id, selected })) }),
  restore: (fileId, dets) => api.restoreDetections(fileId, dets),
};

/** Snapshots of the deleted detections, per file (what redo restores). */
export type CaseSnapshots = Map<number, Detection[]>;

export async function undoCaseRedaction(changes: FileChange[], client: CaseUndoClient = apiCaseClient): Promise<CaseSnapshots> {
  const snaps: CaseSnapshots = new Map();
  for (const c of changes) {
    if (c.newIds.length) {
      const want = new Set(c.newIds);
      snaps.set(c.fileId, (await client.getDetections(c.fileId)).filter((d) => want.has(d.id)));
      await client.deleteDetections(c.fileId, c.newIds);
    }
    if (c.switchedIds.length) await client.setSelected(c.fileId, c.switchedIds, false);
  }
  return snaps;
}

export async function redoCaseRedaction(changes: FileChange[], snaps: CaseSnapshots, client: CaseUndoClient = apiCaseClient): Promise<void> {
  for (const c of changes) {
    const back = snaps.get(c.fileId) ?? [];
    if (back.length) await client.restore(c.fileId, back);
    if (c.switchedIds.length) await client.setSelected(c.fileId, c.switchedIds, true);
  }
}

export function changeCount(changes: FileChange[]): number {
  return changes.reduce((n, c) => n + c.newIds.length + c.switchedIds.length, 0);
}
