import { api } from "../../api/client";
import type { DocumentSummary } from "../../api/types";

const STOPWORDS = new Set([
  "onde", "quando", "como", "porque", "por", "que", "qual", "quais", "quem", "sobre", "para",
  "com", "sem", "uma", "uns", "umas", "dos", "das", "nos", "nas", "ele", "ela", "isso", "esse",
  "essa", "aqui", "fala", "diz", "the", "what", "where", "which", "does", "about",
]);

export interface Found {
  document: DocumentSummary;
  page: number;
  score: number;
}

/** Words worth searching for: the long ones, most specific first. */
export function keywords(question: string): string[] {
  return [...new Set(question.toLowerCase().match(/\p{L}{4,}/gu) ?? [])]
    .filter((word) => !STOPWORDS.has(word))
    .sort((a, b) => b.length - a.length)
    .slice(0, 4);
}

/** Look for the question's words in every book, and keep the page that holds most of them. */
export async function findPassage(
  documents: DocumentSummary[],
  question: string,
): Promise<Found | null> {
  const words = keywords(question);
  if (!words.length) return null;
  let best: Found | null = null;
  for (const document of documents.slice(0, 12)) {
    const perPage = new Map<number, number>();
    for (const word of words) {
      const result = await api
        .search(document.id, word, document.versions[0]?.id ?? null)
        .catch(() => null);
      for (const hit of result?.hits ?? []) {
        perPage.set(hit.page, (perPage.get(hit.page) ?? 0) + Math.min(hit.rects.length, 3));
      }
    }
    for (const [page, score] of perPage) {
      if (!best || score > best.score) best = { document, page, score };
    }
  }
  return best;
}

