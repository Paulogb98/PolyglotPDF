import { useCallback, useEffect, useRef, useState } from "react";
import { t, type Key } from "../../i18n";
import { api } from "../../api/client";
import { ask } from "../../api/sse";
import type { Anchor, Thread } from "../../api/types";
import { errorMessage } from "../../components/Toasts";

export interface Turn {
  role: "user" | "assistant";
  text: string;
  /** Still being written by the model. */
  live?: boolean;
}

export interface CompanionState {
  thread: Thread | null;
  turns: Turn[];
  streaming: boolean;
  error: string | null;
  retryable: boolean;
  /** Start a conversation about a passage (or about a whole page). */
  start(start: Anchor, end: Anchor | null, action: string, question?: string): void;
  /** Ask again in the conversation that is already open. */
  follow(action: string, question?: string): void;
  stop(): void;
  reset(): void;
  /** Bring back a conversation held earlier, to read it or to continue it. */
  reopen(threadId: string): Promise<void>;
}

/** One conversation with the reading companion, streamed as it is written. */
export function useCompanion(documentId: string, version: string | null): CompanionState {
  const [thread, setThread] = useState<Thread | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [retryable, setRetryable] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const threadId = useRef<string | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const run = useCallback(
    (
      body: {
        start?: Anchor | null;
        end?: Anchor | null;
        thread_id?: string | null;
      },
      action: string,
      question: string | undefined,
      label: string,
    ) => {
      abort.current?.abort();
      const controller = new AbortController();
      abort.current = controller;
      setStreaming(true);
      setError(null);
      setTurns((current) => [
        ...current,
        { role: "user", text: question?.trim() || label },
        { role: "assistant", text: "", live: true },
      ]);
      void ask(
        {
          document_id: documentId,
          version_id: version,
          action,
          question: question ?? null,
          ...body,
        },
        {
          onThread: (value) => {
            threadId.current = value.id;
            setThread(value);
          },
          onDelta: (piece) =>
            setTurns((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") {
                copy[copy.length - 1] = { ...last, text: last.text + piece };
              }
              return copy;
            }),
          onDone: () => {
            setTurns((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant") copy[copy.length - 1] = { ...last, live: false };
              return copy;
            });
            setStreaming(false);
          },
          onError: (message, canRetry) => {
            setError(message);
            setRetryable(canRetry);
            setStreaming(false);
            setTurns((current) => {
              const copy = [...current];
              const last = copy[copy.length - 1];
              if (last?.role === "assistant" && !last.text) copy.pop();
              else if (last?.role === "assistant") copy[copy.length - 1] = { ...last, live: false };
              return copy;
            });
          },
        },
        controller.signal,
      ).catch((caught: unknown) => {
        if (controller.signal.aborted) return;
        setError(errorMessage(caught));
        setRetryable(true);
        setStreaming(false);
        setTurns((current) => current.filter((turn) => !turn.live));
      });
    },
    [documentId, version],
  );

  const start = useCallback(
    (from: Anchor, to: Anchor | null, action: string, question?: string) => {
      threadId.current = null;
      setThread(null);
      setTurns([]);
      run({ start: from, end: to }, action, question, actionLabel(action));
    },
    [run],
  );

  const follow = useCallback(
    (action: string, question?: string) => {
      run(
        { thread_id: threadId.current },
        action,
        question,
        actionLabel(action),
      );
    },
    [run],
  );

  const stop = useCallback(() => {
    abort.current?.abort();
    setStreaming(false);
    setTurns((current) => current.map((turn) => ({ ...turn, live: false })));
  }, []);

  const reset = useCallback(() => {
    abort.current?.abort();
    threadId.current = null;
    setThread(null);
    setTurns([]);
    setStreaming(false);
    setError(null);
  }, []);

  const reopen = useCallback(async (id: string) => {
    abort.current?.abort();
    setStreaming(false);
    setError(null);
    try {
      const loaded = await api.thread(id);
      threadId.current = loaded.id;
      setThread(loaded);
      setTurns(
        loaded.messages.map((message) => ({
          role: message.role,
          text: message.text,
        })),
      );
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }, []);

  return { thread, turns, streaming, error, retryable, start, follow, stop, reset, reopen };
}

const ACTIONS = new Set([
  "ask",
  "explain",
  "simplify",
  "context",
  "concepts",
  "vocabulary",
  "summarize",
  "translate",
  "comment",
]);

/** What the reader asked for, as the conversation shows it ("Explicar", "Resumir"…). */
export function actionLabel(action: string): string {
  return t(ACTIONS.has(action) ? (`action.${action}` as Key) : "action.ask");
}
