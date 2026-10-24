import { describe, expect, it } from "vitest";
import {
  applyMatrix,
  canvasRectToVideo,
  charIndexAt,
  chooseDpi,
  clientToView,
  containFit,
  fitScale,
  frameAt,
  invertMatrix,
  lineRects,
  nextZoom,
  normalizeRect,
  pageRectToView,
  timeOfFrame,
  toMatrix,
  trackBoxAt,
  transformRect,
  videoBoxToCanvas,
  viewPointToPage,
  viewRectToPage,
  type Matrix,
} from "./geometry";

const close = (a: number, b: number, eps = 1e-6) => expect(Math.abs(a - b)).toBeLessThan(eps);

describe("page ↔ view (PDF points / image pixels)", () => {
  it("scales boxes into the displayed image", () => {
    const v = pageRectToView({ x0: 72, y0: 144, x1: 216, y1: 180 }, 1.5);
    expect(v).toEqual({ x0: 108, y0: 216, x1: 324, y1: 270 });
  });

  it("round-trips a dragged rectangle back to page units", () => {
    const scale = 0.8125;
    const page = { x0: 100.5, y0: 40.25, x1: 300, y1: 90 };
    const view = pageRectToView(page, scale);
    const back = viewRectToPage(view, scale);
    close(back.x0, page.x0);
    close(back.y0, page.y0);
    close(back.x1, page.x1);
    close(back.y1, page.y1);
  });

  it("normalises a drag made right-to-left / bottom-to-top", () => {
    const r = viewRectToPage({ x0: 200, y0: 100, x1: 50, y1: 20 }, 2);
    expect(r).toEqual({ x0: 25, y0: 10, x1: 100, y1: 50 });
  });

  it("clamps drawn boxes to the page", () => {
    const r = viewRectToPage({ x0: -20, y0: -5, x1: 2000, y1: 30 }, 1, undefined, { width: 612, height: 792 });
    expect(r).toEqual({ x0: 0, y0: 0, x1: 612, y1: 30 });
  });

  it("converts client coordinates relative to the overlay", () => {
    expect(clientToView(350, 220, { left: 300, top: 200 })).toEqual({ x: 50, y: 20 });
  });

  it("handles a 90° rotated page via the rotation matrix", () => {
    // PyMuPDF rotation_matrix for /Rotate 90 on a 612×792 page: (x, y) → (792 − y, x)
    const m = toMatrix([0, 1, -1, 0, 792, 0]);
    const unrotated = { x0: 100, y0: 50, x1: 200, y1: 80 };
    const shown = transformRect(m, unrotated);
    expect(shown).toEqual({ x0: 712, y0: 100, x1: 742, y1: 200 });
    // drawing over that displayed area gives back the unrotated box
    const scale = 0.5;
    const view = { x0: shown.x0 * scale, y0: shown.y0 * scale, x1: shown.x1 * scale, y1: shown.y1 * scale };
    const back = viewRectToPage(view, scale, m, { width: 792, height: 612 });
    close(back.x0, 100);
    close(back.y0, 50);
    close(back.x1, 200);
    close(back.y1, 80);
    const p = viewPointToPage({ x: 371, y: 75 }, scale, m);
    close(p.x, 150);
    close(p.y, 50);
  });

  it("inverts matrices", () => {
    const m: Matrix = [2, 0.5, -1, 3, 10, -4];
    const inv = invertMatrix(m);
    const p = applyMatrix(inv, applyMatrix(m, { x: 7, y: -3 }));
    close(p.x, 7);
    close(p.y, -3);
    expect(toMatrix(undefined)).toEqual([1, 0, 0, 1, 0, 0]);
    expect(toMatrix([1, 2])).toEqual([1, 0, 0, 1, 0, 0]);
  });
});

describe("zoom and resolution", () => {
  it("fits width or the whole page", () => {
    close(fitScale(612, 792, 652, 600, "width", 20), 612 / 612);
    close(fitScale(612, 792, 652, 600, "page", 20), 560 / 792);
  });
  it("steps through zoom levels", () => {
    expect(nextZoom(1, 1)).toBe(1.1);
    expect(nextZoom(1, -1)).toBe(0.9);
    expect(nextZoom(0.95, 1)).toBe(1);
    expect(nextZoom(4, 1)).toBe(4);
    expect(nextZoom(0.25, -1)).toBe(0.25);
  });
  it("picks a cache-friendly render dpi", () => {
    expect(chooseDpi(1, 1)).toBe(72);
    expect(chooseDpi(96 / 72, 1)).toBe(110);
    expect(chooseDpi(96 / 72, 2)).toBe(220);
    expect(chooseDpi(10, 2)).toBe(220);
  });
});

