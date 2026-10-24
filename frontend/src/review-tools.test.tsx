import { describe, expect, it } from "vitest";
import { applyUpdate, editToUpdate, inverseUpdate, isManual, isNoop } from "./pages/review/metaEdit";
import { applyFilter, detectorLabel, EMPTY_FILTER, isFilterActive } from "./pages/review/detectionUtils";
import { matchToManual } from "./pages/review/FindRedactPanel";
import { parseTranslationKeys, segmentAt } from "./pages/review/Translation";
import { isFullFrame, trackShape } from "./pages/review/video/trackUtils";
import { cleanExportParams, isDefaultEnhance } from "./components/ExportDialog";
import { hotkeyName } from "./lib/hotkeys";
import type { MetaHelpers } from "./meta";
import type { Detection, Track } from "./types";

function det(p: Partial<Detection>): Detection {
  return {
    id: p.id ?? Math.random().toString(16).slice(2, 14),
    entity: "PERSON",
    text: "",
    score: 0.9,
    source: "ner:gliner",
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

const CATS: Record<string, string> = { PERSON: "PII", SSN: "PII", DIAGNOSIS: "PHI", FACE: "VISUAL" };
const m = {
  categoryOf: (k: string) => CATS[k] ?? "OTHER",
  entityLabel: (k: string) => k.toLowerCase(),
} as unknown as MetaHelpers;

describe("editing detections in place (PATCH)", () => {
  const poly = det({
    id: "p",
    kind: "manual",
    source: "manual:polygon",
    entity: "CUSTOM",
    exemption: "(b)(6)",
    page: 2,
    score: 1,
    boxes: [{ page: 2, x0: 10, y0: 10, x1: 50, y1: 40 }],
    meta: { shape: "polygon", points: [[10, 10], [50, 10], [30, 40]], fill: [1, 0, 0], note: "witness" },
  });

  it("maps a user edit to an update; null clears", () => {
    expect(editToUpdate("p", { label_text: " (b)(6) ", fill: null, effect: null, note: null })).toEqual({
      id: "p",
      label_text: "(b)(6)",
      fill: [],
      effect: "",
      note: "",
    });
  });

  it("applies updates like the server and keeps id / score / source", () => {
    const next = applyUpdate(poly, { id: "p", label_text: "(b)(6)", fill: [], note: "" });
    expect(next.meta).toEqual({ shape: "polygon", points: [[10, 10], [50, 10], [30, 40]], label_text: "(b)(6)" });
    expect([next.id, next.score, next.source]).toEqual(["p", 1, "manual:polygon"]);
    const moved = applyUpdate(poly, { id: "p", points: [[20, 20], [60, 20], [40, 50]] });
    expect(moved.boxes).toEqual([{ page: 2, x0: 20, y0: 20, x1: 60, y1: 50 }]);
    expect(applyUpdate(poly, { id: "p", shape: "rect" }).meta.shape).toBeUndefined();
  });

  it("builds the exact inverse for undo", () => {
    const fwd = { id: "p", label_text: "Redacted per HIPAA", fill: [0, 0, 1], points: [[20, 20], [60, 20], [40, 50]] };
    const back = inverseUpdate(poly, fwd);
    expect(back).toEqual({
      id: "p",
      label_text: "",
      fill: [1, 0, 0],
      points: [[10, 10], [50, 10], [30, 40]],
      boxes: [{ page: 2, x0: 10, y0: 10, x1: 50, y1: 40 }],
    });
    expect(applyUpdate(applyUpdate(poly, fwd), back)).toEqual(poly);
    const sel = det({ id: "s", selected: false, exemption: "" });
    expect(applyUpdate(applyUpdate(sel, { id: "s", selected: true, exemption: "(b)(7)(C)" }), inverseUpdate(sel, { id: "s", selected: true, exemption: "(b)(7)(C)" }))).toEqual(sel);
  });

  it("detects no-op edits and manual items", () => {
    expect(isNoop(poly, { id: "p", note: "witness" })).toBe(true);
    expect(isNoop(poly, { id: "p", note: "other" })).toBe(false);
    expect(isManual(poly)).toBe(true);
    expect(isManual(det({}))).toBe(false);
  });
});

describe("detection list filters", () => {
  const list = [
    det({ id: "a", entity: "PERSON", score: 0.95, boxes: [{ page: 0, x0: 0, y0: 0, x1: 1, y1: 1 }] }),
    det({ id: "b", entity: "SSN", score: 0.55, selected: false, boxes: [{ page: 1, x0: 0, y0: 0, x1: 1, y1: 1 }] }),
    det({ id: "c", entity: "DIAGNOSIS", score: 0.8, boxes: [{ page: 1, x0: 0, y0: 0, x1: 1, y1: 1 }] }),
    det({ id: "d", entity: "FACE", kind: "visual", score: 0.4, selected: false, boxes: [{ page: 2, x0: 0, y0: 0, x1: 1, y1: 1 }] }),
  ];
  const ids = (ds: Detection[]) => ds.map((d) => d.id);

  it("filters by category, type, page, status and confidence", () => {
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, categories: ["PII"] }, { m }))).toEqual(["a", "b"]);
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, entity: "FACE" }, { m }))).toEqual(["d"]);
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, page: 1 }, { m }))).toEqual(["b", "c"]);
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, page: "current" }, { m, currentPage: 2 }))).toEqual(["d"]);
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, status: "suggested" }, { m }))).toEqual(["b", "d"]);
    expect(ids(applyFilter(list, { ...EMPTY_FILTER, minScore: 0.6 }, { m }))).toEqual(["a", "c"]);
    expect(ids(applyFilter(list, EMPTY_FILTER, { m, showSuggestions: false }))).toEqual(["a", "c"]);
    const withSo = [...list, det({ id: "so", source: "presidio:UsSsnRecognizer", selected: false })];
    expect(ids(applyFilter(withSo, { ...EMPTY_FILTER, secondOpinion: true }, { m }))).toEqual(["so"]);
    expect(isFilterActive({ ...EMPTY_FILTER, secondOpinion: true })).toBe(true);
    expect(isFilterActive(EMPTY_FILTER)).toBe(false);
    expect(isFilterActive({ ...EMPTY_FILTER, minScore: 0.2 })).toBe(true);
  });

  it("names detector families", () => {
    expect(detectorLabel("ner:gliner+rule:ssn")).toBe("AI model");
    expect(detectorLabel("rule:ssn")).toBe("Pattern rule");
    expect(detectorLabel("classify:picture")).toBe("Picture classifier");
    expect(detectorLabel("manual:polygon")).toBe("Manual");
    expect(detectorLabel("")).toBe("—");
    expect(detectorLabel("presidio:UsSsnRecognizer")).toBe("Second opinion (Presidio)");
  });
});

