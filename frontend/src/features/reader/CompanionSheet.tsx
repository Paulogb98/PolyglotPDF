import { ArrowUp, Eye, History, Plus, Sparkles, Square, X } from "lucide-react";
import { useEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from "react";
import type { ThreadSummary } from "../../api/types";
import { submitsOnEnter, useDismiss } from "../../components/ui";
import { relativeTime } from "../../lib/format";
import { linkPageRefs, pageRefTarget, renderMarkdown } from "../../lib/markdown";
import { rich } from "../../i18n/rich";
import type { CompanionState } from "./useCompanion";
import { t, tn, type Key } from "../../i18n";

const QUICK: { action: string; label: Key }[] = [
  { action: "simplify", label: "sheet.quick.simplify" },
  { action: "context", label: "sheet.quick.context" },
  { action: "concepts", label: "sheet.quick.concepts" },
  { action: "vocabulary", label: "sheet.quick.vocabulary" },
  { action: "summarize", label: "sheet.quick.summarize" },
];

/** The ink sheet (1c): a long conversation rises over the book and goes back down. The
 *  passage stays on the left, so the reader never loses what the talk is about. */
export function CompanionSheet({
  companion,
  engine,
  model,
  history,
  pageCount,
  onNew,
  onGoToPage,
  onClose,
}: {
  companion: CompanionState;
  engine: string;
  model: string | null;
  history: ThreadSummary[];
  pageCount: number;
  onNew(): void;
  /** A page the answer points at ("p. 81"), clicked. */
  onGoToPage(page: number): void;
  onClose(): void;
}) {
  const [draft, setDraft] = useState("");
  const [showHistory, setShowHistory] = useState(false);
  const thread = useRef<HTMLDivElement>(null);
  const sheet = useRef<HTMLElement>(null);
  const [tall, setTall] = useState(false);
  // While the grip is dragged: where it started, the height then, and the height now.
  const drag = useRef<{ y: number; time: number; height: number } | null>(null);
  const [height, setHeight] = useState<number | null>(null);
  useDismiss(true, onClose);

  const onGripDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !sheet.current) return;
    event.currentTarget.setPointerCapture(event.pointerId);
    const current = sheet.current.getBoundingClientRect().height;
    drag.current = { y: event.clientY, time: performance.now(), height: current };
    setHeight(current);
  };
  const onGripMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start) return;
    setHeight(Math.min(tallHeight(), Math.max(80, start.height + start.y - event.clientY)));
  };
  const onGripUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    drag.current = null;
    setHeight(null);
    if (!start) return;
    const moved = start.y - event.clientY; // up is positive
    if (Math.abs(moved) < 4) {
      setTall((on) => !on); // a click on the grip switches between the two heights
      return;
    }
    const speed = moved / Math.max(1, performance.now() - start.time); // px per ms
    const reached = start.height + moved;
    const normal = normalHeight();
    if (speed < -0.7 || reached < normal * 0.55) onClose();
    else setTall(speed > 0.7 || reached > (normal + tallHeight()) / 2);
  };

  useEffect(() => {
    thread.current?.scrollTo({ top: thread.current.scrollHeight });
  }, [companion.turns]);

  const send = () => {
    const text = draft.trim();
    if (!text || companion.streaming) return;
    companion.follow("ask", text);
    setDraft("");
  };

  const context = companion.thread?.context;
  const quote = context?.selection || companion.thread?.quote || "";

  return (
    <>
      <div className="sheet-scrim" onMouseDown={onClose} />
      <section
        ref={sheet}
        className={`sheet ${tall ? "tall" : ""} ${height !== null ? "dragging" : ""}`}
        style={height !== null ? { height } : undefined}
        role="dialog"
        aria-label={t("sheet.label")}
      >
        <div
          className="grip"
          title={t("sheet.grip")}
          onPointerDown={onGripDown}
          onPointerMove={onGripMove}
          onPointerUp={onGripUp}
          onPointerCancel={onGripUp}
        >
          <i />
        </div>
        <div className="sheet-head">
          <span className="model-chip">
            <Sparkles size={13} />
            {engine}
            {model ? <span className="model">{model}</span> : null}
          </span>
          <span className="spacer" />
          <button
            type="button"
            className="icon-btn"
            aria-label={t("sheet.history")}
            title={t("sheet.history")}
            onClick={() => setShowHistory((on) => !on)}
          >
            <History size={17} />
          </button>
          <button type="button" className="icon-btn" aria-label={t("sheet.new")} title={t("sheet.new")} onClick={onNew}>
            <Plus size={18} />
          </button>
          <button type="button" className="icon-btn" aria-label={t("common.close")} onClick={onClose}>
            <X size={18} />
          </button>
          {showHistory ? (
            <div className="history">
              {history.length ? (
                history.map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => {
                      setShowHistory(false);
                      void companion.reopen(item.id);
                    }}
                  >
                    “{item.quote.slice(0, 80)}
                    {item.quote.length > 80 ? "…" : ""}”
                    <span>
                      {t("common.page", { page: item.page_label })} · {relativeTime(item.updated_at)}
                    </span>
                  </button>
                ))
              ) : (
                <button type="button" disabled>
                  {t("sheet.noHistory")}
                </button>
              )}
            </div>
          ) : null}
        </div>

        <div className="sheet-body">
          <aside className="sheet-side">
            {quote ? (
              <div className="sheet-quote">
                <p>{quote.length > 360 ? `${quote.slice(0, 360)}…` : quote}</p>
                <div className="row tight wrap">
                  {context ? <span className="chip">{t("common.page", { page: context.page_label })}</span> : null}
                  {context?.section.length ? (
                    <span className="chip">{context.section[context.section.length - 1]}</span>
                  ) : null}
                </div>
              </div>
            ) : null}
            {context ? (
              <span className="sent">
                <Eye size={13} />
                {context.whole_page ? t("sheet.sentPage") : t("sheet.sentParagraph")}
              </span>
            ) : null}
            <div className="row tight wrap">
              {QUICK.map((item) => (
                <button
                  key={item.action}
                  type="button"
                  className="btn btn-xs btn-on-night"
                  disabled={companion.streaming || !companion.thread}
                  onClick={() => companion.follow(item.action)}
                >
                  {t(item.label)}
                </button>
              ))}
            </div>
          </aside>

          <div
            className="sheet-thread"
            ref={thread}
            onClick={(event) => {
              const target = pageRefTarget(event);
              if (target !== null) onGoToPage(target);
            }}
          >
            {companion.turns.map((turn, index) =>
              turn.role === "user" ? (
                <div key={index} className="bubble-you">
                  {turn.text}
                </div>
              ) : (
                <div key={index} className="answer">
                  {turn.text ? (
                    <div
                      className="prose on-night"
                      dangerouslySetInnerHTML={{
                        __html:
                          linkPageRefs(renderMarkdown(turn.text), pageCount) +
                          (turn.live ? '<span class="caret"></span>' : ""),
                      }}
                    />
                  ) : (
                    <span className="thinking" aria-label={t("common.writing")}>
                      <i />
                      <i />
                      <i />
                    </span>
                  )}
                </div>
              ),
            )}
            {companion.error ? (
              <p className="small" style={{ color: "var(--action-light)" }}>
                {companion.error}
              </p>
            ) : null}
          </div>
        </div>

        <div className="sheet-foot">
          <div className="composer">
            <textarea
              rows={1}
              value={draft}
              placeholder={t("sheet.placeholder")}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={submitsOnEnter(send)}
            />
          </div>
          {companion.streaming ? (
            <button type="button" className="send" aria-label={t("sheet.stop")} onClick={companion.stop}>
              <Square size={14} fill="currentColor" />
            </button>
          ) : (
            <button type="button" className="send" aria-label={t("sheet.send")} onClick={send}>
              <ArrowUp size={19} strokeWidth={2.5} />
            </button>
          )}
        </div>
      </section>
    </>
  );
}

