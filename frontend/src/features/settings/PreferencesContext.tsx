import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { api } from "../../api/client";
import type { HighlightInk, Preferences, ReadingPrefs } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { applyReading } from "../../lib/theme";
import { t } from "../../i18n";

export const DEFAULT_READING: ReadingPrefs = {
  text_size: 14.5,
  column_width: "book",
  paper: "cream",
  page_animation: true,
  reduce_motion: false,
  advance: "pages",
  highlight_color: "yellow",
  save_to_notebook: true,
  card_on_highlight: false,
  explain_on_highlight: false,
  open_mode: "ask",
  companion_enabled: true,
  tutor_enabled: true,
};

export const DEFAULT_COLORS: HighlightInk[] = [
  { name: "yellow", ink: "#e8c35a", line: "rgb(168 128 24 / .6)" },
  { name: "green", ink: "#a9c07b", line: "rgb(106 130 66 / .6)" },
  { name: "coral", ink: "#e0937a", line: "rgb(178 98 45 / .6)" },
  { name: "blue", ink: "#9db6c4", line: "rgb(93 130 150 / .6)" },
];

interface PreferencesValue {
  prefs: Preferences | null;
  reading: ReadingPrefs;
  colors: HighlightInk[];
  ink(color: string): HighlightInk;
  ready: boolean;
  update(changes: Partial<Preferences>): Promise<void>;
  updateReading(changes: Partial<ReadingPrefs>): Promise<void>;
  reload(): Promise<void>;
}

const Context = createContext<PreferencesValue | null>(null);

export function PreferencesProvider({ children }: { children: ReactNode }) {
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [colors, setColors] = useState<HighlightInk[]>(DEFAULT_COLORS);
  const toast = useToast();

  const reload = useCallback(async () => {
    const loaded = await api.preferences();
    setPrefs(loaded);
    applyReading(loaded.reading ?? DEFAULT_READING);
  }, []);

  useEffect(() => {
    void reload().catch(() => undefined);
    void api
      .highlightColors()
      .then((result) => setColors(result.colors.length ? result.colors : DEFAULT_COLORS))
      .catch(() => undefined);
  }, [reload]);

  const update = useCallback(
    async (changes: Partial<Preferences>) => {
      try {
        const saved = await api.updatePreferences(changes);
        setPrefs(saved);
        applyReading(saved.reading ?? DEFAULT_READING);
      } catch (error) {
        toast({ kind: "error", title: t("common.saveFailed"), body: errorMessage(error) });
      }
    },
    [toast],
  );

  const updateReading = useCallback(
    async (changes: Partial<ReadingPrefs>) => {
      // Apply at once so the page reacts under the reader's hand, then save.
      setPrefs((current) => {
        if (!current) return current;
        const reading = { ...current.reading, ...changes };
        applyReading(reading);
        return { ...current, reading };
      });
      await update({ reading: changes } as Partial<Preferences>);
    },
    [update],
  );

  const reading = prefs?.reading ?? DEFAULT_READING;
  const ink = useCallback(
    (color: string) => colors.find((item) => item.name === color) ?? colors[0] ?? DEFAULT_COLORS[0],
    [colors],
  );

  const value = useMemo(
    () => ({ prefs, reading, colors, ink, ready: prefs !== null, update, updateReading, reload }),
    [prefs, reading, colors, ink, update, updateReading, reload],
  );
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

export function usePreferences(): PreferencesValue {
  const value = useContext(Context);
  if (!value) throw new Error("usePreferences must be used inside <PreferencesProvider>");
  return value;
}
