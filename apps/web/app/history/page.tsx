/**
 * Past analyses. 7.28.
 *
 * A list, not a dashboard. There are no charts here because three scores over
 * four analyses is not a trend — drawing a line through them would imply a
 * story the data cannot support, and this product's whole argument is against
 * that kind of confident nonsense.
 *
 * The history deliberately does not fetch full reports. A row needs a date and
 * three numbers; shipping ten complete reports to render ten rows is bandwidth
 * spent on a free tier for nothing.
 */
"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { Shell } from "@/components/app/Shell";
import { Button } from "@/components/ui/Button";
import { Empty, SkeletonLine } from "@/components/ui/Loading";
import { Panel } from "@/components/ui/Panel";

type Row = {
  id: string;
  created_at: string;
  status: string;
  scores: {
    overall?: { value: number; band: string };
    job_match?: { value: number };
    quality?: { value: number };
    ats?: { value: number };
  };
};

export default function HistoryPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    fetch("/api/proxy/analyses", { cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error(String(response.status));
        return response.json();
      })
      .then((data: { analyses: Row[] }) => {
        if (!cancelled) setRows(data.analyses ?? []);
      })
      .catch(() => {
        if (!cancelled) setError("Couldn't load your history. Try reloading the page.");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Shell>
      <main className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-10 flex flex-col gap-8">
        <div className="flex flex-col gap-2">
          <h1 className="display" style={{ fontSize: "var(--text-xl)" }}>
            Your analyses
          </h1>
          <p className="text-base text-secondary leading-normal max-w-[62ch]">
            Each one is scored against the specific posting you pasted, so two
            analyses of the same resume can differ by twenty points and both be right.
          </p>
        </div>

        {error ? (
          <p role="alert" className="text-base text-absent">
            {error}
          </p>
        ) : rows === null ? (
          <Panel padded={false}>
            <div className="flex flex-col gap-3 p-5" aria-busy="true">
              <span className="sr-only">Loading your analyses</span>
              <SkeletonLine width="60%" />
              <SkeletonLine width="45%" />
              <SkeletonLine width="52%" />
            </div>
          </Panel>
        ) : rows.length === 0 ? (
          <Panel>
            <Empty
              title="Nothing here yet"
              detail="Upload a resume and paste a job description, and your first analysis will appear here."
              action={
                <Link href="/analyze" className="no-underline">
                  <Button variant="primary">Start an analysis</Button>
                </Link>
              }
            />
          </Panel>
        ) : (
          <Panel padded={false}>
            <ul className="flex flex-col m-0 p-0 list-none">
              {rows.map((row) => (
                <li key={row.id} className="border-b border-line-subtle last:border-b-0">
                  <Link
                    href={`/report/${row.id}`}
                    className="flex items-center gap-4 sm:gap-6 px-5 py-4 min-h-[64px] no-underline hover:bg-raised transition-colors [transition-duration:var(--duration-instant)]"
                  >
                    <span
                      className="display shrink-0 w-[52px] text-primary"
                      style={{ fontSize: "var(--text-lg)" }}
                    >
                      {Math.round(row.scores.overall?.value ?? 0)}
                    </span>

                    <span className="flex-1 min-w-0 flex flex-col gap-0.5">
                      <span className="text-base text-primary">
                        {bandLabel(row.scores.overall?.band)}
                      </span>
                      <span className="label">{when(row.created_at)}</span>
                    </span>

                    <span className="hidden sm:flex gap-5 shrink-0">
                      <Figure label="match" value={row.scores.job_match?.value} />
                      <Figure label="writing" value={row.scores.quality?.value} />
                      <Figure label="ats" value={row.scores.ats?.value} />
                    </span>

                    {row.status === "partial" ? (
                      <span className="label text-capped shrink-0">partial</span>
                    ) : null}
                  </Link>
                </li>
              ))}
            </ul>
          </Panel>
        )}
      </main>
    </Shell>
  );
}

function Figure({ label, value }: { label: string; value: number | undefined }) {
  return (
    <span className="flex flex-col items-end gap-0.5">
      <span className="numeric text-sm text-secondary">
        {value == null ? "—" : Math.round(value)}
      </span>
      <span className="label">{label}</span>
    </span>
  );
}

const BANDS: Record<string, string> = {
  strong: "Strong candidate",
  competitive: "Competitive",
  needs_work: "Needs work",
  significant_gaps: "Significant gaps",
  not_aligned: "Not aligned",
};

function bandLabel(band: string | undefined): string {
  return band ? (BANDS[band] ?? band) : "Analysis";
}

/**
 * A relative date for recent things, an absolute one after that.
 *
 * "3 days ago" is useful; "47 days ago" is arithmetic the reader has to undo.
 */
function when(iso: string): string {
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";

  const days = Math.floor((Date.now() - then.getTime()) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  if (days < 7) return `${days} days ago`;
  return then.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
