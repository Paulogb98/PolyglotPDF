import { Plus, Search, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../../api/client";
import type {
  DictionaryResult,
  HighlightInk,
  Layout,
  Mark,
  SearchResult,
  TutorSession,
} from "../../api/types";
import { CloseButton, Drawer, Key, Segmented, Spinner } from "../../components/ui";
import { relativeTime } from "../../lib/format";
import { paths } from "../../lib/router";
import { t, tn } from "../../i18n";

/** Sumário: the book's chapters, and the tutor's sessions made from them. */
export function OutlineDrawer({
  layout,
  sessions,
  page,
  onGo,
  onClose,
}: {
  layout: Layout;
  sessions: TutorSession[];
  page: number;
  onGo(page: number): void;
  onClose(): void;
}) {
  const [tab, setTab] = useState<"capitulos" | "sessoes">(layout.toc.length ? "capitulos" : "sessoes");
  const go = (target: number) => {
    onGo(target);
    onClose();
  };
  return (
    <Drawer side="left" onClose={onClose}>
      <div className="drawer-head">
        <h2 className="display-s">{t("outline.title")}</h2>
        <CloseButton onClick={onClose} />
      </div>
      <div className="drawer-tabs">
        <Segmented
          variant="on-paper sm"
          value={tab}
          onChange={setTab}
          options={[
            { value: "capitulos", label: t("outline.chapters", { n: layout.toc.length }) },
            { value: "sessoes", label: t("outline.sessions", { n: sessions.length }) },
          ]}
        />
      </div>
      <div className="drawer-body">
        {tab === "capitulos" ? (
          layout.toc.length ? (
            layout.toc.map((entry, index) => (
              <button
                key={`${entry.page}-${index}`}
                type="button"
                className="entry"
                aria-current={entry.page <= page && page < (layout.toc[index + 1]?.page ?? Infinity)}
                style={{ paddingLeft: 10 + (entry.level - 1) * 14 }}
                onClick={() => go(entry.page)}
              >
                <span className="num">{entry.page + 1}</span>
                <span className="spacer">{entry.title}</span>
              </button>
            ))
          ) : (
            <p className="small muted" style={{ padding: 12 }}>
              {t("outline.noToc")}
            </p>
          )
        ) : (
          sessions.map((session) => (
            <button
              key={session.id}
              type="button"
              className="entry"
              aria-current={session.start_page <= page && page <= session.end_page}
              onClick={() => go(session.start_page)}
            >
              <span className="num">{session.start_page + 1}</span>
              <span className="spacer">
                {session.number}. {session.title}
              </span>
              {session.status === "done" ? <span className="chip tutor">{t("outline.read")}</span> : null}
            </button>
          ))
        )}
      </div>
      <div className="drawer-foot caption">
        {tn("outline.foot", sessions.length)}
      </div>
    </Drawer>
  );
}

/** Busca no livro: the text layer, and the reader's own marks. */
export function SearchDrawer({
  documentId,
  version,
  marks,
  page,
  initial = "",
  onGo,
  onClose,
}: {
  documentId: string;
  version: string | null;
  marks: Mark[];
  page: number;
  /** What to look for as the drawer opens (a term of the concept map). */
  initial?: string;
  onGo(page: number, query: string): void;
  onClose(): void;
}) {
  const [query, setQuery] = useState(initial);
  const [scope, setScope] = useState<"texto" | "meus">("texto");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);
  useEffect(() => {
    if (scope !== "texto" || query.trim().length < 2) {
      setResult(null);
      return;
    }
    const timer = window.setTimeout(() => {
      setBusy(true);
      void api
        .search(documentId, query.trim(), version)
        .then(setResult)
        .catch(() => setResult(null))
        .finally(() => setBusy(false));
    }, 260);
    return () => window.clearTimeout(timer);
  }, [documentId, query, scope, version]);

  const mine = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return marks;
    return marks.filter(
      (mark) =>
        mark.quote.toLowerCase().includes(needle) || (mark.note ?? "").toLowerCase().includes(needle),
    );
  }, [marks, query]);

  return (
    <Drawer side="left" onClose={onClose}>
      <div className="drawer-head">
        <label className="search" style={{ width: "auto" }}>
          <Search size={16} strokeWidth={2.5} />
          <input
            ref={input}
            value={query}
            placeholder={t("search.placeholder")}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query ? (
            <button type="button" aria-label={t("search.clear")} onClick={() => setQuery("")}>
              <X size={14} strokeWidth={2.75} />
            </button>
          ) : null}
        </label>
        <CloseButton onClick={onClose} />
      </div>
      <div className="drawer-tabs row">
        <Segmented
          variant="on-paper sm"
          value={scope}
          onChange={setScope}
          options={[
            { value: "texto", label: `${version ? t("search.translation") : t("search.text")}${result ? ` · ${result.total}` : ""}` },
            { value: "meus", label: t("search.mine", { n: mine.length }) },
          ]}
        />
        {busy ? <Spinner /> : null}
      </div>
      <div className="drawer-body">
        {scope === "texto" ? (
          result?.hits.length ? (
            result.hits.map((hit) => (
              <button
                key={hit.page}
                type="button"
                className="entry"
                onClick={() => {
                  onGo(hit.page, query.trim());
                  onClose();
                }}
              >
                <span className="num">{hit.page + 1}</span>
                <span className="spacer">
                  {tn("common.matches", hit.rects.length)}
                  <span className="sub">{hit.page === page ? t("search.onThisPage") : t("common.page", { page: hit.page + 1 })}</span>
                </span>
              </button>
            ))
          ) : query.trim().length >= 2 && !busy ? (
            <p className="small muted" style={{ padding: 12 }}>
              {t("search.nothing")}
            </p>
          ) : null
        ) : mine.length ? (
          mine.map((mark) => (
            <button
              key={mark.id}
              type="button"
              className="entry"
              onClick={() => {
                onGo(mark.start.page, "");
                onClose();
              }}
            >
              <span
                className="swatch"
                style={{ background: mark.source === "tutor" ? "var(--tutor-line)" : "var(--action-light)" }}
              />
              <span className="spacer">
                <span className="quote">“{mark.quote}”</span>
                {mark.note ? <span className="own">{mark.note}</span> : null}
                <span className="sub">
                  {t("common.page", { page: mark.start.page + 1 })}
                  {mark.source === "tutor" ? t("search.fromTutor") : ""} · {relativeTime(mark.updated_at)}
                </span>
              </span>
            </button>
          ))
        ) : (
          <p className="small muted" style={{ padding: 12 }}>
            {t("search.noMarks")}
          </p>
        )}
      </div>
      <div className="drawer-foot shortcuts">
        <span>
          <Key>↵</Key> {t("search.goToPage")}
        </span>
        <span>
          <Key>esc</Key> {t("search.close")}
        </span>
      </div>
    </Drawer>
  );
}