describe("video overlay", () => {
  it("letterboxes with object-fit: contain", () => {
    const f = containFit(1280, 720, 800, 600);
    close(f.scale, 0.625);
    close(f.offsetX, 0);
    close(f.offsetY, 75);
  });
  it("maps track boxes to the canvas and back", () => {
    const box = [640, 360, 800, 520];
    const c = videoBoxToCanvas(box, 1280, 720, 800, 600);
    expect(c).toEqual({ x0: 400, y0: 300, x1: 500, y1: 400 });
    const v = canvasRectToVideo(c, 1280, 720, 800, 600);
    close(v.x0, 640);
    close(v.y0, 360);
    close(v.x1, 800);
    close(v.y1, 520);
  });
  it("clamps a drawn box to the frame", () => {
    const v = canvasRectToVideo({ x0: -10, y0: 0, x1: 900, y1: 80 }, 1280, 720, 800, 600);
    expect(v).toEqual({ x0: 0, y0: 0, x1: 1280, y1: 8 });
  });
  it("computes frame numbers as round(t·fps)", () => {
    expect(frameAt(0, 30)).toBe(0);
    expect(frameAt(1.0, 30)).toBe(30);
    expect(frameAt(1.016, 30)).toBe(30);
    expect(frameAt(1.02, 30)).toBe(31);
    expect(frameAt(99, 30, 150)).toBe(149);
    expect(frameAt(Number.NaN, 30)).toBe(0);
    expect(frameAt(timeOfFrame(42, 29.97), 29.97)).toBe(42);
  });
  it("finds a track box at or next to a frame", () => {
    const boxes = { "10": [1, 2, 3, 4], "12": [5, 6, 7, 8] };
    expect(trackBoxAt(boxes, 10)).toEqual([1, 2, 3, 4]);
    expect(trackBoxAt(boxes, 11)).toEqual([1, 2, 3, 4]);
    expect(trackBoxAt(boxes, 13)).toEqual([5, 6, 7, 8]);
    expect(trackBoxAt(boxes, 20)).toBeNull();
    expect(trackBoxAt(undefined, 1)).toBeNull();
  });
});

describe("text selection on page images", () => {
  // two lines: "AB CD" at y 10–20 and "EF" at y 30–40
  const boxes: ([number, number, number, number] | null)[] = [
    [10, 10, 18, 20],
    [18, 10, 26, 20],
    null,
    [32, 10, 40, 20],
    [40, 10, 48, 20],
    null,
    [10, 30, 18, 40],
    [18, 30, 26, 40],
  ];
  it("hits the character under the pointer", () => {
    expect(charIndexAt(boxes, { x: 12, y: 15 })).toBe(0);
    expect(charIndexAt(boxes, { x: 45, y: 15 })).toBe(4);
  });
  it("prefers the nearest character on the same line", () => {
    // far right of line 1 still selects its last character, not line 2
    expect(charIndexAt(boxes, { x: 120, y: 16 })).toBe(4);
    expect(charIndexAt(boxes, { x: 120, y: 36 })).toBe(7);
  });
  it("ignores points far from any text", () => {
    expect(charIndexAt(boxes, { x: 12, y: 200 })).toBe(-1);
  });
  it("merges a character range into one rectangle per line", () => {
    expect(lineRects(boxes, 0, 8)).toEqual([
      { x0: 10, y0: 10, x1: 48, y1: 20 },
      { x0: 10, y0: 30, x1: 26, y1: 40 },
    ]);
    expect(lineRects(boxes, 3, 5)).toEqual([{ x0: 32, y0: 10, x1: 48, y1: 20 }]);
  });
  it("normalizeRect orders corners", () => {
    expect(normalizeRect({ x: 5, y: 9 }, { x: 1, y: 2 })).toEqual({ x0: 1, y0: 2, x1: 5, y1: 9 });
  });
});
