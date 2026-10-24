import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { buildSegments } from "./pages/review/TextViewer";
import { wordAt, wordCoverage } from "./pages/review/Transcript";
import { normalizeTrack, trackRuns } from "./pages/review/VideoWorkspace";
import { sortDetections } from "./pages/review/DetectionPanel";
import { orderFileTree } from "./pages/case/FilesTab";
import { cleanZone } from "./pages/library/TemplatesTab";
import { draftToBody } from "./pages/library/ListsTab";
import { cleanExportParams, issueText } from "./components/ExportDialog";
import { mergeParams, defaultAnalyzeParams } from "./components/AnalyzeDialog";
import { PasswordRules } from "./pages/ChangePasswordPage";
import { generatePassword, passwordProblems } from "./lib/format";
import type { Detection, FileRecord, TranscriptWord } from "./types";

function det(p: Partial<Detection>): Detection {
  return {
    id: p.id ?? Math.random().toString(16).slice(2, 14),
    entity: "PERSON",
    text: "",
    score: 0.9,
    source: "test",
    boxes: [],
    page: 0,
    start: -1,
    end: -1,
    explanation: "",
    selected: true,
    exemption: "",
    partial: null,
    kind: "text",
    meta: {},
    ...p,
  };
}

describe("text view segments", () => {
  it("splits at detection boundaries and keeps overlaps", () => {
    const a = det({ id: "a", start: 4, end: 10 });
    const b = det({ id: "b", start: 6, end: 8, entity: "SSN" });
    const segs = buildSegments(14, [a, b]);
    expect(segs.map((s) => [s.start, s.end, s.dets.map((d) => d.id).join("")])).toEqual([
      [0, 4, ""],
      [4, 6, "a"],
      [6, 8, "ba"],
      [8, 10, "a"],
      [10, 14, ""],
    ]);
  });
  it("ignores visual detections without offsets", () => {
    expect(buildSegments(5, [det({ start: -1, end: -1 })])).toEqual([{ start: 0, end: 5, dets: [] }]);
  });
});

describe("transcript mapping", () => {
  const words: TranscriptWord[] = [
    { text: "Hi", start: 0, end: 0.4, prob: 1, char_start: 0, char_end: 2 },
    { text: "Daniel", start: 0.5, end: 0.9, prob: 1, char_start: 3, char_end: 9 },
    { text: "Ruiz", start: 1.0, end: 1.3, prob: 1, char_start: 10, char_end: 14 },
    { text: "here", start: 1.5, end: 1.8, prob: 1, char_start: 15, char_end: 19 },
  ];
  it("covers words by character offsets or by time range", () => {
    const byChars = det({ id: "c", start: 3, end: 14, kind: "audio", meta: { t0: 0.4, t1: 1.4 } });
    const byTime = det({ id: "t", kind: "audio", meta: { t0: 1.45, t1: 2 } });
    const cov = wordCoverage(words, [byChars, byTime]);
    expect(cov.map((c) => c.map((d) => d.id).join(""))).toEqual(["", "c", "c", "t"]);
  });
  it("finds the spoken word", () => {
    expect(wordAt(words, 0.6)).toBe(1);
    expect(wordAt(words, 0.45)).toBe(-1);
    expect(wordAt(words, 1.7)).toBe(3);
  });
});

describe("video timeline", () => {
  it("groups frames into runs, bridging small gaps", () => {
    const boxes = Object.fromEntries([1, 2, 3, 5, 6, 20, 21].map((f) => [String(f), [0, 0, 1, 1]]));
    expect(trackRuns(boxes, 1)).toEqual([
      [1, 6],
      [20, 21],
    ]);
    expect(trackRuns(boxes, 0)).toEqual([
      [1, 3],
      [5, 6],
      [20, 21],
    ]);
  });
});

describe("track normalisation", () => {
  it("recomputes first/last from the remaining boxes", () => {
    const t = normalizeTrack({ id: 1, label: "face", enabled: true, source: "auto", first: 5, last: 20, max_score: 1, boxes: { "5": [0, 0, 1, 1], "12": [0, 0, 1, 1] } });
    expect([t.first, t.last]).toEqual([5, 12]);
  });
});