/** The two heights of the sheet, as the stylesheet sets them. */
const normalHeight = () => Math.min(window.innerHeight * 0.58, 540);
const tallHeight = () => window.innerHeight - 72;

/** While a conversation is a note, the sheet waits folded at the bottom of the window:
 *  dragging it up (or a click, or Ctrl+↑) opens it. */
export function SheetPeek({
  count,
  scope,
  onOpen,
}: {
  count: number;
  scope: "session" | "book";
  onOpen(): void;
}) {
  const start = useRef<number | null>(null);
  const [pull, setPull] = useState(0);
  const release = (event: ReactPointerEvent<HTMLDivElement>) => {
    const from = start.current;
    start.current = null;
    setPull(0);
    if (from === null) return;
    const moved = from - event.clientY;
    if (Math.abs(moved) < 4 || moved > 40) onOpen();
  };
  return (
    <div
      className="sheet-peek"
      role="button"
      tabIndex={0}
      aria-label={t("sheet.peek.label")}
      style={pull ? { height: 74 + pull } : undefined}
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        start.current = event.clientY;
      }}
      onPointerMove={(event) => {
        if (start.current === null) return;
        const up = Math.max(0, start.current - event.clientY);
        if (up > 120) {
          start.current = null;
          setPull(0);
          onOpen();
        } else setPull(up);
      }}
      onPointerUp={release}
      onPointerCancel={release}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          onOpen();
        }
      }}
    >
      <div className="grip">
        <i />
      </div>
      <div className="peek-line">
        <Sparkles size={14} />
        <span>
          {tn(scope === "session" ? "sheet.peek.session" : "sheet.peek.book", count)} ·{" "}
          {rich("sheet.peek.hint", { keys: <strong>Ctrl ↑</strong> })}
        </span>
      </div>
    </div>
  );
}
