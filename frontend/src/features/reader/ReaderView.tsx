import {
  BookMarked,
  Bookmark,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Highlighter,
  Languages,
  Link2,
  ListTree,
  Search,
  Sparkles,
  ZoomIn,
  ZoomOut,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, urls } from "../../api/client";
import type {
  Anchor,
  Bookmark as BookmarkEntry,
  DocumentSummary,
  Engine,
  HighlightColor,
  Layout,
  Mark,
  NotebookCounts,
  OpenMode,
  ReaderLayout,
  ThreadSummary,
  TutorSession,
} from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { Segmented } from "../../components/ui";
import { endonym } from "../../lib/format";
import { navigate, paths } from "../../lib/router";
import { readStored, writeStored } from "../../lib/theme";
import { t } from "../../i18n";
import { useJobEvents } from "../jobs/JobsContext";
import { usePreferences } from "../settings/PreferencesContext";
import { TranslateDialog } from "../translate/TranslateDialog";
import { CompanionSheet, SheetPeek } from "./CompanionSheet";
import { DictionaryPanel, MarksDrawer, OutlineDrawer, SearchDrawer } from "./Drawers";
import { CompanionNote, DenseCard, EarlierOnPage, NoteEditor } from "./MarginColumn";
import type { Edge, Point } from "./curl";
import { PageCurl, type CurlMode } from "./PageCurl";
import { imageScale, PageView, type Focus, type PageHit } from "./PageView";
import { SelectionBar } from "./SelectionBar";
import { loadTextLayer } from "./textLayer";
import { readSelection, type PageSelection } from "./selection";
import { SessionBar } from "./SessionBar";
import { ChapterEnd, Debrief, OpeningBook, SessionOpening } from "./SessionDialogs";
import { useCompanion } from "./useCompanion";

type Panel =
  | null
  | "nota"
  | "folha"
  | "traduzir"
  | "sumario"
  | "busca"
  | "dic"
  | "grifos"
  | "minhaNota"
  | "abertura"
  | "marcador"
  | "fim";

const EMPTY_COUNTS: NotebookCounts = {
  total: 0,
  highlights: 0,
  notes: 0,
  tutor: 0,
  cards: 0,
  due: 0,
  new: 0,
  hard: 0,
  ok: 0,
};
/** Minutes a page takes, for "faltam ~9 min de leitura". */
const MINUTES_PER_PAGE = 1.6;
/** Height of the folded sheet waiting at the bottom while a conversation is a note. */
const PEEK_HEIGHT = 74;

/** Zoom over "fit the window" (1). */
const ZOOMS = [0.5, 0.67, 0.8, 1, 1.25, 1.5, 1.75, 2, 2.5, 3];
const zoomKey = (id: string) => `polyglotpdf.zoom.${id}`;

/** The next zoom step up or down from ``current``. */
function stepZoom(current: number, direction: 1 | -1): number {
  if (direction > 0) return ZOOMS.find((value) => value > current + 0.001) ?? ZOOMS[ZOOMS.length - 1];
  return [...ZOOMS].reverse().find((value) => value < current - 0.001) ?? ZOOMS[0];
}

/** A page being turned: the leaf lifts from ``from``'s spread and lands on ``to``'s. */
interface Turn {
  from: number;
  to: number;
  dir: "left" | "right";
  key: number;
  mode: CurlMode;
  edge: Edge;
  grab?: Point;
}

/** How long a page takes to turn by itself: the ``--t-flip`` token. */
function flipDuration(): number {
  const token = getComputedStyle(window.document.documentElement).getPropertyValue("--t-flip");
  return Number.parseFloat(token) || 1200;
}

/** The gutter between the two leaves (``.book .gutter``). */
const GUTTER = 14;
/** A leaf's height around its page: the running head (34) and the frame's padding (22). */
const LEAF_CHROME = 56;

