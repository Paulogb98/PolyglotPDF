import { ArrowRight, BookMarked, Check, ChevronLeft, ChevronRight, PenLine, Sparkles } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import type { ConceptMap, NotebookCounts, SessionAnswer, SessionConcept, TutorSession } from "../../api/types";
import { errorMessage } from "../../components/Toasts";
import { Dialog, Key, Progress, Spinner } from "../../components/ui";
import { renderMarkdown } from "../../lib/markdown";
import { paths } from "../../lib/router";
import { rich } from "../../i18n/rich";
import { t, tn } from "../../i18n";

/** Before the session: what it is about and what the tutor will do. */
export function SessionOpening({
  session,
  total,
  loading,
  error,
  onStart,
  onOnlyRead,
  onRetry,
}: {
  session: TutorSession;
  total: number;
  loading: boolean;
  error: string | null;
  onStart(): void;
  onOnlyRead(): void;
  onRetry(): void;
}) {
  const plan = session.plan;
  return (
    <Dialog onClose={onStart} label={session.title}>
      <div className="stack-2" style={{ paddingRight: 40 }}>
        <span className="kicker tutor">
          {t("opening.kicker", { n: session.number, total, pages: tn("common.pages", session.pages) })}
        </span>
        <h2 className="display-m">{session.title}</h2>
      </div>
      {loading ? (
        <span className="row small muted">
          <Spinner /> {t("session.planning")}
        </span>
      ) : null}
      {plan?.intro ? (
        <div className="lead prose" style={{ fontSize: 15 }} dangerouslySetInnerHTML={{ __html: renderMarkdown(plan.intro) }} />
      ) : null}
      {plan?.expect.length ? (
        <div className="card-tutor stack-2" style={{ padding: "14px 16px" }}>
          {plan.expect.map((line) => (
            <div key={line} className="row top small" style={{ gap: 9 }}>
              <Check size={14} strokeWidth={3} style={{ flex: "none", marginTop: 3, color: "var(--tutor)" }} />
              <span className="prose" style={{ fontSize: "inherit" }} dangerouslySetInnerHTML={{ __html: renderMarkdown(line) }} />
            </div>
          ))}
        </div>
      ) : null}
      {error ? (
        <div className="card-sand stack-2" style={{ padding: "14px 16px" }}>
          <span className="strong small">{t("opening.failed")}</span>
          <span className="small muted">
            {t("opening.failedBody", { error })}
          </span>
          <div className="row tight">
            <button type="button" className="btn btn-sm btn-outline" onClick={onRetry}>
              {t("opening.retry")}
            </button>
            <a className="btn btn-sm btn-quiet" href={paths.settings("ia")}>
              {t("opening.checkKey")}
            </a>
          </div>
        </div>
      ) : null}
      <div className="dialog-foot">
        <span className="spacer" />
        <button type="button" className="btn btn-quiet" onClick={onOnlyRead}>
          {t("opening.onlyRead")}
        </button>
        <button type="button" className="btn btn-tutor btn-lg" onClick={onStart} disabled={loading}>
          <BookMarked size={16} />
          {t("opening.start")}
        </button>
      </div>
    </Dialog>
  );
}

