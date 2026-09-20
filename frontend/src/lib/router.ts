import { useSyncExternalStore } from "react";

export type SettingsTab = "leitura" | "ia" | "traducao" | "dados";

export type Route =
  | { name: "welcome"; empty: boolean }
  | { name: "library" }
  | { name: "settings"; tab: SettingsTab }
  | { name: "notebook"; id: string }
  | { name: "review"; id: string }
  | {
      name: "reader";
      id: string;
      version: string | null;
      page: number | null;
      mode: "tutor" | "read" | null;
    };

const TABS: SettingsTab[] = ["leitura", "ia", "traducao", "dados"];

/** "#/read/<id>?v=<version>&p=<page>" and friends. */
export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, "") || "/";
  const [path = "/", search = ""] = raw.split("?");
  const params = new URLSearchParams(search);
  const parts = path.split("/").filter(Boolean);
  if (parts[0] === "read" && parts[1]) {
    const page = Number(params.get("p"));
    const mode = params.get("mode");
    return {
      name: "reader",
      id: decodeURIComponent(parts[1]),
      version: params.get("v"),
      page: Number.isInteger(page) && page > 0 ? page - 1 : null,
      mode: mode === "tutor" || mode === "read" ? mode : null,
    };
  }
  if (parts[0] === "notebook" && parts[1]) {
    return { name: "notebook", id: decodeURIComponent(parts[1]) };
  }
  if (parts[0] === "review" && parts[1]) {
    return { name: "review", id: decodeURIComponent(parts[1]) };
  }
  if (parts[0] === "settings") {
    const tab = params.get("tab") as SettingsTab | null;
    return { name: "settings", tab: tab && TABS.includes(tab) ? tab : "ia" };
  }
  if (parts[0] === "welcome") return { name: "welcome", empty: params.get("empty") === "1" };
  return { name: "library" };
}

export const paths = {
  /** ``empty``: the reader asked for the library and it has no books yet. */
  welcome: (empty = false) => (empty ? "#/welcome?empty=1" : "#/welcome"),
  library: () => "#/",
  settings: (tab: SettingsTab = "ia") => (tab === "ia" ? "#/settings" : `#/settings?tab=${tab}`),
  notebook: (id: string) => `#/notebook/${encodeURIComponent(id)}`,
  review: (id: string) => `#/review/${encodeURIComponent(id)}`,
  reader: (
    id: string,
    options: {
      version?: string | null;
      page?: number | null;
      mode?: "tutor" | "read" | null;
    } = {},
  ) => {
    const params = new URLSearchParams();
    if (options.version) params.set("v", options.version);
    if (options.page !== null && options.page !== undefined) {
      params.set("p", String(options.page + 1));
    }
    if (options.mode) params.set("mode", options.mode);
    const search = params.toString();
    return `#/read/${encodeURIComponent(id)}${search ? `?${search}` : ""}`;
  },
};

export function navigate(path: string, { replace = false } = {}): void {
  if (replace) {
    history.replaceState(null, "", path);
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  } else {
    window.location.hash = path.replace(/^#/, "");
  }
}

function subscribe(callback: () => void): () => void {
  window.addEventListener("hashchange", callback);
  return () => window.removeEventListener("hashchange", callback);
}

export function useHash(): string {
  return useSyncExternalStore(subscribe, () => window.location.hash);
}
