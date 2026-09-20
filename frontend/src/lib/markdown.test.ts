import { describe, expect, it } from "vitest";
import { linkPageRefs, normaliseMath, pageRefTarget, renderMarkdown } from "./markdown";

describe("renderMarkdown", () => {
  it("renders Markdown and formulas", () => {
    const html = renderMarkdown("**Olá** e $x^2$");
    expect(html).toContain("<strong>Olá</strong>");
    expect(html).toContain("katex");
  });

  it("removes scripts and event handlers from the model's answer", () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)"><script>alert(2)</script>ok');
    expect(html).not.toContain("onerror");
    expect(html).not.toContain("<script");
    expect(html).toContain("ok");
  });

  it("opens links outside the reader", () => {
    const html = renderMarkdown("[fonte](https://example.org)");
    expect(html).toContain('target="_blank"');
    expect(html).toContain('rel="noopener noreferrer"');
  });
});

describe("normaliseMath", () => {
  it("converts LaTeX delimiters outside code", () => {
    expect(normaliseMath("a \\(x\\) b \\[y\\] `\\(z\\)`")).toBe("a $x$ b $$y$$ `\\(z\\)`");
  });
});

describe("linkPageRefs", () => {
  it("links the pages the companion names, and only pages of the book", () => {
    const html = linkPageRefs(renderMarkdown("Duas páginas atrás (p. 81) ele prepara isso; ver pp. 80–81 e p. 900."), 120);
    const box = document.createElement("div");
    box.innerHTML = html;
    const links = [...box.querySelectorAll<HTMLAnchorElement>("a.page-ref")];
    expect(links.map((link) => [link.textContent, link.dataset.page])).toEqual([
      ["p. 81", "80"],
      ["pp. 80–81", "79"],
    ]);
    expect(box.textContent).toContain("p. 900");
  });

  it("leaves code, formulas and real links alone", () => {
    const html = linkPageRefs(renderMarkdown("`p. 3` e [page 4](https://example.org) e $p. 5$"), 10);
    expect(html).not.toContain("page-ref");
  });

  it("tells which page a click asks for", () => {
    const box = document.createElement("div");
    box.innerHTML = linkPageRefs("<p>see page 7</p>", 10);
    let prevented = false;
    const target = box.querySelector("a.page-ref");
    expect(pageRefTarget({ target, preventDefault: () => (prevented = true) })).toBe(6);
    expect(prevented).toBe(true);
    expect(pageRefTarget({ target: box, preventDefault: () => undefined })).toBeNull();
  });
});
