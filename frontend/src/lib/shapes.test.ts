import { describe, expect, it } from "vitest";
import { toMatrix } from "./geometry";
import {
  closesPolygon,
  constrainSquare,
  detectionPoints,
  detectionShape,
  displayShape,
  ellipseFromRect,
  handlePoint,
  pagePolygonToView,
  pointInEllipse,
  pointInPolygon,
  polygonArea,
  polygonBounds,
  polygonBox,
  resizeRect,
  svgPoints,
  translatePolygon,
  viewDragToPageRect,
  viewPolygonToPage,
} from "./shapes";

// PyMuPDF rotation matrix of a 612×792 page rotated by 90°: (x, y) → (792 − y, x)
const ROT90 = toMatrix([0, 1, -1, 0, 792, 0]);

describe("ellipse geometry", () => {
  it("inscribes the ellipse in its rectangle", () => {
    expect(ellipseFromRect({ x0: 10, y0: 20, x1: 50, y1: 40 })).toEqual({ cx: 30, cy: 30, rx: 20, ry: 10 });
  });
  it("hit-tests inside the ellipse only (not the rectangle corners)", () => {
    const r = { x0: 0, y0: 0, x1: 100, y1: 50 };
    expect(pointInEllipse({ x: 50, y: 25 }, r)).toBe(true);
    expect(pointInEllipse({ x: 99, y: 25 }, r)).toBe(true);
    expect(pointInEllipse({ x: 3, y: 3 }, r)).toBe(false); // corner of the box, outside the ellipse
    expect(pointInEllipse({ x: 50, y: 25 }, { x0: 0, y0: 0, x1: 0, y1: 10 })).toBe(false);
  });
});

describe("polygon geometry", () => {
  const tri = [
    { x: 0, y: 0 },
    { x: 100, y: 0 },
    { x: 0, y: 100 },
  ];
  it("computes bounds, area and hit tests", () => {
    expect(polygonBounds(tri)).toEqual({ x0: 0, y0: 0, x1: 100, y1: 100 });
    expect(polygonArea(tri)).toBe(5000);
    expect(pointInPolygon({ x: 10, y: 10 }, tri)).toBe(true);
    expect(pointInPolygon({ x: 90, y: 90 }, tri)).toBe(false);
  });
  it("formats SVG points and translates page polygons", () => {
    expect(svgPoints(tri)).toBe("0,0 100,0 0,100");
    expect(translatePolygon([[1, 2], [3, 4]], 10, -1)).toEqual([
      [11, 1],
      [13, 3],
    ]);
    expect(polygonBox([[5, 9], [1, 3], [7, 2]])).toEqual({ x0: 1, y0: 2, x1: 7, y1: 9 });
  });
  it("closes when clicking near the first vertex, only with 3+ points", () => {
    expect(closesPolygon(tri, { x: 4, y: 3 })).toBe(true);
    expect(closesPolygon(tri, { x: 30, y: 30 })).toBe(false);
    expect(closesPolygon(tri.slice(0, 2), { x: 0, y: 0 })).toBe(false);
  });
});

