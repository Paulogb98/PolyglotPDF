import { describe, expect, it } from "vitest";
import { constrain, corner, fold, releases, sweep, turnedCorner, type Matrix, type Point, type Sheet } from "./curl";

const RIGHT: Sheet = { width: 400, height: 600, spine: "left" }; // the right leaf, turning forward
const LEFT: Sheet = { width: 400, height: 600, spine: "right" }; // the left leaf, turning back

const apply = ([a, b, c, d, e, f]: Matrix, p: Point): Point => ({ x: a * p.x + c * p.y + e, y: b * p.x + d * p.y + f });
const close = (p: Point, q: Point) => {
  expect(p.x).toBeCloseTo(q.x, 6);
  expect(p.y).toBeCloseTo(q.y, 6);
};

describe("fold", () => {
  it("is nothing while the corner is home", () => {
    expect(fold(RIGHT, "bottom", corner(RIGHT, "bottom"))).toBeNull();
  });

  it("lays the back page exactly on the other leaf when the page has turned", () => {
    const turned = fold(RIGHT, "bottom", turnedCorner(RIGHT, "bottom"));
    expect(turned).not.toBeNull();
    // Back content laid out as it reads once turned lands one sheet to the left.
    close(apply(turned!.backMatrix, { x: 0, y: 0 }), { x: -400, y: 0 });
    close(apply(turned!.backMatrix, { x: 400, y: 600 }), { x: 0, y: 600 });
    expect(turned!.progress).toBeCloseTo(1);

    const back = fold(LEFT, "top", turnedCorner(LEFT, "top"));
    close(apply(back!.backMatrix, { x: 0, y: 0 }), { x: 400, y: 0 });
  });

  it("puts the pulled corner where the pointer is and shows the back there", () => {
    const pull = { x: 250, y: 520 };
    const folded = fold(RIGHT, "bottom", pull)!;
    // The sheet's corner, folded over, lands on the pointer...
    const home = corner(RIGHT, "bottom");
    const d = (home.x - folded.line.point.x) * folded.line.normal.x + (home.y - folded.line.point.y) * folded.line.normal.y;
    close({ x: home.x - 2 * d * folded.line.normal.x, y: home.y - 2 * d * folded.line.normal.y }, pull);
    // ...and the back page's point at that corner (its spine-side bottom, u = 0) is there too.
    close(apply(folded.backMatrix, { x: 0, y: 600 }), pull);
  });

  it("splits the page into what stays flat and what lifts", () => {
    const folded = fold(RIGHT, "bottom", { x: 300, y: 500 })!;
    const area = (points: Point[]) =>
      Math.abs(points.reduce((sum, p, i) => sum + p.x * points[(i + 1) % points.length].y - points[(i + 1) % points.length].x * p.y, 0)) / 2;
    expect(area(folded.front) + area(folded.lifted)).toBeCloseTo(400 * 600, 3);
    expect(area(folded.flap)).toBeCloseTo(area(folded.lifted), 3);
  });
});

describe("constrain", () => {
  it("keeps the corner within the paper's reach of the spine", () => {
    const held = constrain(RIGHT, "bottom", { x: -900, y: 600 });
    expect(Math.hypot(held.x - 0, held.y - 600)).toBeCloseTo(400);
    const inside = { x: 200, y: 580 };
    expect(constrain(RIGHT, "bottom", inside)).toEqual(inside);
  });
});

describe("releases", () => {
  it("turns past the middle of the page or when thrown, and falls back otherwise", () => {
    expect(releases(RIGHT, { x: 150, y: 600 }, 0)).toBe(true);
    expect(releases(RIGHT, { x: 320, y: 600 }, 0)).toBe(false);
    expect(releases(RIGHT, { x: 320, y: 600 }, -1)).toBe(true);
    expect(releases(LEFT, { x: 320, y: 600 }, 0)).toBe(true);
    expect(releases(LEFT, { x: 250, y: 600 }, -1)).toBe(false);
  });
});

describe("sweep", () => {
  it("starts at the corner, lifts on the way and lands mirrored over the spine", () => {
    expect(sweep(RIGHT, "bottom", 0)).toEqual(corner(RIGHT, "bottom"));
    close(sweep(RIGHT, "bottom", 1), turnedCorner(RIGHT, "bottom"));
    expect(sweep(RIGHT, "bottom", 0.5).y).toBeLessThan(600);
  });
});
