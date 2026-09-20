/**
 * Reading the analysis stream.
 *
 * The API streams server-sent events over the response to the upload itself,
 * so this is `fetch` plus a `ReadableStream` rather than `EventSource`.
 * `EventSource` cannot send a multipart body, which is why the API is shaped
 * this way — see `apps/api/roleva/api/sse.py`.
 *
 * The parsing looks trivial and is not. A chunk boundary can fall anywhere,
 * including inside a JSON payload, so the buffer is only split on a complete
 * frame terminator and the remainder is carried forward. Parsing per-chunk is
 * the bug this module exists to not have.
 */

import type { ProgressEvent, AnalysisReport } from "@/lib/types";

export type StreamEvent =
  | { kind: "progress"; event: ProgressEvent }
  | { kind: "result"; report: AnalysisReport; analysisId: string | null }
  | { kind: "error"; code: string; message: string };

/** Frames are separated by a blank line; `\r\n` appears behind some proxies. */
const FRAME_BREAK = /\r?\n\r?\n/;

export async function* readAnalysisStream(
  response: Response,
  signal?: AbortSignal,
): AsyncGenerator<StreamEvent> {
  if (!response.body) {
    yield {
      kind: "error",
      code: "no_stream",
      message: "The connection closed before the analysis started. Try again.",
    };
    return;
  }

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";

  try {
    while (true) {
      if (signal?.aborted) return;

      const { done, value } = await reader.read();
      if (done) break;

      buffer += value;

      // Only complete frames are parsed. Whatever is left is the beginning of
      // the next one.
      const frames = buffer.split(FRAME_BREAK);
      buffer = frames.pop() ?? "";

      for (const frame of frames) {
        const parsed = parseFrame(frame);
        if (parsed) yield parsed;
      }
    }
  } finally {
    // Releasing the lock matters when the user navigates away mid-analysis:
    // without it the connection stays open and the request keeps running.
    reader.releaseLock();
  }
}

function parseFrame(frame: string): StreamEvent | null {
  const trimmed = frame.trim();
  // A heartbeat. Its whole purpose is to keep a proxy from closing an idle
  // connection, and it carries nothing.
  if (!trimmed || trimmed.startsWith(":")) return null;

  let name = "";
  const dataLines: string[] = [];

  for (const line of trimmed.split(/\r?\n/)) {
    if (line.startsWith("event:")) name = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }

  if (!dataLines.length) return null;

  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    // A malformed frame is a bug on the server, not something the user can act
    // on. Dropping it keeps the rest of the stream working.
    return null;
  }

  const payload = data as Record<string, unknown>;

  if (name === "progress") {
    return { kind: "progress", event: payload as unknown as ProgressEvent };
  }
  if (name === "result") {
    return {
      kind: "result",
      report: payload.report as AnalysisReport,
      analysisId: (payload.analysis_id as string | null) ?? null,
    };
  }
  if (name === "error") {
    return {
      kind: "error",
      code: String(payload.code ?? "analysis_failed"),
      message: String(payload.message ?? "Something went wrong. Please try again."),
    };
  }
  return null;
}
