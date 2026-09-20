import { describe, expect, it } from "vitest";
import type { Mark, Notebook } from "../../api/types";
import { toCsv, toMarkdown } from "./export";

function mark(changes: Partial<Mark> = {}): Mark {
  return {
    id: "m1",
    document_id: "d1",
    version_id: null,
    kind: "highlight",
    color: "yellow",
    quote: "o começo é ele mesmo um resultado",
    note: null,
    tags: [],
    start: { page: 82, offset: 120 },
    end: { page: 82, offset: 160 },
    page: 82,
    section: ["Com que o livro pode começar"],
    source: "reader",
    in_notebook: true,
    created_at: "2026-09-18T10:00:00+00:00",
    updated_at: "2026-09-18T10:00:00+00:00",
    ...changes,
  };
}

describe("toMarkdown", () => {
  it("files every mark under its chapter, with the page it came from", () => {
    const notebook: Notebook = {
      document: { id: "d1", title: "Ciência da Lógica", authors: "G. W. F. Hegel" },
      chapters: [
        {
          title: "Com que o livro pode começar",
          first_page: 78,
          last_page: 92,
          marks: [
            mark(),
            mark({ id: "m2", kind: "note", note: "comparar com Kant", tags: ["dúvida"] }),
            mark({ id: "m3", source: "tutor", quote: "passagem densa" }),
          ],
        },
      ],
      counts: {
        total: 3,
        highlights: 1,
        notes: 1,
        tutor: 1,
        cards: 0,
        due: 0,
        new: 0,
        hard: 0,
        ok: 0,
      },
      concepts: [],
      marks: [],
      reading_seconds: 0,
      reading_days: 0,
    };
    const text = toMarkdown(notebook);
    expect(text).toContain("# Ciência da Lógica");
    expect(text).toContain("*G. W. F. Hegel*");
    expect(text).toContain("## Com que o livro pode começar");
    expect(text).toContain("> o começo é ele mesmo um resultado");
    expect(text).toContain("comparar com Kant");
    expect(text).toContain("— p. 83 · dúvida");
    expect(text).toContain("— p. 83 · do tutor");
  });
});

describe("toCsv", () => {
  it("quotes the fields and doubles the quotation marks inside them", () => {
    const csv = toCsv([mark({ note: 'ele diz "resultado"', tags: ["ser", "nada"] })]);
    const [header, row] = csv.split("\n");
    expect(header).toBe("Frente,Verso,Etiquetas");
    expect(row).toBe('"ele diz ""resultado""","o começo é ele mesmo um resultado","ser nada"');
  });

  it("falls back to the page when the mark has no note of its own", () => {
    expect(toCsv([mark()]).split("\n")[1]).toMatch(/^"p\. 83"/);
  });
});
