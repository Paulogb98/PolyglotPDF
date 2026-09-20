import {
  BookOpen,
  Check,
  ChevronDown,
  ChevronLeft,
  CircleAlert,
  Database,
  Eye,
  EyeOff,
  FolderOpen,
  Languages,
  Lock,
  Sparkles,
} from "lucide-react";
import { useCallback, useEffect, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { AppInfo, Engine, Language, ReadingPrefs } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { Segmented, Spinner, Switch } from "../../components/ui";
import { bridge, isDesktop } from "../../lib/desktop";
import { languageDisplay } from "../../lib/format";
import { navigate, paths, type SettingsTab } from "../../lib/router";
import { usePreferences } from "./PreferencesContext";
import { lang, resolveLang, t, type Key, type LangSetting } from "../../i18n";

const NAV: { value: SettingsTab; label: Key; icon: ReactNode }[] = [
  { value: "reading", label: "settings.nav.reading", icon: <BookOpen size={17} /> },
  { value: "ai", label: "settings.nav.ai", icon: <Sparkles size={17} /> },
  { value: "translation", label: "settings.nav.translation", icon: <Languages size={17} /> },
  { value: "data", label: "settings.nav.data", icon: <Database size={17} /> },
];

const PAPERS: { value: ReadingPrefs["paper"]; label: Key; color: string }[] = [
  { value: "cream", label: "settings.paper.cream", color: "#fdf9f1" },
  { value: "white", label: "settings.paper.white", color: "#fffdf8" },
  { value: "sepia", label: "settings.paper.sepia", color: "#f6ead4" },
  { value: "night", label: "settings.paper.night", color: "#23211e" },
];

/** Each language is named in itself, so whoever cannot read the current one still finds theirs. */
const APP_LANGUAGES: { value: LangSetting; label: string | null }[] = [
  { value: "auto", label: null },
  { value: "pt-BR", label: "Português (Brasil)" },
  { value: "en", label: "English" },
];

/** Ajustes (1j): state before fields, and where the key is kept. */
export function SettingsView({ tab }: { tab: SettingsTab }) {
  const [engines, setEngines] = useState<Engine[]>([]);
  const [companionEngine, setCompanionEngine] = useState<string | null>(null);
  const [languages, setLanguages] = useState<Language[]>([]);
  const [info, setInfo] = useState<AppInfo | null>(null);

  const loadEngines = useCallback(async () => {
    const result = await api.engines().catch(() => null);
    if (result) {
      setEngines(result.engines);
      setCompanionEngine(result.companion_engine);
    }
  }, []);

  useEffect(() => {
    void loadEngines();
    void api.languages().then((result) => setLanguages(result.languages)).catch(() => undefined);
    void api.info().then(setInfo).catch(() => undefined);
  }, [loadEngines]);

  return (
    <div className="screen">
      <div className="ground" />
      <div className="settings">
        <nav className="settings-nav" aria-label={t("settings.sections")}>
          <div className="head">
            <a className="icon-btn glass" href={paths.library()} aria-label={t("common.back")}>
              <ChevronLeft size={17} strokeWidth={2.5} />
            </a>
            <h1 className="display-m">{t("settings.title")}</h1>
          </div>
          {NAV.map((item) => (
            <button
              key={item.value}
              type="button"
              className="item"
              aria-current={tab === item.value}
              onClick={() => navigate(paths.settings(item.value), { replace: true })}
            >
              {item.icon}
              {t(item.label)}
            </button>
          ))}
          <div className="note-box">
            <div className="t">
              <Lock size={13} /> {t("settings.keyWhere")}
            </div>
            {info
              ? t("settings.keyWhereBody", { store: info.secret_store })
              : t("settings.keyWhereDefault")}
          </div>
        </nav>

        <main className="settings-main">
          {tab === "reading" ? <ReadingTab /> : null}
          {tab === "ai" ? (
            <AiTab
              engines={engines}
              companionEngine={companionEngine}
              languages={languages}
              onChanged={loadEngines}
            />
          ) : null}
          {tab === "translation" ? <TranslationTab engines={engines} languages={languages} /> : null}
          {tab === "data" ? <DataTab info={info} /> : null}
        </main>
      </div>
    </div>
  );
}

function Row({ name, about, children }: { name: string; about?: string; children: ReactNode }) {
  return (
    <div className="pref-row">
      <div className="text">
        <div className="label">{name}</div>
        {about ? <div className="hint">{about}</div> : null}
      </div>
      {children}
    </div>
  );
}

// ---------------------------------------------------------------------- Leitura
function ReadingTab() {
  const { prefs, reading, colors, update, updateReading } = usePreferences();
  const chooseLanguage = (value: LangSetting) => {
    if (!prefs) return;
    const before = resolveLang(prefs.interface_language);
    const after = resolveLang(value);
    const changes: Parameters<typeof update>[0] = { interface_language: value };
    // Answers that followed the interface keep following it.
    if (after !== before && prefs.companion_language === before) changes.companion_language = after;
    void update(changes);
  };
  return (
    <>
      <h1 className="display-l">{t("settings.nav.reading")}</h1>
      <p className="intro">{t("settings.reading.intro")}</p>

      <section className="settings-section">
        <h2 className="display-s">{t("settings.language")}</h2>
        <Row name={t("settings.language.app")} about={t("settings.language.appAbout")}>
          <select
            className="select"
            style={{ width: 260 }}
            value={prefs?.interface_language ?? "auto"}
            aria-label={t("settings.language.app")}
            onChange={(event) => chooseLanguage(event.target.value as LangSetting)}
          >
            {APP_LANGUAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label ?? t("settings.language.auto")}
              </option>
            ))}
          </select>
        </Row>
      </section>

      <section className="settings-section">
        <h2 className="display-s">{t("settings.reading.paperText")}</h2>
        <Row name={t("settings.reading.paper")}>
          <div className="papers">
            {PAPERS.map((paper) => (
              <button
                key={paper.value}
                type="button"
                aria-pressed={reading.paper === paper.value}
                onClick={() => void updateReading({ paper: paper.value })}
              >
                <i style={{ background: paper.color }} />
                {t(paper.label)}
              </button>
            ))}
          </div>
        </Row>
        <Row name={t("settings.reading.textSize")} about={t("settings.reading.textSizeAbout")}>
          <span className="caption">A</span>
          <input
            className="slider"
            style={{ maxWidth: 220 }}
            type="range"
            min={13}
            max={17}
            step={0.5}
            value={reading.text_size}
            aria-label={t("settings.reading.textSize")}
            onChange={(event) => void updateReading({ text_size: Number(event.target.value) })}
          />
          <span style={{ fontSize: 17 }}>A</span>
          <span className="caption" style={{ width: 32, textAlign: "right" }}>
            {reading.text_size.toLocaleString(lang())}
          </span>
        </Row>
        <Row name={t("settings.reading.width")}>
          <Segmented
            variant="on-paper sm"
            value={reading.column_width}
            onChange={(value) => void updateReading({ column_width: value })}
            options={[
              { value: "narrow", label: t("settings.reading.width.narrow") },
              { value: "book", label: t("settings.reading.width.book") },
              { value: "wide", label: t("settings.reading.width.wide") },
            ]}
          />
        </Row>
      </section>

      <section className="settings-section">
        <h2 className="display-s">{t("settings.reading.motion")}</h2>
        <Row name={t("settings.reading.animation")} about={t("settings.reading.animationAbout")}>
          <Switch
            label={t("settings.reading.animationLabel")}
            checked={reading.page_animation}
            onChange={(value) => void updateReading({ page_animation: value })}
          />
        </Row>
        <Row name={t("settings.reading.reduce")} about={t("settings.reading.reduceAbout")}>
          <Switch
            label={t("settings.reading.reduce")}
            checked={reading.reduce_motion}
            onChange={(value) => void updateReading({ reduce_motion: value })}
          />
        </Row>
        <Row name={t("settings.reading.advance")} about={t("settings.reading.advanceAbout")}>
          <Segmented
            variant="on-paper sm"
            value={reading.advance}
            onChange={(value) => void updateReading({ advance: value })}
            options={[
              { value: "pages", label: t("settings.reading.advance.pages") },
              { value: "scroll", label: t("settings.reading.advance.scroll") },
            ]}
          />
        </Row>
      </section>

      <section className="settings-section">
        <h2 className="display-s">{t("settings.reading.highlight")}</h2>
        <Row name={t("settings.reading.defaultInk")}>
          <div className="swatches">
            {colors.map((color) => (
              <button
                key={color.name}
                type="button"
                aria-label={t(`color.${color.name}` as Key)}
                aria-pressed={reading.highlight_color === color.name}
                style={{ background: color.ink }}
                onClick={() => void updateReading({ highlight_color: color.name })}
              />
            ))}
          </div>
        </Row>
        <Row name={t("settings.reading.save")} about={t("settings.reading.saveAbout")}>
          <Switch
            label={t("settings.reading.save")}
            checked={reading.save_to_notebook}
            onChange={(value) => void updateReading({ save_to_notebook: value })}
          />
        </Row>
        <Row name={t("settings.reading.card")}>
          <Switch
            label={t("settings.reading.cardLabel")}
            checked={reading.card_on_highlight}
            onChange={(value) => void updateReading({ card_on_highlight: value })}
          />
        </Row>
        <Row name={t("settings.reading.explain")}>
          <Switch
            label={t("settings.reading.explainLabel")}
            checked={reading.explain_on_highlight}
            onChange={(value) => void updateReading({ explain_on_highlight: value })}
          />
        </Row>
      </section>

      <section className="settings-section">
        <h2 className="display-s">{t("settings.reading.shortcuts")}</h2>
        {[
          ["← →", t("settings.shortcut.turn")],
          ["/", t("settings.shortcut.search")],
          ["b", t("settings.shortcut.bookmark")],
          ["Ctrl ↑", t("settings.shortcut.sheet")],
          ["Ctrl + − 0", t("settings.shortcut.zoom")],
          ["esc", t("settings.shortcut.close")],
          [t("settings.shortcut.reviewKeys"), t("settings.shortcut.review")],
        ].map(([keys, what]) => (
          <Row key={keys} name={what}>
            <kbd className="key">{keys}</kbd>
          </Row>
        ))}
      </section>
    </>
  );
}

