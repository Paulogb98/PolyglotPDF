import {
  BookOpen,
  Check,
  ChevronDown,
  Download,
  GraduationCap,
  Languages,
  Library,
  List,
  MoreHorizontal,
  Pause,
  Plus,
  Search,
  Settings,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from "react";
import { api } from "../../api/client";
import type { DocumentSummary, Job, OpenMode } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import {
  BrandMark,
  CoverArt,
  Menu,
  Progress,
  Segmented,
  Spine,
  Spinner,
} from "../../components/ui";
import { exportBook } from "../../lib/desktop";
import { languageLabel, percent, relativeTime } from "../../lib/format";
import { navigate, paths } from "../../lib/router";
import { t, type Key } from "../../i18n";
import { readStored, writeStored } from "../../lib/theme";
import { ACTIVE_STATUSES, useJobEvents, useJobs } from "../jobs/JobsContext";
import { usePreferences } from "../settings/PreferencesContext";
import { TranslateDialog } from "../translate/TranslateDialog";
import { ImportDialog, type Incoming } from "./ImportDialog";
import { InBookSearch } from "./InBookSearch";
import { StartDialog } from "./StartDialog";
import { useWindowDrop } from "./useWindowDrop";

type View = "lista" | "estante";
type Sort = "recent" | "added" | "title";

const SORTS: { value: Sort; label: Key }[] = [
  { value: "recent", label: "library.sort.recent" },
  { value: "added", label: "library.sort.added" },
  { value: "title", label: "library.sort.title" },
];

export function LibraryView() {
  const [documents, setDocuments] = useState<DocumentSummary[] | null>(null);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<Sort>(() => readStored("polyglotpdf.sort", "recent" as Sort));
  const [view, setView] = useState<View>(() => readStored("polyglotpdf.view", "lista" as View));
  const [sortOpen, setSortOpen] = useState(false);
  const sortButton = useRef<HTMLButtonElement>(null);
  const [incoming, setIncoming] = useState<Incoming | null | undefined>(undefined);
  const [starting, setStarting] = useState<DocumentSummary | null>(null);
  const [translating, setTranslating] = useState<DocumentSummary | null>(null);
  const [inBook, setInBook] = useState(false);
  const toast = useToast();
  const { jobs } = useJobs();
  const { reading } = usePreferences();
  const dragging = useWindowDrop((files) => setIncoming({ files }));

  const load = useCallback(async () => {
    try {
      setDocuments((await api.documents(query || undefined, sort)).documents);
    } catch (error) {
      toast({ kind: "error", title: t("library.loadFailed"), body: errorMessage(error) });
      setDocuments([]);
    }
  }, [query, sort, toast]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), query ? 220 : 0);
    return () => window.clearTimeout(timer);
  }, [load, query]);
  useEffect(() => setInBook(false), [query]);
  useJobEvents(() => void load());
  useEffect(() => writeStored("polyglotpdf.sort", sort), [sort]);
  useEffect(() => writeStored("polyglotpdf.view", view), [view]);

  const running = useMemo(() => {
    const byDocument = new Map<string, Job>();
    for (const job of jobs) {
      if (job.kind === "translate" && ACTIVE_STATUSES.has(job.status)) {
        byDocument.set(job.document_id, job);
      }
    }
    return byDocument;
  }, [jobs]);

  const open = (item: DocumentSummary, mode?: OpenMode) => {
    const version = item.versions[0]?.id ?? null;
    navigate(paths.reader(item.id, { version, page: item.last_page, mode }));
  };

  /** "Ao abrir um livro": the setting decides, then the book's own memory, then you. */
  const begin = async (item: DocumentSummary) => {
    if (!reading.tutor_enabled) return open(item, "read");
    if (reading.open_mode === "tutor" || reading.open_mode === "read") {
      return open(item, reading.open_mode);
    }
    const settings = await api.docSettings(item.id).catch(() => null);
    if (settings?.open_mode) open(item, settings.open_mode);
    else setStarting(item);
  };

  const remove = async (item: DocumentSummary) => {
    if (!window.confirm(t("library.confirmRemove", { title: item.title }))) {
      return;
    }
    try {
      await api.deleteDocument(item.id);
      toast({ title: t("library.removed"), body: item.title });
      void load();
    } catch (error) {
      toast({ kind: "error", title: t("library.removeFailed"), body: errorMessage(error) });
    }
  };

  const actions: BookActions = {
    open: (item) => void begin(item),
    translate: setTranslating,
    notebook: (item) => navigate(paths.notebook(item.id)),
    export: (item) => void exportBook(item.id, item.versions[0]?.id ?? null),
    remove: (item) => void remove(item),
  };

  const list = documents ?? [];
  const continuing = list.find((item) => item.opened_at) ?? null;
  const rest = view === "lista" && continuing ? list.filter((item) => item !== continuing) : list;
  const job = [...running.values()][0];

  return (
    <div className="screen">
      <div className="ground" />
      <header className="page-head">
        <BrandMark />
        <h1 className="display-l title">{t("library.title")}</h1>
        <label className="search">
          <Search size={16} strokeWidth={2.5} />
          <input
            value={query}
            placeholder={t("library.searchPlaceholder")}
            aria-label={t("library.searchLabel")}
            onChange={(event) => setQuery(event.target.value)}
          />
          {query ? (
            <button type="button" aria-label={t("library.clearSearch")} onClick={() => setQuery("")}>
              <X size={14} strokeWidth={2.75} />
            </button>
          ) : null}
        </label>
        <div>
          <button
            ref={sortButton}
            type="button"
            className="btn btn-quiet"
            aria-expanded={sortOpen}
            onClick={() => setSortOpen((on) => !on)}
          >
            {t(SORTS.find((option) => option.value === sort)?.label ?? "library.sort.recent")}
            <ChevronDown size={15} strokeWidth={2.5} />
          </button>
          <Menu open={sortOpen} onClose={() => setSortOpen(false)} anchor={sortButton}>
            {SORTS.map((option) => (
              <button
                key={option.value}
                type="button"
                className="menu-item"
                role="menuitemradio"
                aria-checked={option.value === sort}
                onClick={() => {
                  setSort(option.value);
                  setSortOpen(false);
                }}
              >
                {option.value === sort ? <Check size={14} strokeWidth={3} /> : <span style={{ width: 14 }} />}
                {t(option.label)}
              </button>
            ))}
          </Menu>
        </div>
        <Segmented
          value={view}
          onChange={setView}
          options={[
            { value: "lista", label: (<><List size={15} strokeWidth={2.5} />{t("library.view.list")}</>) },
            { value: "estante", label: (<><Library size={15} strokeWidth={2.5} />{t("library.view.shelf")}</>) },
          ]}
        />
        <button type="button" className="btn btn-action" onClick={() => setIncoming(null)}>
          <Upload size={16} strokeWidth={2.5} />
          {t("library.import")}
        </button>
        <a className="icon-btn glass" href={paths.settings()} aria-label={t("common.settings")} title={t("common.settings")}>
          <Settings size={17} strokeWidth={2.25} />
        </a>
      </header>

      <main className="library">
        {documents === null ? (
          <div className="row muted" style={{ padding: 40 }}>
            <Spinner /> {t("library.opening")}
          </div>
        ) : list.length === 0 ? (
          <Empty query={query} onImport={() => setIncoming(null)} onClear={() => setQuery("")} onInBook={() => setInBook(true)} />
        ) : view === "lista" ? (
          <>
            {continuing && !query ? (
              <ContinueCard item={continuing} onOpen={() => actions.open(continuing)} />
            ) : null}
            <div className="table-head kicker">
              <span />
              <span>{t("library.col.title")}</span>
              <span>{t("library.col.translations")}</span>
              <span>{t("library.col.progress")}</span>
              <span className="right">{t("library.col.lastRead")}</span>
              <span />
            </div>
            {(query ? list : rest).map((item) => (
              <BookRow key={item.id} item={item} job={running.get(item.id)} actions={actions} />
            ))}
          </>
        ) : (
          <Shelf
            items={list}
            running={running}
            actions={actions}
            onImport={() => setIncoming(null)}
          />
        )}

        {query && list.length > 0 && !inBook ? (
          <button type="button" className="btn btn-link" style={{ marginTop: 18 }} onClick={() => setInBook(true)}>
            <Search size={14} />
            {t("library.searchInside", { query })}
          </button>
        ) : null}
        {inBook && query ? (
          <InBookSearch
            query={query}
            documents={documents ?? []}
            companion={reading.companion_enabled}
          />
        ) : null}
      </main>

      {job ? <JobToast job={job} onOpen={() => setTranslating(list.find((d) => d.id === job.document_id) ?? null)} /> : null}
      {dragging ? <div className="drop-veil">{t("common.dropToImport")}</div> : null}

      {incoming !== undefined ? (
        <ImportDialog
          incoming={incoming}
          onClose={() => setIncoming(undefined)}
          onImported={() => void load()}
          onOpen={(item) => {
            setIncoming(undefined);
            void begin(item);
          }}
        />
      ) : null}
      {starting ? (
        <StartDialog
          document={starting}
          onClose={() => setStarting(null)}
          onStart={(mode) => {
            const item = starting;
            setStarting(null);
            open(item, mode);
          }}
        />
      ) : null}
      {translating ? (
        <TranslateDialog
          document={translating}
          onClose={() => setTranslating(null)}
          onStarted={() => void load()}
        />
      ) : null}
    </div>
  );
}