describe("detection ordering", () => {
  it("sorts by page position or confidence", () => {
    const a = det({ id: "a", page: 1, boxes: [{ page: 1, x0: 0, y0: 10, x1: 1, y1: 11 }], score: 0.5 });
    const b = det({ id: "b", page: 0, boxes: [{ page: 0, x0: 0, y0: 500, x1: 1, y1: 501 }], score: 0.7 });
    const c = det({ id: "c", page: 0, boxes: [{ page: 0, x0: 0, y0: 20, x1: 1, y1: 21 }], score: 0.99 });
    expect(sortDetections([a, b, c], "page").map((d) => d.id)).toEqual(["c", "b", "a"]);
    expect(sortDetections([a, b, c], "confidence").map((d) => d.id)).toEqual(["c", "b", "a"]);
    const t1 = det({ id: "t1", kind: "audio", meta: { t0: 5 } });
    const t0 = det({ id: "t0", kind: "audio", meta: { t0: 1 } });
    expect(sortDetections([t1, t0], "page").map((d) => d.id)).toEqual(["t0", "t1"]);
  });
});

describe("case files", () => {
  const f = (id: number, parent: number | null) => ({ id, parent_id: parent }) as FileRecord;
  it("lists email attachments under their parent", () => {
    const tree = orderFileTree([f(1, null), f(2, null), f(3, 1), f(4, 1), f(5, 3)]);
    expect(tree.map((t) => `${t.file.id}:${t.depth}`)).toEqual(["1:0", "3:1", "5:2", "4:1", "2:0"]);
  });
});

describe("library helpers", () => {
  it("cleans template zones into valid fractions", () => {
    const z = cleanZone({ pages: "all", x0: 0.6, y0: -0.1, x1: 0.2, y1: 1.3, entity: "CUSTOM", exemption: "", label: "" });
    expect(z).toMatchObject({ x0: 0.2, y0: 0, x1: 0.6, y1: 1 });
  });
  it("turns the list editor into the API body", () => {
    const body = draftToBody({
      id: null,
      name: " Officers ",
      kind: "allow",
      entity: "CUSTOM",
      exemption: "",
      regex: false,
      caseSensitive: true,
      wholeWord: true,
      text: "Sgt. Lee\n\n  Det. Ortiz  \n",
    });
    expect(body.name).toBe("Officers");
    expect(body.terms).toEqual([
      { text: "Sgt. Lee", regex: false, case_sensitive: true, whole_word: true },
      { text: "Det. Ortiz", regex: false, case_sensitive: true, whole_word: true },
    ]);
  });
});

describe("dialog helpers", () => {
  it("drops empty optional export settings", () => {
    const p = cleanExportParams({ bates_prefix: "", watermark: "", password: "", effect: "blur" }, new Set(["pdf"]));
    expect(p).toMatchObject({ bates_prefix: null, watermark: null, password: null, effect: "blur" });
  });
  it("describes verification issues without values", () => {
    expect(issueText({ type: "text_under_box", page: 0, entity: "SSN", found: "123" })).toBe(
      "Text is still extractable under a redaction box (page 1, Ssn)",
    );
    expect(issueText({ type: "face_visible", frame: 30, time: 1 })).toBe("A face is still visible (at 1.00 s)");
  });
  it("merges saved analysis settings over defaults", () => {
    const p = mergeParams(defaultAnalyzeParams("hipaa"), { use_ml: false, video_mode: "fast" });
    expect(p.profile).toBe("hipaa");
    expect(p.use_ml).toBe(false);
    expect(p.video_mode).toBe("fast");
    expect(p.visual_classes).toEqual(["face", "head", "license_plate"]);
  });
});

describe("passwords", () => {
  it("mirrors the server rules", () => {
    expect(passwordProblems("short", "bob")).toHaveLength(2);
    expect(passwordProblems("bob-Sessions-2026!", "bob")).toEqual(["Must not contain the username"]);
    expect(passwordProblems("Obscura!Dev2026", "admin")).toEqual([]);
  });
  it("generates temporary passwords that satisfy them", () => {
    for (let i = 0; i < 20; i++) expect(passwordProblems(generatePassword(), "admin")).toEqual([]);
  });
  it("renders the live checklist", () => {
    render(<PasswordRules password="abc" username="jane" confirm="abd" />);
    expect(screen.getByText("At least 12 characters")).toBeTruthy();
    expect(screen.getAllByText("(not met)").length).toBe(3);
    expect(screen.getAllByText("(met)").length).toBe(1);
  });
});