// ---------------------------------------------------------------------- IA e chaves
function AiTab({
  engines,
  companionEngine,
  languages,
  onChanged,
}: {
  engines: Engine[];
  companionEngine: string | null;
  languages: Language[];
  onChanged(): Promise<void>;
}) {
  const { prefs, reading, update, updateReading } = usePreferences();
  const [showAll, setShowAll] = useState(false);
  const ai = engines.filter((engine) => engine.kind === "ai" && engine.supports_chat);
  const shown = ai.filter(
    (engine) =>
      engine.key_source ||
      engine.name === "ollama" ||
      engine.name === companionEngine ||
      engine.name === "anthropic" ||
      engine.name === "openai",
  );
  const hidden = ai.filter((engine) => !shown.includes(engine));

  return (
    <>
      <h1 className="display-l">{t("settings.nav.ai")}</h1>
      <p className="intro">{t("settings.ai.intro")}</p>

      <section className="settings-section">
        {(showAll ? ai : shown).map((engine) => (
          <Provider
            key={engine.name}
            engine={engine}
            inUse={engine.name === companionEngine}
            onUse={() => void update({ companion_engine: engine.name }).then(onChanged)}
            onChanged={onChanged}
          />
        ))}
        {hidden.length && !showAll ? (
          <div className="provider-more">
            <span className="spacer">
              {hidden.map((engine) => engine.label.replace(/ \(.*\)$/, "")).join(", ")}
            </span>
            <button type="button" className="btn btn-link btn-sm" onClick={() => setShowAll(true)}>
              {t("settings.ai.showOthers", { n: hidden.length })}
              <ChevronDown size={14} />
            </button>
          </div>
        ) : null}
      </section>

      {prefs ? (
        <section className="settings-section">
          <h2 className="display-s">{t("settings.ai.answers")}</h2>
          <div className="pref-grid">
            <div className="pref">
              <span className="label">{t("settings.ai.context")}</span>
              <span className="hint">{t("settings.ai.contextAbout")}</span>
              <Segmented
                variant="on-paper sm"
                value={prefs.context_size}
                onChange={(value) => void update({ context_size: value })}
                options={[
                  { value: "short", label: t("settings.ai.context.short") },
                  { value: "medium", label: t("settings.ai.context.medium") },
                  { value: "long", label: t("settings.ai.context.long") },
                ]}
              />
            </div>
            <div className="pref">
              <span className="label">{t("settings.ai.language")}</span>
              <span className="hint">{t("settings.ai.languageAbout")}</span>
              <select
                className="select"
                value={prefs.companion_language}
                onChange={(event) => void update({ companion_language: event.target.value })}
              >
                {languages.map((language) => (
                  <option key={language.code} value={language.code}>
                    {languageDisplay(language.code, language.name)}
                  </option>
                ))}
              </select>
            </div>
            <div className="pref">
              <span className="label">{t("settings.ai.effort")}</span>
              <span className="hint">{t("settings.ai.effortAbout")}</span>
              <Segmented
                variant="on-paper sm"
                value={["low", "medium", "high"].includes(prefs.companion_effort) ? prefs.companion_effort : "high"}
                onChange={(value) => void update({ companion_effort: value })}
                options={[
                  { value: "low", label: t("settings.ai.effort.low") },
                  { value: "medium", label: t("settings.ai.effort.medium") },
                  { value: "high", label: t("settings.ai.effort.high") },
                ]}
              />
            </div>
          </div>
        </section>
      ) : null}

      <section className="settings-section">
        <h2 className="display-s">{t("settings.ai.where")}</h2>
        <Row name={t("settings.ai.companion")} about={t("settings.ai.companionAbout")}>
          <Switch
            label={t("settings.ai.companionLabel")}
            checked={reading.companion_enabled}
            onChange={(value) => void updateReading({ companion_enabled: value })}
          />
        </Row>
        <Row name={t("settings.ai.tutor")} about={t("settings.ai.tutorAbout")}>
          <Switch
            label={t("settings.ai.tutorLabel")}
            checked={reading.tutor_enabled}
            onChange={(value) => void updateReading({ tutor_enabled: value })}
          />
        </Row>
        <Row name={t("settings.ai.onOpen")}>
          <Segmented
            variant="on-paper sm"
            value={reading.open_mode}
            onChange={(value) => void updateReading({ open_mode: value })}
            options={[
              { value: "ask", label: t("settings.ai.onOpen.ask") },
              { value: "tutor", label: t("settings.ai.onOpen.tutor") },
              { value: "read", label: t("settings.ai.onOpen.read") },
              { value: "remember", label: t("settings.ai.onOpen.remember") },
            ]}
          />
        </Row>
      </section>
    </>
  );
}