interface BookActions {
  open(item: DocumentSummary): void;
  translate(item: DocumentSummary): void;
  notebook(item: DocumentSummary): void;
  export(item: DocumentSummary): void;
  remove(item: DocumentSummary): void;
}

function BookMenu({
  item,
  open,
  onClose,
  actions,
  anchor,
  align,
}: {
  item: DocumentSummary;
  open: boolean;
  onClose(): void;
  actions: BookActions;
  anchor: RefObject<HTMLElement | null>;
  align?: "left" | "right";
}) {
  const run = (action: (item: DocumentSummary) => void) => () => {
    onClose();
    action(item);
  };
  return (
    <Menu open={open} onClose={onClose} anchor={anchor} align={align}>
      <button type="button" className="menu-item" onClick={run(actions.open)}>
        <BookOpen size={15} strokeWidth={2.25} />
        {t("common.read")}
      </button>
      <button type="button" className="menu-item" onClick={run(actions.translate)}>
        <Languages size={15} strokeWidth={2.25} />
        {t("library.menu.translate")}
      </button>
      <button type="button" className="menu-item" onClick={run(actions.notebook)}>
        <GraduationCap size={15} strokeWidth={2.25} />
        {t("common.notebook")}
      </button>
      <button type="button" className="menu-item" onClick={run(actions.export)}>
        <Download size={15} strokeWidth={2.25} />
        {item.versions.length ? t("library.menu.exportTranslation") : t("library.menu.exportFile")}
      </button>
      <div className="menu-sep" />
      <button type="button" className="menu-item danger" onClick={run(actions.remove)}>
        <Trash2 size={15} strokeWidth={2.25} />
        {t("library.menu.remove")}
      </button>
    </Menu>
  );
}

