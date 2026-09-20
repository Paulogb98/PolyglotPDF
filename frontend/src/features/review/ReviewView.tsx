import { BookMarked, ChevronLeft, Quote } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type { Card, Grade, ReviewQueue } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { Key, Progress, Spinner } from "../../components/ui";
import { navigate, paths } from "../../lib/router";
import { t, tn, type Key as MessageKey } from "../../i18n";

const GRADES: { grade: Grade; name: MessageKey }[] = [
  { grade: "again", name: "review.grade.again" },
  { grade: "hard", name: "review.grade.hard" },
  { grade: "good", name: "review.grade.good" },
  { grade: "easy", name: "review.grade.easy" },
];

/** Review: cards born of your marks and of the tutor's dense passages — nothing without a source. */
export function ReviewView({ id }: { id: string }) {
  const [queue, setQueue] = useState<ReviewQueue | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [done, setDone] = useState({ total: 0, right: 0, hard: 0 });
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      setQueue(await api.reviewQueue(id));
      setIndex(0);
      setFlipped(false);
    } catch (error) {
      toast({ kind: "error", title: t("review.openFailed"), body: errorMessage(error) });
      navigate(paths.library());
    }
  }, [id, toast]);

  useEffect(() => void load(), [load]);

  const card: Card | undefined = queue?.cards[index];

  const grade = useCallback(
    async (value: Grade) => {
      if (!card) return;
      setDone((current) => ({
        total: current.total + 1,
        right: current.right + (value === "good" || value === "easy" ? 1 : 0),
        hard: current.hard + (value === "again" || value === "hard" ? 1 : 0),
      }));
      setFlipped(false);
      setIndex((current) => current + 1);
      await api.reviewCard(card.id, value).catch(() => undefined);
    },
    [card],
  );

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === " ") {
        event.preventDefault();
        setFlipped((on) => !on);
      } else if (flipped && ["1", "2", "3", "4"].includes(event.key)) {
        const option = GRADES[Number(event.key) - 1];
        if (option) void grade(option.grade);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flipped, grade]);

  if (!queue) {
    return (
      <div className="screen">
        <div className="ground" />
        <div className="row muted" style={{ padding: 52 }}>
          <Spinner /> {t("review.building")}
        </div>
      </div>
    );
  }

  const total = queue.cards.length;

  return (
    <div className="screen">
      <div className="ground" />
      <header className="page-head">
        <a className="icon-btn glass" href={paths.notebook(id)} aria-label={t("review.backToNotebook")}>
          <ChevronLeft size={17} strokeWidth={2.5} />
        </a>
        <div className="title stack-2" style={{ gap: 2 }}>
          <span className="kicker">{t("review.kicker")}</span>
          <h1 className="display-s">{card ? t("review.cardOf", { n: index + 1, total }) : t("review.roundDone")}</h1>
        </div>
        <div style={{ width: 180 }}>
          <Progress value={total ? index / total : 1} />
        </div>
        <a className="btn btn-outline" href={paths.notebook(id)}>
          {t("review.stop")}
        </a>
      </header>

      <div className="split">
        <div className="main stack-3">
          {!card ? (
            <section className="flashcard card">
              <span className="kicker">{t("review.endKicker")}</span>
              <div className="front">{total === 0 ? t("review.nothing") : tn("review.reviewed", done.total)}</div>
              <p className="muted">
                {total === 0
                  ? t("review.nothingBody")
                  : t("review.summary", { right: done.right, hard: done.hard })}
              </p>
              <div className="row" style={{ marginTop: "auto" }}>
                <a className="btn btn-action" href={paths.reader(id)}>
                  {t("review.backToBook")}
                </a>
                <a className="btn btn-outline" href={paths.notebook(id)}>
                  {t("common.notebook")}
                </a>
              </div>
            </section>
          ) : (
            <>
              <section className="flashcard card" key={`${card.id}-${flipped}`}>
                <div className="row kicker">
                  {card.source === "tutor" ? <BookMarked size={12} /> : <Quote size={12} />}
                  <span>
                    {card.source === "tutor" ? t("review.fromTutor") : t("review.yourHighlight")} ·{" "}
                    {t("common.page", { page: card.page + 1 })}
                  </span>
                  <span className="spacer" />
                  <span>
                    {tn("review.seen", card.reps)}
                    {card.lapses ? t("review.lapses", { n: card.lapses }) : ""}
                  </span>
                </div>
                <div className="front">{card.front}</div>
                {flipped ? (
                  <>
                    <div className="back selectable">{card.back}</div>
                    {card.quote ? (
                      <p className="quote">
                        “{card.quote}” — {t("common.page", { page: card.page + 1 })}
                      </p>
                    ) : null}
                  </>
                ) : (
                  <>
                    <p className="muted">{t("review.think")}</p>
                    <button
                      type="button"
                      className="btn btn-action"
                      style={{ alignSelf: "flex-start", marginTop: "auto" }}
                      onClick={() => setFlipped(true)}
                    >
                      {t("review.flip")}
                    </button>
                  </>
                )}
              </section>
              {flipped ? (
                <div className="grades">
                  {GRADES.map((option, position) => {
                    const when = card.schedule?.find((item) => item.grade === option.grade);
                    return (
                      <button
                        key={option.grade}
                        type="button"
                        data-grade={option.grade}
                        onClick={() => void grade(option.grade)}
                      >
                        <span className="name">{t(option.name)}</span>
                        <span className="when">{when?.label ?? t("review.keyN", { n: position + 1 })}</span>
                      </button>
                    );
                  })}
                </div>
              ) : (
                <div className="shortcuts">
                  <span>
                    <Key>{t("review.space")}</Key> {t("review.flipShort")}
                  </span>
                  <span>
                    <Key>1–4</Key> {t("review.rate")}
                  </span>
                  <span className="spacer" />
                  <a className="btn-link" href={paths.reader(id, { page: card.page })}>
                    {t("review.seeInBook", { page: card.page + 1 })}
                  </a>
                </div>
              )}
            </>
          )}
        </div>

        <aside className="side">
          <section className="panel card">
            <span className="kicker">{t("review.thisRound")}</span>
            <div className="stack-2 small">
              <span>{t("review.right", { n: done.right })}</span>
              <span>{t("review.hardCount", { n: done.hard })}</span>
              <span>{t("review.left", { n: Math.max(0, total - index) })}</span>
            </div>
          </section>
          <p className="small muted" style={{ padding: "0 4px" }}>
            {t("review.source")}
          </p>
        </aside>
      </div>
    </div>
  );
}
