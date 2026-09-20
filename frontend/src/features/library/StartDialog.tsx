import { BookMarked, BookOpen, Check, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import type { DocumentSummary, OpenMode, SessionsResponse } from "../../api/types";
import { Checkbox, Dialog, Spine, Spinner } from "../../components/ui";
import { usePreferences } from "../settings/PreferencesContext";
import { rich } from "../../i18n/rich";
import { t, tn, type Key } from "../../i18n";

const TUTOR_POINTS: Key[] = ["start.tutor.point1", "start.tutor.point2", "start.tutor.point3"];
const READ_POINTS: Key[] = ["start.read.point1", "start.read.point2", "start.read.point3"];

/** How to read now (2c): the choice is made when the book opens, and decides the tutor. */
export function StartDialog({
  document: item,
  onClose,
  onStart,
}: {
  document: DocumentSummary;
  onClose(): void;
  onStart(mode: OpenMode): void;
}) {
  const { reading } = usePreferences();
  const [mode, setMode] = useState<OpenMode>(
    reading.open_mode === "read" || !reading.tutor_enabled ? "read" : "tutor",
  );
  const [remember, setRemember] = useState(reading.open_mode === "remember");
  const [sessions, setSessions] = useState<SessionsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api
      .sessions(item.id)
      .then((result) => {
        if (cancelled) return;
        setSessions(result);
        if (result.settings.open_mode) setMode(result.settings.open_mode);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [item.id]);

  const current = sessions?.sessions.find((session) => session.number === sessions.current);
  const total = sessions?.sessions.length ?? 0;
  const done = sessions?.sessions.filter((session) => session.status === "done").length ?? 0;

  const begin = async () => {
    if (remember) await api.updateDocSettings(item.id, { open_mode: mode }).catch(() => undefined);
    onStart(mode);
  };

  return (
    <Dialog onClose={onClose} wide label={t("start.title")}>
      <div className="dialog-head">
        <Spine item={item} className="thumb" />
        <div className="stack-2">
          <span className="kicker action">
            {item.opened_at
              ? t("start.stoppedAt", { page: item.last_page + 1, pages: item.pages })
              : t("start.notOpened", { pages: tn("common.pages", item.pages) })}
          </span>
          <h2 className="display-m">{t("start.title")}</h2>
        </div>
      </div>

      <div className="choices">
        <button
          type="button"
          className="choice"
          data-kind="tutor"
          aria-pressed={mode === "tutor"}
          onClick={() => setMode("tutor")}
        >
          {mode === "tutor" ? (
            <span className="tick">
              <Check size={13} strokeWidth={3.2} />
            </span>
          ) : null}
          <BookMarked size={22} strokeWidth={2} />
          <span className="display-s">{t("start.tutor.title")}</span>
          <p>
            {t("start.tutor.body")}
          </p>
          <ul>
            {TUTOR_POINTS.map((point) => (
              <li key={point}>{t(point)}</li>
            ))}
          </ul>
          <span className="foot">
            {sessions === null ? (
              <Spinner />
            ) : current ? (
              rich("start.tutor.resume", {
                session: <strong>{t("start.tutor.sessionOf", { n: current.number, total })}</strong>,
                title: current.title,
              })
            ) : (
              t("start.tutor.allRead")
            )}
          </span>
        </button>

        <button
          type="button"
          className="choice"
          data-kind="read"
          aria-pressed={mode === "read"}
          onClick={() => setMode("read")}
        >
          {mode === "read" ? (
            <span className="tick">
              <Check size={13} strokeWidth={3.2} />
            </span>
          ) : null}
          <BookOpen size={22} strokeWidth={2} />
          <span className="display-s">{t("start.read.title")}</span>
          <p>
            {t("start.read.body")}
          </p>
          <ul>
            {READ_POINTS.map((point) => (
              <li key={point}>{t(point)}</li>
            ))}
          </ul>
          <span className="foot">
            {done > 0 ? (
              rich("start.read.done", {
                sessions: <strong>{t("start.read.doneCount", { done, total })}</strong>,
              })
            ) : (
              t("start.read.kept")
            )}
          </span>
        </button>
      </div>

      <div className="dialog-foot">
        <Checkbox checked={remember} onChange={setRemember}>
          {t("start.remember")}
        </Checkbox>
        <span className="spacer" />
        <button type="button" className="btn btn-quiet" onClick={onClose}>
          {t("common.cancel")}
        </button>
        <button type="button" className="btn btn-action btn-lg" onClick={() => void begin()}>
          {mode === "tutor" && current ? t("start.beginSession", { n: current.number }) : t("start.beginReading")}
          <ChevronRight size={17} strokeWidth={2.5} />
        </button>
      </div>
      <p className="caption">
        {t("start.switchLater")}
      </p>
    </Dialog>
  );
}
