import DOMPurify from "dompurify";
import "katex/dist/katex.min.css";
import { Marked } from "marked";
import markedKatex from "marked-katex-extension";

// Answers of the reading companion: Markdown with LaTeX formulas, sanitised before
// being inserted into the page (the model's output is untrusted).
const marked = new Marked({ gfm: true, breaks: false });
marked.use(markedKatex({ throwOnError: false, nonStandard: true, output: "html" }));

DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A") {
    node.setAttribute("target", "_blank");
    node.setAttribute("rel", "noopener noreferrer");
  }
});

/** Convert \( \) and \[ \] delimiters, which models often use, to $ and $$. */
export function normaliseMath(source: string): string {
  return source
    .split(/(```[\s\S]*?```|`[^`\n]*`)/g)
    .map((part, index) =>
      index % 2 === 1
        ? part
        : part
            .replace(/\\\[([\s\S]+?)\\\]/g, (_, math: string) => `$$${math}$$`)
            .replace(/\\\(([\s\S]+?)\\\)/g, (_, math: string) => `$${math}$`),
    )
    .join("");
}

export function renderMarkdown(source: string): string {
  const html = marked.parse(normaliseMath(source), { async: false });
  return DOMPurify.sanitize(html, {
    USE_PROFILES: { html: true, mathMl: true, svg: true },
    ADD_ATTR: ["target"],
  });
}

// "p. 81", "pp. 80–81", "página 12", "pages 3-4": the companion names pages this way
// (its context marks them as [p. N]), and the reader can follow them.
const PAGE_REF = /\b(?:pp?\.|págs?\.|páginas?|pages?)[\s ]*(\d{1,5})(?:[\s ]*[–-][\s ]*\d{1,5})?/giu;

/** Turn the page references of rendered HTML into links to those pages (1-based numbers
 *  become ``data-page`` 0-based indexes). Links, code and formulas are left alone, and so
 *  is a number outside the book. */
export function linkPageRefs(html: string, pageCount: number): string {
  if (!html || !/\d/.test(html)) return html;
  const box = document.createElement("div");
  box.innerHTML = html;
  const walker = document.createTreeWalker(box, NodeFilter.SHOW_TEXT, {
    acceptNode: (node) =>
      node.parentElement?.closest("a, code, pre, .katex") ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT,
  });
  const nodes: Text[] = [];
  while (walker.nextNode()) nodes.push(walker.currentNode as Text);
  for (const node of nodes) {
    const text = node.data;
    const pieces: (string | HTMLAnchorElement)[] = [];
    let last = 0;
    for (const match of text.matchAll(PAGE_REF)) {
      const page = Number(match[1]);
      if (page < 1 || page > pageCount) continue;
      const link = document.createElement("a");
      link.className = "page-ref";
      link.href = "#";
      link.dataset.page = String(page - 1);
      link.textContent = match[0];
      pieces.push(text.slice(last, match.index), link);
      last = match.index + match[0].length;
    }
    if (!pieces.length) continue;
    pieces.push(text.slice(last));
    node.replaceWith(...pieces);
  }
  return box.innerHTML;
}

/** The page a click on a linked reference asks for (and the click is then handled). */
export function pageRefTarget(event: { target: EventTarget | null; preventDefault(): void }): number | null {
  const link = event.target instanceof Element ? event.target.closest<HTMLElement>("a.page-ref") : null;
  if (!link) return null;
  event.preventDefault();
  return Number(link.dataset.page);
}
