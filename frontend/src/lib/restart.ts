// Waiting for Obscura to come back after it restarts itself (new settings, new data folder, imported models).

export interface HealthPing {
  up: boolean;
  /** changes on every server start (GET /api/health → boot) */
  boot?: string | null;
}

export interface WaitOptions {
  ping: () => Promise<HealthPing>;
  /** `boot` read before the restart was requested; the wait ends when a different one answers */
  previousBoot?: string | null;
  sleep?: (ms: number) => Promise<void>;
  intervalMs?: number;
  /** only without a boot id (older servers): how long to wait to see the server go down before trusting an answer */
  downWithinMs?: number;
  timeoutMs?: number;
  now?: () => number;
  signal?: AbortSignal;
}

const defaultSleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/**
 * Resolves "up" once the restarted server answers: with `previousBoot`, as soon as /api/health reports a different
 * boot id; without it (a server that has no boot id), after seeing the server go down — or `downWithinMs` passing —
 * and then answer. Resolves "timeout" when it does not come back within `timeoutMs`.
 */
export async function waitForRestart(o: WaitOptions): Promise<"up" | "timeout" | "aborted"> {
  const sleep = o.sleep ?? defaultSleep;
  const now = o.now ?? (() => Date.now());
  const interval = o.intervalMs ?? 1000;
  const downWithin = o.downWithinMs ?? 6000;
  const timeout = o.timeoutMs ?? 180_000;
  const start = now();
  let sawDown = false;
  for (;;) {
    if (o.signal?.aborted) return "aborted";
    let r: HealthPing = { up: false };
    try {
      r = await o.ping();
    } catch {
      r = { up: false };
    }
    if (!r.up) sawDown = true;
    else if (o.previousBoot) {
      if (r.boot && r.boot !== o.previousBoot) return "up";
    } else if (sawDown || now() - start >= downWithin) return "up";
    if (now() - start >= timeout) return "timeout";
    await sleep(interval);
  }
}

/** GET /api/health without credentials; any network error counts as "down". */
export async function pingHealth(): Promise<HealthPing> {
  try {
    const r = await fetch("/api/health", { cache: "no-store", credentials: "same-origin" });
    if (!r.ok) return { up: false };
    const body = (await r.json().catch(() => ({}))) as { boot?: string };
    return { up: true, boot: body.boot ?? null };
  } catch {
    return { up: false };
  }
}

/** The current boot id (read just before asking the server to restart); null when unknown. */
export async function currentBoot(): Promise<string | null> {
  const r = await pingHealth();
  return r.up ? (r.boot ?? null) : null;
}