function ContinueCard({ item, onOpen }: { item: DocumentSummary; onOpen(): void }) {
  return (
    <button type="button" className="continue" onClick={onOpen}>
      <Spine item={item} className="thumb md" />
      <div className="body">
        <div className="kicker action">{t("library.continue")}</div>
        <div className="name">{item.title}</div>
        <div className="meta">
          {[item.authors, item.versions[0] ? t("library.inLanguage", { language: languageLabel(item.versions[0].target_lang) }) : null]
            .filter(Boolean)
            .join(" · ")}
        </div>
        <div className="row">
          <Progress value={item.progress} />
          <span className="caption">
            {t("common.pageOf", { page: item.last_page + 1, pages: item.pages })} · {percent(item.progress)}
          </span>
        </div>
      </div>
      <span className="btn btn-ink btn-lg">
        <BookOpen size={18} strokeWidth={2.5} />
        {t("common.read")}
      </span>
    </button>
  );
}

function BookRow({ item, job, actions }: { item: DocumentSummary; job?: Job; actions: BookActions }) {
  const [menu, setMenu] = useState(false);
  const more = useRef<HTMLButtonElement>(null);
  const toast = useToast();
  const pause = async () => {
    if (!job) return;
    await api.cancelJob(job.id).catch((error: Error) =>
      toast({ kind: "error", title: t("library.pauseFailed"), body: error.message }),
    );
  };
  return (
    <div className={`book-row ${menu ? "active" : ""}`}>
      <button type="button" className="open-hit" aria-label={t("common.openTitle", { title: item.title })} onClick={() => actions.open(item)} />
      <Spine item={item} />
      <div className="info" style={{ minWidth: 0 }}>
        <div className="name">{item.title}</div>
        <div className="meta">
          {[item.authors, t("library.pagesShort", { n: item.pages }), item.format.toUpperCase()].filter(Boolean).join(" · ")}
        </div>
      </div>
      <div className="langs">
        {item.versions.map((version) => (
          <span key={version.id} className="chip action">
            {version.target_lang.toUpperCase()}
          </span>
        ))}
        {job ? (
          <span className="chip night">
            <Spinner />
            {(job.params.target_lang ?? "").toUpperCase()}
          </span>
        ) : null}
        {!item.versions.length && !job ? <span className="caption">—</span> : null}
      </div>
      <div className="prog">
        {job ? (
          <div className="stack-2" style={{ gap: 5 }}>
            <Progress value={job.progress} tone="live" />
            <span style={{ font: "650 10.5px var(--font-mono)", color: "var(--action-ink)" }}>
              {t("library.translatedPct", { pct: percent(job.progress) })}
            </span>
          </div>
        ) : item.opened_at ? (
          <Progress value={item.progress} tone={item.progress >= 0.999 ? "done" : "normal"} />
        ) : (
          <span className="caption">{t("library.notOpened")}</span>
        )}
      </div>
      <div className="when">
        {job ? (
          <button type="button" className="btn btn-link btn-xs" style={{ color: "var(--ink-3)" }} onClick={() => void pause()}>
            <Pause size={11} strokeWidth={3} />
            {t("library.pause")}
          </button>
        ) : item.opened_at ? (
          relativeTime(item.opened_at)
        ) : (
          "—"
        )}
      </div>
      <div className="more">
        <button
          ref={more}
          type="button"
          className="icon-btn sm"
          aria-label={t("library.actionsFor", { title: item.title })}
          aria-expanded={menu}
          onClick={() => setMenu((on) => !on)}
        >
          <MoreHorizontal size={16} />
        </button>
        <BookMenu item={item} open={menu} onClose={() => setMenu(false)} actions={actions} anchor={more} />
      </div>
    </div>
  );
}

