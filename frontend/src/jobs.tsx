import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as api from "./api";
import { useAuth } from "./auth";
import { useToast } from "./components/Toast";
import type { Job } from "./types";

// Background jobs: one poll of GET /api/jobs?active=true drives the top-bar indicator and the
// progress shown next to files. Jobs started from this tab are "tracked": when they leave the
// active list their final state is fetched once and the caller's onDone runs.

interface TrackOptions {
  label?: string;
  /** the file the job works on (lets the UI show progress before the first poll lists it) */
  fileId?: number;
  kind?: string;
  onDone?: (job: Job) => void;
  /** show a toast when the job finishes (default true) */
  notify?: boolean;
}

interface JobsContextValue {
  active: Job[];
  finished: Record<number, Job>;
  track: (jobId: number, opts?: TrackOptions) => void;
  jobForFile: (fileId: number) => Job | undefined;
  job: (jobId: number) => Job | undefined;
  refresh: () => void;
}

const JobsContext = createContext<JobsContextValue | null>(null);

export function JobsProvider({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const toast = useToast();
  const [active, setActive] = useState<Job[]>([]);
  const [finished, setFinished] = useState<Record<number, Job>>({});
  const tracked = useRef(new Map<number, TrackOptions>());
  const [tick, setTick] = useState(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inFlight = useRef(false);
  const activeCount = useRef(0);

  const poll = useCallback(async () => {
    if (inFlight.current) return;
    inFlight.current = true;
    try {
      const list = await api.listJobs(true);
      setActive(list);
      activeCount.current = list.length;
      const activeIds = new Set(list.map((j) => j.id));
      for (const [id, opts] of Array.from(tracked.current.entries())) {
        if (activeIds.has(id)) continue;
        // Not active any more (or not yet listed): fetch its state.
        const j = await api.getJob(id).catch(() => null);
        if (!j || !api.FINISHED_JOB_STATES.has(j.status)) continue;
        tracked.current.delete(id);
        setFinished((f) => ({ ...f, [id]: j }));
        if (opts.notify !== false) {
          const what = opts.label ?? `${j.kind} job`;
          if (j.status === "done") toast.success(`${what} finished`);
          else if (j.status === "cancelled") toast.info(`${what} cancelled`);
          else toast.error(j.message || "job failed", what);
        }
        opts.onDone?.(j);
      }
    } catch {
      /* transient; next poll retries */
    } finally {
      inFlight.current = false;
    }
  }, [toast]);

  useEffect(() => {
    if (status !== "authenticated") {
      setActive([]);
      return;
    }
    let stopped = false;
    const loop = async () => {
      await poll();
      if (stopped) return;
      const busy = tracked.current.size > 0 || activeCount.current > 0;
      timer.current = setTimeout(loop, busy ? 1000 : 5000);
    };
    loop();
    return () => {
      stopped = true;
      if (timer.current) clearTimeout(timer.current);
    };
    // `tick` restarts the loop immediately when a job is tracked
  }, [status, poll, tick]);

  const track = useCallback((jobId: number, opts: TrackOptions = {}) => {
    tracked.current.set(jobId, opts);
    setTick((t) => t + 1);
  }, []);

  const value = useMemo<JobsContextValue>(
    () => ({
      active,
      finished,
      track,
      jobForFile: (fileId) => {
        const a = active.find((j) => j.file_id === fileId);
        if (a) return a;
        for (const [id, o] of tracked.current.entries()) {
          if (o.fileId === fileId && !finished[id])
            return { id, kind: o.kind ?? "analyze", file_id: fileId, case_id: null, status: "queued", progress: 0, message: "" };
        }
        return undefined;
      },
      job: (id) => active.find((j) => j.id === id) ?? finished[id],
      refresh: () => setTick((t) => t + 1),
    }),
    // `tick` changes when a job is tracked, so consumers see the queued placeholder at once
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [active, finished, track, tick],
  );
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(): JobsContextValue {
  const ctx = useContext(JobsContext);
  if (!ctx) throw new Error("useJobs outside JobsProvider");
  return ctx;
}
