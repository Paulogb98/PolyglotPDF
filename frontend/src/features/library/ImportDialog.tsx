import { Check, FileText, Upload } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, LANGUAGE_HEADER } from "../../api/client";
import type { DocumentSummary } from "../../api/types";
import { errorMessage } from "../../components/Toasts";
import { Dialog, Progress, Spine, Spinner } from "../../components/ui";
import { bridge } from "../../lib/desktop";
import { formatBytes } from "../../lib/format";
import { lang, t, tn } from "../../i18n";
import type { Key } from "../../i18n";

type Step = "choose" | "working" | "done" | "failed";

const STAGES: Key[] = ["import.stage.read", "import.stage.detect", "import.stage.sessions"];

export const ACCEPT = ".pdf,.epub,.mobi,.azw,.azw3,.fb2,.xps,.cbz";

/** Books to import: dropped or picked files (sent over HTTP) or paths from the native dialog. */
export interface Incoming {
  files?: File[];
  paths?: string[];
}

function upload(file: File, onProgress: (fraction: number) => void) {
  return new Promise<{ document: DocumentSummary; created: boolean }>((resolve, reject) => {
    const form = new FormData();
    form.append("file", file);
    const request = new XMLHttpRequest();
    request.open("POST", "/api/documents");
    request.withCredentials = true;
    request.setRequestHeader(LANGUAGE_HEADER, lang());
    request.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    });
    request.addEventListener("load", () => {
      try {
        const body = JSON.parse(request.responseText) as Record<string, unknown>;
        if (request.status >= 200 && request.status < 300) {
          resolve(body as unknown as { document: DocumentSummary; created: boolean });
        } else {
          reject(new Error(String(body.detail ?? request.status)));
        }
      } catch {
        reject(new Error(t("import.failedStatus", { status: request.status })));
      }
    });
    request.addEventListener("error", () => reject(new Error(t("import.noConnection"))));
    request.send(form);
  });
}

const fileName = (path: string) => path.split(/[\\/]/).pop() ?? path;

