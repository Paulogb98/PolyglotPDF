import type { DocumentSummary } from "../api/types";

/** What the desktop window offers the page (``polyglotpdf.app.desktop.Bridge``). */
interface Bridge {
  choose_books(): Promise<string[]>;
  import_books(
    paths: string[],
  ): Promise<{ path: string; document?: DocumentSummary; created?: boolean; error?: string }[]>;
  save_text(suggested: string, text: string): Promise<string | null>;
  export_document(documentId: string, versionId: string | null): Promise<string | null>;
  reveal_data(): Promise<void>;
  platform(): Promise<{ desktop: boolean; os: string }>;
}

declare global {
  interface Window {
    pywebview?: { api: Bridge };
  }
}

let ready: Promise<Bridge | null> | null = null;

/** The bridge once the window has published it; ``null`` in a plain browser (development). */
export function bridge(): Promise<Bridge | null> {
  if (!ready) {
    ready = new Promise((resolve) => {
      if (window.pywebview?.api) return resolve(window.pywebview.api);
      const done = () => resolve(window.pywebview?.api ?? null);
      window.addEventListener("pywebviewready", done, { once: true });
      // A browser never fires the event: give up quickly and fall back to the web way.
      window.setTimeout(done, window.pywebview ? 3000 : 400);
    });
  }
  return ready;
}

export function isDesktop(): boolean {
  return Boolean(window.pywebview);
}

/** Save text where the reader chooses: a native dialog, or a download in a browser. */
export async function saveText(name: string, text: string, type: string): Promise<boolean> {
  const api = await bridge();
  if (api) return (await api.save_text(name, text)) !== null;
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 2000);
  return true;
}

/** Save a copy of the book (or one of its translations). */
export async function exportBook(documentId: string, versionId: string | null): Promise<boolean> {
  const api = await bridge();
  if (api) return (await api.export_document(documentId, versionId)) !== null;
  const query = versionId ? `?version=${encodeURIComponent(versionId)}` : "";
  const link = document.createElement("a");
  link.href = `/api/documents/${encodeURIComponent(documentId)}/file${query}`;
  link.download = "";
  link.click();
  return true;
}
