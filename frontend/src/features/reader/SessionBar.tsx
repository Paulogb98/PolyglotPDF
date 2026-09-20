import { ChevronDown, MessageCircleQuestion } from "lucide-react";
import type { TutorSession } from "../../api/types";
import { renderMarkdown } from "../../lib/markdown";
import { t } from "../../i18n";

/** The tutor's session along the foot of the reader (1d): where you are, what to expect,
 *  and the way out — three questions at the end. */
export function SessionBar({
  session,
  total,
  page,
  planning,
  minutesLeft,
  onCheck,
  onHide,
}: {
  session: TutorSession;
  total: number;
  page: number;
  planning: boolean;
  minutesLeft: number;
  onCheck(): void;
  onHide(): void;
}) {
  const read = Math.min(session.pages, Math.max(0, page - session.start_page + 1));
  const segments = Math.min(8, Math.max(3, Math.ceil(session.pages / 2)));
  const now = Math.min(segments - 1, Math.floor((read / session.pages) * segments));
  const plan = session.plan;
  const expect = plan?.intro
    ? [plan.intro, plan.expect[0]].filter(Boolean)
    : plan?.expect.slice(0, 2) ?? [];

  return (
    <section className="session-bar" aria-label={t("session.label")}>
      <span className="stripe" />
      <div className="inner">
        <div className="who">
          <span className="kicker tutor">
            {t("session.ofTotal", { n: session.number, total })}
          </span>
          <div className="display-s" style={{ fontSize: 23 }}>
            {session.title}
          </div>
          <div className="segments" aria-label={t("session.pagesRead", { read, pages: session.pages })}>
            {Array.from({ length: segments }, (_, index) => (
              <i key={index} className={index < now ? "done" : index === now ? "now" : ""} />
            ))}
            <span className="caption" style={{ marginLeft: 7 }}>
              {t("session.pageRange", { from: session.start_page + 1, to: session.end_page + 1 })}
            </span>
          </div>
        </div>
        <span className="vdivider" />
        <div className="what">
          <span className="kicker">{t("session.expect")}</span>
          {planning && !plan ? (
            <p className="muted">{t("session.planning")}</p>
          ) : (
            <div className="row top" style={{ gap: 18 }}>
              {expect.map((line) => (
                <div
                  key={line}
                  className="spacer"
                  style={{ fontSize: 13.5, lineHeight: 1.55, color: "var(--ink-2)" }}
                  dangerouslySetInnerHTML={{ __html: renderMarkdown(line) }}
                />
              ))}
            </div>
          )}
          {plan?.concepts.length ? (
            <div className="row tight wrap" style={{ marginTop: "auto" }}>
              {plan.concepts.slice(0, 5).map((concept) => (
                <span key={concept.name} className="chip md" title={concept.definition || undefined}>
                  {concept.name.replace(/^./, (c) => c.toUpperCase())}
                </span>
              ))}
            </div>
          ) : null}
        </div>
        <span className="vdivider" />
        <div className="end">
          <span className="kicker">{t("session.atEnd")}</span>
          <p>
            {t("session.questionsNote", { n: plan?.questions.length ?? 3 })}
          </p>
          <button type="button" className="btn btn-tutor" style={{ marginTop: "auto" }} onClick={onCheck}>
            <MessageCircleQuestion size={16} />
            {t("session.check")}
          </button>
          <span className="caption" style={{ textAlign: "center" }}>
            {minutesLeft > 0 ? t("session.minutesLeft", { n: minutesLeft }) : t("session.reachedEnd")}
          </span>
        </div>
      </div>
      <button
        type="button"
        className="icon-btn sm"
        style={{ position: "absolute", right: 10, top: 10 }}
        aria-label={t("session.hide")}
        onClick={onHide}
      >
        <ChevronDown size={16} />
      </button>
    </section>
  );
}
