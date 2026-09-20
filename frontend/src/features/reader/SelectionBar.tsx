import { X } from "lucide-react";
import type { HighlightColor, HighlightInk } from "../../api/types";
import type { PageSelection } from "./selection";
import { t, type Key } from "../../i18n";

/** The ink bar that follows a selection: the four inks first, then what to do with it. */
export function SelectionBar({
  selection,
  colors,
  companion,
  onHighlight,
  onAnnotate,
  onDictionary,
  onExplain,
  onAsk,
  onClose,
}: {
  selection: PageSelection;
  colors: HighlightInk[];
  /** The companion is switched on: its actions belong on the bar. */
  companion: boolean;
  onHighlight(color: HighlightColor): void;
  onAnnotate(): void;
  onDictionary(): void;
  onExplain(): void;
  onAsk(): void;
  onClose(): void;
}) {
  const rect = selection.rect;
  const left = Math.min(Math.max(rect.left + rect.width / 2, 220), window.innerWidth - 220);
  const top = Math.max(rect.top - 12, 64);
  const oneWord = !/\s/.test(selection.text.trim());

  return (
    <div className="selection-bar" style={{ left, top }} role="toolbar" aria-label={t("selection.label")}>
      <span className="inks">
        {colors.map((color) => (
          <button
            key={color.name}
            type="button"
            style={{ background: color.ink }}
            aria-label={t("selection.highlightIn", { color: t(`color.${color.name}` as Key) })}
            title={t("selection.highlightIn", { color: t(`color.${color.name}` as Key) })}
            onClick={() => onHighlight(color.name)}
          />
        ))}
      </span>
      <span className="sep" />
      <button type="button" className="act" onClick={onAnnotate}>
        {t("selection.annotate")}
      </button>
      {companion ? (
        <>
          {oneWord ? (
            <button type="button" className="act" onClick={onDictionary}>
              {t("selection.dictionary")}
            </button>
          ) : null}
          <button type="button" className="act" onClick={onExplain}>
            {t("selection.explain")}
          </button>
          <button type="button" className="act" onClick={onAsk}>
            {t("selection.ask")}
          </button>
        </>
      ) : null}
      <button type="button" className="x" aria-label={t("common.close")} onClick={onClose}>
        <X size={14} strokeWidth={2.5} />
      </button>
    </div>
  );
}
