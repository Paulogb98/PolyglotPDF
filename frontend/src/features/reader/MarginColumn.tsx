import { Maximize2, NotebookPen, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import type {
  HighlightColor,
  HighlightInk,
  Mark,
  ThreadSummary,
  TutorSession,
} from "../../api/types";
import { CloseButton, Spinner, Thinking } from "../../components/ui";
import { relativeTime } from "../../lib/format";
import { linkPageRefs, pageRefTarget, renderMarkdown } from "../../lib/markdown";
import { paths } from "../../lib/router";
import type { CompanionState } from "./useCompanion";
import { t, tn, type Key } from "../../i18n";

/** The companion's answer as a note beside the paragraph (1b) — ink, never terracota. */
export function CompanionNote({
  companion,
  pageLabel,
  pageCount,
  onExpand,
  onGoToPage,
  onClose,
}: {
  companion: CompanionState;
  pageLabel: string;
  pageCount: number;
  onExpand(): void;
  /** A page the answer points at ("p. 81"), clicked. */
  onGoToPage(page: number): void;
  onClose(): void;
}) {
  const last = companion.turns[companion.turns.length - 1];
  const text = last?.role === "assistant" ? last.text : "";
  return (
    <section className="note ink" aria-label={t("margin.explanation")}>
      <div className="note-head">
        <Sparkles size={14} />
        <span className="kicker night">{t("margin.explanation")}</span>
        <span className="page-no">{t("common.page", { page: pageLabel })}</span>
        <CloseButton className="sm" onClick={onClose} />
      </div>
      {text ? (
        <div
          className="prose on-night"
          onClick={(event) => {
            const target = pageRefTarget(event);
            if (target !== null) onGoToPage(target);
          }}
          dangerouslySetInnerHTML={{ __html: linkPageRefs(renderMarkdown(text), pageCount) }}
        />
      ) : companion.streaming ? (
        <Thinking />
      ) : null}
      {companion.error ? (
        <p className="small" style={{ color: "var(--action-light)" }}>
          {companion.error}
        </p>
      ) : null}
      <div className="tools">
        <button
          type="button"
          className="btn btn-xs btn-on-night"
          disabled={companion.streaming}
          onClick={() => companion.follow("simplify")}
        >
          {t("margin.simpler")}
        </button>
        <button
          type="button"
          className="btn btn-xs btn-on-night"
          disabled={companion.streaming}
          onClick={() => companion.follow("concepts")}
        >
          {t("margin.concepts")}
        </button>
        <button type="button" className="btn btn-xs btn-on-night" onClick={onExpand}>
          <Maximize2 size={12} />
          {t("margin.ask")}
        </button>
      </div>
    </section>
  );
}

/** Conversations already held about this page: closing never deletes them. */
export function EarlierOnPage({
  threads,
  onReopen,
}: {
  threads: ThreadSummary[];
  onReopen(thread: ThreadSummary): void;
}) {
  if (!threads.length) return null;
  return (
    <section className="note dashed">
      <span className="kicker">{t("margin.earlier")}</span>
      {threads.slice(0, 3).map((thread) => (
        <p key={thread.id}>
          “{thread.quote.length > 70 ? `${thread.quote.slice(0, 70)}…` : thread.quote}” —{" "}
          {tn("margin.questions", Math.max(1, Math.floor(thread.message_count / 2)))},{" "}
          {relativeTime(thread.updated_at)}.{" "}
          <button type="button" className="btn-link" onClick={() => onReopen(thread)}>
            {t("margin.reopen")}
          </button>
        </p>
      ))}
    </section>
  );
}

/** Your own annotation: the quote above, your words in the middle, tags below. */
export function NoteEditor({
  mark,
  quote,
  colors,
  saving,
  onSave,
  onDelete,
  onClose,
  documentId,
}: {
  mark: Mark | null;
  quote: string;
  colors: HighlightInk[];
  saving: boolean;
  onSave(note: string, tags: string[], color: HighlightColor): void;
  onDelete(): void;
  onClose(): void;
  documentId: string;
}) {
  const [note, setNote] = useState(mark?.note ?? "");
  const [tags, setTags] = useState<string[]>(mark?.tags ?? []);
  const [draft, setDraft] = useState("");
  const [color, setColor] = useState<HighlightColor>(mark?.color ?? "amarelo");

  useEffect(() => {
    setNote(mark?.note ?? "");
    setTags(mark?.tags ?? []);
    setColor(mark?.color ?? "amarelo");
  }, [mark]);

  const addTag = () => {
    const value = draft.trim().toLowerCase();
    if (value && !tags.includes(value)) setTags([...tags, value]);
    setDraft("");
  };

  return (
    <section className="note paper" aria-label={t("margin.yourNote")}>
      <div className="note-head">
        <NotebookPen size={14} className="muted" />
        <span className="kicker action">{t("margin.yourNote")}</span>
        <CloseButton className="sm" onClick={onClose} />
      </div>
      <p className="quote">“{quote}”</p>
      <textarea
        className="input"
        placeholder={t("margin.notePlaceholder")}
        value={note}
        autoFocus
        onChange={(event) => setNote(event.target.value)}
      />
      <div className="row wrap tight">
        {tags.map((tag) => (
          <button
            key={tag}
            type="button"
            className="chip action"
            title={t("margin.removeTag")}
            onClick={() => setTags(tags.filter((item) => item !== tag))}
          >
            {tag}
          </button>
        ))}
        <input
          className="tag-input"
          value={draft}
          placeholder={t("margin.tagPlaceholder")}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              addTag();
            }
          }}
          onBlur={addTag}
        />
      </div>
      <div className="swatches">
        {colors.map((option) => (
          <button
            key={option.name}
            type="button"
            aria-label={t(`color.${option.name}` as Key)}
            aria-pressed={option.name === color}
            style={{ background: option.ink }}
            onClick={() => setColor(option.name)}
          />
        ))}
      </div>
      <div className="tools">
        <button
          type="button"
          className="btn btn-sm btn-action"
          disabled={saving}
          onClick={() => onSave(note, tags, color)}
        >
          {saving ? <Spinner /> : null}
          {t("margin.saveToNotebook")}
        </button>
        <span className="spacer" />
        {mark ? (
          <button type="button" className="btn btn-sm btn-quiet" onClick={onDelete}>
            <Trash2 size={14} />
            {t("common.delete")}
          </button>
        ) : null}
      </div>
      <a className="caption btn-link" href={paths.notebook(documentId)}>
        {t("margin.openNotebook")}
      </a>
    </section>
  );
}

