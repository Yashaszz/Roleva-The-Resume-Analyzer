/**
 * What the user watches for thirty seconds.
 *
 * This is a designed part of the product, not a spinner. The difference between
 * "this is working through my resume" and "this has frozen" is the whole of it,
 * and the stage names are the real ones the pipeline emits — work the user cares
 * about, never function names.
 *
 * Three things it has to get right:
 *
 * 1. **The cold-start case.** Render's free tier sleeps, and the first request
 *    can take fifty seconds before the analysis even begins. Saying nothing for
 *    fifty seconds is indistinguishable from being broken, so after a few
 *    seconds of silence the screen says what is actually happening.
 * 2. **Never going backwards.** Percentages come from the server, but a late
 *    frame arriving after an early one would make the bar jump back, which reads
 *    as a bug whatever the truth is. The displayed value only ever increases.
 * 3. **Announcing itself once.** A live region that reads every stage change is
 *    useful; one that reads every percentage tick is unusable. Only the stage
 *    message is announced.
 */
"use client";

import { useEffect, useRef, useState } from "react";

import type { ProgressEvent, Stage } from "@/lib/types";

/** After this much silence, explain rather than sit still. */
const COLD_START_MS = 4000;

export function Progress({
  events,
  error,
}: {
  events: ProgressEvent[];
  error: { code: string; message: string } | null;
}) {
  const latest = events.at(-1) ?? null;
  const [waiting, setWaiting] = useState(false);
  // Initialised to 0 and written inside the effect: reading a clock during
  // render is impure, and React is entitled to render twice.
  const lastAt = useRef(0);

  /*
   * A monotonic bar, derived rather than stored.
   *
   * The first version kept the ceiling in state and raised it in an effect,
   * which is a cascading render and, worse, a second source of truth. Taking
   * the maximum over the events that have arrived is pure, cannot be walked
   * backwards by a late frame, and has no state to fall out of step.
   */
  const ceiling = events.length ? Math.max(...events.map((event) => event.percent)) : 0;

  // Detect a long silence — almost always a cold Render instance. The timer
  // both sets and clears the flag, so nothing is assigned during the effect
  // body itself.
  useEffect(() => {
    lastAt.current = Date.now();
    const timer = setInterval(() => {
      setWaiting(Date.now() - lastAt.current > COLD_START_MS);
    }, 500);
    return () => clearInterval(timer);
  }, [events.length]);

  if (error) return <Failure error={error} />;

  const seen = new Set(events.map((event) => event.stage));

  return (
    <div className="flex flex-col gap-10">
      <div className="flex flex-col gap-4 max-w-[30ch]">
        <h1 className="display" style={{ fontSize: "var(--text-xl)" }}>
          {latest?.message ?? "Getting started"}
        </h1>
        {waiting && ceiling < 15 ? (
          <p className="text-base text-secondary leading-normal">
            The analysis service is waking up. It sleeps when nobody is using it, which
            is how Roleva stays free — this takes up to a minute the first time, and a
            second or two after that.
          </p>
        ) : (
          <p className="text-base text-secondary leading-normal">
            Roleva reads your resume and the posting separately, then looks for each
            requirement in your own words.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex items-baseline gap-3">
          <span
            className="numeric text-shown"
            style={{ fontSize: "var(--text-2xl)", lineHeight: 1 }}
          >
            {ceiling}
          </span>
          <span className="label">per cent</span>
        </div>

        {/* The bar is decorative: the number beside it and the stage list below
            both carry the same information in text. */}
        <div className="h-0.5 bg-line-subtle rounded-full" aria-hidden="true">
          <div
            className="h-0.5 bg-shown rounded-full"
            style={{
              width: `${ceiling}%`,
              transition: "width var(--duration-settle) var(--ease-out)",
            }}
          />
        </div>
      </div>

      {/* One polite announcement per stage. */}
      <p className="sr-only" aria-live="polite">
        {latest ? `${latest.message}, ${ceiling} per cent` : ""}
      </p>

      <ol className="flex flex-col m-0 p-0 list-none max-w-[620px]">
        {events.map((event, index) => {
          const isLast = index === events.length - 1;
          return (
            <li
              key={`${event.stage}-${index}`}
              className="flex items-center gap-4 py-3 border-b border-line-subtle last:border-b-0"
            >
              {isLast ? <Running /> : <Done />}
              <span
                className={`flex-1 text-base ${isLast ? "text-primary font-medium" : "text-muted"}`}
              >
                {event.message}
              </span>
              {isLast ? <span className="label text-shown">now</span> : null}
            </li>
          );
        })}

        {/* Stages still ahead, so the user can see how much is left rather than
            guessing from a percentage. */}
        {REMAINING.filter(({ stage }) => !seen.has(stage)).map(({ stage, message }) => (
          <li
            key={stage}
            className="flex items-center gap-4 py-3 border-b border-line-subtle last:border-b-0"
          >
            <Pending />
            <span className="flex-1 text-base text-dim">{message}</span>
          </li>
        ))}
      </ol>

      <div className="flex gap-3 items-start p-4 bg-panel border border-line-subtle rounded-md max-w-[620px]">
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="var(--text-muted)"
          strokeWidth="1.7"
          aria-hidden="true"
          className="shrink-0 mt-0.5"
        >
          <circle cx="12" cy="12" r="9" />
          <path d="M12 16v-5M12 8h.01" />
        </svg>
        <p className="text-sm text-muted leading-normal m-0">
          Every number in your report is computed from what Roleva found in your own
          words. Nothing here is a language model&rsquo;s opinion of you — you will be
          able to click any figure and see the line it came from.
        </p>
      </div>
    </div>
  );
}

/**
 * The stages that have not been reported yet.
 *
 * Duplicated from the API's `MESSAGES` table rather than fetched, because this
 * list is only ever shown *before* the server has said anything — there is
 * nothing to fetch it from yet. The wording is kept identical so a stage does
 * not appear to rename itself the moment it starts.
 *
 * Typed as `Stage`, which comes from the generated OpenAPI types: a stage the
 * API does not have is a compile error here rather than a row that silently
 * never disappears.
 */
const REMAINING: { stage: Stage; message: string }[] = [
  { stage: "validating", message: "Checking your file" },
  { stage: "extracting", message: "Reading the document" },
  { stage: "structuring", message: "Finding your experience, projects and skills" },
  { stage: "reading_job", message: "Reading the job description" },
  { stage: "matching", message: "Matching your evidence against each requirement" },
  { stage: "checking_ats", message: "Checking how applicant tracking systems will parse this" },
  { stage: "assessing_quality", message: "Assessing how your bullets are written" },
  { stage: "scoring", message: "Computing your scores" },
  { stage: "writing_advice", message: "Writing suggestions" },
];

function Done() {
  return (
    <svg
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--evidence-shown)"
      strokeWidth="2.4"
      aria-hidden="true"
      className="shrink-0"
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function Running() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true" className="shrink-0 motion-safe:animate-spin">
      <circle cx="12" cy="12" r="9" stroke="var(--line-subtle)" strokeWidth="2.4" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="var(--evidence-shown)" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

function Pending() {
  return (
    <span className="w-[15px] h-[15px] shrink-0 flex items-center justify-center" aria-hidden="true">
      <span className="w-[5px] h-[5px] rounded-full bg-line-strong" />
    </span>
  );
}

function Failure({ error }: { error: { code: string; message: string } }) {
  return (
    <div className="flex flex-col gap-5 max-w-[46ch]">
      <h1 className="display" style={{ fontSize: "var(--text-xl)" }}>
        {TITLES[error.code] ?? "That didn't work"}
      </h1>
      {/* The message comes from the API's error taxonomy — already written for
          a person, already telling them what to do. It is shown as-is rather
          than being replaced with something vaguer. */}
      <p role="alert" className="text-base text-secondary leading-normal">
        {error.message}
      </p>
      <a href="/analyze" className="text-shown text-base w-fit">
        Start again
      </a>
    </div>
  );
}

/** A heading for each failure, so the page does not open with an apology. */
const TITLES: Record<string, string> = {
  quota_exceeded: "That's your five for today",
  capacity_reached: "Roleva is at capacity today",
  rate_limited: "Too many requests",
  pdf_encrypted: "That PDF is locked",
  pdf_scanned: "That looks like a scan",
  jd_too_short: "That posting is too short",
  upstream_unavailable: "Couldn't reach the service",
};