/** One provider: its state first (key saved, in use, local), the field only when asked. */
function Provider({
  engine,
  inUse,
  onUse,
  onChanged,
}: {
  engine: Engine;
  inUse: boolean;
  onUse(): void;
  onChanged(): Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState("");
  const [visible, setVisible] = useState(false);
  const [busy, setBusy] = useState<"check" | "save" | null>(null);
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(null);
  const [local, setLocal] = useState<string[] | null>(null);
  const toast = useToast();
  const model = engine.model ?? engine.default_model;

  useEffect(() => {
    if (engine.name !== "ollama") return;
    void api
      .models("ollama")
      .then((result) => setLocal(result.models))
      .catch(() => setLocal([]));
  }, [engine.name]);

  const test = async () => {
    setBusy("check");
    setMessage(null);
    try {
      const result = await api.checkEngine(engine.name);
      setMessage({ ok: result.ok, text: result.message });
    } catch (error) {
      setMessage({ ok: false, text: errorMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  const save = async () => {
    const key = value.trim();
    if (!key) return;
    setBusy("save");
    setMessage(null);
    try {
      const result = await api.checkEngine(engine.name, { api_key: key });
      if (!result.ok) {
        setMessage({ ok: false, text: result.message });
        return;
      }
      await api.setKey(engine.name, key);
      setValue("");
      setEditing(false);
      await onChanged();
      toast({ kind: "success", title: t("settings.provider.connected", { engine: engine.label }) });
    } catch (error) {
      setMessage({ ok: false, text: errorMessage(error) });
    } finally {
      setBusy(null);
    }
  };

  const remove = async () => {
    await api.deleteKey(engine.name).catch(() => undefined);
    await onChanged();
  };

  const isLocal = engine.name === "ollama";
  const detail = isLocal
    ? local === null
      ? t("settings.provider.lookingOllama")
      : local.length
        ? t("settings.provider.detectedAt", {
            where: engine.base_url ?? engine.default_base_url ?? "127.0.0.1:11434",
            models: local.slice(0, 3).join(", "),
          })
        : t("settings.provider.ollamaMissing")
    : engine.key_source
      ? `${engine.key_hint ?? t("settings.provider.keySaved")}${model ? t("settings.provider.model", { model }) : ""}${
          engine.key_source === "env" ? t("settings.provider.fromEnv", { name: engine.key_env[0] ?? "" }) : ""
        }`
      : `${t("settings.provider.noKey")}${engine.key_env[0] ? t("settings.provider.alsoEnv", { name: engine.key_env[0] }) : ""}`;

  return (
    <div className={`provider ${editing ? "editing" : ""}`}>
      <div className="row" style={{ gap: 16 }}>
        <div className="text">
          <div className="name">
            {engine.label}
            {isLocal ? (
              <span className="chip tutor">{t("settings.provider.localNoKey")}</span>
            ) : engine.key_source ? (
              <span className="chip tutor">
                <Check size={11} strokeWidth={3} /> {t("settings.provider.keySaved")}
              </span>
            ) : null}
            {inUse ? <span className="chip action">{t("settings.provider.inUse")}</span> : null}
          </div>
          <div className="detail">{detail}</div>
        </div>
        {engine.key_source ? (
          <>
            <button type="button" className="btn btn-outline btn-sm" disabled={busy !== null} onClick={() => void test()}>
              {busy === "check" ? <Spinner /> : null}
              {t("settings.provider.test")}
            </button>
            {!inUse ? (
              <button type="button" className="btn btn-outline btn-sm" onClick={onUse}>
                {t("settings.provider.use")}
              </button>
            ) : null}
            {engine.key_source === "app" ? (
              <button type="button" className="btn btn-link btn-sm" onClick={() => setEditing((on) => !on)}>
                {t("settings.provider.change")}
              </button>
            ) : null}
          </>
        ) : isLocal ? (
          !inUse && local?.length ? (
            <button type="button" className="btn btn-outline btn-sm" onClick={onUse}>
              {t("settings.provider.use")}
            </button>
          ) : null
        ) : !editing ? (
          <button type="button" className="btn btn-action btn-sm" onClick={() => setEditing(true)}>
            {t("settings.provider.add")}
          </button>
        ) : null}
      </div>

      {editing ? (
        <>
          <div className="key-row">
            <input
              className="input"
              type={visible ? "text" : "password"}
              placeholder={engine.key_env[0] ?? t("settings.provider.keyPlaceholder")}
              value={value}
              autoFocus
              autoComplete="off"
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && void save()}
            />
            <button
              type="button"
              className="icon-btn"
              aria-label={visible ? t("settings.provider.hide") : t("settings.provider.show")}
              onClick={() => setVisible((on) => !on)}
            >
              {visible ? <EyeOff size={16} /> : <Eye size={16} />}
            </button>
            <button
              type="button"
              className="btn btn-action"
              disabled={!value.trim() || busy !== null}
              onClick={() => void save()}
            >
              {busy === "save" ? <Spinner /> : null}
              {t("settings.provider.validate")}
            </button>
          </div>
          <div className="row caption">
            <span className="spacer">
              {busy === "save"
                ? t("settings.provider.checking")
                : engine.description}
            </span>
            {engine.key_source === "app" ? (
              <button type="button" className="btn btn-link btn-xs" onClick={() => void remove()}>
                {t("settings.provider.remove")}
              </button>
            ) : null}
            <button type="button" className="btn btn-link btn-xs" onClick={() => setEditing(false)}>
              {t("common.cancel")}
            </button>
          </div>
        </>
      ) : null}

      {message ? (
        <div className="row caption" style={{ color: message.ok ? "var(--tutor-hover)" : "var(--action-ink)" }}>
          {message.ok ? <Check size={13} strokeWidth={3} /> : <CircleAlert size={13} />}
          {message.text}
        </div>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------- Translation
function TranslationTab({ engines, languages }: { engines: Engine[]; languages: Language[] }) {
  const { prefs, update } = usePreferences();
  if (!prefs) return <Spinner />;
  const usable = engines.filter((engine) => engine.kind !== "offline" || engine.name === "pseudo");
  return (
    <>
      <h1 className="display-l">{t("settings.nav.translation")}</h1>
      <p className="intro">{t("settings.translation.intro")}</p>
      <section className="settings-section">
        <h2 className="display-s">{t("settings.translation.engine")}</h2>
        <div className="engines">
          {usable.map((engine) => (
            <button
              key={engine.name}
              type="button"
              className="engine"
              aria-pressed={prefs.translation_engine === engine.name}
              onClick={() => void update({ translation_engine: engine.name })}
            >
              <span className="name">
                {engine.label}
                {engine.requires_key && !engine.ready ? (
                  <span className="chip outline upper">{t("translate.badge.noKey")}</span>
                ) : null}
              </span>
              <span className="about">{engine.description}</span>
            </button>
          ))}
        </div>
      </section>
      <section className="settings-section">
        <h2 className="display-s">{t("settings.translation.languages")}</h2>
        <Row name={t("settings.translation.source")} about={t("settings.translation.sourceAbout")}>
          <select
            className="select"
            style={{ width: 240 }}
            value={prefs.source_lang}
            onChange={(event) => void update({ source_lang: event.target.value })}
          >
            <option value="auto">{t("settings.translation.detect")}</option>
            {languages.map((language) => (
              <option key={language.code} value={language.code}>
                {languageDisplay(language.code, language.name)}
              </option>
            ))}
          </select>
        </Row>
        <Row name={t("settings.translation.target")}>
          <select
            className="select"
            style={{ width: 240 }}
            value={prefs.target_lang}
            onChange={(event) => void update({ target_lang: event.target.value })}
          >
            {languages.map((language) => (
              <option key={language.code} value={language.code}>
                {languageDisplay(language.code, language.name)}
              </option>
            ))}
          </select>
        </Row>
      </section>
    </>
  );
}

// ---------------------------------------------------------------------- Biblioteca e dados
function DataTab({ info }: { info: AppInfo | null }) {
  if (!info) return <Spinner />;
  return (
    <>
      <h1 className="display-l">{t("settings.nav.data")}</h1>
      <p className="intro">{t("settings.data.intro")}</p>
      <section className="settings-section">
        <Row name={t("settings.data.folder")} about={info.data_dir}>
          {isDesktop() ? (
            <button
              type="button"
              className="btn btn-outline btn-sm"
              onClick={() => void bridge().then((api_) => api_?.reveal_data())}
            >
              <FolderOpen size={15} />
              {t("settings.data.openFolder")}
            </button>
          ) : null}
        </Row>
        <Row name={t("settings.data.formats")} about={info.formats.join(" · ")}>
          <span />
        </Row>
        <Row name={t("settings.data.keys")} about={info.secret_store}>
          <Lock size={16} className="muted" />
        </Row>
        <Row name={t("settings.data.version")} about={`PolyglotPDF ${info.version}`}>
          <span />
        </Row>
      </section>
    </>
  );
}
