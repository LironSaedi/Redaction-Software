import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as api from "../../../api";
import { useToast } from "../../../components/Toast";
import type { OpHistory } from "../../../lib/history";
import type { ManualTrackIn, Track, TrackPatch } from "../../../types";
import { normalizeTrack, type TrackEffect, type TrackShape } from "./trackUtils";

export interface TrackOps {
  setEnabled: (t: Track, enabled: boolean) => void;
  rename: (t: Track, label: string) => void;
  /** null = use the effect chosen at export */
  setEffect: (t: Track, effect: TrackEffect | null) => void;
  setShape: (t: Track, shape: TrackShape) => void;
  remove: (t: Track) => void;
  trim: (t: Track, edge: { trim_start?: number; trim_end?: number }) => void;
  add: (body: ManualTrackIn, label?: string) => Promise<Track | null>;
  reload: () => void;
}

/**
 * Video tracks with optimistic updates and undo / redo (shared history with the detections). Undo of a delete,
 * trim or add uses POST /video/tracks/restore, which puts the exact track (same id, every per-frame box) back.
 */
export function useTracks(fileId: number, hasTracks: boolean, history: OpHistory) {
  const toast = useToast();
  const [tracks, setTracks] = useState<Track[] | null>(null);
  const [nonce, setNonce] = useState(0);
  const ref = useRef<Track[]>([]);
  ref.current = tracks ?? [];
  const queue = useRef<Promise<unknown>>(Promise.resolve());

  const serial = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const p = queue.current.then(fn, fn);
    queue.current = p.catch(() => undefined);
    return p;
  }, []);

  const fetchTracks = useCallback(async () => {
    const r = await api.getTracks(fileId);
    setTracks(r.tracks.map(normalizeTrack));
  }, [fileId]);

  useEffect(() => {
    const ctl = new AbortController();
    api.getTracks(fileId, ctl.signal).then(
      (r) => setTracks(r.tracks.map(normalizeTrack)),
      (e: unknown) => {
        if (e instanceof DOMException) return;
        setTracks([]);
        toast.error(e, "Could not load tracks");
      },
    );
    return () => ctl.abort();
  }, [fileId, nonce, hasTracks, toast]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  const current = (id: number) => ref.current.find((x) => x.id === id);

  // ---- primitives ----------------------------------------------------------------------------------------
  const send = useCallback(
    async (id: number, body: TrackPatch, local?: (t: Track) => Track | null) => {
      const before = ref.current;
      if (local) setTracks((ts) => (ts ?? []).map((t) => (t.id === id ? local(t) : t)).filter((t): t is Track => t !== null));
      try {
        await serial(() => api.patchTrack(fileId, id, body));
        if (body.trim_start != null || body.trim_end != null) await fetchTracks();
      } catch (e) {
        setTracks(before);
        throw e;
      }
    },
    [fetchTracks, fileId, serial],
  );

  const restore = useCallback(
    async (t: Track) => {
      await serial(() => api.restoreTrack(fileId, t));
      await fetchTracks();
    },
    [fetchTracks, fileId, serial],
  );

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

  /** a reversible PATCH (enabled, label, effect, shape) */
  const change = useCallback(
    (t: Track, fwd: TrackPatch, back: TrackPatch, apply: (x: Track, p: TrackPatch) => Track, label: string, what: string) => {
      const run = (p: TrackPatch) => send(t.id, p, (x) => apply(x, p));
      attempt(what, async () => {
        await run(fwd);
        history.push({ label, undo: () => run(back), redo: () => run(fwd) });
      });
    },
    [attempt, history, send],
  );

  const setEnabled = useCallback(
    (t: Track, enabled: boolean) => {
      if (t.enabled === enabled) return;
      change(t, { enabled }, { enabled: !enabled }, (x, p) => ({ ...x, enabled: !!p.enabled }), enabled ? "Redact track" : "Keep track visible", "Could not update the track");
    },
    [change],
  );

  const rename = useCallback(
    (t: Track, label: string) => {
      if (!label || label === t.label) return;
      change(t, { label }, { label: t.label }, (x, p) => ({ ...x, label: p.label ?? x.label }), "Rename track", "Could not rename the track");
    },
    [change],
  );

  const setEffect = useCallback(
    (t: Track, effect: TrackEffect | null) => {
      if ((t.effect ?? null) === effect) return;
      change(t, { effect: effect ?? "" }, { effect: t.effect ?? "" }, (x, p) => ({ ...x, effect: p.effect || null }), "Change track effect", "Could not change the effect");
    },
    [change],
  );

  const setShape = useCallback(
    (t: Track, shape: TrackShape) => {
      const prev: TrackShape = t.shape === "ellipse" ? "ellipse" : "rect";
      if (prev === shape) return;
      change(t, { shape }, { shape: prev }, (x, p) => ({ ...x, shape: p.shape === "ellipse" ? "ellipse" : null }), "Change track shape", "Could not change the shape");
    },
    [change],
  );

  const add = useCallback(
    async (body: ManualTrackIn, label?: string) => {
      const t = await attempt("Could not add the redaction", async () => {
        const created = await serial(() => api.addTrack(fileId, body));
        await fetchTracks();
        return created;
      });
      if (!t) return null;
      let snapshot: Track | undefined;
      history.push({
        label: label ?? "Add video redaction",
        undo: async () => {
          snapshot = current(t.id) ?? snapshot;
          await send(t.id, { delete: true }, () => null);
        },
        redo: async () => {
          if (snapshot) await restore(snapshot);
        },
      });
      return t;
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, fetchTracks, fileId, history, restore, send, serial],
  );

  const remove = useCallback(
    (t: Track) => {
      const snapshot = current(t.id) ?? t;
      attempt("Could not delete the track", async () => {
        await send(t.id, { delete: true }, () => null);
        history.push({
          label: "Delete track",
          undo: () => restore(snapshot),
          redo: () => send(t.id, { delete: true }, () => null),
        });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, history, restore, send],
  );

  const trim = useCallback(
    (t: Track, edge: { trim_start?: number; trim_end?: number }) => {
      const snapshot = current(t.id) ?? t;
      attempt("Could not trim the track", async () => {
        await send(t.id, edge);
        history.push({
          label: edge.trim_start != null ? "Trim track start" : "Trim track end",
          // restore replaces the trimmed track (same id) with all of its frames
          undo: () => restore(snapshot),
          redo: () => send(t.id, edge),
        });
      });
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [attempt, history, restore, send],
  );

  const ops = useMemo<TrackOps>(
    () => ({ setEnabled, rename, setEffect, setShape, remove, trim, add, reload }),
    [setEnabled, rename, setEffect, setShape, remove, trim, add, reload],
  );
  return { tracks, ops };
}
