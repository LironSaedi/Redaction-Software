// Export helpers. A "marked review copy" (export setting marked_copy) shows every redaction as an outline
// with its label but removes nothing: it is for internal QC only and must never be mistaken for a release.

import type { ExportSummary, FileRecord } from "../types";

export const REVIEW_COPY_LABEL = "Review copy — not for release";

type ExportLike = { marked_copy?: boolean; settings?: Record<string, unknown> | null };

/** Export summaries carry `marked_copy`; a full export (GET /api/exports/{id}) also has it in its settings. */
export function isReviewCopy(e: ExportLike): boolean {
  if (typeof e.marked_copy === "boolean") return e.marked_copy;
  return !!e.settings && typeof e.settings === "object" && e.settings.marked_copy === true;
}

/** Latest *release* export of a file (review copies are never offered as "the" redacted file). */
export function latestExport(f: Pick<FileRecord, "exports">): ExportSummary | undefined {
  return f.exports.reduce<ExportSummary | undefined>(
    (best, e) => (isReviewCopy(e) ? best : !best || e.id > best.id ? e : best),
    undefined,
  );
}

export function latestReviewCopy(f: Pick<FileRecord, "exports">): ExportSummary | undefined {
  return f.exports.reduce<ExportSummary | undefined>(
    (best, e) => (!isReviewCopy(e) ? best : !best || e.id > best.id ? e : best),
    undefined,
  );
}

/** Exports a viewer may receive: verified release copies only. */
export function releasedExports<T extends ExportLike & { verified: boolean }>(exports: T[]): T[] {
  return exports.filter((e) => e.verified && !isReviewCopy(e));
}
