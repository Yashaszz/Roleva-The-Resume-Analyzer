/**
 * The public share view. 8.7 and 8.8.
 *
 * Reached by anyone holding the token, with no account. What they see is
 * whatever the API sent — the redaction already happened server-side, so this
 * page renders its input rather than deciding what to hide. That is the whole
 * point of Gate 8: opening devtools here shows the same bytes as reading the
 * JSON, because there is nothing extra to find.
 *
 * Never indexed. `robots` covers crawlers that read the HTML; the API sets
 * `X-Robots-Tag` for anything that fetches the JSON directly and never sees a
 * meta tag. Both, because either alone leaves a gap.
 */
import Link from "next/link";
import { notFound } from "next/navigation";

import { AtsChecklist, Recommendations } from "@/components/report/Advice";
import { SkillLedger } from "@/components/report/SkillLedger";
import { ThreadMap, type ThreadRow } from "@/components/report/Thread";
import { Verdict } from "@/components/report/Verdict";
import { ToastProvider } from "@/components/ui/Toast";
import type { AnalysisReport } from "@/lib/types";

const API_BASE_URL = process.env.API_BASE_URL ?? "http://localhost:8000";

export const metadata = {
  title: "A Roleva analysis",
  robots: { index: false, follow: false, nocache: true },
};

/** Never cached: a revoked link has to stop working on the next request. */
export const dynamic = "force-dynamic";

export default async function SharedReportPage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  const report = await loadShared(token);

  // Expired, revoked and never-existed are the same page. Telling somebody
  // holding an old link that it used to work is information the owner did not
  // agree to share.
  if (!report) notFound();

  const requirements = report.job.requirements ?? [];
  const matches = report.matches.matches ?? [];

  // `scores_only` strips every quote, so the thread map would draw a column of
  // stubs and say nothing. It is left out rather than rendered empty.
  const hasEvidence = matches.some((match) => (match.evidence ?? []).length > 0);

  return (
    <ToastProvider>
      <div className="min-h-dvh flex flex-col">
        <header className="border-b border-line-subtle">
          <div className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-4 flex items-center justify-between gap-4">
            <span className="display text-lg">Roleva</span>
            <span className="label">Shared analysis</span>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1100px] px-5 sm:px-8 py-10 sm:py-14 flex flex-col gap-14">
          <Verdict
            scores={report.scores}
            headline={report.headline}
            body={report.verdict}
            roleTitle={roleTitle(report)}
            requirementCount={requirements.length}
            degradedStages={report.degraded_stages ?? []}
          />

          {hasEvidence ? <ThreadMap rows={threadRows(requirements, matches)} /> : null}

          <Recommendations items={report.recommendations ?? []} />

          <SkillLedger requirements={requirements} matches={matches} />

          <AtsChecklist
            findings={report.ats.findings ?? []}
            checksRun={report.ats.checks_run}
            hiddenText={report.ats.hidden_text_detected}
          />

          <footer className="border-t border-line-subtle pt-8 flex flex-col gap-3">
            <p className="text-sm text-muted leading-normal max-w-[62ch] m-0">
              This was shared with you by the person it is about. Some details may have
              been removed before you saw it — that happens on the server, so nothing
              hidden is still in the page.
            </p>
            <Link href="/" className="text-sm text-shown w-fit">
              What is Roleva?
            </Link>
          </footer>
        </main>
      </div>
    </ToastProvider>
  );
}

async function loadShared(token: string): Promise<AnalysisReport | null> {
  try {
    const response = await fetch(`${API_BASE_URL}/shared/${encodeURIComponent(token)}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as AnalysisReport;
  } catch {
    return null;
  }
}

function threadRows(
  requirements: NonNullable<AnalysisReport["job"]["requirements"]>,
  matches: NonNullable<AnalysisReport["matches"]["matches"]>,
): ThreadRow[] {
  const byId = new Map(matches.map((match) => [match.requirement_id, match]));
  const priority = { must: 0, strong: 1, nice: 2 } as const;
  const stateRank = { absent: 0, listed: 1, shown: 2 } as const;

  return requirements
    .map((requirement): ThreadRow => {
      const match = byId.get(requirement.id ?? "");
      const strength = match?.strength ?? 0;
      const best = match?.evidence?.[0];
      return {
        id: requirement.id ?? requirement.text,
        requirement: requirement.text,
        priority: requirement.priority,
        state:
          !match || match.status === "missing" || strength === 0
            ? "absent"
            : match.status === "partial" || strength <= 0.5
              ? "listed"
              : "shown",
        evidence: best?.span.text,
        location: best ? "Experience" : undefined,
      };
    })
    .sort(
      (a, b) =>
        priority[a.priority] - priority[b.priority] ||
        stateRank[a.state] - stateRank[b.state],
    );
}

function roleTitle(report: AnalysisReport): string {
  const { title, company, seniority } = report.job;
  const base = title ?? "This role";
  const level = seniority && seniority !== "unknown" ? `, ${seniority}` : "";
  return company ? `${base} at ${company}${level}` : `${base}${level}`;
}
