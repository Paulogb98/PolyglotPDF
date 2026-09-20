import type { Language } from "../api/types";
import { lang, t } from "../i18n";

export function formatNumber(value: number): string {
  return value.toLocaleString(lang());
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toLocaleString(lang(), { maximumFractionDigits: unit ? 1 : 0 })} ${units[unit]}`;
}

export function relativeTime(iso: string, now = Date.now()): string {
  const seconds = Math.round((new Date(iso).getTime() - now) / 1000);
  const format = new Intl.RelativeTimeFormat(lang(), { numeric: "auto" });
  const steps: [Intl.RelativeTimeFormatUnit, number][] = [
    ["year", 31_536_000],
    ["month", 2_592_000],
    ["week", 604_800],
    ["day", 86_400],
    ["hour", 3_600],
    ["minute", 60],
  ];
  for (const [unit, size] of steps) {
    if (Math.abs(seconds) >= size) return format.format(Math.round(seconds / size), unit);
  }
  return format.format(0, "minute");
}

export function percent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

export function languageName(code: string, languages: Language[]): string {
  if (code === "auto") return t("format.detectAuto");
  return languages.find((language) => language.code === code)?.name ?? code;
}

/** Unicode code points in ``text`` (the API counts offsets in code points). */
export function codePoints(text: string): number {
  let count = 0;
  for (const _ of text) count += 1;
  return count;
}

const ENDONYMS: Record<string, string> = {
  pt: "Português",
  "pt-BR": "Português",
  "pt-PT": "Português",
  es: "Español",
  en: "English",
  fr: "Français",
  de: "Deutsch",
  it: "Italiano",
  nl: "Nederlands",
  la: "Latina",
  ru: "Русский",
  el: "Ελληνικά",
  ar: "العربية",
  he: "עברית",
  ja: "日本語",
  ko: "한국어",
  zh: "中文",
  "zh-CN": "中文",
};

const namesByLocale = new Map<string, Intl.DisplayNames | null>();

/** The language's name in the interface's language, via the platform's own table. */
function displayName(code: string): string | null {
  const locale = lang();
  if (!namesByLocale.has(locale)) {
    try {
      namesByLocale.set(locale, new Intl.DisplayNames([locale], { type: "language" }));
    } catch {
      namesByLocale.set(locale, null);
    }
  }
  try {
    const name = namesByLocale.get(locale)?.of(code);
    return name && name !== code ? name : null;
  } catch {
    return null;
  }
}

/** "alemão" / "German" — the language's name as it runs in a sentence of the interface:
 *  Portuguese writes language names in lower case, English capitalises them. */
export function languageLabel(code: string | null | undefined): string {
  if (!code) return "";
  const base = code.split("-")[0] ?? code;
  const name = displayName(code.startsWith("zh") ? code : base);
  if (!name) return code;
  return lang() === "pt-BR" ? name.toLowerCase() : name;
}

/** "Deutsch", "Português" — the language's name in itself, for the running heads. */
export function endonym(code: string | null | undefined): string {
  if (!code) return "";
  return ENDONYMS[code] ?? ENDONYMS[code.split("-")[0] ?? ""] ?? code.toUpperCase();
}

/** "Português (Brasil)", "German" — a language list in the interface's own language. */
export function languageDisplay(code: string, fallback: string): string {
  const name = displayName(code);
  if (!name) return fallback;
  return name.charAt(0).toUpperCase() + name.slice(1);
}
