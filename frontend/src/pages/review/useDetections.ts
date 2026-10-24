import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../api";
import { useToast } from "../../components/Toast";
import type { OpHistory } from "../../lib/history";
import type { Box, Detection, DetectionUpdate, ManualDetectionIn, RedactTextIn, RedactTextOut, SearchIn, SearchResult } from "../../types";
import { changeCount, changesOf, redoCaseRedaction, undoCaseRedaction, type CaseSnapshots } from "../../lib/caseRedaction";
import { applyUpdate, editToUpdate, inverseUpdate, isNoop, shapeName, type MetaEdit } from "./metaEdit";

export interface DetectionPatch {
  entity?: string;
  exemption?: string;
  boxes?: Box[];
  partial?: string | null;
}

export interface DetectionOps {
  /** redact / un-redact one detection */
  toggle: (id: string, selected?: boolean) => void;
  /** bulk accept / reject (one request, one undo step) */
  setSelected: (ids: string[], selected: boolean, label?: string) => void;
  /** type, exemption, boxes, partial — and appearance / geometry (label, colour, effect, note, shape, points) */
  update: (id: string, patch: DetectionPatch, label?: string) => void;
  edit: (id: string, edit: MetaEdit, label?: string) => Promise<boolean>;
  selectEntities: (map: Record<string, boolean>) => void;
  add: (body: ManualDetectionIn, label?: string) => Promise<Detection | null>;
  remove: (id: string) => void;
  /** delete several at once (one request, one undo step that restores them exactly) */
  removeMany: (ids: string[], label?: string) => void;
  /** Find & Redact "Redact all" (POST /search add=true), recorded for undo */
  searchAdd: (body: SearchIn) => Promise<{ result: SearchResult; added: number } | null>;
  /** "Apply to every file in this case": one undoable step across every file it changed */
  caseRedact: (caseId: number, body: RedactTextIn) => Promise<RedactTextOut | null>;
  reload: () => void;
  replaceAll: (dets: Detection[]) => void;
}

/**
 * Detections of one file. Every change is sent to the server immediately (the server is the source of truth and
 * audits each step), applied optimistically, and recorded in the session history for undo / redo. Undo uses the
 * server's exact inverses: PATCH with the previous values, bulk delete, and restore (same ids, scores, detectors and
 * reasons). Writes are also serialised here (the server locks per file as well).
 */