describe("Find & Redact: one match", () => {
  it("redacts by time range, text range or boxes", () => {
    expect(matchToManual(det({ meta: { t0: 1, t1: 2 } }), "SSN", "")).toEqual({ entity: "SSN", t0: 1, t1: 2, note: "found by search" });
    expect(matchToManual(det({ page: 3, start: 4, end: 9 }), "CUSTOM", "(b)(6)")).toEqual({
      entity: "CUSTOM",
      exemption: "(b)(6)",
      page: 3,
      start: 4,
      end: 9,
    });
    const boxes = [{ page: 0, x0: 1, y0: 2, x1: 3, y1: 4 }];
    expect(matchToManual(det({ boxes }), "CUSTOM", "")).toEqual({ entity: "CUSTOM", page: 0, boxes });
    expect(matchToManual(det({}), "CUSTOM", "")).toBeNull();
  });
});

describe("translations", () => {
  it("parses translation keys (list from the server, or an older map)", () => {
    const want = [
      { lang: "de", redacted: true },
      { lang: "es", redacted: true },
      { lang: "es", redacted: false },
    ];
    expect(parseTranslationKeys(["es:o", "de:r", "es:r"])).toEqual(want);
    expect(parseTranslationKeys({ "es:r": "x", "es:o": "y", "de:r": "z" })).toEqual(want);
    expect(parseTranslationKeys(undefined)).toEqual([]);
  });
  it("finds the playing segment", () => {
    const segs = [
      { start: 0, end: 2 },
      { start: 2, end: 5 },
    ];
    expect(segmentAt(segs, 2.5)).toBe(1);
    expect(segmentAt(segs, 9)).toBe(-1);
  });
});

