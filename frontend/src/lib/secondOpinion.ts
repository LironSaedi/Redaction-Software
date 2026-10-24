// Second opinion (Microsoft Presidio, running locally): suggestions during analysis, and a final check of exports.

import type { Detection, SecondOpinionFinding, SecondOpinionReport } from "../types";

export const SECOND_OPINION_PREFIX = "presidio:";

export function isSecondOpinion(d: Pick<Detection, "source">): boolean {
  return (d.source ?? "").startsWith(SECOND_OPINION_PREFIX);
}

/** Presidio recognizer that produced a suggestion ("presidio:UsSsnRecognizer" → "UsSsnRecognizer"). */
export function recognizerOf(d: Pick<Detection, "source">): string {
  const s = d.source ?? "";
  return s.startsWith(SECOND_OPINION_PREFIX) ? s.slice(SECOND_OPINION_PREFIX.length).split("+")[0] : "";
}

export type FinalCheckState =
  | { state: "passed"; engine: string; reviewed: number }
  | { state: "open"; engine: string; open: number; reviewed: number; findings: SecondOpinionFinding[] }
  | { state: "unchecked"; reason: string };

/** What the export's final check found (report.second_opinion), or null when the export has no such report. */
export function finalCheckState(r: SecondOpinionReport | null | undefined): FinalCheckState | null {
  if (!r) return null;
  if (!r.checked) return { state: "unchecked", reason: r.reason || "not checked" };
  const findings = r.findings ?? [];
  const reviewed = findings.filter((f) => f.reviewed).length;
  if (!r.open) return { state: "passed", engine: r.engine, reviewed };
  return { state: "open", engine: r.engine, open: r.open, reviewed, findings };
}

/** Headline for an export result (never contains the found text itself). */
export function finalCheckHeadline(s: FinalCheckState): string {
  if (s.state === "passed") return "Final check passed — nothing left that looks personal";
  if (s.state === "open") return `${s.open} possible item${s.open === 1 ? "" : "s"} still readable`;
  return "Final check not run";
}
