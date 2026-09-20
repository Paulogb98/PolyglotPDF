import { Fragment, useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "./api/client";
import { ToastProvider } from "./components/Toasts";
import { JobsProvider } from "./features/jobs/JobsContext";
import { LibraryView } from "./features/library/LibraryView";
import { WelcomeView } from "./features/library/WelcomeView";
import { NotebookView } from "./features/notebook/NotebookView";
import { ReaderView } from "./features/reader/ReaderView";
import { ReviewView } from "./features/review/ReviewView";
import { PreferencesProvider, usePreferences } from "./features/settings/PreferencesContext";
import { SettingsView } from "./features/settings/SettingsView";
import { lang, resolveLang, setLang } from "./i18n";
import { navigate, parseHash, paths, useHash } from "./lib/router";

/** The library is the home; an empty one sends the reader back to the first-run screen,
 *  which then says why instead of just bouncing. */
function useFirstRun(active: boolean): void {
  const [checked, setChecked] = useState(false);
  useEffect(() => {
    if (!active || checked) return;
    let cancelled = false;
    void api
      .documents()
      .then((result) => {
        if (!cancelled && result.documents.length === 0) {
          navigate(paths.welcome(true), { replace: true });
        }
      })
      .catch(() => undefined)
      .finally(() => !cancelled && setChecked(true));
    return () => {
      cancelled = true;
    };
  }, [active, checked]);
}

function Routes() {
  const hash = useHash();
  const route = useMemo(() => parseHash(hash), [hash]);
  useFirstRun(route.name === "library");

  switch (route.name) {
    case "welcome":
      return <WelcomeView emptyLibrary={route.empty} />;
    case "settings":
      return <SettingsView tab={route.tab} />;
    case "notebook":
      return <NotebookView key={route.id} id={route.id} />;
    case "review":
      return <ReviewView key={route.id} id={route.id} />;
    case "reader":
      return (
        <ReaderView
          key={route.id}
          id={route.id}
          version={route.version}
          initialPage={route.page}
          mode={route.mode}
        />
      );
    default:
      return <LibraryView />;
  }
}

/** The interface speaks the language the reader chose ("auto": the system's). Changing it
 *  remounts the screens, so no text is left over from the other language. */
function Localized({ children }: { children: ReactNode }) {
  const { prefs } = usePreferences();
  const wanted = resolveLang(prefs?.interface_language);
  if (prefs && wanted !== lang()) setLang(wanted);
  return <Fragment key={lang()}>{children}</Fragment>;
}

export function App() {
  return (
    <ToastProvider>
      <PreferencesProvider>
        <Localized>
          <JobsProvider>
            <div className="app">
              <Routes />
            </div>
          </JobsProvider>
        </Localized>
      </PreferencesProvider>
    </ToastProvider>
  );
}