export function useDetections(fileId: number, enabled: boolean, history: OpHistory, onChanged?: () => void) {
  const toast = useToast();
  const [dets, setDets] = useState<Detection[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<Detection[]>([]);
  ref.current = dets ?? [];
  const changedRef = useRef(onChanged);
  changedRef.current = onChanged;
  const [nonce, setNonce] = useState(0);
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  useEffect(() => {
    if (!enabled) return;
    const ctl = new AbortController();
    api
      .getDetections(fileId, ctl.signal)
      .then((r) => {
        setDets(r.detections);
        setError(null);
      })
      .catch((e: unknown) => {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setError(e instanceof Error ? e.message : "could not load detections");
      });
    return () => ctl.abort();
  }, [fileId, enabled, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  /** run `fn` after every earlier write has settled */
  const serial = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const p = queue.current.then(fn, fn);
    queue.current = p.catch(() => undefined);
    return p;
  }, []);

  const find = (id: string) => ref.current.find((d) => d.id === id);

  // ---- primitives (throw on failure; local state is rolled back for the affected items only) -------------

  /** PATCH a list of updates, applying them locally first */
  const sendUpdates = useCallback(
    async (updates: DetectionUpdate[]) => {
      const byId = new Map(updates.map((u) => [u.id, u]));
      const before = new Map(ref.current.filter((d) => byId.has(d.id)).map((d) => [d.id, d]));
      setDets((ds) => (ds ?? []).map((d) => (byId.has(d.id) ? applyUpdate(d, byId.get(d.id)!) : d)));
      try {
        await serial(() => api.patchDetections(fileId, { updates }));
        changedRef.current?.();
      } catch (e) {
        setDets((ds) => (ds ?? []).map((d) => before.get(d.id) ?? d));
        throw e;
      }
    },
    [fileId, serial],
  );

  const removeLocal = (ids: Set<string>) => setDets((ds) => (ds ?? []).filter((d) => !ids.has(d.id)));
  const addLocal = (items: Detection[]) =>
    setDets((ds) => {
      const have = new Set((ds ?? []).map((d) => d.id));
      return [...(ds ?? []), ...items.filter((d) => !have.has(d.id))];
    });

  const destroy = useCallback(
    async (ids: string[]) => {
      const set = new Set(ids);
      const snapshot = ref.current.filter((d) => set.has(d.id));
      removeLocal(set);
      try {
        await serial(() => api.deleteDetections(fileId, ids));
        changedRef.current?.();
      } catch (e) {
        addLocal(snapshot);
        throw e;
      }
      return snapshot;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fileId, serial],
  );

  const restore = useCallback(
    async (items: Detection[]) => {
      if (!items.length) return;
      addLocal(items);
      try {
        await serial(() => api.restoreDetections(fileId, items));
        changedRef.current?.();
      } catch (e) {
        removeLocal(new Set(items.map((d) => d.id)));
        throw e;
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [fileId, serial],
  );

  // ---- operations (toast on failure, push to history on success) -------------------------------------

  const attempt = useCallback(
    async <T,>(what: string, fn: () => Promise<T>): Promise<T | null> => {
      try {
        return await fn();
      } catch (e) {
        toast.error(e, what);
        return null;
      }
    },
    [toast],
  );

  const setSelected = useCallback(
    (list: string[], sel: boolean, label?: string) => {
      const want = new Set(list);
      const items = ref.current.filter((d) => want.has(d.id) && d.selected !== sel);
      if (!items.length) return;
      const fwd = items.map((d) => ({ id: d.id, selected: sel }));
      const back = items.map((d) => ({ id: d.id, selected: d.selected }));
      const name = label ?? `${sel ? "Redact" : "Un-redact"} ${items.length} item${items.length === 1 ? "" : "s"}`;
      attempt("Could not update redactions", async () => {
        await sendUpdates(fwd);
        history.push({ label: name, undo: () => sendUpdates(back), redo: () => sendUpdates(fwd) });
      });
    },
    [attempt, history, sendUpdates],
  );

  const toggle = useCallback(
    (id: string, selected?: boolean) => {
      const cur = find(id);
      if (!cur) return;
      const sel = selected ?? !cur.selected;
      if (sel === cur.selected) return;
      setSelected([cur.id], sel, sel ? "Redact" : "Un-redact");
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [setSelected],
  );

  const selectEntities = useCallback(
    (map: Record<string, boolean>) => {
      const keys = Object.keys(map);
      for (const sel of [true, false]) {
        const list = ref.current.filter((d) => keys.includes(d.entity) && map[d.entity] === sel).map((d) => d.id);
        if (list.length) setSelected(list, sel, `${sel ? "Accept" : "Reject"} ${list.length} item${list.length === 1 ? "" : "s"}`);
      }
    },
    [setSelected],
  );

  const edit = useCallback(
    async (id: string, e: MetaEdit, label?: string) => {
      const cur = find(id);
      if (!cur) return false;
      const fwd = editToUpdate(id, e);
      if (isNoop(cur, fwd)) return true;
      const back = inverseUpdate(cur, fwd);
      const name =
        label ??
        (e.points || e.boxes ? "Move / resize" : e.entity ? "Change type" : e.exemption !== undefined ? "Change exemption" : "Edit properties");
      const ok = await attempt("Could not update redaction", async () => {
        await sendUpdates([fwd]);
        history.push({ label: name, undo: () => sendUpdates([back]), redo: () => sendUpdates([fwd]) });
        return true;
      });
      return !!ok;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, history, sendUpdates],
  );

  const update = useCallback(
    (id: string, patch: DetectionPatch, label?: string) => {
      void edit(id, patch, label);
    },
    [edit],
  );

  const add = useCallback(
    async (body: ManualDetectionIn, label?: string) => {
      const d = await attempt("Could not add redaction", async () => {
        const created = await serial(() => api.addDetection(fileId, body));
        addLocal([created]);
        changedRef.current?.();
        return created;
      });
      if (!d) return null;
      let snapshot: Detection[] = [d];
      history.push({
        label: label ?? `Add ${body.shape && body.shape !== "rect" ? body.shape : body.t0 != null ? "time range" : body.start != null ? "text selection" : "rectangle"}`,
        undo: async () => {
          snapshot = await destroy([d.id]);
        },
        redo: () => restore(snapshot),
      });
      return d;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, destroy, fileId, history, restore, serial],
  );

  const remove = useCallback(
    (id: string) => {
      const cur = find(id);
      if (!cur) return;
      attempt("Could not delete redaction", async () => {
        let snapshot = await destroy([cur.id]);
        history.push({
          label: `Delete ${shapeName(cur)}`,
          undo: () => restore(snapshot),
          redo: async () => {
            snapshot = await destroy([cur.id]);
          },
        });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, destroy, history, restore],
  );

  const removeMany = useCallback(
    (ids: string[], label?: string) => {
      const want = new Set(ids);
      const list = ref.current.filter((d) => want.has(d.id)).map((d) => d.id);
      if (!list.length) return;
      attempt("Could not delete redactions", async () => {
        let snapshot = await destroy(list);
        history.push({
          label: label ?? `Delete ${list.length} items`,
          undo: () => restore(snapshot),
          redo: async () => {
            snapshot = await destroy(list);
          },
        });
      });
    },
    [attempt, destroy, history, restore],
  );

  const searchAdd = useCallback(
    async (body: SearchIn) => {
      const r = await attempt("Could not add redactions", async () => {
        const res = await serial(() => api.searchFile(fileId, { ...body, add: true }));
        const fresh = await api.getDetections(fileId);
        setDets(fresh.detections);
        changedRef.current?.();
        return res;
      });
      if (!r) return null;
      // new detections are deleted on undo; suggestions that existed before are only un-selected again
      const newIds = r.new_ids ?? [];
      const switched = r.switched_ids ?? (r.new_ids ? [] : (r.added_ids ?? []));
      const total = newIds.length + switched.length;
      if (total) {
        let snapshot: Detection[] = [];
        history.push({
          label: `Redact ${total} match${total === 1 ? "" : "es"}`,
          undo: async () => {
            if (newIds.length) snapshot = await destroy(newIds);
            if (switched.length) await sendUpdates(switched.map((id) => ({ id, selected: false })));
          },
          redo: async () => {
            await restore(snapshot);
            if (switched.length) await sendUpdates(switched.map((id) => ({ id, selected: true })));
          },
        });
      }
      return { result: r, added: total };
    },
    [attempt, destroy, fileId, history, restore, sendUpdates, serial],
  );

  const refreshNow = useCallback(async () => {
    const fresh = await api.getDetections(fileId);
    setDets(fresh.detections);
    changedRef.current?.();
  }, [fileId]);

  const caseRedact = useCallback(
    async (caseId: number, body: RedactTextIn) => {
      const r = await attempt("Could not redact across the case", async () => {
        const res = await serial(() => api.caseRedactText(caseId, { ...body, preview: false }));
        await refreshNow();
        return res;
      });
      if (!r) return null;
      const changes = changesOf(r);
      const n = changeCount(changes);
      if (n) {
        let snaps: CaseSnapshots = new Map();
        history.push({
          label: `Redact ${n} item${n === 1 ? "" : "s"} in ${changes.length} file${changes.length === 1 ? "" : "s"}`,
          undo: async () => {
            snaps = await serial(() => undoCaseRedaction(changes));
            await refreshNow();
          },
          redo: async () => {
            await serial(() => redoCaseRedaction(changes, snaps));
            await refreshNow();
          },
        });
      }
      return r;
    },
    [attempt, history, refreshNow, serial],
  );

  const replaceAll = useCallback((next: Detection[]) => setDets(next), []);

  const ops = useMemo<DetectionOps>(
    () => ({ toggle, setSelected, update, edit, selectEntities, add, remove, removeMany, searchAdd, caseRedact, reload, replaceAll }),
    [toggle, setSelected, update, edit, selectEntities, add, remove, removeMany, searchAdd, caseRedact, reload, replaceAll],
  );
  return { dets, error, ops };
}