type DenseTab = "expl" | "perg" | "para";

/** A dense passage the tutor marked: the same object in its three modes (1d). */
export function DenseCard({
  mark,
  session,
  onClose,
  onAsk,
}: {
  mark: Mark;
  session: TutorSession | null;
  onClose(): void;
  onAsk(): void;
}) {
  const [tab, setTab] = useState<DenseTab>("expl");
  const entry = session?.plan?.dense.find((item) => item.quote === mark.quote);
  const text =
    tab === "expl"
      ? (entry?.explain ?? mark.note ?? "")
      : tab === "perg"
        ? (entry?.question ?? "")
        : (entry?.paraphrase ?? "");
  const tabs: { value: DenseTab; label: Key }[] = [
    { value: "expl", label: "margin.dense.explain" },
    { value: "perg", label: "margin.dense.question" },
    { value: "para", label: "margin.dense.scaffold" },
  ];
  return (
    <section className="note dense" aria-label={t("margin.dense")}>
      <div className="note-head">
        <span className="kicker">{t("margin.dense")}</span>
        <CloseButton className="sm" onClick={onClose} />
      </div>
      {entry?.why ? <p className="small">{entry.why}</p> : null}
      <p className="quote">“{mark.quote}”</p>
      <div className="tabs">
        {tabs.map((item) => (
          <button
            key={item.value}
            type="button"
            aria-pressed={item.value === tab}
            onClick={() => setTab(item.value)}
          >
            {t(item.label)}
          </button>
        ))}
      </div>
      {text ? (
        <div className="prose" dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }} />
      ) : (
        <p className="small">{t("margin.dense.notReady")}</p>
      )}
      <div className="row tight">
        <button type="button" className="btn btn-xs btn-on-night solid" onClick={onClose}>
          {t("margin.dense.gotIt")}
        </button>
        <button type="button" className="btn btn-xs btn-on-night" onClick={onAsk}>
          {t("margin.dense.notYet")}
        </button>
      </div>
    </section>
  );
}
