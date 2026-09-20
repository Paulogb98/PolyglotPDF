/**
 * The geometry of a page being turned by its corner, like paper.
 *
 * A sheet is one leaf plus half the gutter, so it hinges in the middle of the spine. In
 * the sheet's own box ([0, width] × [0, height]) the spine is the left edge when the right
 * leaf turns forward, the right edge when the left leaf turns back.
 *
 * Pulling the outer corner C to a point P folds the sheet along the perpendicular
 * bisector of C and P. What lies on C's side of that line lifts: it is reflected over the
 * line and shows the back of the sheet (the next page); what lies on the spine side stays
 * flat. The corner cannot go farther from the spine than the paper allows, so P is held
 * within reach of the two spine corners, as a real page is.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Sheet {
  width: number;
  height: number;
  /** Which edge of the sheet is bound to the spine. */
  spine: "left" | "right";
}

export type Edge = "top" | "bottom";

/** A 2D affine transform in CSS ``matrix(a, b, c, d, e, f)`` order. */
export type Matrix = [number, number, number, number, number, number];

export interface Fold {
  /** The part of the sheet still flat on the book (sheet coordinates). */
  front: Point[];
  /** The part that lifted, i.e. the page uncovered under it (sheet coordinates). */
  lifted: Point[];
  /** Where the lifted part lies once folded over (sheet coordinates). */
  flap: Point[];
  /** The lifted part in the back page's own coordinates, to clip it. */
  backClip: Point[];
  /** Places the back page (laid out as it reads when turned) onto the flap. */
  backMatrix: Matrix;
  /** A point on the fold line and its normal, pointing to the lifted side. */
  line: { point: Point; normal: Point };
  /** 0 when the corner is home, 1 when the sheet lies on the other side. */
  progress: number;
}

const dot = (a: Point, b: Point) => a.x * b.x + a.y * b.y;

export function spineX(sheet: Sheet): number {
  return sheet.spine === "left" ? 0 : sheet.width;
}

/** The outer corner the reader pulls. */
export function corner(sheet: Sheet, edge: Edge): Point {
  return { x: sheet.spine === "left" ? sheet.width : 0, y: edge === "top" ? 0 : sheet.height };
}

/** Where the corner ends when the page has turned: mirrored over the spine. */
export function turnedCorner(sheet: Sheet, edge: Edge): Point {
  const home = corner(sheet, edge);
  return { x: 2 * spineX(sheet) - home.x, y: home.y };
}

/** Keep the corner within reach of the paper: no farther from the spine's corners
 *  than the page's edge and diagonal. */
export function constrain(sheet: Sheet, edge: Edge, point: Point): Point {
  const x = spineX(sheet);
  const near = { x, y: edge === "top" ? 0 : sheet.height };
  const far = { x, y: edge === "top" ? sheet.height : 0 };
  const limit = (anchor: Point, reach: number, p: Point): Point => {
    const dx = p.x - anchor.x;
    const dy = p.y - anchor.y;
    const distance = Math.hypot(dx, dy);
    if (distance <= reach || distance === 0) return p;
    return { x: anchor.x + (dx * reach) / distance, y: anchor.y + (dy * reach) / distance };
  };
  const held = limit(near, sheet.width, point);
  return limit(far, Math.hypot(sheet.width, sheet.height), held);
}

/** The rectangle [0,w]×[0,h] cut by the line through ``point`` with ``normal``, keeping
 *  the side where (X − point)·normal has the sign of ``side``. */
export function cut(width: number, height: number, point: Point, normal: Point, side: 1 | -1): Point[] {
  const box = [
    { x: 0, y: 0 },
    { x: width, y: 0 },
    { x: width, y: height },
    { x: 0, y: height },
  ];
  const value = (p: Point) => side * (dot({ x: p.x - point.x, y: p.y - point.y }, normal));
  const kept: Point[] = [];
  for (let index = 0; index < box.length; index += 1) {
    const current = box[index];
    const next = box[(index + 1) % box.length];
    const a = value(current);
    const b = value(next);
    if (a >= 0) kept.push(current);
    if ((a >= 0) !== (b >= 0)) {
      const t = a / (a - b);
      kept.push({ x: current.x + (next.x - current.x) * t, y: current.y + (next.y - current.y) * t });
    }
  }
  return kept;
}