export function ReaderView({
  id,
  version: routeVersion,
  initialPage: routePage,
  mode: routeMode,
}: {
  id: string;
  version: string | null;
  initialPage: number | null;
  mode: OpenMode | null;
}) {
  const toast = useToast();
  const { reading, colors, ink } = usePreferences();

  const [document_, setDocument] = useState<DocumentSummary | null>(null);
  const [layout, setLayout] = useState<Layout | null>(null);
  const [sourceLanguage, setSourceLanguage] = useState<string | null>(null);
  // The address carries the place while reading (page, version, mode) and is rewritten as
  // the reader goes; it only says where to *open*. Reading it again on every change would
  // reload the book and undo choices made since, like going back to the original.
  const [opening] = useState(() => ({ version: routeVersion, page: routePage, mode: routeMode }));
  const initialVersion = opening.version;
  const initialPage = opening.page;
  const initialMode = opening.mode;
  const [versionId, setVersionId] = useState<string | null>(initialVersion);
  const [readerLayout, setReaderLayout] = useState<ReaderLayout>(initialVersion ? "traducao" : "original");
  const [mode, setMode] = useState<OpenMode>(initialMode ?? "read");
  const [page, setPage] = useState(initialPage ?? 0);
  const [panel, setPanel] = useState<Panel>(null);
  /** What the search drawer opens with (a term clicked on the concept map). */
  const [searchFor, setSearchFor] = useState("");
  const [selection, setSelection] = useState<PageSelection | null>(null);
  const [marks, setMarks] = useState<Mark[]>([]);
  const [bookmarks, setBookmarks] = useState<BookmarkEntry[]>([]);
  const [sessions, setSessions] = useState<TutorSession[]>([]);
  const [sessionNumber, setSessionNumber] = useState<number | null>(null);
  const [sessionHidden, setSessionHidden] = useState(false);
  const [planning, setPlanning] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [counts, setCounts] = useState<NotebookCounts>(EMPTY_COUNTS);
  const [readingSeconds, setReadingSeconds] = useState(0);
  const [readingDays, setReadingDays] = useState(0);
  const [activeMark, setActiveMark] = useState<Mark | null>(null);
  const [pendingNote, setPendingNote] = useState<PageSelection | null>(null);
  const [savingNote, setSavingNote] = useState(false);
  const [dictionary, setDictionary] = useState<{ word: string; anchor: Anchor } | null>(null);
  const [turn, setTurn] = useState<Turn | null>(null);
  const [settle, setSettle] = useState<"left" | "right" | null>(null);
  const [zoom, setZoom] = useState(() => readStored(zoomKey(id), 1));
  const [hits, setHits] = useState<{ page: number; rects: PageHit["rects"] }[]>([]);
  const [chapterEnd, setChapterEnd] = useState<string | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  const [progressOpen, setProgressOpen] = useState(0);
  const [threads, setThreads] = useState<ThreadSummary[]>([]);
  const [engines, setEngines] = useState<Engine[]>([]);
  const [companionEngine, setCompanionEngine] = useState<string | null>(null);
  const [sessionHeight, setSessionHeight] = useState(0);

  const spread = useRef<HTMLDivElement>(null);
  const settleTimer = useRef(0);
  /** The text on the page: the original has no version. */
  const activeVersion = readerLayout === "original" ? null : versionId;
  const companion = useCompanion(id, activeVersion);

  // ---------------------------------------------------------------- loading
  const loadStudy = useCallback(async () => {
    const [markList, bookmarkList, notebook] = await Promise.all([
      api.marks(id).catch(() => ({ marks: [] as Mark[] })),
      api.bookmarks(id).catch(() => ({ bookmarks: [] as BookmarkEntry[] })),
      api.notebook(id).catch(() => null),
    ]);
    setMarks(markList.marks);
    setBookmarks(bookmarkList.bookmarks);
    if (notebook) {
      setCounts(notebook.counts);
      setReadingSeconds(notebook.reading_seconds);
      setReadingDays(notebook.reading_days);
    }
  }, [id]);

  const loadThreads = useCallback(async () => {
    const result = await api.threads(id).catch(() => null);
    if (result) setThreads(result.threads);
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    setProgressOpen(0.1);
    void (async () => {
      try {
        const item = await api.document(id);
        if (cancelled) return;
        setDocument(item);
        setProgressOpen(0.34);
        const chosen = initialVersion ?? item.versions[0]?.id ?? null;
        setVersionId(chosen);
        setReaderLayout(chosen ? "traducao" : "original");
        const [geometry, original] = await Promise.all([
          api.layout(id, chosen),
          chosen ? api.layout(id, null) : Promise.resolve(null),
        ]);
        if (cancelled) return;
        setLayout(geometry);
        setSourceLanguage((original ?? geometry).language);
        setProgressOpen(0.75);
        if (initialPage === null) setPage(item.last_page);
        await api.updateDocument(id, { opened: true }).catch(() => undefined);
        await Promise.all([loadStudy(), loadThreads()]);
        const [result, engineList] = await Promise.all([
          api.sessions(id).catch(() => null),
          api.engines().catch(() => null),
        ]);
        if (cancelled) return;
        if (result) {
          setSessions(result.sessions);
          setSessionNumber(result.current);
        }
        if (engineList) {
          setEngines(engineList.engines);
          setCompanionEngine(engineList.companion_engine);
        }
        setProgressOpen(1);
      } catch (error) {
        if (!cancelled) {
          toast({ kind: "error", title: t("reader.openFailed"), body: errorMessage(error) });
          navigate(paths.library());
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, initialVersion, initialPage, loadStudy, loadThreads, toast]);

  // The running heads and the outline follow the text on the page.
  const loadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!document_) return;
    const key = activeVersion ?? "";
    if (loadedFor.current === null) {
      loadedFor.current = key;
      return;
    }
    if (loadedFor.current === key) return;
    loadedFor.current = key;
    let cancelled = false;
    void api
      .layout(id, activeVersion)
      .then((geometry) => !cancelled && setLayout(geometry))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [id, activeVersion, document_]);

  // A conversation that just got its thread belongs in the history.
  useEffect(() => {
    if (companion.thread && !companion.streaming) void loadThreads();
  }, [companion.thread, companion.streaming, loadThreads]);

  useJobEvents((job) => {
    if (job.document_id !== id || job.status !== "done") return;
    void api.document(id).then(setDocument).catch(() => undefined);
    if (job.version_id) {
      toast({
        kind: "success",
        title: t("reader.translationReady"),
        body: t("reader.translationReadyBody"),
        action: {
          label: t("common.open"),
          run: () => {
            setVersionId(job.version_id);
            setReaderLayout("traducao");
          },
        },
      });
    }
  });

  const session = useMemo(
    () => sessions.find((item) => item.number === sessionNumber) ?? null,
    [sessions, sessionNumber],
  );

  // Opening the book with the tutor: the session opens first.
  const opened = useRef(false);
  useEffect(() => {
    if (opened.current || sessionNumber === null) return;
    opened.current = true;
    if (initialMode === "tutor" && reading.tutor_enabled) setPanel("abertura");
  }, [sessionNumber, initialMode, reading.tutor_enabled]);

  const plan = useCallback(
    async (number: number, refresh = false) => {
      setPlanning(true);
      setPlanError(null);
      try {
        const planned = await api.planSession(id, number, activeVersion, refresh);
        setSessions((list) => list.map((item) => (item.number === number ? planned : item)));
        await loadStudy();
      } catch (error) {
        setPlanError(errorMessage(error));
      } finally {
        setPlanning(false);
      }
    },
    [id, activeVersion, loadStudy],
  );

  /** Plan a later session in the background (the end of a session prepares the next). */
  const prepare = useCallback(
    async (number: number) => {
      try {
        const planned = await api.planSession(id, number, activeVersion);
        setSessions((list) => list.map((item) => (item.number === number ? planned : item)));
        await loadStudy();
        return true;
      } catch {
        return false;
      }
    },
    [id, activeVersion, loadStudy],
  );

  useEffect(() => {
    if (panel === "abertura" && session && !session.has_plan && !planning && !planError) {
      void plan(session.number);
    }
  }, [panel, session, planning, planError, plan]);

  // ---------------------------------------------------------------- geometry
  useLayoutEffect(() => {
    const element = spread.current;
    if (!element) return;
    const measure = () => setSize({ width: element.clientWidth, height: element.clientHeight });
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, [layout, panel]);

  const pageSize = layout?.pages[Math.min(page, (layout?.pages.length ?? 1) - 1)] ?? [595, 842];
  const [pageWidth, pageHeight] = pageSize;
  const scrolling = reading.advance === "scroll";
  const columns = scrolling && readerLayout !== "lado" ? 1 : 2;
  const fit = useMemo(() => {
    if (!size.width || !size.height) return 0;
    const horizontal = (size.width - 8) / (pageWidth * columns + 14);
    const vertical = (size.height - LEAF_CHROME - 4) / pageHeight;
    return Math.max(0.2, Math.min(horizontal, scrolling ? vertical * 1.15 : vertical, 2.4));
  }, [size, pageWidth, pageHeight, columns, scrolling]);
  const scale = fit * zoom;

  // Zooming keeps the point in the middle of the view where it was.
  const zoomCenter = useRef<{ x: number; y: number } | null>(null);
  const changeZoom = useCallback(
    (next: number) => {
      const element = spread.current;
      if (element) {
        zoomCenter.current = {
          x: (element.scrollLeft + element.clientWidth / 2) / Math.max(1, element.scrollWidth),
          y: (element.scrollTop + element.clientHeight / 2) / Math.max(1, element.scrollHeight),
        };
      }
      const clamped = Math.min(ZOOMS[ZOOMS.length - 1], Math.max(ZOOMS[0], next));
      setZoom(clamped);
      writeStored(zoomKey(id), clamped);
    },
    [id],
  );
  const zoomBy = useCallback((direction: 1 | -1) => changeZoom(stepZoom(zoom, direction)), [changeZoom, zoom]);
  useLayoutEffect(() => {
    const element = spread.current;
    const center = zoomCenter.current;
    if (!element || !center) return;
    zoomCenter.current = null;
    element.scrollLeft = center.x * element.scrollWidth - element.clientWidth / 2;
    element.scrollTop = center.y * element.scrollHeight - element.clientHeight / 2;
  }, [zoom]);

  // Ctrl + wheel zooms the page, not the window.
  useEffect(() => {
    const element = spread.current;
    if (!element) return;
    const onWheel = (event: WheelEvent) => {
      if (!event.ctrlKey) return;
      event.preventDefault();
      zoomBy(event.deltaY < 0 ? 1 : -1);
    };
    element.addEventListener("wheel", onWheel, { passive: false });
    return () => element.removeEventListener("wheel", onWheel);
  }, [zoomBy, layout, panel]);

  useLayoutEffect(() => {
    const card = window.document.querySelector<HTMLElement>(".session-bar");
    if (!card) {
      setSessionHeight(0);
      return;
    }
    const measure = () => setSessionHeight(card.offsetHeight);
    const observer = new ResizeObserver(measure);
    observer.observe(card);
    measure();
    return () => observer.disconnect();
  });

  // ---------------------------------------------------------------- navigation
  const pageCount = layout?.page_count ?? document_?.pages ?? 1;
  const step = columns === 1 || readerLayout === "lado" ? 1 : 2;

  const chapters = useMemo(() => {
    const top = (layout?.toc ?? []).filter((entry) => entry.level === 1);
    if (top.length >= 2) return top.map((entry) => ({ title: entry.title, page: entry.page }));
    return sessions.map((item) => ({ title: item.title, page: item.start_page }));
  }, [layout, sessions]);

  const chapterOf = useCallback(
    (target: number) => {
      let title: string | null = null;
      for (const entry of layout?.toc ?? []) if (entry.page <= target) title = entry.title;
      return title;
    },
    [layout],
  );

  const goTo = useCallback(
    (target: number, direction?: "left" | "right") => {
      const clamped = Math.max(0, Math.min(pageCount - 1, target));
      if (direction && readerLayout === "lado" && reading.page_animation && !reading.reduce_motion) {
        // Side by side both leaves change at once: they settle in rather than turn.
        window.clearTimeout(settleTimer.current);
        setSettle(direction);
        settleTimer.current = window.setTimeout(() => setSettle(null), 420);
      }
      setPage((current) => {
        const before = chapterOf(current);
        const after = chapterOf(clamped);
        if (before && after && before !== after && clamped > current) setChapterEnd(before);
        return clamped;
      });
      setSelection(null);
    },
    [pageCount, readerLayout, reading.page_animation, reading.reduce_motion, chapterOf],
  );

  useEffect(() => () => window.clearTimeout(settleTimer.current), []);

  // ---------------------------------------------------------------- turning the page
  // In the two-page book a page turns by its corner: by itself (arrows, buttons, a click
  // on the corner) or pulled by the reader. The page number changes when it has turned.
  const turnRef = useRef<Turn | null>(null);
  turnRef.current = turn;
  const pageNow = useRef(page);
  pageNow.current = page;
  const curls = columns === 2 && readerLayout !== "lado" && !scrolling;

  const finishTurn = useCallback(
    (done: Turn, turned: boolean) => {
      if (turnRef.current?.key !== done.key) return;
      turnRef.current = null;
      setTurn(null);
      if (turned) goTo(done.to);
    },
    [goTo],
  );

  const turnPage = useCallback(
    (direction: "left" | "right", how?: { mode: CurlMode; edge: Edge; grab?: Point }) => {
      const running = turnRef.current;
      if (running?.mode === "drag") return; // the hand is on the page
      let from = pageNow.current;
      if (running) {
        // Asked again while a page is still turning: that one is done, the next one starts.
        finishTurn(running, true);
        from = running.to;
      }
      const to = Math.max(0, Math.min(pageCount - 1, from + (direction === "right" ? step : -step)));
      if (to === from) return;
      const animated = how?.mode === "drag" || (reading.page_animation && !reading.reduce_motion);
      if (!curls || !animated || Math.abs(to - from) !== 2) {
        goTo(to, direction);
        return;
      }
      const next: Turn = {
        from,
        to,
        dir: direction,
        key: performance.now(),
        mode: how?.mode ?? "auto",
        edge: how?.edge ?? "bottom",
        grab: how?.grab,
      };
      turnRef.current = next;
      setTurn(next);
      setSelection(null);
    },
    [pageCount, step, curls, reading.page_animation, reading.reduce_motion, goTo, finishTurn],
  );

  // Keep the place, and the address, in step with the page being read.
  useEffect(() => {
    if (!document_) return;
    const timer = window.setTimeout(() => {
      void api.updateDocument(id, { last_page: page }).catch(() => undefined);
      navigate(paths.reader(id, { version: versionId, page, mode }), { replace: true });
    }, 600);
    return () => window.clearTimeout(timer);
  }, [id, page, versionId, mode, document_]);

  // Reading time, a minute at a time, only while the window is in front.
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (window.document.visibilityState !== "visible") return;
      void api
        .addReadingTime(id, 60)
        .then((result) => setReadingSeconds(result.seconds))
        .catch(() => undefined);
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [id]);

  // The spreads around this one are fetched ahead, so a turning leaf never shows an
  // empty page on its back.
  useEffect(() => {
    if (!scale) return;
    const resolution = imageScale(scale);
    const shown =
      readerLayout === "lado" ? [null, versionId] : [readerLayout === "original" ? null : versionId];
    const timer = window.setTimeout(() => {
      for (let offset = -2 * step; offset <= 3 * step; offset += 1) {
        const target = page + offset;
        if ((offset >= 0 && offset < step) || target < 0 || target >= pageCount) continue;
        for (const version of shown) {
          new Image().src = urls.pageImage(id, target, resolution, version);
          void loadTextLayer(id, target, version).catch(() => undefined);
        }
      }
    }, 250);
    return () => window.clearTimeout(timer);
  }, [id, page, step, pageCount, scale, readerLayout, versionId]);

  // ---------------------------------------------------------------- continuous scroll
  // "Avançar por: rolagem" lays the pages in one column. Only a window of them is
  // mounted; spacers above and below keep the scrollbar the size of the whole book.
  const rowHeight = pageHeight * scale + LEAF_CHROME + 16;
  const window_ = useMemo(() => {
    const first = Math.max(0, page - 2 * step);
    const last = Math.min(pageCount - 1, page + 4 * step);
    const pages: number[] = [];
    for (let target = first; target <= last; target += step) pages.push(target);
    return { first, last, pages };
  }, [page, pageCount, step]);
  const scrollingProgrammatically = useRef(false);

  const onScroll = useCallback(() => {
    const element = spread.current;
    if (!element || !rowHeight || scrollingProgrammatically.current) return;
    const target = Math.round(element.scrollTop / rowHeight);
    setPage((current) => (target !== current ? Math.min(pageCount - 1, target) : current));
  }, [rowHeight, pageCount]);

  useEffect(() => {
    const element = spread.current;
    if (!scrolling || !element || scale === 0) return;
    const wanted = page * rowHeight;
    if (Math.abs(element.scrollTop - wanted) < rowHeight / 2) return;
    // Jump rather than glide: a smooth scroll would feed its own positions back into
    // ``page`` and fight the reader for the place.
    scrollingProgrammatically.current = true;
    element.scrollTop = wanted;
    const timer = window.setTimeout(() => {
      scrollingProgrammatically.current = false;
    }, 120);
    return () => window.clearTimeout(timer);
  }, [page, rowHeight, scrolling, scale]);

  // ---------------------------------------------------------------- selection
  useEffect(() => {
    const onUp = () => {
      const root = spread.current;
      if (!root) return;
      window.setTimeout(() => setSelection(readSelection(root)), 0);
    };
    window.document.addEventListener("mouseup", onUp);
    return () => window.document.removeEventListener("mouseup", onUp);
  }, []);

  const clearSelection = useCallback(() => {
    window.getSelection()?.removeAllRanges();
    setSelection(null);
  }, []);

  const highlight = useCallback(
    async (color: HighlightColor) => {
      if (!selection) return;
      try {
        const mark = await api.createMark(id, {
          version_id: selection.version,
          kind: "highlight",
          color,
          quote: selection.text,
          start: selection.start,
          end: selection.end,
          in_notebook: reading.save_to_notebook,
        });
        setMarks((list) => [...list, mark]);
        clearSelection();
        void loadStudy();
        if (reading.card_on_highlight) {
          await api
            .createCard(id, {
              front: `O que este trecho estabelece? (p. ${mark.start.page + 1})`,
              back: mark.quote,
              quote: mark.quote,
              page: mark.start.page,
              mark_id: mark.id,
            })
            .catch(() => undefined);
        }
        if (reading.explain_on_highlight && reading.companion_enabled) {
          companion.start(mark.start, mark.end, "explain");
          setPanel("nota");
        } else {
          toast({
            title: reading.save_to_notebook ? t("reader.highlightedSaved") : t("reader.highlighted"),
            action: {
              label: t("reader.annotate"),
              run: () => {
                setActiveMark(mark);
                setPanel("minhaNota");
              },
            },
          });
        }
      } catch (error) {
        toast({ kind: "error", title: t("reader.highlightFailed"), body: errorMessage(error) });
      }
    },
    [selection, id, clearSelection, loadStudy, reading, companion, toast],
  );

  const saveNote = useCallback(
    async (note: string, tags: string[], color: HighlightColor) => {
      setSavingNote(true);
      try {
        if (activeMark) {
          const updated = await api.updateMark(activeMark.id, { note, tags, color });
          setMarks((list) => list.map((item) => (item.id === updated.id ? updated : item)));
          setActiveMark(updated);
        } else if (pendingNote) {
          const created = await api.createMark(id, {
            version_id: pendingNote.version,
            kind: "note",
            color,
            quote: pendingNote.text,
            note,
            tags,
            start: pendingNote.start,
            end: pendingNote.end,
          });
          setMarks((list) => [...list, created]);
          setActiveMark(created);
          setPendingNote(null);
        }
        void loadStudy();
        toast({ title: t("reader.savedToNotebook") });
        setPanel(null);
      } catch (error) {
        toast({ kind: "error", title: t("common.saveFailed"), body: errorMessage(error) });
      } finally {
        setSavingNote(false);
      }
    },
    [activeMark, pendingNote, id, loadStudy, toast],
  );

  const removeMark = useCallback(async () => {
    if (!activeMark) return;
    await api.deleteMark(activeMark.id).catch(() => undefined);
    setMarks((list) => list.filter((item) => item.id !== activeMark.id));
    setActiveMark(null);
    setPanel(null);
    void loadStudy();
  }, [activeMark, loadStudy]);

  const toggleBookmark = useCallback(async () => {
    try {
      const result = await api.toggleBookmark(id, page, chapterOf(page) ?? "");
      setBookmarks(result.bookmarks);
    } catch (error) {
      toast({ kind: "error", title: t("reader.bookmarkFailed"), body: errorMessage(error) });
    }
  }, [id, page, chapterOf, toast]);

  const askAboutPage = useCallback(() => {
    companion.start({ page, offset: 0 }, null, "summarize");
    setPanel("folha");
  }, [companion, page]);

  // ---------------------------------------------------------------- keyboard
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
      if (panel === "fim") return;
      if (event.ctrlKey && (event.key === "=" || event.key === "+" || event.key === "-" || event.key === "0")) {
        event.preventDefault();
        if (event.key === "0") changeZoom(1);
        else zoomBy(event.key === "-" ? -1 : 1);
        return;
      }
      if (event.key === "ArrowRight" || event.key === "PageDown") turnPage("right");
      else if (event.key === "ArrowLeft" || event.key === "PageUp") turnPage("left");
      else if (event.key === "/") {
        event.preventDefault();
        setPanel("busca");
      } else if (event.key === "b") void toggleBookmark();
      else if (event.key === "Escape" && !panel) clearSelection();
      else if (event.key === "ArrowUp" && event.ctrlKey && reading.companion_enabled) {
        if (companion.thread) setPanel("folha");
        else askAboutPage();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [turnPage, toggleBookmark, clearSelection, panel, companion.thread, askAboutPage, reading.companion_enabled, zoomBy, changeZoom]);

  // ---------------------------------------------------------------- derived
  // Offsets belong to the text of one version: a mark made on the original would land on
  // the wrong words of a translation, so each leaf only paints its own marks.
  const pageMarks = useCallback(
    (target: number, leafVersion: string | null) =>
      marks.filter(
        (mark) =>
          mark.start.page <= target &&
          mark.end.page >= target &&
          (mark.version_id ?? null) === leafVersion,
      ),
    [marks],
  );
  const pageHits = useCallback(
    (target: number): PageHit[] => {
      const found = hits.find((hit) => hit.page === target);
      return found ? [{ rects: found.rects, current: true }] : [];
    },
    [hits],
  );

  const versions = document_?.versions ?? [];
  const hasTranslation = versions.length > 0;
  const marked = bookmarks.some((bookmark) => bookmark.page === page);
  const conversationOpen = panel === "nota" || panel === "folha";
  const focus: Focus | null =
    conversationOpen && companion.thread
      ? { start: companion.thread.start, end: companion.thread.end }
      : null;
  const showMargin = panel === "nota" || panel === "minhaNota" || panel === "marcador";
  const tutorOn = mode === "tutor" && reading.tutor_enabled && session !== null;
  const showSession = tutorOn && !sessionHidden && !showMargin && panel !== "fim";
  const translationEngine = engines.find((engine) => engine.name === versions[0]?.engine);
  const chat = engines.find((engine) => engine.name === companionEngine);
  // A conversation held as a note grows into the sheet once it passes three exchanges.
  const asked = companion.turns.filter((turn) => turn.role === "user").length;
  const askedBefore = useRef(asked);
  useEffect(() => {
    const before = askedBefore.current;
    askedBefore.current = asked;
    if (panel === "nota" && companion.streaming && asked > before && asked > 3) setPanel("folha");
  }, [asked, panel, companion.streaming]);
  const peek = panel === "nota" && reading.companion_enabled && companion.thread !== null;
  const kept =
    tutorOn && session
      ? threads.filter((thread) => thread.page >= session.start_page && thread.page <= session.end_page).length
      : threads.length;

  const earlier = threads.filter(
    (thread) => thread.id !== companion.thread?.id && thread.page >= page && thread.page <= page + step - 1,
  );
  const currentChapter = chapters.reduce(
    (found, entry, index) => (entry.page <= page ? index : found),
    -1,
  );
  const minutesLeft = session
    ? Math.max(0, Math.round((session.end_page - page + 1) * MINUTES_PER_PAGE))
    : 0;
  const label = (target: number) => `${target + 1}`;

  if (!document_ || !layout) {
    return (
      <div className="screen">
        <div className="ground center" />
        <OpeningBook title={document_?.title ?? "…"} progress={progressOpen} />
      </div>
    );
  }

  if (panel === "fim" && session) {
    return (
      <div className="screen">
        <div className="ground" />
        <Debrief
          documentId={id}
          version={activeVersion}
          session={session}
          next={sessions.find((item) => item.number === session.number + 1) ?? null}
          readingSeconds={readingSeconds}
          readingDays={readingDays}
          onBack={() => setPanel(null)}
          onGo={(target) => {
            setPanel(null);
            goTo(target);
          }}
          onSearch={(term) => {
            setSearchFor(term);
            setPanel("busca");
          }}
          onPrepare={prepare}
          onNext={() => {
            const next = sessions.find((item) => item.number === session.number + 1);
            if (!next) return;
            setSessionNumber(next.number);
            setSessionHidden(false);
            setPanel("abertura");
            goTo(next.start_page);
          }}
        />
      </div>
    );
  }

  /** One leaf of the book. */
  const leaf = (side: "left" | "right", target: number, single: boolean) => {
    if (scale === 0) return null;
    if (target < 0 || target >= pageCount) {
      // Before the first page or after the last: blank paper keeps the book whole.
      return single ? null : (
        <div
          key={`${side}-blank`}
          className={`leaf ${side} blank`}
          style={{ width: pageWidth * scale }}
        />
      );
    }
    const leafVersion =
      readerLayout === "original" ? null : readerLayout === "lado" && side === "left" ? null : versionId;
    const head =
      readerLayout === "lado" ? (
        side === "left" ? (
          <>
            <span>{label(target)}</span>
            <span className="lang original">{endonym(sourceLanguage) || t("reader.original")}</span>
          </>
        ) : (
          <>
            <span className="lang">
              {endonym(versions[0]?.target_lang)}
              {translationEngine ? ` · ${translationEngine.label.replace("Anthropic ", "")}` : ""}
            </span>
            <span>{label(target)}</span>
          </>
        )
      ) : side === "left" ? (
        <>
          <span>{label(target)}</span>
          <span>{chapterOf(target) ?? layout.title}</span>
        </>
      ) : (
        <>
          <span>{chapterOf(target) ?? layout.title}</span>
          <span>{label(target)}</span>
        </>
      );
    return (
      <div
        key={`${side}-${target}`}
        className={`leaf ${single ? "single" : side}`}
        data-settle={settle ?? undefined}
        style={{ width: pageWidth * scale }}
      >
        {target === page && marked && side === (single ? "left" : "right") ? (
          <button type="button" className="ribbon" aria-label={t("reader.removeBookmark")} onClick={() => void toggleBookmark()} />
        ) : null}
        <div className="running-head">{head}</div>
        <div className="page-frame">
          <PageView
            documentId={id}
            page={target}
            version={leafVersion}
            width={pageWidth}
            height={pageHeight}
            scale={scale}
            side={single ? "right" : side}
            marks={pageMarks(target, leafVersion)}
            hits={pageHits(target)}
            focus={focus && leafVersion === activeVersion ? focus : null}
            ink={ink}
            onMarkClick={(mark) => {
              setActiveMark(mark);
              setPanel(mark.source === "tutor" ? "marcador" : "minhaNota");
            }}
          />
        </div>
      </div>
    );
  };

  /** The corners a page can be taken by: the outer ones, where there is a page to go to. */
  const corners = (at: number) => {
    if (!curls) return null;
    const grab = (direction: "left" | "right", edge: Edge) => (event: React.PointerEvent) => {
      if (event.button !== 0) return;
      event.preventDefault();
      turnPage(direction, { mode: "drag", edge, grab: { x: event.clientX, y: event.clientY } });
    };
    const zone = (direction: "left" | "right", edge: Edge) => (
      <span
        key={`${direction}-${edge}`}
        className={`curl-zone ${direction} ${edge}`}
        title={direction === "right" ? t("reader.dragForward") : t("reader.dragBack")}
        onPointerDown={grab(direction, edge)}
      />
    );
    return (
      <>
        {at > 0 ? [zone("left", "top"), zone("left", "bottom")] : null}
        {at + step < pageCount ? [zone("right", "top"), zone("right", "bottom")] : null}
      </>
    );
  };

  const book = (at: number) =>
    columns === 1 ? (
      <div className="book" key={at}>
        {leaf("left", at, true)}
      </div>
    ) : (
      <div className="book pair" key={at}>
        {leaf("left", at, false)}
        <div className={`gutter ${readerLayout === "lado" ? "linked" : ""}`} />
        {leaf("right", readerLayout === "lado" ? at : at + 1, false)}
        {corners(at)}
      </div>
    );

  /** A page turning by its corner: under it, the pages it uncovers and lands on. */
  const turningBook = (current: Turn) => {
    const forward = current.dir === "right";
    return (
      <PageCurl
        key={current.key}
        forward={forward}
        leafWidth={pageWidth * scale}
        gutter={GUTTER}
        edge={current.edge}
        mode={current.mode}
        grab={current.grab}
        duration={flipDuration()}
        base={
          <>
            {leaf("left", forward ? current.from : current.to, false)}
            <div className="gutter" />
            {leaf("right", forward ? current.to + 1 : current.from + 1, false)}
          </>
        }
        front={leaf(forward ? "right" : "left", forward ? current.from + 1 : current.from, false)}
        back={leaf(forward ? "left" : "right", forward ? current.to : current.to + 1, false)}
        onFinish={(turned) => finishTurn(current, turned)}
      />
    );
  };

  const pillAside = showMargin || conversationOpen;
  // The pill floats above the session card, whatever height the card takes.
  const lift = showSession && sessionHeight ? sessionHeight + 22 + 14 : 0;
  const where =
    columns === 1 || readerLayout === "lado"
      ? label(page)
      : `${label(page)} – ${label(Math.min(page + 1, pageCount - 1))}`;

  return (
    <div className="screen">
      <div className="ground center" />
      <div className="reader">
        <header className="reader-top">
          <div className="left">
            <a className="icon-btn glass" href={paths.library()} aria-label={t("reader.backToLibrary")}>
              <ChevronLeft size={17} strokeWidth={2.5} />
            </a>
          </div>
          <div className="where">
            <b>{document_.title}</b>
            {chapterOf(page) ? ` · ${chapterOf(page)}` : ""}
          </div>
          <div className="right">
            <div className="zoom" role="group" aria-label={t("reader.zoom")}>
              <button
                type="button"
                aria-label={t("reader.zoomOut")}
                title={t("reader.zoomOutTitle")}
                disabled={zoom <= ZOOMS[0]}
                onClick={() => zoomBy(-1)}
              >
                <ZoomOut size={15} strokeWidth={2.25} />
              </button>
              <button
                type="button"
                className="level"
                title={zoom === 1 ? t("reader.zoomFitted") : t("reader.zoomFit")}
                aria-label={t("reader.zoomLevel", { pct: `${Math.round(zoom * 100)}%` })}
                onClick={() => changeZoom(1)}
              >
                {Math.round(zoom * 100)}%
              </button>
              <button
                type="button"
                aria-label={t("reader.zoomIn")}
                title={t("reader.zoomInTitle")}
                disabled={zoom >= ZOOMS[ZOOMS.length - 1]}
                onClick={() => zoomBy(1)}
              >
                <ZoomIn size={15} strokeWidth={2.25} />
              </button>
            </div>
            <button type="button" className="icon-btn" aria-label={t("reader.search")} title={t("reader.searchTitle")} onClick={() => setPanel("busca")}>
              <Search size={16} strokeWidth={2.25} />
            </button>
            <button
              type="button"
              className="icon-btn"
              aria-label={t("reader.marks")}
              title={t("reader.marks")}
              onClick={() => setPanel("grifos")}
            >
              <Highlighter size={16} strokeWidth={2.25} />
              {counts.total ? <span className="badge">{counts.total}</span> : null}
            </button>
            <button
              type="button"
              className={`icon-btn ${marked ? "on" : ""}`}
              aria-label={marked ? t("reader.removeBookmark") : t("reader.bookmark")}
              title={t("reader.bookmarkTitle")}
              onClick={() => void toggleBookmark()}
            >
              <Bookmark size={16} strokeWidth={2.25} fill={marked ? "currentColor" : "none"} />
            </button>
            {hasTranslation ? (
              <Segmented
                variant="sm"
                value={readerLayout}
                onChange={setReaderLayout}
                options={[
                  { value: "original", label: t("reader.original") },
                  { value: "traducao", label: t("reader.layout.translation") },
                  { value: "lado", label: t("reader.layout.sideBySide") },
                ]}
              />
            ) : null}
            {reading.tutor_enabled ? (
              <button
                type="button"
                className="mode-chip"
                data-mode={mode === "tutor" ? "tutor" : "read"}
                onClick={() => {
                  const next = mode === "tutor" ? "read" : "tutor";
                  setMode(next);
                  setSessionHidden(false);
                  if (next === "tutor" && session && !session.has_plan) setPanel("abertura");
                }}
              >
                {mode === "tutor" ? <BookMarked size={14} /> : <Sparkles size={14} />}
                {mode === "tutor" ? t("reader.mode.tutor") : t("reader.mode.read")}
              </button>
            ) : null}
          </div>
        </header>

        <div className="stage" style={lift ? { paddingBottom: lift + 58 + 16 } : undefined}>
          <div
            className="spread"
            ref={spread}
            onScroll={scrolling ? onScroll : undefined}
          >
            {scrolling ? (
              <div className="scroll-column">
                <div style={{ height: window_.first * rowHeight }} />
                {window_.pages.map((target) => book(target))}
                <div style={{ height: (pageCount - window_.last - 1) * rowHeight }} />
              </div>
            ) : turn && curls ? (
              turningBook(turn)
            ) : (
              book(page)
            )}
          </div>

          {showMargin ? (
            <aside className={`margin ${peek ? "over-peek" : ""}`}>
              {panel === "nota" ? (
                <>
                  <CompanionNote
                    companion={companion}
                    pageLabel={label(companion.thread?.page ?? page)}
                    pageCount={pageCount}
                    onExpand={() => setPanel("folha")}
                    onGoToPage={(target) => goTo(target)}
                    onClose={() => setPanel(null)}
                  />
                  <EarlierOnPage
                    threads={earlier}
                    onReopen={(thread) => void companion.reopen(thread.id).then(() => setPanel("nota"))}
                  />
                </>
              ) : null}
              {panel === "minhaNota" ? (
                <NoteEditor
                  documentId={id}
                  mark={activeMark}
                  quote={activeMark?.quote ?? pendingNote?.text ?? ""}
                  colors={colors}
                  saving={savingNote}
                  onSave={(note, tags, color) => void saveNote(note, tags, color)}
                  onDelete={() => void removeMark()}
                  onClose={() => setPanel(null)}
                />
              ) : null}
              {panel === "marcador" && activeMark ? (
                <DenseCard
                  mark={activeMark}
                  session={session}
                  onClose={() => setPanel(null)}
                  onAsk={() => {
                    companion.start(activeMark.start, activeMark.end, "simplify");
                    setPanel("nota");
                  }}
                />
              ) : null}
            </aside>
          ) : null}
        </div>

        {chapters.length > 1 && !showMargin && !scrolling ? (
          <nav className="rail" aria-label={t("reader.chapters")}>
            {chapters.map((entry, index) => (
              <button
                key={`${entry.page}-${index}`}
                type="button"
                aria-current={index === currentChapter}
                title={`${entry.title} · ${t("common.page", { page: entry.page + 1 })}`}
                onClick={() => goTo(entry.page)}
              >
                <i />
              </button>
            ))}
          </nav>
        ) : null}

        <div
          className={`pill ${pillAside ? "aside" : ""}`}
          style={lift ? { bottom: lift } : peek ? { bottom: PEEK_HEIGHT + 22 } : undefined}
        >
          <button
            type="button"
            className="icon-btn lg"
            aria-label={t("reader.previous")}
            disabled={page === 0}
            onClick={() => turnPage("left")}
          >
            <ChevronLeft size={19} strokeWidth={2.5} />
          </button>
          <div className="where">
            <div className="numbers">
              <span>{where}</span>
              <span>{t("reader.of", { n: pageCount })}</span>
            </div>
            <div
              className="track"
              role="slider"
              aria-label={t("reader.position")}
              aria-valuemin={1}
              aria-valuemax={pageCount}
              aria-valuenow={page + 1}
              tabIndex={0}
              onClick={(event) => {
                const box = event.currentTarget.getBoundingClientRect();
                goTo(Math.round(((event.clientX - box.left) / box.width) * (pageCount - 1)));
              }}
            >
              <i style={{ width: `${((page + 1) / pageCount) * 100}%` }} />
            </div>
          </div>
          <button
            type="button"
            className="icon-btn lg"
            aria-label={t("reader.next")}
            disabled={page + step >= pageCount}
            onClick={() => turnPage("right")}
          >
            <ChevronRight size={19} strokeWidth={2.5} />
          </button>
          <span className="sep" />
          {readerLayout === "lado" && !pillAside ? (
            <span className="sync">
              <Link2 size={13} />
              {t("reader.aligned")}
            </span>
          ) : null}
          <button type="button" className="icon-btn lg" aria-label={t("reader.contents")} title={t("reader.contents")} onClick={() => setPanel("sumario")}>
            <ListTree size={18} strokeWidth={2.25} />
          </button>
          <button type="button" className="icon-btn lg" aria-label={t("reader.translate")} title={t("reader.translate")} onClick={() => setPanel("traduzir")}>
            <Languages size={18} strokeWidth={2.25} />
          </button>
          {reading.companion_enabled ? (
            pillAside ? (
              <button
                type="button"
                className="icon-btn lg ink"
                aria-label={t("reader.companion")}
                onClick={() => (companion.thread ? setPanel("folha") : askAboutPage())}
              >
                <Sparkles size={17} />
              </button>
            ) : (
              <button
                type="button"
                className="btn btn-ink companion"
                onClick={() => (companion.thread ? setPanel("folha") : askAboutPage())}
              >
                <Sparkles size={16} />
                {t("reader.companion")}
              </button>
            )
          ) : null}
          {tutorOn && sessionHidden ? (
            <button
              type="button"
              className="btn btn-sm"
              style={{ background: "var(--tutor-soft)", color: "var(--tutor-deep)" }}
              onClick={() => setSessionHidden(false)}
            >
              <ChevronUp size={14} />
              {t("reader.session", { n: session?.number ?? "" })}
            </button>
          ) : null}
        </div>

        {showSession && session ? (
          <SessionBar
            session={session}
            total={sessions.length}
            page={page}
            planning={planning}
            minutesLeft={minutesLeft}
            onHide={() => setSessionHidden(true)}
            onCheck={() => {
              void api
                .finishSession(id, session.number)
                .then((finished) => {
                  setSessions((list) => list.map((item) => (item.number === finished.number ? finished : item)));
                  setPanel("fim");
                  void loadStudy();
                })
                .catch((error: Error) => toast({ kind: "error", title: t("reader.closeSessionFailed"), body: error.message }));
            }}
          />
        ) : null}
      </div>

      {selection ? (
        <SelectionBar
          selection={selection}
          colors={colors}
          companion={reading.companion_enabled}
          onHighlight={(color) => void highlight(color)}
          onAnnotate={() => {
            setPendingNote(selection);
            setActiveMark(null);
            setPanel("minhaNota");
            clearSelection();
          }}
          onDictionary={() => {
            setDictionary({ word: selection.text.trim(), anchor: selection.start });
            setPanel("dic");
            clearSelection();
          }}
          onExplain={() => {
            companion.start(selection.start, selection.end, "explain");
            setPanel("nota");
            clearSelection();
          }}
          onAsk={() => {
            companion.start(selection.start, selection.end, "explain");
            setPanel("folha");
            clearSelection();
          }}
          onClose={clearSelection}
        />
      ) : null}

      {peek ? (
        <SheetPeek count={Math.max(1, kept)} scope={tutorOn ? "session" : "book"} onOpen={() => setPanel("folha")} />
      ) : null}

      {panel === "folha" ? (
        <CompanionSheet
          companion={companion}
          engine={chat?.label.replace("Anthropic ", "") ?? t("reader.companion")}
          model={chat ? (chat.model ?? chat.default_model) : null}
          history={threads}
          pageCount={pageCount}
          onNew={askAboutPage}
          onGoToPage={(target) => {
            // The sheet folds back into the note, so the page it points at is in view.
            setPanel("nota");
            goTo(target);
          }}
          onClose={() => setPanel(companion.thread ? "nota" : null)}
        />
      ) : null}

      {panel === "sumario" ? (
        <OutlineDrawer layout={layout} sessions={sessions} page={page} onGo={(target) => goTo(target)} onClose={() => setPanel(null)} />
      ) : null}

      {panel === "busca" ? (
        <SearchDrawer
          documentId={id}
          version={activeVersion}
          marks={marks}
          page={page}
          initial={searchFor}
          onGo={(target, query) => {
            goTo(target);
            if (query) {
              void api
                .search(id, query, activeVersion)
                .then((result) => setHits(result.hits))
                .catch(() => undefined);
            }
          }}
          onClose={() => {
            setSearchFor("");
            setPanel(null);
          }}
        />
      ) : null}

      {panel === "grifos" ? (
        <MarksDrawer
          documentId={id}
          marks={marks}
          dueCards={counts.due}
          ink={ink}
          onGo={(target) => goTo(target)}
          onClose={() => setPanel(null)}
        />
      ) : null}

      {panel === "dic" && dictionary ? (
        <DictionaryPanel
          documentId={id}
          word={dictionary.word}
          page={dictionary.anchor.page}
          offset={dictionary.anchor.offset}
          version={activeVersion}
          onClose={() => setPanel(null)}
          onCard={(front, back) => {
            void api
              .createCard(id, { front, back, page: dictionary.anchor.page })
              .then(() => {
                toast({ title: t("reader.cardCreated") });
                void loadStudy();
              })
              .catch((error: Error) => toast({ kind: "error", title: t("common.error"), body: error.message }));
          }}
          onContext={() => {
            companion.start(dictionary.anchor, null, "vocabulary", dictionary.word);
            setPanel("nota");
          }}
        />
      ) : null}

      {panel === "traduzir" ? (
        <TranslateDialog document={document_} onClose={() => setPanel(null)} onStarted={() => setPanel(null)} />
      ) : null}

      {panel === "abertura" && session ? (
        <SessionOpening
          session={session}
          total={sessions.length}
          loading={planning}
          error={planError}
          onStart={() => {
            setPanel(null);
            setMode("tutor");
            setSessionHidden(false);
            void api.startSession(id, session.number).catch(() => undefined);
            if (page < session.start_page || page > session.end_page) goTo(session.start_page);
          }}
          onOnlyRead={() => {
            setMode("read");
            setPanel(null);
          }}
          onRetry={() => void plan(session.number, true)}
        />
      ) : null}

      {chapterEnd ? (
        <ChapterEnd
          title={chapterEnd}
          page={page}
          pages={pageCount}
          counts={counts}
          minutes={Math.round(readingSeconds / 60)}
          documentId={id}
          onClose={() => setChapterEnd(null)}
        />
      ) : null}
    </div>
  );
}