/** Grifos e anotações: every mark in the book, by chapter. */
export function MarksDrawer({
  documentId,
  marks,
  dueCards,
  ink,
  onGo,
  onClose,
}: {
  documentId: string;
  marks: Mark[];
  dueCards: number;
  ink(color: string): HighlightInk;
  onGo(page: number): void;
  onClose(): void;
}) {
  const [filter, setFilter] = useState<"tudo" | "highlight" | "note" | "tutor">("tudo");
  const shown = marks.filter((mark) =>
    filter === "tudo"
      ? true
      : filter === "tutor"
        ? mark.source === "tutor"
        : mark.source === "reader" && mark.kind === filter,
  );
  const groups = new Map<string, Mark[]>();
  for (const mark of shown) {
    const title = mark.section[mark.section.length - 1] ?? t("marks.noChapter");
    groups.set(title, [...(groups.get(title) ?? []), mark]);
  }
  const count = (kind: "highlight" | "note") =>
    marks.filter((mark) => mark.source === "reader" && mark.kind === kind).length;

  return (
    <Drawer side="right" onClose={onClose}>
      <div className="drawer-head">
        <h2 className="display-s">{t("marks.title")}</h2>
        <CloseButton onClick={onClose} />
      </div>
      <div className="drawer-tabs">
        <Segmented
          variant="on-paper sm"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "tudo", label: t("marks.all", { n: marks.length }) },
            { value: "highlight", label: t("marks.highlights", { n: count("highlight") }) },
            { value: "note", label: t("marks.notes", { n: count("note") }) },
            { value: "tutor", label: t("marks.tutor", { n: marks.filter((m) => m.source === "tutor").length }) },
          ]}
        />
      </div>
      <div className="drawer-body">
        {shown.length === 0 ? (
          <p className="small muted" style={{ padding: 12 }}>
            {t("marks.empty")}
          </p>
        ) : null}
        {[...groups.entries()].map(([title, list]) => (
          <div key={title}>
            <div className="group kicker">{title}</div>
            {list.map((mark) => (
              <button
                key={mark.id}
                type="button"
                className="entry"
                onClick={() => {
                  onGo(mark.start.page);
                  onClose();
                }}
              >
                <span
                  className="swatch"
                  style={{ background: mark.source === "tutor" ? "var(--tutor-line)" : ink(mark.color).ink }}
                />
                <span className="spacer">
                  <span className="quote">“{mark.quote}”</span>
                  {mark.note ? <span className="own">{mark.note}</span> : null}
                  <span className="sub">
                    {t("common.page", { page: mark.start.page + 1 })}
                    {mark.source === "tutor" ? t("search.fromTutor") : ""} · {relativeTime(mark.updated_at)}
                  </span>
                </span>
              </button>
            ))}
          </div>
        ))}
      </div>
      <div className="drawer-foot">
        <a className="btn btn-outline btn-sm" href={paths.notebook(documentId)}>
          {t("common.notebook")}
        </a>
        <span className="spacer" />
        <a className="btn btn-action btn-sm" href={paths.review(documentId)}>
          {t("marks.review", { n: dueCards })}
        </a>
      </div>
    </Drawer>
  );
}