/** Covers of one size, laid in as many per row as the window holds, each row on a board. */
function Shelf({
  items,
  running,
  actions,
  onImport,
}: {
  items: DocumentSummary[];
  running: Map<string, Job>;
  actions: BookActions;
  onImport(): void;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [perRow, setPerRow] = useState(6);
  const [selected, setSelected] = useState<string | null>(null);

  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const measure = () => {
      const styles = getComputedStyle(element);
      const cover = parseFloat(styles.getPropertyValue("--cover-w")) || 148;
      const gap = 26;
      setPerRow(Math.max(2, Math.floor((element.clientWidth - 8 + gap) / (cover + gap))));
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  const slots: (DocumentSummary | "drop")[] = [...items, "drop"];
  const rows: (DocumentSummary | "drop")[][] = [];
  for (let start = 0; start < slots.length; start += perRow) {
    rows.push(slots.slice(start, start + perRow));
  }
  const continuing = items.find((item) => item.opened_at)?.id;

  return (
    <div className="shelf" ref={box}>
      {rows.map((row, index) => (
        <div key={index}>
          <div className="shelf-row">
            {row.map((slot) =>
              slot === "drop" ? (
                <button key="drop" type="button" className="drop-tile" onClick={onImport}>
                  <Plus size={20} strokeWidth={2} />
                  {t("library.dropTile.1")}
                  <br />
                  {t("library.dropTile.2")}
                </button>
              ) : (
                <ShelfItem
                  key={slot.id}
                  item={slot}
                  job={running.get(slot.id)}
                  continuing={slot.id === continuing}
                  selected={selected === slot.id}
                  onSelect={() => setSelected(slot.id)}
                  actions={actions}
                />
              ),
            )}
            {index === rows.length - 1 && row.length < perRow ? (
              <p className="shelf-aside">
                {t("library.shelfAside")}
              </p>
            ) : null}
          </div>
          <div className="shelf-board" />
        </div>
      ))}
    </div>
  );
}

function ShelfItem({
  item,
  job,
  continuing,
  selected,
  onSelect,
  actions,
}: {
  item: DocumentSummary;
  job?: Job;
  continuing: boolean;
  selected: boolean;
  onSelect(): void;
  actions: BookActions;
}) {
  const [menu, setMenu] = useState(false);
  const more = useRef<HTMLButtonElement>(null);
  const done = item.progress >= 0.999;
  return (
    <div className="shelf-item">
      <div
        className="cover"
        data-selected={selected || menu}
        role="button"
        tabIndex={0}
        aria-label={item.title}
        onClick={onSelect}
        onDoubleClick={() => actions.open(item)}
        onKeyDown={(event) => event.key === "Enter" && actions.open(item)}
      >
        <span className="art">
          <CoverArt item={item} />
        </span>
        <span className="edge" />
        <span className="cover-title">{item.title}</span>
        <span className="cover-author">{item.authors}</span>
        {continuing ? <span className="ribbon-tag">{t("library.continuing")}</span> : null}
        {done ? (
          <span className="corner done-tick">
            <Check size={13} strokeWidth={3} />
          </span>
        ) : item.opened_at && !continuing ? (
          <span className="corner chip night">
            <span style={{ width: 5, height: 5, borderRadius: 999, background: "var(--action-light)" }} />
            {percent(item.progress)}
          </span>
        ) : null}
        <span className="actions">
          <button
            type="button"
            className="btn btn-ink btn-xs"
            onClick={(event) => {
              event.stopPropagation();
              actions.open(item);
            }}
          >
            <BookOpen size={13} strokeWidth={2.5} />
            {continuing ? t("library.continueShort") : t("common.read")}
          </button>
          <span>
            <button
              ref={more}
              type="button"
              className="round"
              aria-label={t("library.actionsFor", { title: item.title })}
              aria-expanded={menu}
              onClick={(event) => {
                event.stopPropagation();
                setMenu((on) => !on);
              }}
            >
              <MoreHorizontal size={14} />
            </button>
          </span>
        </span>
        <div
          className="cover-menu"
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
        >
          <BookMenu
            item={item}
            open={menu}
            onClose={() => setMenu(false)}
            actions={actions}
            anchor={more}
            align="left"
          />
        </div>
      </div>
      <div className="shelf-caption">
        <div className="name">{item.title}</div>
        <Progress
          value={job ? job.progress : item.progress}
          tone={job ? "live" : done ? "done" : "normal"}
        />
        <div className="meta">
          {job
            ? t("library.translatingTo", { language: languageLabel(job.params.target_lang ?? "") })
            : done
              ? t("library.finished")
              : item.opened_at
                ? t("common.pageOf", { page: item.last_page + 1, pages: item.pages })
                : t("library.notOpenedFormat", { format: item.format.toUpperCase() })}
        </div>
      </div>
    </div>
  );
}

function JobToast({ job, onOpen }: { job: Job; onOpen(): void }) {
  const stages = Object.keys(job.stages).length;
  const stageIndex = Math.max(1, ["analyze", "translate", "render"].indexOf(job.stage ?? "") + 1);
  return (
    <div className="toasts">
      <div className="toast">
        <div className="toast-head">
          <Languages size={15} />
          <span className="spacer">{t("library.job.translatingTo", { language: languageLabel(job.params.target_lang ?? "") })}</span>
          <span style={{ color: "var(--night-muted)", fontWeight: 500 }}>{percent(job.progress)}</span>
        </div>
        <div className="toast-body">
          {t("library.job.stage", { title: job.params.title ?? "", stage: stageIndex, stages: Math.max(3, stages) })}
        </div>
        <Progress value={job.progress} tone="live" onNight />
        <div className="toast-actions">
          <button type="button" className="btn btn-xs btn-on-night solid" onClick={onOpen}>
            {t("library.job.details")}
          </button>
          <button
            type="button"
            className="btn btn-xs btn-on-night"
            onClick={() => void api.cancelJob(job.id).catch(() => undefined)}
          >
            {t("common.cancel")}
          </button>
        </div>
      </div>
    </div>
  );
}

function Empty({
  query,
  onImport,
  onClear,
  onInBook,
}: {
  query: string;
  onImport(): void;
  onClear(): void;
  onInBook(): void;
}) {
  if (query) {
    return (
      <div className="empty">
        <h2 className="display-s">{t("library.empty.noMatch")}</h2>
        <p>{t("library.empty.noMatchBody")}</p>
        <div className="row">
          <button type="button" className="btn btn-action" onClick={onInBook}>
            <Search size={15} />
            {t("library.empty.searchInside")}
          </button>
          <button type="button" className="btn btn-outline" onClick={onClear}>
            {t("library.clearSearch")}
          </button>
        </div>
      </div>
    );
  }
  return (
    <div className="empty">
      <h2 className="display-s">{t("library.empty.title")}</h2>
      <p>{t("library.empty.body")}</p>
      <button type="button" className="btn btn-action" onClick={onImport}>
        <Upload size={15} />
        {t("library.empty.import")}
      </button>
    </div>
  );
}
