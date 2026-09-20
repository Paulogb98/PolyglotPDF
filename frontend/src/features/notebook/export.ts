import type { Mark, Notebook } from "../../api/types";
import { t } from "../../i18n";

/** The notebook as one Markdown file: chapters, quotes, notes and where they came from. */
export function toMarkdown(notebook: Notebook): string {
  const lines = [`# ${notebook.document.title}`];
  if (notebook.document.authors) lines.push(`*${notebook.document.authors}*`);
  lines.push("");
  for (const chapter of notebook.chapters) {
    lines.push(`## ${chapter.title || t("marks.noChapter")}`, "");
    for (const mark of chapter.marks) {
      lines.push(`> ${mark.quote}`);
      if (mark.note) lines.push("", mark.note);
      const meta = [t("common.page", { page: mark.start.page + 1 })];
      if (mark.source === "tutor") meta.push(t("export.fromTutor"));
      if (mark.tags.length) meta.push(mark.tags.join(", "));
      lines.push("", `— ${meta.join(" · ")}`, "");
    }
  }
  return lines.join("\n");
}

const escape = (value: string) => `"${value.replace(/"/g, '""')}"`;

/** Cards for Anki: the note (or the page) in front, the quoted passage behind. */
export function toCsv(marks: Mark[]): string {
  return [
    t("export.csvHeader"),
    ...marks.map((mark) =>
      [
        escape(mark.note ? mark.note : t("common.page", { page: mark.start.page + 1 })),
        escape(mark.quote),
        escape(mark.tags.join(" ")),
      ].join(","),
    ),
  ].join("\n");
}
