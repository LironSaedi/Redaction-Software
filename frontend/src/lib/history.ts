// Undo / redo for review operations in this session.
//
// Every operation is recorded as a pair of async functions that call the API (the server stays the source
// of truth and audits each step). Undo runs the inverse call (PATCH with the previous values, bulk delete, or
// restore — which puts items back with the same ids); redo runs the forward call again.

export interface HistoryEntry {
  /** shown in tooltips: "Undo: add rectangle" */
  label: string;
  undo: () => Promise<void>;
  redo: () => Promise<void>;
}

export interface HistorySnapshot {
  canUndo: boolean;
  canRedo: boolean;
  undoLabel: string | null;
  redoLabel: string | null;
  busy: boolean;
}

export class OpHistory {
  private past: HistoryEntry[] = [];
  private future: HistoryEntry[] = [];
  private running = false;
  private listeners = new Set<() => void>();
  private snap: HistorySnapshot;

  constructor(private readonly limit = 200) {
    this.snap = this.compute();
  }

  /** Record an operation that has already been applied. Clears the redo stack. */
  push(entry: HistoryEntry): void {
    this.past.push(entry);
    if (this.past.length > this.limit) this.past.splice(0, this.past.length - this.limit);
    this.future = [];
    this.emit();
  }

  /** Undo the latest operation. Resolves false when there is nothing to undo, it is busy, or the call fails. */
  async undo(): Promise<boolean> {
    if (this.running || !this.past.length) return false;
    const e = this.past[this.past.length - 1];
    this.running = true;
    this.emit();
    try {
      await e.undo();
      this.past.pop();
      this.future.push(e);
      return true;
    } finally {
      this.running = false;
      this.emit();
    }
  }

  async redo(): Promise<boolean> {
    if (this.running || !this.future.length) return false;
    const e = this.future[this.future.length - 1];
    this.running = true;
    this.emit();
    try {
      await e.redo();
      this.future.pop();
      this.past.push(e);
      return true;
    } finally {
      this.running = false;
      this.emit();
    }
  }

  clear(): void {
    this.past = [];
    this.future = [];
    this.emit();
  }

  get size(): { past: number; future: number } {
    return { past: this.past.length, future: this.future.length };
  }

  snapshot(): HistorySnapshot {
    return this.snap;
  }

  subscribe(fn: () => void): () => void {
    this.listeners.add(fn);
    return () => {
      this.listeners.delete(fn);
    };
  }

  private compute(): HistorySnapshot {
    return {
      canUndo: !this.running && this.past.length > 0,
      canRedo: !this.running && this.future.length > 0,
      undoLabel: this.past.length ? this.past[this.past.length - 1].label : null,
      redoLabel: this.future.length ? this.future[this.future.length - 1].label : null,
      busy: this.running,
    };
  }

  private emit(): void {
    this.snap = this.compute();
    for (const fn of this.listeners) fn();
  }
}