/** The end of the session (1e): questions answered in your own words, and the concept map. */
export function Debrief({
  documentId,
  version,
  session,
  next,
  readingSeconds,
  readingDays,
  onBack,
  onGo,
  onSearch,
  onPrepare,
  onNext,
}: {
  documentId: string;
  version: string | null;
  session: TutorSession;
  next: TutorSession | null;
  readingSeconds: number;
  readingDays: number;
  onBack(): void;
  onGo(page: number): void;
  /** Look for a term in the book. */
  onSearch(term: string): void;
  /** Plan a later session ahead of time; resolves to whether it worked. */
  onPrepare(number: number): Promise<boolean>;
  onNext(): void;
}) {
  const questions = session.plan?.questions ?? [];
  const [answers, setAnswers] = useState<Record<string, SessionAnswer>>(session.plan?.answers ?? {});
  const firstOpen = questions.findIndex((_, index) => !answers[String(index)]);
  const [open, setOpen] = useState(firstOpen < 0 ? 0 : firstOpen);
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [map, setMap] = useState<ConceptMap | null>(null);
  const [loaded, setLoaded] = useState(0);

  useEffect(() => {
    let cancelled = false;
    void api
      .sessionConcepts(documentId, session.number, version)
      .then((result) => !cancelled && setMap(result))
      .catch(() => !cancelled && setMap(EMPTY_MAP));
    return () => {
      cancelled = true;
    };
  }, [documentId, session.number, version, loaded]);

  // The next session gets its plan now, while the reader answers: its concepts join the
  // map as the ones still ahead, and opening it later costs nothing.
  const nextNumber = next && !next.has_plan ? next.number : null;
  const prepare = useRef(onPrepare);
  prepare.current = onPrepare;
  useEffect(() => {
    if (nextNumber === null) return;
    let cancelled = false;
    void prepare.current(nextNumber).then((planned) => {
      if (planned && !cancelled) setLoaded((count) => count + 1);
    });
    return () => {
      cancelled = true;
    };
  }, [nextNumber]);

  const submit = async () => {
    setSending(true);
    setError(null);
    try {
      const result = await api.answerQuestion(documentId, session.number, open, draft, version);
      setAnswers((current) => ({ ...current, [String(open)]: result }));
      setDraft("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSending(false);
    }
  };

  const answered = answers[String(open)];
  const nextOpen = questions.findIndex((_, index) => index > open && !answers[String(index)]);
  const time = duration(readingSeconds);

  return (
    <div className="debrief">
      <section className="debrief-main">
        <div className="row">
          <button type="button" className="icon-btn glass" aria-label={t("debrief.back")} onClick={onBack}>
            <ChevronLeft size={17} strokeWidth={2.5} />
          </button>
          <span className="kicker">
            {t("debrief.kicker", { n: session.number, from: session.start_page + 1, to: session.end_page + 1 })}
          </span>
        </div>
        <div className="stack-3">
          <h1 className="display-l" style={{ maxWidth: "16ch", lineHeight: 1.08 }}>
            {questions.length ? t("debrief.title") : t("debrief.titleNone")}
          </h1>
          <p className="lead">
            {questions.length
              ? t("debrief.lead")
              : t("debrief.leadNone")}
          </p>
        </div>

        <div className="questions">
          {questions.map((question, index) => {
            const mine = answers[String(index)];
            const isOpen = index === open;
            return (
              <div
                key={question.text}
                className={`question ${isOpen ? "open" : ""} ${mine ? "answered" : ""}`}
              >
                <button type="button" className="q" onClick={() => setOpen(index)}>
                  <span className="n">{mine ? <Check size={12} strokeWidth={3} /> : index + 1}</span>
                  <span className="spacer">{question.text}</span>
                  {!isOpen ? <span className="state">{mine ? t("debrief.answered") : t("debrief.next")}</span> : null}
                </button>
                {isOpen && mine ? (
                  <>
                    <div className="yours">{mine.answer || t("debrief.noAnswer")}</div>
                    {mine.comment ? (
                      <div
                        className="comment prose"
                        dangerouslySetInnerHTML={{ __html: renderMarkdown(mine.comment) }}
                      />
                    ) : null}
                  </>
                ) : null}
                {isOpen && !mine ? (
                  <>
                    <textarea
                      className="input"
                      placeholder={t("debrief.placeholder")}
                      value={draft}
                      autoFocus
                      onChange={(event) => setDraft(event.target.value)}
                    />
                    {question.hint ? <span className="caption">{t("debrief.hint", { hint: question.hint })}</span> : null}
                    {error ? <span className="small" style={{ color: "var(--action-ink)" }}>{error}</span> : null}
                  </>
                ) : null}
              </div>
            );
          })}
        </div>

        <div className="row" style={{ marginTop: "auto" }}>
          {questions.length && !answered ? (
            <button
              type="button"
              className="btn btn-action btn-lg"
              disabled={sending || !draft.trim()}
              onClick={() => void submit()}
            >
              {sending ? <Spinner /> : <PenLine size={16} />}
              {t("debrief.answer", { n: open + 1 })}
            </button>
          ) : nextOpen >= 0 ? (
            <button type="button" className="btn btn-action btn-lg" onClick={() => setOpen(nextOpen)}>
              {t("debrief.goTo", { n: nextOpen + 1 })}
              <ChevronRight size={17} strokeWidth={2.5} />
            </button>
          ) : null}
          {next ? (
            <button type="button" className="btn btn-outline btn-lg" onClick={onNext}>
              {t("debrief.nextSession", { n: next.number })}
            </button>
          ) : (
            <a className="btn btn-outline btn-lg" href={paths.library()}>
              {t("debrief.toLibrary")}
            </a>
          )}
        </div>
      </section>

      <aside className="debrief-side">
        <div className="stack-2">
          <span className="kicker row tight">
            <Sparkles size={12} /> {t("debrief.map")}
          </span>
          <p className="small muted">{t("debrief.mapLead")}</p>
        </div>
        {map === null ? (
          <Spinner />
        ) : map.concepts.length ? (
          <ConceptList concepts={map.concepts} onGo={onGo} onSearch={onSearch} />
        ) : (
          <p className="small muted">{t("debrief.noConcepts")}</p>
        )}
        <div className="card-sand small" style={{ marginTop: "auto", padding: "14px 16px", lineHeight: 1.55 }}>
          {rich("debrief.readTime", { time: <strong>{time}</strong> })}
          {readingDays > 1
            ? rich("debrief.readDays", { days: <strong>{tn("debrief.days", readingDays)}</strong> })
            : null}
          .{map ? <Pace pace={map.pace} /> : null}
        </div>
      </aside>
    </div>
  );
}

const EMPTY_MAP: ConceptMap = {
  concepts: [],
  pace: { scope: "done", title: null, sessions_left: 0, minutes_left: null },
};

/** The concept map (1e): what this session brought, what came back, what is ahead. */
function ConceptList({
  concepts,
  onGo,
  onSearch,
}: {
  concepts: SessionConcept[];
  onGo(page: number): void;
  onSearch(term: string): void;
}) {
  const [showEarlier, setShowEarlier] = useState(false);
  const earlier = concepts.filter((concept) => concept.state === "earlier");
  const item = (concept: SessionConcept) => {
    const term = concept.term && concept.term.toLowerCase() !== concept.name.toLowerCase() ? concept.term : "";
    return (
      <div key={`${concept.state}-${concept.name}`} className={`concept ${concept.state}`}>
        <button
          type="button"
          className="name"
          title={t("debrief.whereTitle")}
          onClick={() => onSearch(concept.term || concept.name)}
        >
          {concept.name.replace(/^./, (c) => c.toUpperCase())}
        </button>
        {concept.state === "ahead" ? (
          <div className="sub">{t("debrief.aheadIn", { n: concept.session })}</div>
        ) : (
          <>
            <div className="sub">
              {term ? <em className="term">{term}</em> : null}
              {term && concept.uses ? " · " : null}
              {concept.uses ? tn("common.matches", concept.uses) : null}
              {concept.first_page !== null ? (
                <>
                  {" · "}
                  <button type="button" onClick={() => onGo(concept.first_page ?? 0)}>
                    {t("common.page", { page: concept.first_page + 1 })} →
                  </button>
                </>
              ) : null}
              {concept.state !== "new"
                ? `${term || concept.uses ? " · " : ""}${t("debrief.since", { n: concept.session })}`
                : null}
            </div>
            {concept.definition ? <p className="definition">{concept.definition}</p> : null}
          </>
        )}
      </div>
    );
  };
  return (
    <div className="concepts">
      {concepts.filter((concept) => concept.state === "new" || concept.state === "again").map(item)}
      {earlier.length ? (
        <>
          {showEarlier ? earlier.map(item) : null}
          <button type="button" className="concept-more" onClick={() => setShowEarlier((on) => !on)}>
            {showEarlier ? t("debrief.earlierHide") : tn("debrief.earlier", earlier.length)}
          </button>
        </>
      ) : null}
      {concepts.filter((concept) => concept.state === "ahead").map(item)}
    </div>
  );
}

/** What is left of the part of the book the session is in (or of the whole book). */
function Pace({ pace }: { pace: ConceptMap["pace"] }) {
  if (pace.scope === "done") return <>{t("debrief.pace.done")}.</>;
  const sessions = <strong>{tn("debrief.sessions", pace.sessions_left)}</strong>;
  return (
    <>
      {pace.scope === "section"
        ? rich("debrief.pace.section", { title: <strong>“{pace.title}”</strong>, sessions })
        : rich("debrief.pace.book", { sessions })}
      {pace.minutes_left
        ? rich("debrief.pace.time", { time: <strong>{duration(pace.minutes_left * 60)}</strong> })
        : null}
      .
    </>
  );
}

/** "4h 20min", "35 min". */
function duration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  if (!hours) return `${minutes} min`;
  return minutes ? `${hours}h ${String(minutes).padStart(2, "0")}min` : `${hours}h`;
}

