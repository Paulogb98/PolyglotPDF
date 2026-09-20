import { ArrowRight, KeyRound, Languages } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { DocumentSummary, Engine, Estimate, Job, Language } from "../../api/types";
import { errorMessage, useToast } from "../../components/Toasts";
import { Dialog, Segmented, Spinner } from "../../components/ui";
import { formatNumber, languageDisplay, languageLabel } from "../../lib/format";
import { navigate, paths } from "../../lib/router";
import { lang, t, tn, type Key } from "../../i18n";
import { useJobs } from "../jobs/JobsContext";
import { usePreferences } from "../settings/PreferencesContext";

const AI_ORDER = ["anthropic", "openai", "gemini", "deepseek", "mistral", "xai", "qwen", "openrouter"];
const ABOUT: Record<string, Key> = {
  google: "translate.about.google",
  deepl: "translate.about.deepl",
  ollama: "translate.about.ollama",
  pseudo: "translate.about.pseudo",
};

function thousands(value: number): string {
  // "198 mil", "198K": big counts read better compact, in the interface's own way.
  return value >= 10_000
    ? new Intl.NumberFormat(lang(), { notation: "compact", maximumFractionDigits: 0 }).format(value)
    : formatNumber(value);
}

/** Translate (1g): the engine as a choice of quality and cost, not a form field. */
export function TranslateDialog({
  document: item,
  onClose,
  onStarted,
}: {
  document: DocumentSummary;
  onClose(): void;
  onStarted?(job: Job): void;
}) {
  const { prefs, update } = usePreferences();
  const { track } = useJobs();
  const toast = useToast();
  const [engines, setEngines] = useState<Engine[]>([]);
  const [languages, setLanguages] = useState<Language[]>([]);
  const [source, setSource] = useState<string | null>(null);
  const [target, setTarget] = useState(prefs?.target_lang ?? "pt-BR");
  const [engine, setEngine] = useState<string | null>(null);
  const [range, setRange] = useState<"all" | "some">("all");
  const [pages, setPages] = useState("");
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [starting, setStarting] = useState(false);

  useEffect(() => {
    void api.engines().then((result) => setEngines(result.engines)).catch(() => undefined);
    void api.languages().then((result) => setLanguages(result.languages)).catch(() => undefined);
    void api.layout(item.id).then((layout) => setSource(layout.language)).catch(() => undefined);
  }, [item.id]);

  // How much text the book holds, measured once in the background.
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const poll = async (jobId: string) => {
      for (let attempt = 0; attempt < 150 && !cancelled; attempt += 1) {
        const job = await api.job(jobId).catch(() => null);
        if (!job) return;
        if (job.status === "done") {
          if (!cancelled) setEstimate(job.result as unknown as Estimate);
          return;
        }
        if (job.status !== "queued" && job.status !== "running") return;
        await new Promise((resolve) => {
          timer = window.setTimeout(resolve, 400);
        });
      }
    };
    void api
      .estimate(item.id, null)
      .then((job) => poll(job.id))
      .catch(() => undefined);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [item.id]);

  /** Four engines in sight — the AI you have a key for, Google, DeepL, Ollama — the rest below. */
  const featured = useMemo(() => {
    const byName = new Map(engines.map((candidate) => [candidate.name, candidate]));
    const companion = prefs?.companion_engine ?? "";
    const ai =
      AI_ORDER.map((name) => byName.get(name)).find((candidate) => candidate?.ready) ??
      (AI_ORDER.includes(companion) ? byName.get(companion) : undefined) ??
      byName.get("anthropic");
    return [ai, byName.get("google"), byName.get("deepl"), byName.get("ollama")].filter(
      (candidate): candidate is Engine => Boolean(candidate),
    );
  }, [engines, prefs?.companion_engine]);
  const others = engines.filter(
    (candidate) =>
      !featured.includes(candidate) && (candidate.kind !== "offline" || candidate.name === "pseudo"),
  );

  useEffect(() => {
    if (engine || !engines.length) return;
    const preferred = engines.find((candidate) => candidate.name === prefs?.translation_engine);
    setEngine((preferred ?? featured[0])?.name ?? null);
  }, [engines, engine, featured, prefs?.translation_engine]);

  const chosen = engines.find((candidate) => candidate.name === engine) ?? null;
  const blocked = Boolean(chosen?.requires_key && !chosen.ready);

  const start = useCallback(async () => {
    if (!chosen) return;
    setStarting(true);
    try {
      const job = await api.translate(item.id, {
        engine: chosen.name,
        source_lang: source ?? prefs?.source_lang ?? "auto",
        target_lang: target,
        pages: range === "some" ? pages.trim() || null : null,
        translate_code: false,
      });
      track(job);
      void update({ translation_engine: chosen.name, target_lang: target });
      onStarted?.(job);
      onClose();
    } catch (error) {
      toast({ kind: "error", title: t("translate.startFailed"), body: errorMessage(error) });
    } finally {
      setStarting(false);
    }
  }, [chosen, item.id, source, prefs, target, range, pages, track, update, onStarted, onClose, toast]);

  const describe = (candidate: Engine) => {
    if (ABOUT[candidate.name]) return t(ABOUT[candidate.name]);
    const model = candidate.model ?? candidate.default_model;
    return `${t("translate.about.ai")}${model ? ` ${model}.` : ""}`;
  };
  const badge = (candidate: Engine) => {
    if (candidate.name === "google") return <span className="chip tutor upper">{t("translate.badge.free")}</span>;
    if (candidate.name === "ollama") return <span className="chip upper">{t("translate.badge.local")}</span>;
    if (candidate.requires_key) {
      return candidate.ready ? (
        <span className="chip action upper">{t("translate.badge.yourKey")}</span>
      ) : (
        <span className="chip outline upper">{t("translate.badge.noKey")}</span>
      );
    }
    return null;
  };

  return (
    <Dialog onClose={onClose} label={t("translate.label")}>
      <div className="stack-2" style={{ paddingRight: 40 }}>
        <span className="kicker action">{t("translate.kicker")}</span>
        <h2 className="display-m">{item.title}</h2>
        <p className="small muted">
          {tn("common.pages", item.pages)}
          {source ? ` · ${t("translate.detectedIn", { language: languageLabel(source) })}` : ""} ·{" "}
          {t("translate.keepsLayout")}
        </p>
      </div>

      <div className="engines">
        {featured.map((candidate) => (
          <button
            key={candidate.name}
            type="button"
            className="engine"
            aria-pressed={candidate.name === engine}
            onClick={() => setEngine(candidate.name)}
          >
            <span className="name">
              {candidate.name === "google" ? "Google" : candidate.label.replace("Anthropic ", "")}
              {badge(candidate)}
            </span>
            <span className="about">{describe(candidate)}</span>
          </button>
        ))}
        {featured.length === 0 ? <Spinner /> : null}
      </div>
      {others.length ? (
        <select
          className="select"
          value={featured.some((candidate) => candidate.name === engine) ? "" : (engine ?? "")}
          onChange={(event) => event.target.value && setEngine(event.target.value)}
        >
          <option value="">{t("translate.otherEngine")}</option>
          {others.map((candidate) => (
            <option key={candidate.name} value={candidate.name}>
              {candidate.label}
              {candidate.requires_key && !candidate.ready ? t("translate.noKeySuffix") : ""}
            </option>
          ))}
        </select>
      ) : null}

      <div className="lang-route">
        <div className="from">
          <span>{source ? languageLabel(source).replace(/^./, (c) => c.toUpperCase()) : t("translate.detect")}</span>
          <span className="caption">{source ? t("translate.detected") : t("translate.automatic")}</span>
        </div>
        <ArrowRight size={18} strokeWidth={2.5} />
        <select className="select" value={target} onChange={(event) => setTarget(event.target.value)}>
          {languages.map((language) => (
            <option key={language.code} value={language.code}>
              {languageDisplay(language.code, language.name)}
            </option>
          ))}
        </select>
      </div>

      <div className="row">
        <Segmented
          variant="on-paper sm"
          value={range}
          onChange={setRange}
          options={[
            { value: "all", label: t("translate.allPages", { n: item.pages }) },
            { value: "some", label: t("translate.somePages") },
          ]}
        />
        {range === "some" ? (
          <input
            className="input"
            style={{ width: 150, height: 36 }}
            placeholder={t("translate.pagesExample")}
            value={pages}
            autoFocus
            onChange={(event) => setPages(event.target.value)}
          />
        ) : null}
        <span className="caption spacer">
          {t("translate.outsideRange")}
        </span>
      </div>

      <div className="stats">
        {estimate ? (
          <>
            <div>
              <div className="n">{formatNumber(estimate.segments)}</div>
              <div className="l">{t("translate.stat.segments")}</div>
            </div>
            <div>
              <div className="n">{thousands(estimate.words)}</div>
              <div className="l">{t("translate.stat.words")}</div>
            </div>
            <div>
              <div className="n">{formatNumber(estimate.merged_paragraphs)}</div>
              <div className="l">{t("translate.stat.merged")}</div>
            </div>
            <div>
              <div className="n">{formatNumber(estimate.formulas)}</div>
              <div className="l">{t("translate.stat.formulas")}</div>
            </div>
          </>
        ) : (
          <span className="row small muted" style={{ gridColumn: "1 / -1" }}>
            <Spinner /> {t("translate.measuring")}
          </span>
        )}
      </div>

      {blocked && chosen ? (
        <div className="row card-sand" style={{ padding: "12px 14px" }}>
          <KeyRound size={16} className="muted" />
          <span className="small spacer">
            {t("translate.needsKey", { engine: chosen.label })}
          </span>
          <button type="button" className="btn btn-sm btn-outline" onClick={() => navigate(paths.settings("ai"))}>
            {t("translate.addKey")}
          </button>
        </div>
      ) : null}

      <div className="dialog-foot">
        <span className="caption spacer" style={{ maxWidth: "34ch" }}>
          {t("translate.background")}
        </span>
        <button type="button" className="btn btn-quiet" onClick={onClose}>
          {t("common.cancel")}
        </button>
        <button
          type="button"
          className="btn btn-action btn-lg"
          disabled={!chosen || starting || blocked}
          onClick={() => void start()}
        >
          {starting ? <Spinner /> : <Languages size={17} strokeWidth={2.25} />}
          {t("translate.go")}
        </button>
      </div>
    </Dialog>
  );
}