describe("screen ↔ page conversion of shapes", () => {
  it("converts a view polygon to page units and back (unrotated)", () => {
    const view = [
      { x: 20, y: 40 },
      { x: 200, y: 40 },
      { x: 110, y: 300 },
    ];
    const page = viewPolygonToPage(view, 2, undefined, { width: 612, height: 792 });
    expect(page).toEqual([
      [10, 20],
      [100, 20],
      [55, 150],
    ]);
    const back = pagePolygonToView(page, 2);
    back.forEach((p, i) => {
      expect(p.x).toBeCloseTo(view[i].x);
      expect(p.y).toBeCloseTo(view[i].y);
    });
  });

  it("clamps polygon points to the page", () => {
    const page = viewPolygonToPage([{ x: -50, y: 10 }, { x: 5000, y: 5000 }, { x: 10, y: 10 }], 1, undefined, { width: 612, height: 792 });
    expect(page[0][0]).toBe(0);
    expect(page[1]).toEqual([612, 792]);
  });

  it("round-trips through a rotated page (90°)", () => {
    // displayed page is 792 wide × 612 high; points are stored unrotated
    const view = [
      { x: 100, y: 50 },
      { x: 300, y: 80 },
      { x: 200, y: 400 },
    ];
    const scale = 1.5;
    const page = viewPolygonToPage(view, scale, ROT90, { width: 792, height: 612 });
    const back = pagePolygonToView(page, scale, ROT90);
    back.forEach((p, i) => {
      expect(p.x).toBeCloseTo(view[i].x, 1);
      expect(p.y).toBeCloseTo(view[i].y, 1);
    });
  });

  it("maps a dragged ellipse / rectangle box to page units", () => {
    expect(viewDragToPageRect({ x: 300, y: 200 }, { x: 100, y: 100 }, 2, toMatrix(null), { width: 612, height: 792 })).toEqual({
      x0: 50,
      y0: 50,
      x1: 150,
      y1: 100,
    });
    // rotated: the drawn box comes back in the unrotated page space (612 × 792)
    const r = viewDragToPageRect({ x: 0, y: 0 }, { x: 792, y: 612 }, 1, ROT90, { width: 792, height: 612 });
    expect(r).toEqual({ x0: 0, y0: 0, x1: 612, y1: 792 });
  });

  it("draws stored polygons on the displayed (rotated) page", () => {
    const d = { meta: { shape: "polygon" as const, points: [[0, 0], [100, 0], [0, 50]] } };
    const s = displayShape(d, { x0: 0, y0: 0, x1: 100, y1: 50 }, ROT90);
    expect(s.kind).toBe("polygon");
    if (s.kind === "polygon") {
      expect(s.pts[0]).toEqual({ x: 792, y: 0 });
      expect(s.pts[1]).toEqual({ x: 792, y: 100 });
      expect(s.r).toEqual({ x0: 742, y0: 0, x1: 792, y1: 100 });
    }
    const e = displayShape({ meta: { shape: "ellipse" } }, { x0: 10, y0: 10, x1: 30, y1: 20 });
    expect(e.kind).toBe("ellipse");
    if (e.kind === "ellipse") expect(e.e).toEqual({ cx: 20, cy: 15, rx: 10, ry: 5 });
  });
});

describe("resize handles and constraints", () => {
  const r = { x0: 10, y0: 10, x1: 50, y1: 30 };
  it("moves only the dragged edges and never inverts", () => {
    expect(resizeRect(r, "se", { x: 80, y: 60 })).toEqual({ x0: 10, y0: 10, x1: 80, y1: 60 });
    expect(resizeRect(r, "w", { x: 0, y: 999 })).toEqual({ x0: 0, y0: 10, x1: 50, y1: 30 });
    expect(resizeRect(r, "n", { x: 0, y: 100 }, 2)).toEqual({ x0: 10, y0: 28, x1: 50, y1: 30 });
  });
  it("places handles on corners and edge midpoints", () => {
    expect(handlePoint(r, "nw")).toEqual({ x: 10, y: 10 });
    expect(handlePoint(r, "e")).toEqual({ x: 50, y: 20 });
    expect(handlePoint(r, "s")).toEqual({ x: 30, y: 30 });
  });
  it("constrains to a square / circle", () => {
    expect(constrainSquare({ x: 0, y: 0 }, { x: 30, y: -10 })).toEqual({ x: 30, y: -30 });
  });
});

describe("detection shapes", () => {
  it("reads meta.shape and meta.points", () => {
    expect(detectionShape({ meta: {} })).toBe("rect");
    expect(detectionShape({ meta: { shape: "ellipse" } })).toBe("ellipse");
    expect(detectionPoints({ meta: { shape: "polygon", points: [[1, 2], [3, 4], [5, "6"] as unknown as number[]] } })).toEqual([
      [1, 2],
      [3, 4],
      [5, 6],
    ]);
    expect(detectionPoints({ meta: { shape: "polygon", points: [[1, 2]] } })).toBeNull();
    expect(detectionPoints({ meta: { shape: "rect", points: [[1, 2], [3, 4], [5, 6]] } })).toBeNull();
  });
});
