import { lang, t } from "../i18n";
import type {
  Anchor,
  AppInfo,
  Bookmark,
  Card,
  CheckResult,
  CompanionAction,
  ContextFull,
  DictionaryResult,
  DocSettings,
  DocumentSummary,
  Engine,
  EnginesResponse,
  Grade,
  HighlightColor,
  HighlightInk,
  Job,
  Language,
  Layout,
  Mark,
  Notebook,
  Preferences,
  ReviewQueue,
  SearchResult,
  ConceptMap,
  SessionsResponse,
  TextLayer,
  Thread,
  ThreadSummary,
  TutorSession,
} from "./types";

/** An error answered by the API (``detail``) or a network failure. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly retryable = false,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function errorFrom(response: Response): Promise<ApiError> {
  let message = `${response.status} ${response.statusText}`;
  let retryable = false;
  try {
    const data = (await response.json()) as { detail?: unknown; retryable?: unknown };
    if (typeof data.detail === "string") {
      message = data.detail;
    } else if (Array.isArray(data.detail)) {
      message = data.detail.map((item: { msg?: string }) => item.msg ?? "").join("; ");
    }
    retryable = Boolean(data.retryable);
  } catch {
    // Not JSON: keep the status line.
  }
  return new ApiError(message, response.status, retryable);
}

/** Sent with every call, so what the server writes for people comes in their language. */
export const LANGUAGE_HEADER = "X-PolyglotPDF-Language";

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin" };
  const headers: Record<string, string> = { [LANGUAGE_HEADER]: lang() };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  init.headers = headers;
  let response: Response;
  try {
    response = await fetch(path, init);
  } catch (error) {
    throw new ApiError(t("common.noConnection", { detail: String(error) }), 0, true);
  }
  if (!response.ok) throw await errorFrom(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function query(params: Record<string, string | number | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

const doc = (id: string) => `/api/documents/${encodeURIComponent(id)}`;

export const api = {
  info: () => request<AppInfo>("GET", "/api/info"),

  // Library
  documents: (q?: string, sort?: string) =>
    request<{ documents: DocumentSummary[] }>("GET", `/api/documents${query({ q, sort })}`),
  document: (id: string) => request<DocumentSummary>("GET", doc(id)),
  importFile: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<{ document: DocumentSummary; created: boolean }>("POST", "/api/documents", form);
  },
  updateDocument: (
    id: string,
    changes: Partial<{ title: string; authors: string; last_page: number; favorite: boolean; opened: boolean }>,
  ) => request<DocumentSummary>("PATCH", doc(id), changes),
  deleteDocument: (id: string) => request<void>("DELETE", doc(id)),
  deleteVersion: (id: string, version: string) =>
    request<void>("DELETE", `${doc(id)}/versions/${encodeURIComponent(version)}`),

  // Reader
  layout: (id: string, version?: string | null) =>
    request<Layout>("GET", `${doc(id)}/layout${query({ version })}`),
  textLayer: (id: string, page: number, version?: string | null) =>
    request<TextLayer>("GET", `${doc(id)}/pages/${page}/text${query({ version })}`),
  search: (id: string, q: string, version?: string | null) =>
    request<SearchResult>("GET", `${doc(id)}/search${query({ q, version })}`),
  context: (id: string, start: Anchor, end: Anchor | null, version?: string | null) =>
    request<ContextFull>("POST", `${doc(id)}/context`, { start, end, version_id: version ?? null }),

  // Engines, keys and preferences
  engines: () => request<EnginesResponse>("GET", "/api/engines"),
  setKey: (name: string, apiKey: string) =>
    request<Engine>("PUT", `/api/engines/${name}/key`, { api_key: apiKey }),
  deleteKey: (name: string) => request<Engine>("DELETE", `/api/engines/${name}/key`),
  checkEngine: (name: string, body: { api_key?: string; base_url?: string } = {}) =>
    request<CheckResult>("POST", `/api/engines/${name}/check`, body),
  models: (name: string) => request<{ models: string[] }>("GET", `/api/engines/${name}/models`),
  languages: () => request<{ languages: Language[] }>("GET", "/api/languages"),
  preferences: () => request<Preferences>("GET", "/api/preferences"),
  updatePreferences: (changes: Partial<Preferences>) =>
    request<Preferences>("PUT", "/api/preferences", changes),
  actions: () => request<{ actions: CompanionAction[] }>("GET", "/api/companion/actions"),

  // Jobs
  translate: (
    id: string,
    body: {
      engine: string;
      model?: string | null;
      source_lang: string;
      target_lang: string;
      pages?: string | null;
      translate_code?: boolean;
    },
  ) => request<Job>("POST", `${doc(id)}/translate`, body),
  estimate: (id: string, pages?: string | null) =>
    request<Job>("POST", `${doc(id)}/estimate`, { pages: pages || null }),
  jobs: (documentId?: string) =>
    request<{ jobs: Job[] }>("GET", `/api/jobs${query({ document_id: documentId })}`),
  job: (id: string) => request<Job>("GET", `/api/jobs/${id}`),
  cancelJob: (id: string) => request<Job>("POST", `/api/jobs/${id}/cancel`),

  // Reading companion
  threads: (documentId: string) =>
    request<{ threads: ThreadSummary[] }>("GET", `${doc(documentId)}/threads`),
  thread: (id: string) => request<Thread>("GET", `/api/threads/${id}`),
  threadContext: (id: string) =>
    request<{ before: string; current: string; after: string; selection: string }>(
      "GET",
      `/api/threads/${id}/context`,
    ),
  deleteThread: (id: string) => request<void>("DELETE", `/api/threads/${id}`),

  // Highlights, annotations and bookmarks
  highlightColors: () => request<{ colors: HighlightInk[] }>("GET", "/api/highlight-colors"),
  marks: (id: string, options: { page?: number; kind?: string; notebook?: string } = {}) =>
    request<{ marks: Mark[] }>("GET", `${doc(id)}/marks${query(options)}`),
  createMark: (
    id: string,
    body: {
      version_id?: string | null;
      kind?: "highlight" | "note";
      color?: HighlightColor;
      quote: string;
      note?: string | null;
      tags?: string[];
      start: Anchor;
      end: Anchor;
      section?: string[];
      source?: "reader" | "tutor";
      in_notebook?: boolean;
    },
  ) => request<Mark>("POST", `${doc(id)}/marks`, body),
  updateMark: (
    markId: string,
    changes: Partial<{
      color: HighlightColor;
      note: string;
      tags: string[];
      kind: string;
      in_notebook: boolean;
    }>,
  ) => request<Mark>("PATCH", `/api/marks/${markId}`, changes),
  deleteMark: (markId: string) => request<void>("DELETE", `/api/marks/${markId}`),
  bookmarks: (id: string) => request<{ bookmarks: Bookmark[] }>("GET", `${doc(id)}/bookmarks`),
  toggleBookmark: (id: string, page: number, label = "") =>
    request<{ page: number; marked: boolean; bookmarks: Bookmark[] }>(
      "POST",
      `${doc(id)}/bookmarks`,
      { page, label },
    ),

  // Notebook, cards and review
  notebook: (id: string) => request<Notebook>("GET", `${doc(id)}/notebook`),
  addReadingTime: (id: string, seconds: number) =>
    request<{ seconds: number }>("POST", `${doc(id)}/reading-time`, { seconds }),
  cards: (id: string, due = false) =>
    request<{ cards: Card[] }>("GET", `${doc(id)}/cards${query({ due: due ? "true" : "" })}`),
  createCard: (
    id: string,
    body: { front: string; back: string; quote?: string; page?: number; mark_id?: string | null; source?: string },
  ) => request<Card>("POST", `${doc(id)}/cards`, body),
  deleteCard: (cardId: string) => request<void>("DELETE", `/api/cards/${cardId}`),
  reviewQueue: (id: string) => request<ReviewQueue>("GET", `${doc(id)}/review`),
  reviewCard: (cardId: string, grade: Grade) =>
    request<Card>("POST", `/api/cards/${cardId}/review`, { grade }),

  // Tutor sessions and per-document settings
  sessions: (id: string, version?: string | null) =>
    request<SessionsResponse>("GET", `${doc(id)}/sessions${query({ version })}`),
  planSession: (id: string, number: number, version?: string | null, refresh = false) =>
    request<TutorSession>(
      "POST",
      `${doc(id)}/sessions/${number}/plan${query({ version, refresh: refresh ? "true" : "" })}`,
    ),
  startSession: (id: string, number: number) =>
    request<TutorSession>("POST", `${doc(id)}/sessions/${number}/start`),
  finishSession: (id: string, number: number) =>
    request<TutorSession>("POST", `${doc(id)}/sessions/${number}/finish`),
  answerQuestion: (id: string, number: number, index: number, answer: string, version?: string | null) =>
    request<{ index: number; answer: string; comment: string }>(
      "POST",
      `${doc(id)}/sessions/${number}/answer${query({ version })}`,
      { index, answer },
    ),
  sessionConcepts: (id: string, number: number, version?: string | null) =>
    request<ConceptMap>(
      "GET",
      `${doc(id)}/sessions/${number}/concepts${query({ version })}`,
    ),
  docSettings: (id: string) => request<DocSettings>("GET", `${doc(id)}/settings`),
  updateDocSettings: (id: string, changes: Partial<DocSettings>) =>
    request<DocSettings>("PUT", `${doc(id)}/settings`, changes),

  // Dictionary
  dictionary: (
    id: string,
    word: string,
    options: { page?: number; offset?: number; version?: string | null } = {},
  ) => request<DictionaryResult>("GET", `${doc(id)}/dictionary${query({ word, ...options })}`),
};

export const urls = {
  cover: (id: string) => `${doc(id)}/cover`,
  pageImage: (id: string, page: number, scale: number, version?: string | null) =>
    `${doc(id)}/pages/${page}/image${query({ scale, version })}`,
  file: (id: string, version?: string | null) => `${doc(id)}/file${query({ version })}`,
};
