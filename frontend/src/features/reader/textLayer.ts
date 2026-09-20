import { api } from "../../api/client";
import type { Anchor, LayerWord, Rect, TextLayer } from "../../api/types";
import { codePoints } from "../../lib/format";

// The text layer is a transparent copy of the page's words laid over the page image,
// so that the reader can select text. Each word is a <span data-o="offset"> placed at
// its box on the page (in PDF points; the layer is scaled with CSS) and stretched to
// the word's width; offsets are those of the page text on the server.

export function compareAnchors(a: Anchor, b: Anchor): number {
  return a.page - b.page || a.offset - b.offset;
}

/** Rectangles of the words intersecting ``[start, end)``, merged along each line. */
export function rangeRects(words: LayerWord[], start: number, end: number): Rect[] {
  const rects: Rect[] = [];
  for (const [x0, y0, x1, y1, offset, text] of words) {
    const wordEnd = offset + codePoints(text.trimEnd());
    if (wordEnd <= start || offset >= end) continue;
    const last = rects[rects.length - 1];
    const sameLine =
      last !== undefined &&
      Math.abs(last[1] - y0) < 2 &&
      Math.abs(last[3] - y1) < 2 &&
      x0 >= last[0] &&
      x0 - last[2] < 20;
    if (last && sameLine) last[2] = Math.max(last[2], x1);
    else rects.push([x0, y0, x1, y1]);
  }
  return rects;
}

/** Text for the clipboard: words hyphenated at line ends are joined again. */
export function cleanCopy(text: string): string {
  return text
    .replace(/(\p{L})[-­]\s+(\p{Ll})/gu, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

let context: CanvasRenderingContext2D | null | undefined;

function measure(text: string, fontSize: number): number {
  if (context === undefined) context = document.createElement("canvas").getContext("2d");
  if (!context) return 0;
  context.font = `${fontSize}px sans-serif`;
  return context.measureText(text).width;
}

export function buildTextLayer(container: HTMLElement, layer: TextLayer): void {
  const fragment = document.createDocumentFragment();
  for (const [x0, y0, x1, y1, start, text] of layer.words) {
    const width = x1 - x0;
    const height = y1 - y0;
    if (width <= 0 || height <= 0) continue;
    const fontSize = height * 0.82;
    const span = document.createElement("span");
    span.textContent = text;
    span.dataset.o = String(start);
    span.style.left = `${x0}px`;
    span.style.top = `${y0}px`;
    span.style.fontSize = `${fontSize}px`;
    span.style.lineHeight = `${height}px`;
    span.style.height = `${height}px`;
    const natural = measure(text.trimEnd(), fontSize);
    if (natural > 0) span.style.transform = `scaleX(${(width / natural).toFixed(4)})`;
    fragment.append(span);
  }
  container.replaceChildren(fragment);
}

const cache = new Map<string, Promise<TextLayer>>();

/** Text layer of a page, fetched once and shared by every view of the page. */
export function loadTextLayer(documentId: string, page: number, version: string | null): Promise<TextLayer> {
  const key = `${documentId}|${version ?? ""}|${page}`;
  let promise = cache.get(key);
  if (!promise) {
    promise = api.textLayer(documentId, page, version);
    promise.catch(() => cache.delete(key));
    cache.set(key, promise);
    if (cache.size > 400) {
      const oldest = cache.keys().next().value;
      if (oldest !== undefined) cache.delete(oldest);
    }
  }
  return promise;
}