export function reflect(p: Point, point: Point, normal: Point): Point {
  const distance = dot({ x: p.x - point.x, y: p.y - point.y }, normal);
  return { x: p.x - 2 * distance * normal.x, y: p.y - 2 * distance * normal.y };
}

/** Fold the sheet so that its ``edge`` corner sits at ``pull``; null while the corner
 *  is (practically) home. */
export function fold(sheet: Sheet, edge: Edge, pull: Point): Fold | null {
  const home = corner(sheet, edge);
  const at = constrain(sheet, edge, pull);
  const dx = home.x - at.x;
  const dy = home.y - at.y;
  const length = Math.hypot(dx, dy);
  if (length < 0.5) return null;
  const normal = { x: dx / length, y: dy / length };
  const point = { x: (home.x + at.x) / 2, y: (home.y + at.y) / 2 };
  const { width, height } = sheet;
  const lifted = cut(width, height, point, normal, 1);
  const front = cut(width, height, point, normal, -1);

  // Back page content at U shows the sheet's point S(U) = (width − u, v); folding maps that
  // point to R(S(U)). As a matrix: R·D with D = diag(−1, 1), then the translations.
  const { x: nx, y: ny } = normal;
  const r11 = 1 - 2 * nx * nx;
  const r12 = -2 * nx * ny;
  const r22 = 1 - 2 * ny * ny;
  const offset = 2 * dot(point, normal);
  const backMatrix: Matrix = [
    -r11,
    -r12,
    r12,
    r22,
    r11 * width + offset * nx,
    r12 * width + offset * ny,
  ];
  const travel = Math.abs(turnedCorner(sheet, edge).x - home.x);
  return {
    front,
    lifted,
    flap: lifted.map((p) => reflect(p, point, normal)),
    backClip: lifted.map((p) => ({ x: width - p.x, y: p.y })),
    backMatrix,
    line: { point, normal },
    progress: Math.min(1, Math.max(0, Math.abs(at.x - home.x) / travel)),
  };
}

/** Let go: does the page turn, or fall back? Once the corner is past the middle of the
 *  page, or when it is thrown toward the spine. */
export function releases(sheet: Sheet, pull: Point, velocityX: number): boolean {
  const towardSpine = sheet.spine === "left" ? -velocityX : velocityX;
  if (towardSpine > 0.5) return true;
  if (towardSpine < -0.5) return false;
  const share = sheet.spine === "left" ? pull.x / sheet.width : 1 - pull.x / sheet.width;
  return share < 0.5;
}

/** The corner's way over the book when the page turns by itself: it lifts a little,
 *  crosses the spine and lands on the other side. ``t`` is already eased. */
export function sweep(sheet: Sheet, edge: Edge, t: number): Point {
  const from = corner(sheet, edge);
  const to = turnedCorner(sheet, edge);
  const lift = sheet.height * 0.16 * Math.sin(Math.PI * t);
  return { x: from.x + (to.x - from.x) * t, y: from.y + (edge === "top" ? lift : -lift) };
}

export function polygon(points: Point[], dx = 0, dy = 0): string {
  return `polygon(${points.map((p) => `${(p.x + dx).toFixed(1)}px ${(p.y + dy).toFixed(1)}px`).join(", ")})`;
}

/** A CSS linear gradient over a box ``width``×``height`` that starts at ``point`` and runs
 *  along ``direction``: ``stops`` are [distance in px, colour] measured from the point. */
export function band(
  width: number,
  height: number,
  point: Point,
  direction: Point,
  stops: [number, string][],
): string {
  const angle = (Math.atan2(direction.x, -direction.y) * 180) / Math.PI;
  const length = Math.abs(width * direction.x) + Math.abs(height * direction.y);
  const start = { x: width / 2 - (direction.x * length) / 2, y: height / 2 - (direction.y * length) / 2 };
  const origin = dot({ x: point.x - start.x, y: point.y - start.y }, direction);
  const list = stops.map(([distance, colour]) => `${colour} ${(origin + distance).toFixed(1)}px`);
  return `linear-gradient(${angle.toFixed(2)}deg, transparent ${origin.toFixed(1)}px, ${list.join(", ")})`;
}

export const easeInOut = (t: number) => 0.5 - Math.cos(Math.PI * t) / 2;
export const easeOut = (t: number) => 1 - (1 - t) ** 3;