/** The end of a chapter: what you did in it, and what is waiting to be reviewed. */
export function ChapterEnd({
  title,
  page,
  pages,
  counts,
  minutes,
  documentId,
  onClose,
}: {
  title: string;
  page: number;
  pages: number;
  counts: NotebookCounts;
  minutes: number;
  documentId: string;
  onClose(): void;
}) {
  return (
    <Dialog onClose={onClose} label={title}>
      <div className="stack-2" style={{ paddingRight: 40 }}>
        <span className="kicker action">
          {t("chapter.kicker", { page: page + 1, pages })}
        </span>
        <h2 className="display-m">{title}</h2>
        <p className="muted">{t("chapter.lead")}</p>
      </div>
      <div className="stats" style={{ gridTemplateColumns: "repeat(3, 1fr)" }}>
        <div>
          <div className="n">{t("chapter.minutes", { n: minutes })}</div>
          <div className="l">{t("chapter.reading")}</div>
        </div>
        <div>
          <div className="n">{counts.highlights + counts.notes}</div>
          <div className="l">{t("chapter.marks")}</div>
        </div>
        <div>
          <div className="n">{counts.due}</div>
          <div className="l">{counts.due === 1 ? t("chapter.due.one") : t("chapter.due.other")}</div>
        </div>
      </div>
      <div className="dialog-foot">
        <a className="btn btn-quiet" href={paths.library()}>
          {t("chapter.library")}
        </a>
        <span className="spacer" />
        <button type="button" className="btn btn-outline" onClick={onClose}>
          {t("chapter.keepReading")}
        </button>
        <a className="btn btn-action" href={paths.review(documentId)}>
          {t("chapter.review", { n: counts.due })}
          <ArrowRight size={15} />
        </a>
      </div>
    </Dialog>
  );
}

