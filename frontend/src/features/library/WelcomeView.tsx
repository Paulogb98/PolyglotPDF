import { BookOpen, LibraryBig, Upload } from "lucide-react";
import { useState } from "react";
import type { DocumentSummary } from "../../api/types";
import { Brand } from "../../components/ui";
import { navigate, paths } from "../../lib/router";
import { t } from "../../i18n";
import { ImportDialog, type Incoming } from "./ImportDialog";
import { useWindowDrop } from "./useWindowDrop";

const FORMATS = ["PDF", "EPUB", "MOBI", "FB2", "XPS", "CBZ"];

/** First run (1i): one sentence, one action, no tour. ``emptyLibrary`` means the reader
 *  asked for the library and was sent here because there is no book in it yet. */
export function WelcomeView({ emptyLibrary = false }: { emptyLibrary?: boolean }) {
  const [incoming, setIncoming] = useState<Incoming | null | undefined>(undefined);
  const [imported, setImported] = useState(false);
  const dragging = useWindowDrop((files) => setIncoming({ files }));

  const open = (document: DocumentSummary) => {
    setIncoming(undefined);
    navigate(paths.reader(document.id, { page: document.last_page }));
  };

  return (
    <div className="screen">
      <div className="ground" />
      <div className="welcome">
        <div className="welcome-copy">
          <Brand size={17} tag />
          <h1 className="display-xl">{t("welcome.headline")}</h1>
          <p className="lead">
            {t("welcome.lead")}
          </p>
          <div className="row">
            <button
              type="button"
              className="btn btn-action btn-lg"
              onClick={() => setIncoming(null)}
            >
              <Upload size={17} strokeWidth={2.5} />
              {t("welcome.choose")}
            </button>
            <span className="small muted">{t("welcome.orDrag")}</span>
          </div>
          {emptyLibrary ? (
            <p className="welcome-note">
              <LibraryBig size={15} strokeWidth={2.2} />
              {t("welcome.emptyLibrary")}
            </p>
          ) : null}
          <div className="formats">
            {FORMATS.map((format) => (
              <span key={format} className="chip">
                {format}
              </span>
            ))}
          </div>
          <p className="welcome-foot">
            {t("welcome.foot")}{" "}
            <a className="btn-link" href={paths.settings("ai")}>
              {t("welcome.setUpNow")}
            </a>
            {emptyLibrary ? null : (
              <>
                {" · "}
                <a className="btn-link" href={paths.library()}>
                  {t("welcome.openLibrary")}
                </a>
              </>
            )}
          </p>
        </div>

        <div className="welcome-art" aria-hidden="true">
          <span className="sun" />
          <span className="moon" />
          <span className="sheet-back" />
          <div className="sheet-art">
            <div className="chapter-label">{t("welcome.art.chapter")}</div>
            {[88, 94, 70, 0, 90, 96, 64].map((width, index) =>
              width ? (
                <div key={index} className="line" style={{ width: `${width}%` }} />
              ) : (
                <div key={index} style={{ height: 14 }} />
              ),
            )}
            <div className="note-art">
              <div className="kicker night">{t("welcome.art.explanation")}</div>
              {t("welcome.art.note")}
            </div>
            <div className="tutor-chip">
              <BookOpen size={14} />
              {t("welcome.art.tutor")}
            </div>
          </div>
        </div>
      </div>

      {dragging ? <div className="drop-veil">{t("common.dropToImport")}</div> : null}
      {incoming !== undefined ? (
        <ImportDialog
          incoming={incoming}
          onClose={() => {
            setIncoming(undefined);
            // Books came in: this screen is done, the shelf has them now.
            if (imported) navigate(paths.library());
          }}
          onImported={() => setImported(true)}
          onOpen={open}
        />
      ) : null}
    </div>
  );
}
