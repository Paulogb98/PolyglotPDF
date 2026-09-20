import { lang, t } from "../i18n";
import { errorFrom, LANGUAGE_HEADER } from "./client";
import type { Anchor, Message, Thread } from "./types";

export interface AskBody {
  document_id: string;
  version_id?: string | null;
  thread_id?: string | null;
  start?: Anchor | null;
  end?: Anchor | null;
  action: string;
  question?: string | null;
}

export interface AskHandlers {
  onThread(thread: Thread): void;
  onDelta(text: string): void;
  onDone(message: Message | null): void;
  onError(message: string, retryable: boolean): void;
}

export interface ServerEvent {
  event: string;
  data: unknown;
}

/** Parse one Server-Sent Events block ("event: x\ndata: {...}"). */
export function parseEvent(block: string): ServerEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) };
  } catch {
    return null;
  }
}

/** Ask the reading companion; the answer arrives through ``handlers`` as it is written. */
export async function ask(body: AskBody, handlers: AskHandlers, signal: AbortSignal): Promise<void> {
  const response = await fetch("/api/companion/ask", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream", [LANGUAGE_HEADER]: lang() },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) throw await errorFrom(response);
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      dispatch(parseEvent(buffer.slice(0, boundary)), handlers);
      buffer = buffer.slice(boundary + 2);
      boundary = buffer.indexOf("\n\n");
    }
  }
  if (buffer.trim()) dispatch(parseEvent(buffer), handlers);
}

function dispatch(event: ServerEvent | null, handlers: AskHandlers): void {
  if (!event) return;
  const data = event.data as Record<string, unknown>;
  switch (event.event) {
    case "thread":
      handlers.onThread(event.data as Thread);
      break;
    case "delta":
      handlers.onDelta(String(data.text ?? ""));
      break;
    case "done":
      handlers.onDone((data.message as Message | null) ?? null);
      break;
    case "error":
      handlers.onError(String(data.message ?? t("common.unknownError")), Boolean(data.retryable));
      break;
  }
}
