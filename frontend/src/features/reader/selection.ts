import type { Anchor } from "../../api/types";
import { codePoints } from "../../lib/format";
import { compareAnchors } from "./textLayer";

export interface PageSelection {
  start: Anchor;
  end: Anchor;
  /** Translation shown where the text was selected (null: the original). */
  version: string | null;
  text: string;
  rect: DOMRect;
}

interface Boundary extends Anchor {
  version: string | null;
}

/** Map one end of a DOM range to a page and an offset of the page text. */
function boundary(node: Node, offset: number): Boundary | null {
  let element: Element | null;
  let within = 0;
  if (node.nodeType === Node.TEXT_NODE) {
    element = node.parentElement;
    within = codePoints((node.textContent ?? "").slice(0, offset));
  } else {
    element = node as Element;
    if (element.classList.contains("text-layer")) {
      // Between two words: take the word after the boundary (or the end of the last one).
      const words = element.children;
      if (!words.length) return null;
      const next = words[offset];
      if (next) {
        element = next;
      } else {
        element = words[words.length - 1] ?? null;
        within = codePoints(element?.textContent ?? "");
      }
    } else if (element.hasAttribute("data-o")) {
      within = offset > 0 ? codePoints(element.textContent ?? "") : 0;
    }
  }
  const word = element?.closest<HTMLElement>("[data-o]");
  const page = word?.closest<HTMLElement>("[data-page]");
  if (!word || !page) return null;
  return {
    page: Number(page.dataset.page),
    offset: Number(word.dataset.o) + within,
    version: page.dataset.version || null,
  };
}

/** The current selection when it lies on the text layers inside ``root``. */
export function readSelection(root: HTMLElement): PageSelection | null {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || selection.rangeCount === 0) return null;
  const range = selection.getRangeAt(0);
  if (!root.contains(range.commonAncestorContainer)) return null;
  const first = boundary(range.startContainer, range.startOffset);
  const last = boundary(range.endContainer, range.endOffset);
  if (!first || !last || first.version !== last.version) return null;
  const text = selection.toString().replace(/\s+/g, " ").trim();
  if (!text) return null;
  const start: Anchor = { page: first.page, offset: first.offset };
  const end: Anchor = { page: last.page, offset: last.offset };
  const ordered = compareAnchors(start, end) <= 0;
  return {
    start: ordered ? start : end,
    end: ordered ? end : start,
    version: first.version,
    text,
    rect: range.getBoundingClientRect(),
  };
}
