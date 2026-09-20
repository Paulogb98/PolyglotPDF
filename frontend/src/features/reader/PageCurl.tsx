import { useEffect, useLayoutEffect, useRef, type ReactNode } from "react";
import {
  band,
  corner,
  easeInOut,
  easeOut,
  fold,
  polygon,
  releases,
  sweep,
  turnedCorner,
  type Edge,
  type Point,
  type Sheet,
} from "./curl";

/** How the turn is driven: by itself (arrows, buttons), or by the reader's hand. */
export type CurlMode = "auto" | "drag";

/** Pointer travel under which a press on the corner counts as a click (turn the page). */
const CLICK = 6;

/**
 * A page turning by its corner. The book underneath shows the spreads the leaf uncovers
 * and lands on (``base``); over it lies the sheet — the leaf plus half the gutter — cut
 * along the fold: the flat part (``front``), the shadow on the page it uncovers, the
 * lifted part carrying the next page on its back (``back``) and the light on the curl.
 *
 * Geometry comes from ``curl.ts``; this component only moves the corner, per animation
 * frame and without React renders, and tells the reader whether the page turned.
 */
export function PageCurl({
  forward,
  leafWidth,
  gutter,
  edge,
  mode,
  grab,
  duration,
  base,
  front,
  back,
  onFinish,
}: {
  forward: boolean;
  leafWidth: number;
  gutter: number;
  edge: Edge;
  mode: CurlMode;
  /** Where the pointer went down (client coordinates), for a drag. */
  grab?: Point;
  /** Milliseconds a whole turn takes when the page turns by itself. */
  duration: number;
  base: ReactNode;
  front: ReactNode;
  back: ReactNode;
  onFinish(turned: boolean): void;
}) {
  const sheetRef = useRef<HTMLDivElement>(null);
  const frontRef = useRef<HTMLDivElement>(null);
  const castRef = useRef<HTMLDivElement>(null);
  const flapRef = useRef<HTMLDivElement>(null);
  const backRef = useRef<HTMLDivElement>(null);
  const lightRef = useRef<HTMLDivElement>(null);
  const finished = useRef(onFinish);
  useEffect(() => {
    finished.current = onFinish;
  });

  const width = leafWidth + gutter / 2;

  useLayoutEffect(() => {
    const element = sheetRef.current;
    if (!element) return;
    const sheet: Sheet = { width, height: element.offsetHeight, spine: forward ? "left" : "right" };
    const home = corner(sheet, edge);

    const draw = (pull: Point) => {
      // The book can change size under the page (zoom, a resized window): measure again.
      sheet.width = element.offsetWidth;
      sheet.height = element.offsetHeight;
      // Shadow layers span the whole book (two sheets), so polygons shift by the sheet's
      // place in it: nothing on the left of the right sheet, a sheet on the left of the left.
      const pad = { x: forward ? sheet.width : 0, y: 0 };
      const layerSize = { width: sheet.width * 2, height: sheet.height };
      const folded = fold(sheet, edge, pull);
      const lifted = Boolean(folded);
      for (const layer of [castRef.current, flapRef.current, lightRef.current]) {
        if (layer) layer.style.visibility = lifted ? "visible" : "hidden";
      }
      if (!folded) {
        if (frontRef.current) frontRef.current.style.clipPath = "none";
        return;
      }
      const { point, normal } = folded.line;
      const away = { x: -normal.x, y: -normal.y };
      const at = { x: point.x + pad.x, y: point.y + pad.y };
      // Shadows grow as the leaf stands up and fade as it lands.
      const depth = Math.sin(Math.PI * Math.min(1, folded.progress * 1.15)) * 0.85 + 0.15;
      if (frontRef.current) frontRef.current.style.clipPath = polygon(folded.front);
      if (castRef.current) {
        castRef.current.style.clipPath = polygon(folded.lifted, pad.x, pad.y);
        castRef.current.style.backgroundImage = band(layerSize.width, layerSize.height, at, normal, [
          [0, `rgb(46 43 37 / ${(0.42 * depth).toFixed(3)})`],
          [sheet.width * 0.05, `rgb(46 43 37 / ${(0.16 * depth).toFixed(3)})`],
          [sheet.width * 0.22, "rgb(46 43 37 / 0)"],
        ]);
      }
      if (backRef.current) {
        backRef.current.style.transform = `matrix(${folded.backMatrix.map((value) => value.toFixed(5)).join(",")})`;
        backRef.current.style.clipPath = polygon(folded.backClip);
      }
      if (flapRef.current) {
        flapRef.current.style.filter = `drop-shadow(0 0 ${(4 + 14 * depth).toFixed(1)}px rgb(46 43 37 / ${(0.3 * depth).toFixed(3)}))`;
      }
      if (lightRef.current) {
        lightRef.current.style.clipPath = polygon(folded.flap, pad.x, pad.y);
        lightRef.current.style.backgroundImage = band(layerSize.width, layerSize.height, at, away, [
          [0, `rgb(46 43 37 / ${(0.24 * depth).toFixed(3)})`],
          [sheet.width * 0.035, "rgb(255 252 244 / 0.16)"],
          [sheet.width * 0.12, "rgb(255 252 244 / 0)"],
          [sheet.width * 0.6, "rgb(46 43 37 / 0)"],
          [sheet.width * 1.1, `rgb(46 43 37 / ${(0.1 * depth).toFixed(3)})`],
        ]);
      }
    };

    let frame = 0;
    let guard = 0;
    const animate = (from: Point, to: (t: number) => Point, ms: number, ease: (t: number) => number, turned: boolean) => {
      const started = performance.now();
      let over = false;
      const end = () => {
        if (over) return;
        over = true;
        cancelAnimationFrame(frame);
        window.clearTimeout(guard);
        draw(to(1));
        finished.current(turned);
      };
      const step = (now: number) => {
        const t = Math.min(1, (now - started) / Math.max(1, ms));
        if (t >= 1) {
          end();
          return;
        }
        draw(to(ease(t)));
        frame = requestAnimationFrame(step);
      };
      draw(from);
      frame = requestAnimationFrame(step);
      // A hidden or minimised window gets no animation frames: the page still turns.
      guard = window.setTimeout(end, ms + 250);
    };
    const glide = (from: Point, target: Point, turned: boolean, full: number) => {
      const share = Math.hypot(target.x - from.x, target.y - from.y) / (2 * sheet.width);
      const ms = Math.max(220, full * Math.min(1, share));
      animate(from, (t) => ({ x: from.x + (target.x - from.x) * t, y: from.y + (target.y - from.y) * t }), ms, easeOut, turned);
    };

    if (mode === "auto") {
      animate(home, (t) => sweep(sheet, edge, t), duration, easeInOut, true);
      return () => {
        cancelAnimationFrame(frame);
        window.clearTimeout(guard);
      };
    }

    // Dragging: the corner follows the hand, keeping the offset it was grabbed with.
    // Client pixels to sheet pixels (the window may be zoomed or scaled).
    const box = element.getBoundingClientRect();
    const ratio = element.offsetWidth / Math.max(1, box.width);
    const local = (x: number, y: number) => ({ x: (x - box.left) * ratio, y: (y - box.top) * ratio });
    const start = grab ? local(grab.x, grab.y) : home;
    const offset = { x: home.x - start.x, y: home.y - start.y };
    let pull = home;
    let travelled = 0;
    let last = { x: grab?.x ?? 0, time: performance.now() };
    let velocity = 0;
    let pending = false;
    const startedAt = performance.now();
    draw(home);

    const onMove = (event: PointerEvent) => {
      const at = local(event.clientX, event.clientY);
      pull = { x: at.x + offset.x, y: at.y + offset.y };
      travelled = Math.max(travelled, Math.hypot(at.x - start.x, at.y - start.y));
      const now = performance.now();
      if (now > last.time) velocity = velocity * 0.4 + ((event.clientX - last.x) / (now - last.time)) * 0.6;
      last = { x: event.clientX, time: now };
      if (!pending) {
        pending = true;
        frame = requestAnimationFrame(() => {
          pending = false;
          draw(pull);
        });
      }
    };
    const release = (event: PointerEvent | null) => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
      cancelAnimationFrame(frame);
      const clicked = event !== null && travelled < CLICK && performance.now() - startedAt < 400;
      if (clicked) {
        // A click on the corner turns the page, as the arrows do.
        animate(home, (t) => sweep(sheet, edge, t), duration, easeInOut, true);
        return;
      }
      const turned = event !== null && releases(sheet, pull, velocity);
      glide(pull, turned ? turnedCorner(sheet, edge) : home, turned, duration * 0.8);
    };
    const onUp = (event: PointerEvent) => release(event);
    const onCancel = () => release(null);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.stopPropagation();
        release(null);
      }
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onCancel);
    window.addEventListener("keydown", onKey, true);
    window.document.documentElement.dataset.dragging = "page";
    return () => {
      delete window.document.documentElement.dataset.dragging;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onCancel);
      window.removeEventListener("keydown", onKey, true);
      cancelAnimationFrame(frame);
      window.clearTimeout(guard);
    };
    // The turn is set up once: a new turn is a new component (keyed by the reader).
  }, []);

  const spineAt = forward ? "start" : "end";
  return (
    <div className="book pair curling">
      {base}
      <div
        ref={sheetRef}
        className={`curl ${forward ? "forward" : "backward"}`}
        style={{ width, left: forward ? leafWidth + gutter / 2 : 0 }}
        aria-hidden="true"
      >
        <div ref={frontRef} className={`curl-face spine-${spineAt}`}>
          <i className="face-gutter" />
          {front}
        </div>
        <div ref={castRef} className="curl-shadow" />
        <div ref={flapRef} className="curl-flap">
          <div ref={backRef} className={`curl-face curl-back spine-${forward ? "end" : "start"}`}>
            <i className="face-gutter" />
            {back}
          </div>
        </div>
        <div ref={lightRef} className="curl-shadow" />
      </div>
    </div>
  );
}
