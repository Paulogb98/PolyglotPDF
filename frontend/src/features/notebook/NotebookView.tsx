import { ChevronLeft, Download, FileDown, Layers, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Notebook } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { Segmented, Spinner } from "../../components/ui";
import { exportBook, saveText } from "../../lib/desktop";
import { relativeTime } from "../../lib/format";
import { t, tn } from "../../i18n";
import { navigate, paths } from "../../lib/router";
import { usePreferences } from "../settings/PreferencesContext";
import { toCsv, toMarkdown } from "./export";

type Filter = "tudo" | "highlight" | "note" | "tutor";

/** The study notebook: everything you marked in one book, filed under its chapter. */
export function NotebookView({ id }: { id: string }) {
  const [notebook, setNotebook] = useState<Notebook | null>(null);
  const [filter, setFilter] = useState<Filter>("tudo");
  const toast = useToast();
  const { ink } = usePreferences();

  const load = useCallback(async () => {
    try {
      setNotebook(await api.notebook(id));
    } catch (error) {
      toast({ kind: "error", title: t("notebook.openFailed"), body: errorMessage(error) });
      navigate(paths.library());
    }
  }, [id, toast]);

  useEffect(() => void load(), [load]);

  const chapters = useMemo(() => {
    if (!notebook) return [];
    return notebook.chapters
      .map((chapter) => ({
        ...chapter,
        marks: chapter.marks.filter((mark) =>
          filter === "tudo"
            ? true
            : filter === "tutor"
              ? mark.source === "tutor"
              : mark.source === "reader" && mark.kind === filter,
        ),
      }))
      .filter((chapter) => chapter.marks.length > 0);
  }, [notebook, filter]);

  if (!notebook) {
    return (
      <div className="screen">
        <div className="ground" />
        <div className="row muted" style={{ padding: 52 }}>
          <Spinner /> {t("notebook.opening")}
        </div>
      </div>
    );
  }

  const { counts, concepts } = notebook;
  const minutes = Math.round(notebook.reading_seconds / 60);
  const saved = (done: boolean) => done && toast({ kind: "success", title: t("notebook.exported") });

  return (
    <div className="screen">
      <div className="ground" />
      <header className="page-head">
        <a className="icon-btn glass" href={paths.library()} aria-label={t("common.back")}>
          <ChevronLeft size={17} strokeWidth={2.5} />
        </a>
        <div className="title">
          <h1 className="display-l">{t("common.notebook")}</h1>
        </div>
        <a className="btn btn-outline" href={paths.reader(id)}>
          {t("notebook.backToBook")}
        </a>
        <a className="btn btn-action" href={paths.review(id)}>
          <Sparkles size={15} />
          {tn("notebook.reviewCards", counts.due)}
        </a>
      </header>

      <div className="split">
        <div className="main stack-4">
          <p className="small muted" style={{ maxWidth: "70ch" }}>
            <strong style={{ color: "var(--ink-2)" }}>{notebook.document.title}</strong> ·{" "}
            {tn("notebook.yours", counts.highlights + counts.notes)},{" "}
            {t("notebook.fromTutor", { n: counts.tutor })}
            {minutes ? t("notebook.readingMinutes", { n: minutes }) : ""}
            {t("notebook.anchored")}
          </p>
          <div>
            <Segmented
              variant="sm"
              value={filter}
              onChange={setFilter}
              options={[
                { value: "tudo", label: t("notebook.all", { n: counts.total }) },
                { value: "highlight", label: t("notebook.highlights", { n: counts.highlights }) },
                { value: "note", label: t("notebook.notes", { n: counts.notes }) },
                { value: "tutor", label: t("notebook.tutor", { n: counts.tutor }) },
              ]}
            />
          </div>

          {chapters.length === 0 ? (
            <div className="empty">
              <h2 className="display-s">{t("notebook.empty")}</h2>
              <p>
                {t("notebook.emptyBody")}
              </p>
              <a className="btn btn-action" href={paths.reader(id)}>
                {t("notebook.backToBook")}
              </a>
            </div>
          ) : (
            <div className="card" style={{ padding: "18px 12px 6px" }}>
              {chapters.map((chapter) => (
                <div key={chapter.title} className="chapter">
                  <div className="chapter-head">
                    <span className="name">{chapter.title || t("marks.noChapter")}</span>
                    <span className="range">
                      {t("notebook.pageRange", { from: chapter.first_page + 1, to: chapter.last_page + 1 })}
                    </span>
                  </div>
                  {chapter.marks.map((mark) => (
                    <a key={mark.id} className="entry" href={paths.reader(id, { page: mark.start.page })}>
                      <span
                        className="swatch"
                        style={{
                          background: mark.source === "tutor" ? "var(--tutor-line)" : ink(mark.color).ink,
                        }}
                      />
                      <span className="spacer">
                        <span className="quote">“{mark.quote}”</span>
                        {mark.note ? <span className="own">{mark.note}</span> : null}
                        <span className="sub">
                          {t("common.page", { page: mark.start.page + 1 })}
                          {mark.source === "tutor" ? t("search.fromTutor") : ""} · {relativeTime(mark.updated_at)}
                          {mark.tags.length ? ` · ${mark.tags.join(", ")}` : ""}
                        </span>
                      </span>
                    </a>
                  ))}
                </div>
              ))}
            </div>
          )}
        </div>

        <aside className="side">
          <section className="panel card">
            <span className="kicker">{t("notebook.today")}</span>
            <span className="figure">
              {counts.due}
              <span> {counts.due === 1 ? t("notebook.cards.one") : t("notebook.cards.other")}</span>
            </span>
            <p>
              {t("notebook.todayBody", { n: Math.max(1, Math.round(counts.due * 0.75)) })}
            </p>
            <div className="row tight wrap">
              <span className="chip action">{t("notebook.new", { n: counts.new })}</span>
              <span className="chip">{t("notebook.hard", { n: counts.hard })}</span>
              <span className="chip tutor">{t("notebook.ok", { n: counts.ok })}</span>
            </div>
            <a className="btn btn-action btn-block" href={paths.review(id)} style={{ marginTop: 4 }}>
              {t("notebook.reviewNow")}
            </a>
          </section>

          {concepts.length ? (
            <section className="panel card">
              <span className="kicker row tight">
                <Layers size={12} /> {t("notebook.concepts")}
              </span>
              <div className="row tight wrap">
                {concepts.map((concept) => (
                  <span key={concept.name} className="chip tutor">
                    {concept.name} · {concept.count}
                  </span>
                ))}
              </div>
            </section>
          ) : null}

          <section className="panel card">
            <span className="kicker">{t("notebook.export")}</span>
            <button
              type="button"
              className="btn btn-outline btn-sm btn-block"
              onClick={() =>
                void saveText(`${notebook.document.title}.md`, toMarkdown(notebook), "text/markdown").then(saved)
              }
            >
              <Download size={14} />
              {t("notebook.exportMarkdown")}
            </button>
            <button
              type="button"
              className="btn btn-outline btn-sm btn-block"
              onClick={() =>
                void saveText(`${notebook.document.title}.csv`, toCsv(notebook.marks), "text/csv").then(saved)
              }
            >
              <Download size={14} />
              {t("notebook.exportCsv")}
            </button>
            <button
              type="button"
              className="btn btn-outline btn-sm btn-block"
              onClick={() => void exportBook(id, null).then(saved)}
            >
              <FileDown size={14} />
              {t("notebook.exportBook")}
            </button>
          </section>
        </aside>
      </div>
    </div>
  );
}