export function ImportDialog({
  incoming,
  onClose,
  onImported,
  onOpen,
}: {
  incoming?: Incoming | null;
  onClose(): void;
  /** Something entered the library — refresh what is behind the dialog. */
  onImported(document: DocumentSummary, created: boolean): void;
  /** "Abrir agora". */
  onOpen(document: DocumentSummary): void;
}) {
  const startsWorking = Boolean(incoming?.files?.length || incoming?.paths?.length);
  const [step, setStep] = useState<Step>(startsWorking ? "working" : "choose");
  const [stage, setStage] = useState(0);
  const [value, setValue] = useState(0);
  const [current, setCurrent] = useState<{ name: string; size: number | null } | null>(null);
  const [position, setPosition] = useState({ index: 0, total: 0 });
  const [imported, setImported] = useState<DocumentSummary[]>([]);
  const [failures, setFailures] = useState<string[]>([]);
  const [over, setOver] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const started = useRef(false);

  const finish = useCallback(async (document: DocumentSummary, created: boolean) => {
    setStage(1);
    setValue((v) => Math.max(v, 0.62));
    // Building the tutor's sessions is the real third stage: ask for them now.
    setStage(2);
    setValue((v) => Math.max(v, 0.82));
    await api.sessions(document.id).catch(() => undefined);
    setValue(1);
    setImported((list) => [...list, document]);
    onImported(document, created);
  }, [onImported]);

  const run = useCallback(
    async (items: Incoming) => {
      setStep("working");
      setImported([]);
      setFailures([]);
      const files = items.files ?? [];
      const paths = items.paths ?? [];
      const total = files.length + paths.length;
      let index = 0;
      for (const file of files) {
        setPosition({ index: (index += 1), total });
        setCurrent({ name: file.name, size: file.size });
        setStage(0);
        setValue(0);
        try {
          const result = await upload(file, (fraction) => setValue(fraction * 0.34));
          await finish(result.document, result.created);
        } catch (error) {
          setFailures((list) => [...list, `${file.name}: ${errorMessage(error)}`]);
        }
      }
      const desktop = paths.length ? await bridge() : null;
      for (const path of paths) {
        setPosition({ index: (index += 1), total });
        setCurrent({ name: fileName(path), size: null });
        setStage(0);
        setValue(0.2);
        try {
          const [result] = desktop ? await desktop.import_books([path]) : [];
          if (!result?.document) throw new Error(result?.error ?? t("import.unreadable"));
          await finish(result.document, Boolean(result.created));
        } catch (error) {
          setFailures((list) => [...list, `${fileName(path)}: ${errorMessage(error)}`]);
        }
      }
      setStep((current_) => (current_ === "working" ? "done" : current_));
    },
    [finish],
  );

  useEffect(() => {
    if (startsWorking && incoming && !started.current) {
      started.current = true;
      void run(incoming);
    }
  }, [startsWorking, incoming, run]);

  const choose = async () => {
    const desktop = await bridge();
    if (desktop) {
      const paths = await desktop.choose_books();
      if (paths.length) void run({ paths });
      return;
    }
    input.current?.click();
  };

  const noneImported = step === "done" && imported.length === 0;

  return (
    <Dialog onClose={onClose} label={t("import.label")}>
      {step === "choose" ? (
        <>
          <div className="stack-2">
            <h2 className="display-m">{t("import.title")}</h2>
            <p className="muted">
              {t("import.lead")}
            </p>
          </div>
          <button
            type="button"
            className="drop-zone"
            data-over={over}
            onClick={() => void choose()}
            onDragOver={(event) => {
              event.preventDefault();
              setOver(true);
            }}
            onDragLeave={() => setOver(false)}
            onDrop={(event) => {
              event.preventDefault();
              setOver(false);
              const files = [...(event.dataTransfer.files ?? [])];
              if (files.length) void run({ files });
            }}
          >
            <Upload size={22} />
            <span className="strong">{t("import.drop")}</span>
            <span className="small muted">{t("import.orClick")}</span>
          </button>
          <input
            ref={input}
            type="file"
            multiple
            accept={ACCEPT}
            className="visually-hidden"
            onChange={(event) => {
              const files = [...(event.target.files ?? [])];
              if (files.length) void run({ files });
            }}
          />
          <div className="dialog-foot">
            <span className="caption spacer">{t("import.staysLocal")}</span>
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {t("common.cancel")}
            </button>
          </div>
        </>
      ) : null}

      {step === "working" ? (
        <>
          <div className="import-head stack-2">
            <span className="kicker action">
              {position.total > 1 ? t("import.importingOf", { index: position.index, total: position.total }) : t("import.importing")}
            </span>
            <div className="import-file">
              <FileText size={20} className="muted" style={{ flex: "none" }} />
              <span className="name">{current?.name}</span>
            </div>
          </div>
          <div className="import-meter">
            <Progress value={value} tone="live" />
            <div className="readout">
              <span>{current?.size ? formatBytes(current.size) : t("import.fromDisk")}</span>
              <span className="pct">{Math.round(value * 100)}%</span>
            </div>
          </div>
          <div className="steps">
            {STAGES.map((label, index) => (
              <div
                key={label}
                className="step"
                data-state={index < stage ? "done" : index === stage ? "now" : "todo"}
              >
                <span className="dot">
                  {index < stage ? (
                    <Check size={14} strokeWidth={3} />
                  ) : index === stage ? (
                    <Spinner />
                  ) : null}
                </span>
                {t(label)}
              </div>
            ))}
          </div>
          <div className="dialog-foot">
            <span className="caption spacer">{t("import.canClose")}</span>
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {t("import.background")}
            </button>
          </div>
        </>
      ) : null}

      {step === "done" && imported.length === 1 ? (
        <>
          <div className="import-head row top" style={{ gap: 18 }}>
            <Spine item={imported[0]} className="thumb lg" />
            <div className="spacer stack-2" style={{ minWidth: 0 }}>
              <span className="kicker tutor">{t("import.ready")}</span>
              <div className="display-s">{imported[0].title}</div>
              <div className="caption">
                {[imported[0].authors, tn("common.pages", imported[0].pages), imported[0].format.toUpperCase()]
                  .filter(Boolean)
                  .join(" · ")}
              </div>
            </div>
          </div>
          <p className="small muted">
            {t("import.sessionsReady")}
          </p>
          <Failures failures={failures} />
          <div className="dialog-foot">
            <span className="spacer" />
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {t("common.later")}
            </button>
            <button type="button" className="btn btn-action" onClick={() => onOpen(imported[0])}>
              {t("import.openNow")}
            </button>
          </div>
        </>
      ) : null}

      {step === "done" && imported.length > 1 ? (
        <>
          <div className="import-head stack-2">
            <span className="kicker tutor">{tn("import.booksReady", imported.length)}</span>
            <h2 className="display-m">{t("import.onShelf")}</h2>
            <p className="small muted">
              {t("import.sessionsReadyMany")}
            </p>
          </div>
          <div className="imported">
            {imported.map((document) => (
              <button
                key={document.id}
                type="button"
                className="imported-book"
                title={document.title}
                onClick={() => onOpen(document)}
              >
                <Spine item={document} className="thumb lg" />
                <span className="name">{document.title}</span>
                <span className="meta">{tn("common.pages", document.pages)}</span>
              </button>
            ))}
          </div>
          <Failures failures={failures} />
          <div className="dialog-foot">
            <span className="spacer" />
            <button type="button" className="btn btn-action" onClick={onClose}>
              {t("import.seeShelf")}
            </button>
          </div>
        </>
      ) : null}

      {noneImported || step === "failed" ? (
        <>
          <h2 className="display-m">{t("import.failed")}</h2>
          <p className="muted">
            {failures.join(" · ") || t("import.failedUnreadable")} {t("import.nothingChanged")}
          </p>
          <div className="dialog-foot">
            <span className="spacer" />
            <button type="button" className="btn btn-outline" onClick={onClose}>
              {t("common.close")}
            </button>
            <button type="button" className="btn btn-action" onClick={() => setStep("choose")}>
              {t("import.chooseAnother")}
            </button>
          </div>
        </>
      ) : null}
    </Dialog>
  );
}

/** The files of the batch that did not come in, and why. */
function Failures({ failures }: { failures: string[] }) {
  if (!failures.length) return null;
  return (
    <div className="card-sand stack-1" style={{ padding: "12px 14px" }}>
      <span className="small strong">
        {tn("import.notIn", failures.length)}
      </span>
      {failures.map((failure) => (
        <span key={failure} className="caption">
          {failure}
        </span>
      ))}
    </div>
  );
}
