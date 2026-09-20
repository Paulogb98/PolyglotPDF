import { ArrowRight, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { ask } from "../../api/sse";
import type { DocumentSummary } from "../../api/types";
import { errorMessage } from "../../components/Toasts";
import { Spinner, Thinking } from "../../components/ui";
import { renderMarkdown } from "../../lib/markdown";
import { navigate, paths } from "../../lib/router";
import { t, tn } from "../../i18n";
import { findPassage, type Found } from "./findPassage";

interface Hit {
  document: DocumentSummary;
  page: number;
  count: number;
}

/** The library's search, inside the pages: where the words are, and — if you ask — what
 *  the companion makes of the best passage. */
export function InBookSearch({
  query,
  documents,
  companion,
}: {
  query: string;
  documents: DocumentSummary[];
  companion: boolean;
}) {
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [answer, setAnswer] = useState("");
  const [asking, setAsking] = useState<"idle" | "looking" | "answering" | "done">("idle");
  const [found, setFound] = useState<Found | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    setHits(null);
    void (async () => {
      const results: Hit[] = [];
      for (const document of documents.slice(0, 24)) {
        const found_ = await api
          .search(document.id, query, document.versions[0]?.id ?? null)
          .catch(() => null);
        for (const hit of found_?.hits ?? []) {
          results.push({ document, page: hit.page, count: hit.rects.length });
        }
        if (cancelled) return;
      }
      setHits(results.slice(0, 40));
    })();
    return () => {
      cancelled = true;
    };
  }, [query, documents]);

  useEffect(() => () => abort.current?.abort(), []);

  const askCompanion = async () => {
    abort.current?.abort();
    const controller = new AbortController();
    abort.current = controller;
    setAsking("looking");
    setAnswer("");
    setError(null);
    try {
      const passage = await findPassage(documents, query);
      if (!passage) {
        setError(t("inbook.notFound"));
        setAsking("done");
        return;
      }
      setFound(passage);
      setAsking("answering");
      await ask(
        {
          document_id: passage.document.id,
          version_id: passage.document.versions[0]?.id ?? null,
          start: { page: passage.page, offset: 0 },
          action: "ask",
          question: query,
        },
        {
          onThread: () => undefined,
          onDelta: (piece) => setAnswer((text) => text + piece),
          onDone: () => setAsking("done"),
          onError: (message) => {
            setError(message);
            setAsking("done");
          },
        },
        controller.signal,
      );
    } catch (caught) {
      if (!controller.signal.aborted) {
        setError(errorMessage(caught));
        setAsking("done");
      }
    }
  };

  const go = (document: DocumentSummary, page: number) =>
    navigate(paths.reader(document.id, { version: document.versions[0]?.id ?? null, page }));

  return (
    <section className="inbook card">
      <div className="row">
        <span className="kicker">{t("inbook.title")}</span>
        <span className="spacer" />
        {companion && asking === "idle" ? (
          <button type="button" className="btn btn-ink btn-sm" onClick={() => void askCompanion()}>
            <Sparkles size={14} />
            {t("inbook.ask")}
          </button>
        ) : null}
      </div>

      {asking !== "idle" ? (
        <div className="note ink" style={{ padding: "16px 18px" }}>
          <div className="note-head">
            <Sparkles size={13} />
            <span className="kicker night">{t("inbook.companion")}</span>
            {found ? (
              <button
                type="button"
                className="btn btn-xs btn-on-night"
                style={{ marginLeft: "auto" }}
                onClick={() => go(found.document, found.page)}
              >
                {found.document.title} · {t("common.page", { page: found.page + 1 })}
                <ArrowRight size={12} />
              </button>
            ) : null}
          </div>
          {answer ? (
            <div className="prose" dangerouslySetInnerHTML={{ __html: renderMarkdown(answer) }} />
          ) : asking === "looking" ? (
            <span className="small row tight" style={{ color: "var(--night-muted)" }}>
              <Spinner /> {t("inbook.looking")}
            </span>
          ) : asking === "answering" ? (
            <Thinking />
          ) : null}
          {error ? <p className="small" style={{ color: "var(--action-light)" }}>{error}</p> : null}
        </div>
      ) : null}

      {hits === null ? (
        <span className="row small muted">
          <Spinner /> {t("inbook.searching", { query })}
        </span>
      ) : hits.length === 0 ? (
        <p className="small muted">{t("inbook.none", { query })}</p>
      ) : (
        hits.map((hit) => (
          <button
            key={`${hit.document.id}-${hit.page}`}
            type="button"
            className="hit"
            onClick={() => go(hit.document, hit.page)}
          >
            <span className="strong spacer" style={{ fontSize: 13.5 }}>
              {hit.document.title}
            </span>
            <span className="caption">
              {t("common.page", { page: hit.page + 1 })} · {tn("common.matches", hit.count)}
            </span>
            <ArrowRight size={14} className="muted" />
          </button>
        ))
      )}
    </section>
  );
}