describe("video tracks", () => {
  const t = (p: Partial<Track>): Track => ({ id: 1, label: "face", enabled: true, source: "yolo", first: 0, last: 0, max_score: 0.9, ...p });
  it("reads shape and full-frame tracks", () => {
    expect(trackShape(t({ shape: "ellipse" }))).toBe("ellipse");
    expect(trackShape(t({ shape: null }))).toBe("rect");
    expect(isFullFrame(t({ label: "full_frame" }))).toBe(true);
    expect(isFullFrame(t({ label: "x", source: "manual:full_frame" }))).toBe(true);
    expect(isFullFrame(t({}))).toBe(false);
  });
});

describe("export options", () => {
  it("sends enhance only when changed and the review copy only for PDFs / images", () => {
    const base = { padding: 3, enhance: { brightness: 0, contrast: 1, sharpen: 0, gamma: 1, denoise: false }, marked_copy: true };
    const pdf = cleanExportParams({ ...base }, new Set(["pdf"]));
    expect(pdf.enhance).toBeUndefined();
    expect(pdf.marked_copy).toBe(true);
    expect(pdf.padding).toBe(3);
    const mixed = cleanExportParams({ ...base, enhance: { ...base.enhance, gamma: 1.4 } }, new Set(["pdf", "video"]));
    expect(mixed.marked_copy).toBeUndefined();
    expect(mixed.enhance?.gamma).toBe(1.4);
    expect(cleanExportParams({ padding: 40 }, new Set(["image"])).padding).toBe(10);
    expect(isDefaultEnhance(null)).toBe(true);
    expect(isDefaultEnhance({ brightness: 0, contrast: 1, sharpen: 0, gamma: 1, denoise: true })).toBe(false);
  });
});

describe("hotkey names", () => {
  it("normalises modifiers", () => {
    expect(hotkeyName({ key: "z", shiftKey: false, metaKey: true, ctrlKey: false })).toBe("mod+z");
    expect(hotkeyName({ key: "Z", shiftKey: true, metaKey: false, ctrlKey: true })).toBe("mod+shift+z");
    expect(hotkeyName({ key: "ArrowLeft", shiftKey: true, metaKey: false, ctrlKey: false })).toBe("shift+ArrowLeft");
    expect(hotkeyName({ key: "?", shiftKey: true, metaKey: false, ctrlKey: false })).toBe("?");
    expect(hotkeyName({ key: "G", shiftKey: false, metaKey: false, ctrlKey: false })).toBe("g");
  });
});

describe("speakers", () => {
  it("labels words from their own field or their segment, in order of appearance", async () => {
    const { wordSpeakers, speakerList, speakerColor } = await import("./pages/review/Transcript");
    const w = (text: string, start: number, speaker?: string) => ({ text, start, end: start + 0.4, prob: 1, char_start: 0, char_end: 1, speaker });
    const t = {
      words: [w("hi", 0.1), w("there", 0.6), w("yes", 2.1, "Speaker 1"), w("ok", 5)],
      segments: [
        { start: 0, end: 1, speaker: "Speaker 2" },
        { start: 2, end: 3, speaker: "Speaker 2" },
      ],
    };
    const sp = wordSpeakers(t);
    expect(sp).toEqual(["Speaker 2", "Speaker 2", "Speaker 1", null]);
    const list = speakerList(sp);
    expect(list).toEqual(["Speaker 2", "Speaker 1"]);
    expect(speakerColor(list, "Speaker 2")).not.toBe(speakerColor(list, "Speaker 1"));
    expect(speakerColor(list, "Speaker 1")).toBe(speakerColor(["Speaker 2", "Speaker 1"], "Speaker 1"));
  });
});
