/**
 * Upload, paste, analyse.
 *
 * One page with two states rather than two routes. An analysis cannot be
 * resumed — the upload lives in memory and the stream belongs to this request —
 * so navigating to a `/analyze/running` URL would create a page that breaks on
 * refresh and lies in the back button. Staying put makes the impossible thing
 * impossible.
 */
"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Dropzone } from "@/components/analyze/Dropzone";
import { Progress } from "@/components/analyze/Progress";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Field";
import { GOOD_JD_CHARS, MIN_JD_CHARS, jdQuality, jdWarning } from "@/lib/preflight";
import { readAnalysisStream } from "@/lib/stream";
import type { ProgressEvent } from "@/lib/types";

export default function AnalyzePage() {
  const router = useRouter();

  const [file, setFile] = useState<File | null>(null);
  const [jd, setJd] = useState("");
  const [running, setRunning] = useState(false);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const abort = useRef<AbortController | null>(null);

  /*
   * Wake the API as soon as the page opens.
   *
   * Render cold-starts in up to fifty seconds; choosing a file and pasting a
   * posting takes about a minute. Overlapping the two means the wait mostly
   * disappears, and it costs one request to an endpoint that reads no rows.
   */
  useEffect(() => {
    void fetch("/api/warmup", { method: "GET" }).catch(() => {
      // A failed warm-up changes nothing: the analysis request wakes it anyway,
      // just more slowly.
    });
  }, []);

  // Cancel in flight if the user navigates away, so the stream is not left open.
  useEffect(() => () => abort.current?.abort(), []);

  const quality = jdQuality(jd);
  const warning = jdWarning(jd);
  const ready = file !== null && quality !== "short";

  async function start() {
    if (!ready || !file) return;

    setRunning(true);
    setEvents([]);
    setError(null);

    const controller = new AbortController();
    abort.current = controller;

    const body = new FormData();
    body.append("file", file);
    body.append("job_description", jd);

    let response: Response;
    try {
      response = await fetch("/api/analyze", {
        method: "POST",
        body,
        signal: controller.signal,
      });
    } catch {
      if (controller.signal.aborted) return;
      setError({
        code: "upstream_unavailable",
        message: "Couldn't reach the analysis service. Check your connection and try again.",
      });
      return;
    }

    // A rejection before the stream opens arrives as JSON with a real status —
    // quota, capacity, a file the server refused.
    if (!response.ok) {
      const detail = await response.json().catch(() => null);
      setError({
        code: detail?.code ?? detail?.detail?.code ?? "analysis_failed",
        message:
          detail?.message ??
          detail?.detail?.message ??
          "Something went wrong. Please try again.",
      });
      return;
    }

    for await (const event of readAnalysisStream(response, controller.signal)) {
      if (event.kind === "progress") {
        setEvents((current) => [...current, event.event]);
      } else if (event.kind === "error") {
        setError({ code: event.code, message: event.message });
        return;
      } else if (event.kind === "result") {
        // The report is already persisted by this point, so the id is a real
        // route rather than a handle to something held in memory.
        if (event.analysisId) {
          router.push(`/report/${event.analysisId}`);
        } else {
          setError({
            code: "analysis_failed",
            message: "The analysis finished but could not be saved. Please try again.",
          });
        }
        return;
      }
    }
  }

  if (running) {
    return (
      <main className="mx-auto w-full max-w-[860px] px-6 sm:px-10 py-14">
        <Progress events={events} error={error} />
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-[720px] px-6 sm:px-10 py-14 flex flex-col gap-10">
      <div className="flex flex-col gap-3">
        <h1 className="display max-w-[20ch]" style={{ fontSize: "var(--text-xl)" }}>
          Which job are you applying for?
        </h1>
        <p className="text-base text-secondary leading-normal max-w-[58ch]">
          Roleva scores your resume against one specific posting, not against resumes in
          general. The more of the posting you paste, the more it has to work with.
        </p>
      </div>

      <Dropzone file={file} onFile={setFile} />

      <Textarea
        label="Job description"
        hint="Paste the whole posting — requirements, responsibilities, everything."
        placeholder="Paste the job description here…"
        value={jd}
        onChange={(event) => setJd(event.target.value)}
        meta={<JdMeter length={jd.trim().length} quality={quality} />}
      />

      {warning ? (
        <div className="flex gap-3 p-4 bg-capped-bg border-l-2 border-capped rounded-r-sm">
          <p className="text-sm text-secondary leading-normal m-0">{warning}</p>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        <Button variant="primary" onClick={start} disabled={!ready} className="w-full sm:w-auto sm:self-start">
          Analyse my resume
        </Button>
        {/* Says what is still missing, rather than leaving a disabled button
            with no explanation — the commonest dead end in a form. */}
        {!ready ? (
          <p className="text-sm text-muted">
            {!file && quality === "short"
              ? "Add your resume and paste the job description to continue."
              : !file
                ? "Add your resume to continue."
                : `Paste at least ${MIN_JD_CHARS} characters of the job description to continue.`}
          </p>
        ) : null}
      </div>
    </main>
  );
}

function JdMeter({ length, quality }: { length: number; quality: ReturnType<typeof jdQuality> }) {
  const copy = {
    short: `${MIN_JD_CHARS - length} more characters needed`,
    thin: `Enough to analyse — ${GOOD_JD_CHARS} gives a better result`,
    ok: "Good length",
  }[quality];

  const colour = { short: "text-muted", thin: "text-capped", ok: "text-shown" }[quality];

  return (
    <span className={`text-2xs font-mono uppercase tracking-[var(--tracking-label)] ${colour}`}>
      <span className="numeric">{length}</span>
      {" — "}
      {copy}
    </span>
  );
}
