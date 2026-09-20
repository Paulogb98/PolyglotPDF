import type { ReadingPrefs } from "../api/types";

const COLUMNS = { narrow: "48ch", book: "62ch", wide: "78ch" };

/** Paper, text size, column width and movement, applied to the document root. */
export function applyReading(prefs: ReadingPrefs): void {
  const root = document.documentElement;
  root.dataset.paper = prefs.paper;
  if (prefs.reduce_motion) root.dataset.motion = "off";
  else delete root.dataset.motion;
  root.style.setProperty("--bookfs", `${prefs.text_size}px`);
  root.style.setProperty("--bookcol", COLUMNS[prefs.column_width] ?? COLUMNS.book);
}

export function readStored<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw === null ? fallback : (JSON.parse(raw) as T);
  } catch {
    return fallback;
  }
}

export function writeStored(key: string, value: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Ignore: preferences of the interface are a convenience.
  }
}