/** While a book opens: the paper shows up before the text. */
export function OpeningBook({ title, progress }: { title: string; progress: number }) {
  const steps = [t("openingBook.step1"), t("openingBook.step2"), t("openingBook.step3")];
  const stage = progress < 0.34 ? 0 : progress < 0.75 ? 1 : 2;
  return (
    <div className="opening">
      <div className="skeleton">
        {[0, 1].map((leaf) => (
          <div key={leaf} className={`leaf ${leaf ? "right" : "left"}`}>
            {[92, 100, 96, 88, 100, 74, 100, 62].map((width, index) => (
              <div key={index} className="line" style={{ width: `${width}%` }} />
            ))}
          </div>
        ))}
      </div>
      <div className="opening-card card">
        <div className="row">
          <Spinner />
          <div className="spacer">
            <div className="strong">{t("openingBook.title")}</div>
            <div className="caption">{title}</div>
          </div>
          <span style={{ font: "650 14px var(--font-mono)" }}>{Math.round(progress * 100)}%</span>
        </div>
        <Progress value={progress} tone="live" />
        <div className="steps">
          {steps.map((label, index) => (
            <div key={label} className="step" data-state={index < stage ? "done" : index === stage ? "now" : "todo"}>
              <span className="dot">
                {index < stage ? <Check size={14} strokeWidth={3} /> : index === stage ? <Spinner /> : null}
              </span>
              {label}
            </div>
          ))}
        </div>
        <span className="caption">
          <Key>esc</Key> {t("openingBook.esc")}
        </span>
      </div>
    </div>
  );
}
