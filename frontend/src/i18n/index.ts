/**
 * The interface's two languages. Every text on screen is a key of ``pt.ts``; ``en.ts`` must
 * have the same keys (the compiler holds it to that). ``t()`` reads the current language,
 * set once from the preferences; the app remounts when it changes, so nothing keeps an
 * old text on screen.
 */

import { en } from "./en";
import { pt, type Messages } from "./pt";

export type Lang = "pt-BR" | "en";
/** What the reader chose: a language, or "auto" for the system's. */
export type LangSetting = "auto" | Lang;
export type Key = keyof Messages;
/** Keys that come in ``.one`` / ``.other`` pairs, for ``tn``. */
export type PluralKey = { [K in Key]: K extends `${infer Base}.one` ? Base : never }[Key];

export const LANGS: Lang[] = ["pt-BR", "en"];
const TABLES: Record<Lang, Messages> = { "pt-BR": pt, en };
const STORAGE = "polyglotpdf.lang";

/** The system's language: Portuguese if it is any Portuguese, English otherwise. */
export function systemLang(): Lang {
  const wanted = (typeof navigator !== "undefined" && navigator.language) || "";
  return wanted.toLowerCase().startsWith("pt") ? "pt-BR" : "en";
}

export function resolveLang(setting: string | null | undefined): Lang {
  return setting === "pt-BR" || setting === "en" ? setting : systemLang();
}

function initial(): Lang {
  // The last language used, so the first paint (before the preferences arrive) is right.
  try {
    const stored = localStorage.getItem(STORAGE);
    if (stored === "pt-BR" || stored === "en") return stored;
  } catch {
    // Private or blocked storage: the system's language will do.
  }
  return systemLang();
}

let current: Lang = initial();

export function lang(): Lang {
  return current;
}

export function setLang(next: Lang): void {
  current = next;
  if (typeof document !== "undefined") document.documentElement.lang = next;
  try {
    localStorage.setItem(STORAGE, next);
  } catch {
    // Nothing to remember it in: the preferences still hold it.
  }
}

/** The text for ``key`` in the current language, with ``{name}`` placeholders filled. */
export function t(key: Key, vars?: Record<string, string | number>): string {
  const text = TABLES[current][key] ?? pt[key] ?? key;
  if (!vars) return text;
  return text.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole,
  );
}

/** "1 cartão" / "3 cartões": ``key.one`` or ``key.other``, with ``{n}`` the formatted count. */
export function tn(key: PluralKey, count: number, vars?: Record<string, string | number>): string {
  const form = (count === 1 ? `${key}.one` : `${key}.other`) as Key;
  return t(form, { n: count.toLocaleString(current), ...vars });
}
