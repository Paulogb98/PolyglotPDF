import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { api } from "../../api/client";
import type { Job } from "../../api/types";
import { useToast } from "../../components/Toasts";
import { navigate, paths } from "../../lib/router";
import { t } from "../../i18n";

type Listener = (job: Job) => void;

interface JobsValue {
  jobs: Job[];
  /** Show a job the interface has just started (before the next poll). */
  track(job: Job): void;
  refresh(): Promise<void>;
  /** Be told when a job finishes (done, failed or cancelled). */
  subscribe(listener: Listener): () => void;
}

export const ACTIVE_STATUSES = new Set<Job["status"]>(["queued", "running"]);
const JobsContext = createContext<JobsValue | null>(null);

export function JobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const toast = useToast();
  const statuses = useRef(new Map<string, Job["status"]>());
  const listeners = useRef(new Set<Listener>());

  const announce = useCallback(
    (job: Job) => {
      if (job.kind !== "translate") return;
      const title = job.params.title ?? t("common.document");
      if (job.status === "done") {
        const version = job.version_id;
        const failed = Number(job.result?.failed ?? 0);
        const total = Number(job.result?.segments ?? 0);
        toast({
          kind: failed ? "info" : "success",
          title: failed ? t("jobs.partial") : t("jobs.done"),
          body: failed
            ? t("jobs.partialBody", { title, failed, total })
            : title,
          action: version
            ? { label: t("common.open"), run: () => navigate(paths.reader(job.document_id, { version })) }
            : undefined,
        });
      } else if (job.status === "failed") {
        toast({ kind: "error", title: t("jobs.failed"), body: job.error ?? title });
      } else if (job.status === "cancelled") {
        toast({ kind: "info", title: t("jobs.cancelled"), body: title });
      }
    },
    [toast],
  );

  const absorb = useCallback(
    (list: Job[]) => {
      for (const job of list) {
        const before = statuses.current.get(job.id);
        statuses.current.set(job.id, job.status);
        if (before && ACTIVE_STATUSES.has(before) && !ACTIVE_STATUSES.has(job.status)) {
          for (const listener of listeners.current) listener(job);
          announce(job);
        }
      }
      setJobs(list);
    },
    [announce],
  );

  const refresh = useCallback(async () => {
    try {
      absorb((await api.jobs()).jobs);
    } catch {
      // The next poll tries again.
    }
  }, [absorb]);

  const track = useCallback((job: Job) => {
    statuses.current.set(job.id, job.status);
    setJobs((list) => [job, ...list.filter((item) => item.id !== job.id)]);
  }, []);

  const subscribe = useCallback((listener: Listener) => {
    listeners.current.add(listener);
    return () => {
      listeners.current.delete(listener);
    };
  }, []);

  const active = jobs.some((job) => ACTIVE_STATUSES.has(job.status));
  useEffect(() => {
    void refresh();
  }, [refresh]);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => window.clearInterval(timer);
  }, [active, refresh]);

  const value = useMemo(() => ({ jobs, track, refresh, subscribe }), [jobs, track, refresh, subscribe]);
  return <JobsContext.Provider value={value}>{children}</JobsContext.Provider>;
}

export function useJobs(): JobsValue {
  const value = useContext(JobsContext);
  if (!value) throw new Error("useJobs must be used inside <JobsProvider>");
  return value;
}

/** Run ``listener`` whenever a job finishes. */
export function useJobEvents(listener: Listener): void {
  const { subscribe } = useJobs();
  const latest = useRef(listener);
  useEffect(() => {
    latest.current = listener;
  });
  useEffect(() => subscribe((job) => latest.current(job)), [subscribe]);
}
