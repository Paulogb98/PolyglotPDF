// Shapes of the JSON returned by the PolyglotPDF API (src/polyglotpdf/app/routes).

export interface AppInfo {
  version: string;
  data_dir: string;
  formats: string[];
  secret_store: string;
}

export interface Version {
  id: string;
  target_lang: string;
  engine: string;
  pages: number[] | null;
  created_at: string;
  translated: number | null;
  failed: number | null;
  warnings: string[];
}

export interface DocumentSummary {
  id: string;
  title: string;
  authors: string | null;
  filename: string;
  format: string;
  pages: number;
  size: number;
  added_at: string;
  opened_at: string | null;
  last_page: number;
  progress: number;
  favorite: boolean;
  versions: Version[];
}

export interface TocEntry {
  level: number;
  title: string;
  page: number;
}

export interface Layout {
  page_count: number;
  pages: [number, number][];
  title: string;
  authors: string | null;
  /** Detected language of the text ("de", "pt"…), or null when unsure. */
  language: string | null;
  toc: TocEntry[];
}

/** [x0, y0, x1, y1, start offset (code points), text including the following spaces] */
export type LayerWord = [number, number, number, number, number, string];

export interface TextLayer {
  width: number;
  height: number;
  label: string;
  words: LayerWord[];
}

export type Rect = [number, number, number, number];

export interface SearchResult {
  query: string;
  total: number;
  hits: { page: number; rects: Rect[] }[];
}

export interface Anchor {
  page: number;
  offset: number;
}

export interface ContextSummary {
  title: string;
  authors: string | null;
  section: string[];
  page: number;
  page_label: string;
  page_count: number;
  selection: string;
  whole_page: boolean;
  characters: { before: number; current: number; after: number };
}

export interface ContextFull extends ContextSummary {
  before: string;
  current: string;
  after: string;
  start: Anchor;
  end: Anchor;
}

export interface Message {
  id: number;
  role: "user" | "assistant";
  text: string;
  action: string | null;
  engine: string | null;
  model: string | null;
  status: string;
  created_at: string;
}

export interface ThreadSummary {
  id: string;
  document_id: string;
  version_id: string | null;
  quote: string;
  page: number;
  page_label: string;
  whole_page: boolean;
  start: Anchor;
  end: Anchor;
  created_at: string;
  updated_at: string;
  message_count: number;
}

export interface Thread extends ThreadSummary {
  context: ContextSummary;
  messages: Message[];
}

export type EngineKind = "standard" | "ai" | "offline";

export interface Engine {
  name: string;
  label: string;
  kind: EngineKind;
  description: string;
  website: string;
  requires_key: boolean;
  key_env: string[];
  key_source: "app" | "env" | null;
  /** The last characters of the key in use ("••••4f2a"), never the key itself. */
  key_hint: string | null;
  ready: boolean;
  default_model: string | null;
  model: string | null;
  default_base_url: string | null;
  base_url: string | null;
  lists_models: boolean;
  supports_glossary: boolean;
  supports_chat: boolean;
}

export interface EnginesResponse {
  engines: Engine[];
  companion_engine: string | null;
}

export interface Language {
  code: string;
  name: string;
}

export type ContextSize = "short" | "medium" | "long";

export interface EnginePrefs {
  model: string | null;
  base_url: string | null;
}

export interface Preferences {
  translation_engine: string;
  source_lang: string;
  target_lang: string;
  companion_engine: string | null;
  companion_language: string;
  /** "auto" (the system's), "pt-BR" or "en": the language of the interface. */
  interface_language: "auto" | "pt-BR" | "en";
  companion_effort: string;
  context_size: ContextSize;
  reading: ReadingPrefs;
  engines: Record<string, EnginePrefs>;
}

export type JobStatus = "queued" | "running" | "done" | "failed" | "cancelled";

export interface Job {
  id: string;
  kind: "translate" | "estimate";
  document_id: string;
  params: {
    title?: string;
    engine?: string;
    engine_label?: string;
    model?: string | null;
    source_lang?: string;
    target_lang?: string;
    pages?: string | null;
  };
  status: JobStatus;
  stage: string | null;
  stages: Record<string, { done: number; total: number }>;
  progress: number;
  result: Record<string, unknown> | null;
  error: string | null;
  version_id: string | null;
  created_at: string;
  finished_at: string | null;
}

export interface Estimate {
  pages: number;
  blocks: number;
  segments: number;
  merged_paragraphs: number;
  characters: number;
  words: number;
  formulas: number;
}

export interface CompanionAction {
  key: string;
  label: string;
}

export interface CheckResult {
  ok: boolean;
  message: string;
  models: string[];
}

// ---------------------------------------------------------------- study
export type HighlightColor = "yellow" | "green" | "coral" | "blue";

export interface HighlightInk {
  name: HighlightColor;
  ink: string;
  line: string;
}

