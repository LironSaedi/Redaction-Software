import { describe, expect, it } from "vitest";
import { cropLayout, filterPictures, isPicture, pictureClass, pictureCounts, pictureMediaName, sortPictures } from "./pictures";
import { isReviewCopy, latestExport, latestReviewCopy, releasedExports } from "./exports";
import type { Detection, ExportSummary } from "../types";

function det(p: Partial<Detection>): Detection {
  return {
    id: p.id ?? Math.random().toString(16).slice(2, 14),
    entity: "IMAGE_PHOTO",
    text: "",
    score: 0.7,
    source: "classify:picture",
    boxes: [{ page: 0, x0: 10, y0: 10, x1: 110, y1: 60 }],
    page: 0,
    start: -1,
    end: -1,
    explanation: "",
    selected: false,
    exemption: "",
    partial: null,
    kind: "region",
    meta: { class: "IMAGE_PHOTO", whole_picture: true },
    ...p,
  };
}

describe("pictures", () => {
  const card = det({ id: "card", entity: "IMAGE_ID_CARD", selected: true, boxes: [{ page: 1, x0: 0, y0: 300, x1: 100, y1: 360 }] });
  const sig = det({ id: "sig", entity: "IMAGE_SIGNATURE", selected: true, boxes: [{ page: 0, x0: 50, y0: 500, x1: 150, y1: 530 }] });
  const photo = det({ id: "photo" });
  const office = det({ id: "office", entity: "IMAGE_CHART", boxes: [], meta: { class: "IMAGE_CHART", media: "word/media/image3.png" } });
  const face = det({ id: "face", entity: "FACE", kind: "visual", meta: {} });
  const all = [card, sig, photo, office, face];

  it("recognises whole-picture items only", () => {
    expect(all.filter(isPicture).map((d) => d.id)).toEqual(["card", "sig", "photo", "office"]);
    expect(isPicture(det({ entity: "CUSTOM", meta: { class: "IMAGE_PHOTO" } }))).toBe(true);
    expect(isPicture(det({ kind: "manual" }))).toBe(false);
  });

  it("uses the reviewer's type over the classifier's class", () => {
    expect(pictureClass(det({ entity: "IMAGE_MEDICAL", meta: { class: "IMAGE_PHOTO" } }))).toBe("IMAGE_MEDICAL");
    expect(pictureClass(det({ entity: "CUSTOM", meta: { class: "IMAGE_TABLE" } }))).toBe("IMAGE_TABLE");
  });

  it("filters by class chips and status", () => {
    expect(filterPictures(all).length).toBe(4);
    expect(filterPictures(all, { classes: ["IMAGE_ID_CARD", "IMAGE_CHART"] }).map((d) => d.id)).toEqual(["card", "office"]);
    expect(filterPictures(all, { classes: new Set<string>() }).length).toBe(4);
    expect(filterPictures(all, { status: "redacted" }).map((d) => d.id)).toEqual(["card", "sig"]);
    expect(filterPictures(all, { status: "kept", classes: ["IMAGE_PHOTO", "IMAGE_CHART"] }).map((d) => d.id)).toEqual(["photo", "office"]);
  });

  it("counts per class in the canonical order", () => {
    expect(pictureCounts(all)).toEqual([
      { cls: "IMAGE_ID_CARD", total: 1, selected: 1 },
      { cls: "IMAGE_SIGNATURE", total: 1, selected: 1 },
      { cls: "IMAGE_PHOTO", total: 1, selected: 0 },
      { cls: "IMAGE_CHART", total: 1, selected: 0 },
    ]);
  });

  it("sorts in reading order and names office media parts", () => {
    expect(sortPictures([card, sig, photo]).map((d) => d.id)).toEqual(["photo", "sig", "card"]);
    expect(pictureMediaName(office)).toBe("image3.png");
    expect(pictureMediaName(photo)).toBeNull();
  });

  it("lays out a cropped thumbnail centred in its frame", () => {
    const lay = cropLayout({ x0: 100, y0: 200, x1: 300, y1: 300 }, { width: 600, height: 800 }, { w: 200, h: 100 }, 0);
    expect(lay.scale).toBe(1); // 200×100 box into a 200×100 frame
    expect(lay.imgWidth).toBe(600);
    expect(lay.left).toBe(-100);
    expect(lay.top).toBe(-200);
    const tall = cropLayout({ x0: 0, y0: 0, x1: 50, y1: 100 }, { width: 100, height: 100 }, { w: 200, h: 100 }, 0);
    expect(tall.scale).toBe(1);
    expect(tall.left).toBe(75); // centred horizontally
  });
});

describe("review copies", () => {
  const ex = (id: number, name: string, verified: boolean, extra: Partial<ExportSummary> = {}): ExportSummary => ({
    id,
    name,
    verified,
    created_at: "",
    sha256: "",
    size: 1,
    ...extra,
  });
  const rel = ex(1, "a_REDACTED.pdf", true, { marked_copy: false });
  const review = ex(2, "a_REVIEW-COPY_REDACTED.pdf", false, { marked_copy: true });
  const fromSettings = ex(3, "renamed.pdf", false, { settings: { marked_copy: true } });

  it("uses marked_copy (or the export's settings), never the file name", () => {
    expect(isReviewCopy(rel)).toBe(false);
    expect(isReviewCopy(review)).toBe(true);
    expect(isReviewCopy(fromSettings)).toBe(true);
    expect(isReviewCopy(ex(4, "x_REVIEW-COPY.pdf", true))).toBe(false);
  });

  it("never offers a review copy as the latest export or to viewers", () => {
    const f = { exports: [rel, review, fromSettings] };
    expect(latestExport(f)?.id).toBe(1);
    expect(latestReviewCopy(f)?.id).toBe(3);
    expect(releasedExports([rel, review, fromSettings, ex(5, "b.pdf", false)]).map((e) => e.id)).toEqual([1]);
  });
});