/** The word tapped twice: its senses, and the one it has in this book. */
export function DictionaryPanel({
  documentId,
  word,
  page,
  offset,
  version,
  onClose,
  onCard,
  onContext,
}: {
  documentId: string;
  word: string;
  page: number;
  offset: number;
  version: string | null;
  onClose(): void;
  onCard(front: string, back: string): void;
  onContext(): void;
}) {
  const [result, setResult] = useState<DictionaryResult | null>(null);
  const [failed, setFailed] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setFailed(null);
    void api
      .dictionary(documentId, word, { page, offset, version })
      .then((value) => !cancelled && setResult(value))
      .catch((error: Error) => !cancelled && setFailed(error.message));
    return () => {
      cancelled = true;
    };
  }, [documentId, word, page, offset, version]);

  const entry = result?.entry;
  return (
    <Drawer side="right" onClose={onClose}>
      <div className="drawer-head">
        <span className="kicker">{t("dict.title")}</span>
        <CloseButton onClick={onClose} />
      </div>
      <div className="drawer-body padded">
        <div>
          <div className="dict-word">{entry?.word || word}</div>
          {entry?.pronunciation || entry?.grammar ? (
            <div className="caption">{[entry.pronunciation, entry.grammar].filter(Boolean).join(" · ")}</div>
          ) : null}
        </div>
        {!result && !failed ? (
          <span className="row small muted">
            <Spinner /> {t("dict.looking")}
          </span>
        ) : null}
        {entry?.senses.map((sense, index) => (
          <div key={index} className="sense">
            <span className="n">{index + 1}</span>
            <span>{sense.gloss}</span>
          </div>
        ))}
        {entry?.in_book ? (
          <div className="in-book">
            <strong>{t("dict.inBook")}</strong> · {entry.in_book}
          </div>
        ) : null}
        {result?.error ? (
          <div className="card-sand stack-2" style={{ padding: "14px 16px" }}>
            <span className="strong small">{t("dict.needsAi")}</span>
            <span className="small muted">
              {t("dict.needsAiBody", { n: result.uses })}
            </span>
            <a className="btn btn-outline btn-sm" style={{ alignSelf: "flex-start" }} href={paths.settings("ia")}>
              {t("dict.toSettings")}
            </a>
          </div>
        ) : null}
        {failed ? <p className="small">{failed}</p> : null}
        {entry?.related.length ? (
          <div className="row tight wrap">
            {entry.related.map((related) => (
              <span key={related} className="chip">
                {related}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      <div className="drawer-foot">
        <button type="button" className="btn btn-ink btn-sm" onClick={onContext}>
          <Sparkles size={14} />
          {t("dict.inContext")}
        </button>
        {entry ? (
          <button
            type="button"
            className="btn btn-outline btn-sm"
            onClick={() =>
              onCard(
                t("dict.cardQuestion", { word: entry.word || word }),
                entry.in_book || entry.senses.map((sense) => sense.gloss).join(" / "),
              )
            }
          >
            <Plus size={14} />
            {t("dict.card")}
          </button>
        ) : null}
        <span className="spacer caption">{result ? tn("dict.uses", result.uses) : null}</span>
      </div>
    </Drawer>
  );
}