export interface Mark {
  id: string;
  document_id: string;
  version_id: string | null;
  kind: "highlight" | "note";
  color: HighlightColor;
  quote: string;
  note: string | null;
  tags: string[];
  start: Anchor;
  end: Anchor;
  page: number;
  section: string[];
  source: "reader" | "tutor";
  /** False: the highlight stays on the page but is left out of the notebook. */
  in_notebook: boolean;
  created_at: string;
  updated_at: string;
}

export interface Bookmark {
  page: number;
  label: string;
  created_at: string;
}

export type Grade = "again" | "hard" | "good" | "easy";

export interface CardSchedule {
  grade: Grade;
  due_at: string;
  label: string;
}

export interface Card {
  id: string;
  document_id: string;
  mark_id: string | null;
  front: string;
  back: string;
  quote: string;
  page: number;
  source: "reader" | "tutor";
  due_at: string;
  interval_days: number;
  ease: number;
  reps: number;
  lapses: number;
  last_grade: Grade | null;
  state: "new" | "hard" | "ok";
  created_at: string;
  schedule?: CardSchedule[];
}

export interface NotebookChapter {
  title: string;
  first_page: number;
  last_page: number;
  marks: Mark[];
}

export interface NotebookCounts {
  total: number;
  highlights: number;
  notes: number;
  tutor: number;
  cards: number;
  due: number;
  new: number;
  hard: number;
  ok: number;
}

export interface Notebook {
  document: { id: string; title: string; authors: string | null };
  chapters: NotebookChapter[];
  counts: NotebookCounts;
  concepts: { name: string; count: number }[];
  marks: Mark[];
  reading_seconds: number;
  reading_days: number;
}

export interface ReviewQueue {
  cards: Card[];
  counts: { total: number; new: number; hard: number; ok: number };
}

// ---------------------------------------------------------------- tutor
export interface DensePassage {
  quote: string;
  why: string;
  explain: string;
  question: string;
  paraphrase: string;
}

export interface SessionQuestion {
  text: string;
  answer: string;
  hint: string;
}

export interface SessionAnswer {
  answer: string;
  comment: string;
}

export interface SessionPlan {
  version: string;
  intro: string;
  expect: string[];
  concepts: PlanConcept[];
  dense: DensePassage[];
  questions: SessionQuestion[];
  /** The reader's answers to the closing questions, by index. */
  answers?: Record<string, SessionAnswer>;
}

/** A concept the tutor put in play: its name in the reader's language, the word the book
 *  uses for it (may be empty, or the same), and what it means here. */
export interface PlanConcept {
  name: string;
  term: string;
  definition: string;
}

/** On the map: new in this session, back from an earlier one, met earlier and not seen
 *  again, or coming in a later session already planned. */
export type ConceptState = "new" | "again" | "earlier" | "ahead";

export interface SessionConcept extends PlanConcept {
  /** The session that introduced it. */
  session: number;
  state: ConceptState;
  uses: number;
  first_page: number | null;
  in_session: boolean;
}

export interface SessionPace {
  /** What the projection is about: the part of the book the session is in, the whole
   *  book, or nothing (the book ends here). */
  scope: "section" | "book" | "done";
  title: string | null;
  sessions_left: number;
  /** At the reader's pace so far; null until there is one. */
  minutes_left: number | null;
}

export interface ConceptMap {
  concepts: SessionConcept[];
  pace: SessionPace;
}

export interface TutorSession {
  id: string;
  document_id: string;
  number: number;
  title: string;
  start_page: number;
  end_page: number;
  pages: number;
  status: "pending" | "running" | "done";
  plan: SessionPlan | null;
  has_plan: boolean;
  started_at: string | null;
  finished_at: string | null;
}

export type OpenMode = "tutor" | "read";
export type ReaderLayout = "translation" | "original" | "side";

export interface DocSettings {
  open_mode: OpenMode | null;
  layout: ReaderLayout | null;
  version_id: string | null;
  session_number: number;
}

export interface SessionsResponse {
  sessions: TutorSession[];
  current: number | null;
  settings: DocSettings;
}

// ---------------------------------------------------------------- dictionary
export interface DictionarySense {
  gloss: string;
  common: boolean;
}

export interface DictionaryEntry {
  word: string;
  pronunciation: string;
  grammar: string;
  senses: DictionarySense[];
  in_book: string;
  related: string[];
}

export interface DictionaryResult {
  word: string;
  entry: DictionaryEntry | null;
  error: string | null;
  uses: number;
  pages: number[];
  page: number;
}

// ---------------------------------------------------------------- reading preferences
export interface ReadingPrefs {
  text_size: number;
  column_width: "narrow" | "book" | "wide";
  paper: "cream" | "white" | "sepia" | "night";
  page_animation: boolean;
  reduce_motion: boolean;
  advance: "pages" | "scroll";
  highlight_color: HighlightColor;
  save_to_notebook: boolean;
  card_on_highlight: boolean;
  explain_on_highlight: boolean;
  open_mode: "ask" | "tutor" | "read" | "remember";
  companion_enabled: boolean;
  tutor_enabled: boolean;
}
